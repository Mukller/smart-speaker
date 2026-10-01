#!/usr/bin/env python3
"""Детектор речи без сети и без моделей.

Детектор — чистая логика, ему не нужны ни модель распознавания, ни сеть,
ни готовая запись. Именно поэтому его стоит гонять в CI на каждом коммите:
настройка порога тишины ломает фразы совершенно незаметно, и заметить это
можно было только живым разговором.

Звук синтетический: громкий тон - это «речь», тишина - пауза. Проверяем то,
что реально ломалось: фраза закрывается после паузы в 780 мс, при любом
размере куска одинаково, тишина сама по себе фразу не закрывает, а
бесконечный шум обрывается предохранителем.
"""
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Ищем корень с исходниками в нескольких местах: при запуске из репозитория
# это соседний vendor/irene-va, а в контейнере и в CI файл может лежать
# отдельно, и путь от __file__ тогда указывает в никуда.
CANDIDATES = [
    os.path.join(REPO, "vendor", "irene-va"),
    os.path.join(REPO, "irene-va"),
    "/app/vendor/irene-va",
    os.getcwd(),
]
for cand in CANDIDATES:
    if os.path.isfile(os.path.join(cand, "runva_webapi.py")):
        sys.path.insert(0, cand)
        break
else:
    print("runva_webapi.py не найден, искали в: %r" % CANDIDATES)
    raise SystemExit(2)

try:
    import runva_webapi as A
except Exception as e:
    print("НЕ УДАЛОСЬ импортировать runva_webapi: %s: %s"
          % (type(e).__name__, e))
    print("Для этого теста нужны fastapi, uvicorn, starlette, requests, termcolor")
    raise SystemExit(2)

RATE = 16000
fails = []


def ok(m):
    print("OK    " + m)


def bad(m):
    print("FAIL  " + m)
    fails.append(m)


def tone(ms, freq=220, amp=6000):
    """«Речь»: громкий сигнал на месте голоса."""
    n = int(RATE * ms / 1000)
    out = bytearray()
    for i in range(n):
        v = int(amp * math.sin(2 * math.pi * freq * i / RATE))
        out += struct.pack("<h", v)
    return bytes(out)


def silence(ms):
    return b"\x00\x00" * int(RATE * ms / 1000)


def feed(chunk_ms, speech_ms, quiet_ms):
    """Прогоняет фразу с куском заданного размера. Возвращает
    (закрылась ли, на какой миллисекунде)."""
    g = A._SpeechGate()
    step = max(2, int(RATE * chunk_ms / 1000)) * 2
    speech = tone(speech_ms)
    sent = 0
    done_at = None

    def push_all(data):
        nonlocal sent, done_at
        for i in range(0, len(data), step):
            sent += len(data[i:i + step]) // 2
            if g.push(data[i:i + step]):
                done_at = sent * 1000 // RATE
                return True
        return False

    if push_all(speech):
        return True, done_at
    if push_all(silence(quiet_ms)):
        return True, done_at
    return False, None


print("=== настройки детектора ===")
hang_ms = A.DEV_VAD_HANGOVER * A.DEV_VAD_FRAME * 1000 // RATE
print("  кадр %d отсчётов, задержка %d кадров = %d мс, предохранитель %d кадров"
      % (A.DEV_VAD_FRAME, A.DEV_VAD_HANGOVER, hang_ms, A.DEV_VAD_MAX_FRAMES))

print("")
print("=== 1. тишина сама по себе фразу не закрывает ===")
g = A._SpeechGate()
closed = False
for _ in range(60):            # 1.8 секунды чистой тишины
    if g.push(silence(30)):
        closed = True
        break
if closed:
    bad("детектор закрыл фразу на одной тишине - колонка отвечала бы сама на себя")
else:
    ok("тишина фразу не закрывает")

print("")
print("=== 2. фраза закрывается после паузы, не раньше ===")
closed, at = feed(20, 1200, 2000)
if not closed:
    bad("фраза не закрылась вообще")
elif at is not None and at < 1200 + hang_ms - 60:
    bad("закрылась на %d мс - раньше паузы в %d мс, фраза режется на словах"
        % (at, hang_ms))
else:
    ok("закрылась на %d мс, пауза %d мс учтена" % (at or 0, hang_ms))

print("")
print("=== 3. результат не зависит от размера куска ===")
# ровно та поломка, что была: счётчик тишины считал куски, а не кадры,
# и одна фраза распознавалась или нет в зависимости от нарезки потока
results = {}
for chunk in (20, 50, 100, 500):
    closed, at = feed(chunk, 1200, 2000)
    results[chunk] = bool(closed)
    print("      кусок %3d мс: закрылась %s, на %s мс" % (chunk, closed, at))
if len(set(results.values())) == 1 and all(results.values()):
    ok("одинаково при любом размере куска")
else:
    bad("результат зависит от размера куска: %r" % results)

print("")
print("=== 4. предохранитель обрывает бесконечный шум ===")
g = A._SpeechGate()
frames = 0
closed = False
while frames < A.DEV_VAD_MAX_FRAMES + 50:
    frames += 1
    if g.push(tone(30)):
        closed = True
        break
if closed and frames <= A.DEV_VAD_MAX_FRAMES + 2:
    ok("оборвался на %d кадрах" % frames)
else:
    bad("предохранитель не сработал за %d кадров" % frames)

print("")
print("=== 5. пересчёт частоты ===")
raw = tone(100)                    # 100 мс при 22050
conv = A._pcm_resample(raw, 22050, RATE)
expect = int(len(raw) / 2 * RATE / 22050)
if abs(len(conv) // 2 - expect) <= max(2, expect * 0.05):
    ok("22050 -> 16000: %d -> %d выборок, ожидалось ~%d"
       % (len(raw) // 2, len(conv) // 2, expect))
else:
    bad("пересчёт дал %d выборок, ожидалось ~%d" % (len(conv) // 2, expect))
same = A._pcm_resample(raw, RATE, RATE)
if same == raw:
    ok("одинаковая частота - байты не трогаются")
else:
    bad("при одинаковой частоте данные изменились")

print("")
print("ИТОГ: провалено %d" % len(fails))
raise SystemExit(1 if fails else 0)