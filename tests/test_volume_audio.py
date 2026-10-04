"""Проверка, что громкость меняет звук, а не только текст ответа.

Класс бага здесь такой: колонка отвечает «Громче», сохраняет число, но сам звук
не меняется. Проверять это по ответу бессмысленно - ответ всегда правильный.
Поэтому сравниваются пики настоящих WAV-байт: одна и та же фраза, синтез на
двух громкостях.

Тест нарочно громкий в проверке. Он уже поймал то, что проверка по коду не
видит: ветка обработки звука не выполнялась вообще, потому что synth_audio
отдаёт int16, а условие ждало плавающий тип. Тогда отношение пиков было 1.1
вместо 10.

Прогон: python tests/test_volume_audio.py [url]
"""

import io
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

DEFAULT = "https://antonpetnitsky.com/kolonka/api"

PHRASE = "Проверка громкости"
MIN_10BIT = 2000      # ниже колонка на телефонных динамиках не говорит
MAX_10BIT = 29491     # 0.9 * 32767, опорный пик
STEP = 15


def _peak(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise AssertionError("неожиданный формат звука")
        raw = w.readframes(w.getnframes())
    if not raw:
        raise AssertionError("пустой звук")
    vals = []
    for i in range(0, len(raw) - 1, 2):
        v = raw[i] | (raw[i + 1] << 8)
        vals.append(v - 65536 if v > 32767 else v)
    return max(abs(v) for v in vals)


def _get(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _say(api, cmd):
    """Говорит команду. 429 - это отказ, а не «ну ладно»: молча пропустив
    его, тест сравнивал бы две одинаковые громкости и радовался бы."""
    url = api + "/sendTxtCmd?cmd=" + urllib.parse.quote(cmd)
    for attempt in range(6):
        try:
            _get(url, 120)
            time.sleep(1.5)
            return True
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            wait = 8 * (attempt + 1)
            print("   %s: лимит, жду %d с" % (cmd, wait))
            time.sleep(wait)
    raise AssertionError("лимит не отпустил после 6 попыток: " + cmd)


def _tts(api, phrase):
    return _get(api + "/tts?text=" + urllib.parse.quote(phrase), 180)


def main():
    api = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT).rstrip("/")
    fails = []

    # В упор с обеих сторон: сравнение не зависит от того, с чего колонка
    # стартовала. Шаг 15, диапазон 10..100, восемь шагов гарантированно
    # упираются в оба края.
    for _ in range(8):
        _say(api, "тише")
    lo = _peak(_tts(api, PHRASE))

    for _ in range(8):
        _say(api, "громче")
    hi = _peak(_tts(api, PHRASE))

    print("пик на минимуме: %d" % lo)
    print("пик на максимуме: %d" % hi)

    if not MIN_10BIT < hi <= MAX_10BIT:
        fails.append("на максимуме звук не выходит на опорный пик: %d" % hi)

    if not lo < hi:
        fails.append("тише не тише: %d против %d" % (lo, hi))
    else:
        ratio = hi / float(max(lo, 1))
        print("отношение: %.1f" % ratio)
        if ratio < 5:
            fails.append("громкость влияет слишком слабо: отношение %.1f" % ratio)

    # Возвращаем примерно половину, чтобы колонка не осталась на максимуме.
    for _ in range(4):
        _say(api, "тише")

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    громкость меняет звук, а не только текст ответа")
    print("ИТОГ: провалено %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())