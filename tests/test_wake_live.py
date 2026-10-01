"""Проверка ожидания будильникового слова на живом канале устройства.

Главное здесь не «сообщение пришло», а две вещи, которые снаружи не видны:

1. Плата с локальным словом после hello СПИТ и не отвечает на звук.
2. Пришедший во сне поток действительно отбрасывается, а не распознаётся.

Второе - единственная причина, по которой режим ожидания вообще экономит
трафик и нагрузку. Если проверять только «плата подключилась», смысла в нём
нет: можно годами считать колонку умной, а сервер всё это время распознавал
пустую комнату.

    python tests/test_wake_live.py
"""
import asyncio, json, struct, sys, urllib.parse, urllib.request

URL = "wss://antonpetnitsky.com/kolonka/api/ws/device"
API = "https://antonpetnitsky.com/kolonka/api"
PHRASE = "какая сейчас погода"
RATE = 22050
fails = []


def ok(m):   print("OK    " + m)
def bad(m):  print("FAIL  " + m); fails.append(m)
def info(m): print("      " + m)


def tts_bytes(text):
    u = API + "/tts?text=" + urllib.parse.quote(text)
    return urllib.request.urlopen(u, timeout=120).read()


def wav_rate(data):
    """Частота из заголовка RIFF, а не из памяти."""
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


async def wait(ws, t=30):
    return await asyncio.wait_for(ws.recv(), t)


async def drain(ws, t):
    """Что сервер сказал за t секунд, пока ничего не ждали. None - молчание."""
    try:
        m = await asyncio.wait_for(ws.recv(), t)
    except asyncio.TimeoutError:
        return None
    if isinstance(m, bytes):
        return "bytes %d" % len(m)
    return json.loads(m).get("type")


async def device_state(dev_id):
    j = json.load(urllib.request.urlopen(API + "/wsDevices", timeout=30))
    for d in (j.get("devices") or []):
        if d.get("id") == dev_id:
            return d
    return None


async def run():
    import websockets
    speech = tts_bytes(PHRASE)
    rate = wav_rate(speech)
    info("речь %r: %d байт, частота по заголовку %s Гц"
         % (PHRASE, len(speech), rate))
    if rate != 22050:
        bad("синтез отдал %s Гц вместо 22050" % rate)
        return

    async with websockets.connect(URL, open_timeout=60, max_size=16 * 1024 * 1024,
                                  ping_interval=None) as ws:
        ready = json.loads(await wait(ws))
        if ready.get("type") != "ready":
            bad("первым пришло не ready: %r" % ready.get("type"))
            return
        ok("сервер готов: stt=%s tts=%s" % (ready.get("stt"), ready.get("tts")))

        # Плата объявляет, что умеет ловить будильниковое слово сама.
        await ws.send(json.dumps({"type": "hello", "rate": rate,
                                  "local_wake": True, "wake": "дженет"}))
        hello_ok = None
        for _ in range(4):
            m = json.loads(await wait(ws))
            info("от сервера: %s" % json.dumps(m, ensure_ascii=False))
            if m.get("type") == "hello-ok":
                hello_ok = m
                break
        if hello_ok is None:
            bad("сервер не ответил hello-ok")
            return

        ok("сервер принял плату")
        if hello_ok.get("local_wake") is True:
            ok("плата знает, что слово локальное")
        else:
            bad("плата не знает, что слово локальное")
        if hello_ok.get("state") == "sleeping":
            ok("после hello плата спит")
        else:
            bad("после hello плата не спит: %s" % hello_ok.get("state"))
        if "listen_window" in hello_ok:
            bad("локальной плате окно прослушивания не нужно")

        dev_id = hello_ok.get("id")

        # --- поток во сне ------------------------------------------------
        # Настоящую речь шлём, а не гудок: если бы сервер её распознал, пришёл
        # бы heard. Молчание означает, что на неё не потратили ни секунды.
        chunk = int(rate * 0.1) * 2
        for i in range(0, len(speech), chunk):
            await ws.send(speech[i:i + chunk])
            await asyncio.sleep(0.005)
        spoke = await drain(ws, 4)
        if spoke is None:
            ok("речь во сне отброшена, сервер не распознавал")
        else:
            bad("сервер ответил на спящую плату: %s" % spoke)

        st = await device_state(dev_id)
        if st:
            info("в реестре: %s" % json.dumps(st, ensure_ascii=False))
            if (st.get("dropped") or 0) > 0:
                ok("реестр видит отброшенные пакеты (%d)" % st["dropped"])
            else:
                bad("реестр не видит отброшенные: %s" % st.get("dropped"))
            if st.get("wake") == "sleeping":
                ok("реестр показывает сон")
            else:
                bad("реестр показывает %s" % st.get("wake"))
        else:
            bad("платы нет в реестре")

        # --- поймали слово -------------------------------------------------
        await ws.send(json.dumps({"type": "wake"}))
        r = json.loads(await wait(ws))
        if r.get("type") == "listening":
            ok("после слова плата слушает")
        else:
            bad("после слова пришло %s" % r.get("type"))
            return

        st_before = await device_state(dev_id)
        for i in range(0, len(speech), chunk):
            await ws.send(speech[i:i + chunk])
            await asyncio.sleep(0.005)
        await ws.send(b"\x00\x00" * int(rate * 1.5))

        heard = text = None
        deadline = asyncio.get_event_loop().time() + 90
        while asyncio.get_event_loop().time() < deadline:
            try:
                m = await asyncio.wait_for(ws.recv(), 20)
            except asyncio.TimeoutError:
                break
            if isinstance(m, bytes):
                continue
            d = json.loads(m)
            t = d.get("type")
            if t == "heard":
                heard = d.get("text") or ""
            elif t == "text":
                text = d.get("text") or ""
                break
        if heard:
            ok("проснувшаяся плата распознана: %r" % heard[:44])
        else:
            bad("проснувшаяся плата не распознана")
        if text:
            ok("колонка ответила: %r" % text[:44])

        st_after = await device_state(dev_id)
        if st_after and (st_after.get("dropped") or 0) == (st_before or {}).get("dropped", 0):
            ok("пока плата слушает, аудио не отбрасывается")
        else:
            bad("аудио в бодрствующем состоянии всё равно отбросили")

        # --- сервер усыпляет плату сам --------------------------------------
        # Ответ приходит раньше голоса, а голос синтезируется долго. Поэтому
        # ждём именно sleeping, пропуская wav и всё прочее, - иначе проверка
        # падала бы на скорости синтеза, а не на логике сна.
        nap = None
        deadline = asyncio.get_event_loop().time() + 90
        while asyncio.get_event_loop().time() < deadline:
            try:
                m = await asyncio.wait_for(ws.recv(), 25)
            except asyncio.TimeoutError:
                break
            if isinstance(m, bytes):
                continue
            d = json.loads(m)
            if d.get("type") == "sleeping":
                nap = "sleeping"
                break
        if nap == "sleeping":
            ok("сервер усыпил плату сам")
        else:
            bad("после ответа не пришло sleeping")

        st_sleep = await device_state(dev_id)
        for i in range(0, len(speech), chunk):
            await ws.send(speech[i:i + chunk])
            await asyncio.sleep(0.005)
        await asyncio.sleep(2)
        st_end = await device_state(dev_id)
        grew = (st_end.get("dropped") or 0) - (st_sleep.get("dropped") or 0)
        if (st_end.get("wake") == "sleeping" and grew > 0) or grew > 0:
            ok("после ответа поток отбрасывается (+%d пакетов)" % grew)
        else:
            bad("после ответа поток не отбрасывается: %s -> %s"
                % (st_sleep.get("wake"), st_end.get("wake")))

    # --- плата без локального слова: окна, а не вечный микрофон ------------
    async with websockets.connect(URL, open_timeout=60, max_size=16 * 1024 * 1024,
                                  ping_interval=None) as ws2:
        await ws2.recv()
        await ws2.send(json.dumps({"type": "hello", "rate": rate,
                                   "local_wake": False, "wake": ""}))
        h2 = json.loads(await wait(ws2))
        info("плата без локального слова: %s" % json.dumps(h2, ensure_ascii=False))
        if h2.get("type") == "listen":
            ok("без локального слова сервер открывает окна")
        else:
            bad("без локального слова пришло %s" % h2.get("type"))
        if 0 < (h2.get("listen_window") or 0) <= 30:
            ok("окно прослушивания разумное: %s с" % h2.get("listen_window"))
        else:
            bad("окно прослушивания неразумное: %s" % h2.get("listen_window"))


if __name__ == "__main__":
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("нужен websockets: pip install websockets")
        sys.exit(2)
    asyncio.run(run())
    print()
    print("ИТОГ: провалено %d" % len(fails))
    sys.exit(1 if fails else 0)
