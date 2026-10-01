#!/usr/bin/env python3
"""Детектор обязан работать одинаково при любом размере куска.

Это и есть смысл проверки: раньше счётчик тишины считал куски, а не кадры,
поэтому одна и та же фраза распознавалась или нет в зависимости от того, как
плата нарезает поток. Гоняем речь кусками 20, 50, 100, 500 мс и тишину после
неё, и результат должен совпасть.
"""
import io, sys, urllib.request, urllib.parse, wave
sys.path.insert(0, "/app/vendor/irene-va")
import runva_webapi as A

API = "http://127.0.0.1:5003"
u = "%s/tts?text=%s" % (API, urllib.parse.quote("какая сейчас погода"))
raw = urllib.request.urlopen(u, timeout=120).read()
with wave.open(io.BytesIO(raw), "rb") as w:
    rate = w.getframerate()
    pcm = w.readframes(w.getnframes())

if not A._stt_ready():
    print("модель не загрузилась:", A._stt["err"])
    raise SystemExit(1)

print("фраза: %d байт при %d Гц" % (len(pcm), rate))
# ресемплим один раз, как это делает канал. Раньше детектор получал звук
# 22050 Гц и считал кадры по 30 мс, то есть на деле по 20 мс, а потом
# распознавал этот кусок как 16000 Гц. Совпадение не доказывало ничего.
conv = A._pcm_resample(pcm, rate, 16000)
info_speech = conv
print("после пересчёта в 16 кГц: %d байт" % len(conv))
print("задержка тишины: %d кадров по 30 мс = %.0f мс"
      % (A.DEV_VAD_HANGOVER, A.DEV_VAD_HANGOVER * 30))
print("")
bad = 0
for ms in (20, 50, 100, 500):
    g = A._SpeechGate()
    step = 16000 * ms // 1000 * 2
    closed = 0
    recognized = ""
    for i in range(0, len(conv), step):
        if g.push(conv[i:i + step]):
            closed += 1
            recognized = A._recognize_wav(g.take(), 16000)
            break
    if not closed:
        # тишины нужно не меньше задержки (780 мс) независимо от размера
        # куска: раньше тут стояло три порции, и при куске 20 мс это 30 мс -
        # детектор физически не мог закрыть фразу, и проверка объявляла его
        # сломанным
        need = int(1500 / ms) + 1
        for _ in range(need):
            if g.push(b"\x00\x00" * (step // 2)):
                closed += 1
                recognized = A._recognize_wav(g.take(), 16000)
                break
    whole = "да я сейчас по" not in recognized and recognized.strip() != ""
    mark = "OK   " if whole else "ПРОВАЛ"
    if not whole:
        bad += 1
    print("%s кусок %3d мс: фраз закрыто %d, распознано %r"
          % (mark, ms, closed, recognized))

print("")
print("ИТОГ: расхождений %d" % bad)
