#!/usr/bin/env python3
"""Проверка канала устройства.

Клиент притворяется платой: подключается, объявляет частоту микрофона и льёт
настоящую речь кусками, как живой микрофон. Ждёт, что сервер сам поймёт конец
фразы, распознает и ответит голосом.

Частота в hello ставится 22050, потому что WAV из /tts именно такой: так
одновременно проверяется, что сервер пересчитывает поток в 16 кГц сам. Раньше
тест объявлял 16000 и кормил сервер звуком 22050 - тот принимал шум за речь,
и проверка падала с враньём, что канал не работает.
"""
import asyncio, json, sys, urllib.request, urllib.parse
import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:5003/ws/device"
API = "http://127.0.0.1:5003"
PHRASE = "какая сейчас погода"

fails = []
def ok(m):   print("OK    " + m)
def bad(m):  print("FAIL  " + m); fails.append(m)
def info(m): print("      " + m)


def tts_bytes(text):
    u = "%s/tts?text=%s" % (API, urllib.parse.quote(text))
    return urllib.request.urlopen(u, timeout=120).read()


def wav_rate(data):
    """Частота из заголовка RIFF: тест не должен полагаться на память."""
    import struct
    if data[:4] != b"RIFF":
        return 0
    i = 12
    while i + 8 <= len(data):
        cid = data[i:i + 4]
        sz = struct.unpack("<I", data[i + 4:i + 8])[0]
        if cid == b"fmt ":
            return struct.unpack("<I", data[i + 12:i + 16])[0]
        i += 8 + sz + (sz & 1)
    return 0


async def main():
    speech = tts_bytes(PHRASE)
    rate = wav_rate(speech)
    info("фраза %r: %d байт, частота по заголовку %s Гц"
         % (PHRASE, len(speech), rate))
    if rate != 22050:
        bad("тест ждёт 22050 Гц от синтеза, а пришло %s" % rate)
        return

    async with websockets.connect(URL, max_size=16 * 1024 * 1024) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), 20))
        if hello.get("type") != "ready":
            bad("первым пришло не ready: %r" % hello)
            return
        ok("сервер готов: stt=%s tts=%s" % (hello.get("stt"), hello.get("tts")))

        # local_wake false - плата без локального слова: она честно шлёт
        # непрерывный поток, и сервер открывает ей окна. По умолчанию здесь
        # local_wake true, и такой тест просто уснул бы, а его речь была бы
        # отброшена: проверка падала бы с враньём, что канал не работает.
        await ws.send(json.dumps({"type": "hello", "rate": rate, "wake": "",
                                  "local_wake": False}))
        h2 = json.loads(await asyncio.wait_for(ws.recv(), 20))
        if h2.get("type") not in ("hello-ok", "listen"):
            bad("hello не принят: %r" % h2)
            return
        ok("hello принят, сервер пересчитает в %s Гц" % h2.get("want_rate"))

        chunk = int(rate * 0.1) * 2
        for i in range(0, len(speech), chunk):
            await ws.send(speech[i:i + chunk])
            await asyncio.sleep(0.01)
        await ws.send(b"\x00\x00" * int(rate * 1.2))
        info("речь отправлена, ждём ответ...")

        got_heard = got_text = None
        got_wav = 0
        deadline = asyncio.get_event_loop().time() + 90
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), 20)
            except asyncio.TimeoutError:
                info("тишина от сервера")
                break
            if isinstance(msg, bytes):
                got_wav += len(msg)
                continue
            d = json.loads(msg)
            t = d.get("type")
            if t == "heard":
                got_heard = d
                info("услышано: %r" % d.get("text"))
            elif t == "text":
                got_text = d
                info("ответ: %r из %s" % (d.get("text"), d.get("source")))
                if got_wav == 0:
                    continue      # голос может прийти сразу после текста
                break
            elif t == "error":
                bad("ошибка от сервера: %s" % d.get("message"))
                break

        if got_heard and got_heard.get("text"):
            ok("сервер распознал речь сам, без кнопки: %r" % got_heard["text"][:40])
        else:
            bad("речь не распознана")
        if got_text and got_text.get("text"):
            ok("колонка ответила: %s" % got_text["text"][:60])
        else:
            bad("ответа не было")
        if got_wav:
            ok("ответ пришёл голосом: %d байт" % got_wav)
        else:
            bad("голоса в ответе не было")


asyncio.run(main())
print("")
print("ИТОГ: провалено %d" % len(fails))
