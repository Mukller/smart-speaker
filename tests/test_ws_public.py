#!/usr/bin/env python3
"""Канал снаружи, через nginx: рукопожатие и разговор.

Проверяем wss:// - то есть именно то, как к колонке подключится плата.
Если nginx не передаёт Upgrade, соединение закрывается на рукопожатии, а
все HTTP-эндпоинты рядом продолжают отвечать 200 - полезно знать, что
именно так это и выглядит снаружи.
"""
import asyncio, json, sys, urllib.request, urllib.parse
import websockets

URL = "wss://antonpetnitsky.com/kolonka/api/ws/device"
API = "https://antonpetnitsky.com/kolonka/api"

fails = []
def ok(m):   print("OK    " + m)
def bad(m):  print("FAIL  " + m); fails.append(m)
def info(m): print("      " + m)


async def main():
    try:
        async with websockets.connect(URL, max_size=16 * 1024 * 1024,
                                      open_timeout=25) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 20))
    except Exception as e:
        bad("не подключился через nginx: %s: %s" % (type(e).__name__, e))
        return

    if hello.get("type") != "ready":
        bad("первым пришло не ready: %r" % hello)
        return
    ok("рукопожатие через nginx прошло, сервер ответил: stt=%s tts=%s"
       % (hello.get("stt"), hello.get("tts")))

    await ws.send(json.dumps({"type": "hello", "rate": 16000, "wake": ""}))
    h2 = json.loads(await asyncio.wait_for(ws.recv(), 20))
    if h2.get("type") == "hello-ok":
        ok("поток принят, сервер пересчитает в %s Гц" % h2.get("want_rate"))
    else:
        bad("hello не принят: %r" % h2)
        return

    # короткая проверка: плата шлёт тишину, ответа быть не должно,
    # но соединение обязано остаться живым
    await ws.send(b"\x00\x00" * 3200)
    await asyncio.sleep(0.5)
    try:
        await ws.send(json.dumps({"type": "ping"}))
        r = json.loads(await asyncio.wait_for(ws.recv(), 10))
        info("ответ на неизвестный тип: %r" % r)
    except websockets.ConnectionClosed:
        bad("соединение закрылось на живом потоке")
        return
    ok("соединение держится на потоке и отвечает")

asyncio.run(main())
print("")
print("ИТОГ: провалено %d" % len(fails))