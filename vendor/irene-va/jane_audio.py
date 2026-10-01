"""Аудио для канала устройства: пересчёт частоты и детекция конца фразы.

Отдельный модуль не для красоты. runva_webapi.py при импорте поднимает весь
стек ассистента (vosk, fastapi, lingua_franca) и в обычной среде падает на
зависимостях раньше, чем дело дойдёт до кода. Проверять детектор было
нечем: тест запускался только внутри контейнера, то есть только вручную.

Здесь нужен только numpy. Логика ровно та же, что работает в колонке, а не
её копия: детектор однажды считал паузу в кусках, а не в кадрах, и фразы
рвались в зависимости от того, как плата нарезает поток.
"""

import numpy as np

STT_RATE = 16000          # во что переводим любой вход
VAD_FRAME = 480           # 30 мс при 16 кГц
VAD_HANGOVER = 26         # сколько тихих кадров ждём перед концом фразы
VAD_MAX_FRAMES = 500      # предохранитель: 15 секунд непрерывного шума


def pcm_resample(data, src, dst):
    """Линейный пересчёт PCM s16le. Микрофон платы не обязан уметь 16 кГц,
    и требовать от железа конкретную частоту значит отказывать половине
    модулей, поэтому пересчитываем на сервере."""
    if not data or src == dst:
        return data
    x = np.frombuffer(data, dtype="<i2").astype(np.float32)
    if x.size == 0:
        return b""
    n = int(x.size * dst / float(src))
    if n < 2:
        return b""
    grid = np.linspace(0, x.size - 1, n, dtype=np.float32)
    return np.interp(grid, np.arange(x.size, dtype=np.float32),
                     x).astype("<i2").tobytes()


def frame_rms_peak(data):
    """Громкость кадра: среднеквадратичная и пик."""
    x = np.frombuffer(data, dtype="<i2").astype(np.float32)
    if x.size == 0:
        return 0.0, 0.0
    return float(np.sqrt(np.mean(x * x))), float(np.max(np.abs(x)))


class SpeechGate:
    """Решает, где кончилась фраза. webrtcvad в контейнере нет, поэтому
    энергия: порог плывёт вместе с шумом комнаты, а после тишины держится
    задержка, чтобы не резать фразу на паузе между словами.

    Кусок приходящего аудио режется на кадры по 30 мс внутри, иначе счётчик
    тишины считает куски, а не время. Тогда пауза в 780 мс распознавалась бы
    только при определённом размере куска: плата с 20 мс считала бы паузу в
    15 раз быстрее, с 500 мс - в 15 раз медленнее, и будильник молчал бы.
    """

    def __init__(self, speech_floor=500.0, ratio=3.0):
        self.frame_bytes = VAD_FRAME * 2
        self.floor = speech_floor
        self.ratio = ratio
        self.active = False
        self.loud_run = 0
        self.quiet = 0
        self.frames = 0
        self.buf = bytearray()
        self.pending = bytearray()

    def push(self, data):
        """Возвращает True, когда фраза только что закончилась."""
        self.buf += data
        self.pending += data
        while len(self.pending) >= self.frame_bytes:
            frame = bytes(self.pending[:self.frame_bytes])
            del self.pending[:self.frame_bytes]
            if self._frame(frame):
                return True
        return False

    def _frame(self, frame):
        self.frames += 1
        rms, peak = frame_rms_peak(frame)
        # фон подстраивается только пока никто не говорит, иначе колонка
        # привыкает к собственному голосу и перестаёт его слышать
        if not self.active and rms < self.floor:
            self.floor = max(300.0, min(self.floor, rms * 1.2 + 60.0))
        loud = rms > self.floor * self.ratio or peak > 12000.0
        if loud:
            self.loud_run += 1
        else:
            self.loud_run = 0
        # Открываем фразу только после двух громких кадров подряд. Без этого
        # щелчок или первый слог давали короткий обрывок.
        if not self.active and self.loud_run >= 2:
            self.active = True
            self.quiet = 0
        elif self.active and loud:
            self.quiet = 0
        elif self.active:
            self.quiet += 1
        if self.active and self.quiet >= VAD_HANGOVER:
            return True
        if self.active and self.frames >= VAD_MAX_FRAMES:
            return True
        return False

    def take(self):
        data = bytes(self.buf) + bytes(self.pending)
        self.reset()
        return data

    def reset(self):
        self.active = False
        self.loud_run = 0
        self.quiet = 0
        self.frames = 0
        self.buf = bytearray()
        self.pending = bytearray()


# ---------------------------------------------------------------------------
# Проверки. Держатся тут же, чтобы логика и её проверка не расходились, и
# запускаются без сети и без модели: python3 vendor/irene-va/jane_audio.py
# ---------------------------------------------------------------------------
def _tone(seconds, freq=220, rate=STT_RATE, amp=6000):
    t = np.arange(int(rate * seconds)) / float(rate)
    return (np.sin(2 * np.pi * freq * t) * amp).astype("<i2").tobytes()


def _silence(seconds, rate=STT_RATE):
    return b"\x00\x00" * int(rate * seconds)


def selfcheck():
    fails = []

    # 1. ресемплинг меняет длину ровно во столько раз, во сколько частота
    for src, dst in ((22050, 16000), (16000, 48000), (8000, 16000)):
        data = _tone(0.5, rate=src)
        out = pcm_resample(data, src, dst)
        want = int(len(data) // 2 * dst / src)
        got = len(out) // 2
        if abs(got - want) > want * 0.02:
            fails.append("ресемплинг %d->%d дал %d, ждали ~%d"
                         % (src, dst, got, want))
        if pcm_resample(data, dst, dst) != data:
            fails.append("ресемплинг в себя изменил данные")

    speech = _tone(1.0) + _silence(1.5)
    segments = {}
    for ms in (20, 50, 100, 500):
        g = SpeechGate()
        step = STT_RATE * ms // 1000 * 2
        closed = None
        for i in range(0, len(speech), step):
            if g.push(speech[i:i + step]):
                closed = g.take()
                break
        if closed is None:
            fails.append("кусок %d мс: фраза не закрылась" % ms)
        else:
            segments[ms] = closed

    # 2. Граница фразы не должна зависеть от размера куска по существу, но
    # отрезок может быть длиннее на один кусок: кусок приходит целиком и
    # попадает в буфер до того, как кадры внутри него обработаны. Поэтому
    # проверяем настоящий инвариант - перебор ограничен размером куска,
    # а не точное совпадение длин.
    if len(segments) > 1:
        small = len(segments[min(segments)])
        for ms, seg in sorted(segments.items()):
            limit = STT_RATE * ms // 1000 * 2
            if abs(len(seg) - small) > limit:
                fails.append("кусок %d мс дал отрезок %d байт, самый мелкий - "
                             "%d: расхождение больше одного куска (%d)"
                             % (ms, len(seg), small, limit))

    # 3. тишина не должна открывать фразу
    g = SpeechGate()
    if g.push(_silence(3.0)):
        fails.append("тишина была принята за речь")

    # 4. щелчок на один кадр не должен открывать фразу
    g = SpeechGate()
    click = _tone(0.03) + _silence(0.2)
    if g.push(click):
        fails.append("один громкий кадр открыл фразу")

    # 5. пауза короче задержки фразу не закрывает
    g = SpeechGate()
    short = _tone(1.0) + _silence(0.4)
    if g.push(short):
        fails.append("пауза в 400 мс закрыла фразу, хотя задержка 780 мс")

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    jane_audio: ресемплинг, детектор и независимость от "
              "нарезки в порядке")
    print("ИТОГ: провалено %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(selfcheck())