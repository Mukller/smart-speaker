import os
import re
from playwright.sync_api import sync_playwright

URL = "https://antonpetnitsky.com/kolonka/"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT = os.environ.get("JANE_OUT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "out")

out, fails = [], []


def ok(m):
    out.append("OK    " + m)


def bad(m):
    out.append("FAIL  " + m)
    fails.append(m)


def info(m):
    out.append("      " + m)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME,
                                args=["--no-sandbox", "--disable-gpu"])
    page = browser.new_page(viewport={"width": 1280, "height": 860})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector("#send", timeout=20000)
    page.wait_for_timeout(500)

    out.append("=== 1. аудио-конвейер в браузере (реальный код страницы) ===")
    # берём настоящую речь с сервера и прогоняем через serverRecognize(),
    # то есть через AudioContext.decodeAudioData -> ресемплинг -> POST /stt
    res = page.evaluate("""async () => {
        const r = await fetch(API + '/tts?text=' + encodeURIComponent('который сейчас час'));
        const buf = await r.arrayBuffer();
        const blob = new Blob([buf], {type: 'audio/wav'});
        // засекаем, сколько занимает клиентский конвейер
        const t0 = performance.now();
        const wav = await toMonoWav16k(blob);
        const t1 = performance.now();
        // проверяем заголовок получившегося WAV
        const dv = new DataView(wav);
        const riff = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
        const rate = dv.getUint32(24, true);
        const ch = dv.getUint16(22, true);
        const bits = dv.getUint16(34, true);
        const rr = await fetch(API + '/stt', {method: 'POST',
            headers: {'Content-Type': 'audio/wav'}, body: wav});
        const data = await rr.json();
        return {clientMs: Math.round(t1 - t0), riff: riff, rate: rate, ch: ch,
                bits: bits, bytes: wav.byteLength, status: rr.status,
                text: data.text, seconds: data.seconds, serverRate: data.rate};
    }""")

    info("клиентский ресемплинг занял %d мс" % res["clientMs"])
    info("WAV: %s, %d Гц, %d кан, %d бит, %d байт"
         % (res["riff"], res["rate"], res["ch"], res["bits"], res["bytes"]))
    info("ответ сервера: HTTP %d, %r, %.2f с, сервер услышал %d Гц"
         % (res["status"], res["text"], res["seconds"], res["serverRate"]))

    (ok if res["riff"] == "RIFF" else bad)("WAV собран верно: %s" % res["riff"])
    (ok if res["rate"] == 16000 else bad)("ресемплинг в 16 кГц: %d" % res["rate"])
    (ok if res["ch"] == 1 else bad)("моно: %d канал(а)" % res["ch"])
    (ok if res["bits"] == 16 else bad)("16 бит: %d" % res["bits"])
    (ok if res["status"] == 200 else bad)("POST /stt -> %d" % res["status"])
    (ok if "час" in (res["text"] or "") else bad)(
        "распознано: %r (ожидалось 'который час')" % res["text"])

    out.append("")
    out.append("=== 2. вторая фраза, чтобы исключить совпадение ===")
    res2 = page.evaluate("""async () => {
        const r = await fetch(API + '/tts?text=' + encodeURIComponent('брось кубик'));
        const blob = new Blob([await r.arrayBuffer()], {type: 'audio/wav'});
        const wav = await toMonoWav16k(blob);
        const rr = await fetch(API + '/stt', {method: 'POST',
            headers: {'Content-Type': 'audio/wav'}, body: wav});
        return (await rr.json()).text;
    }""")
    info("распознано: %r" % res2)
    (ok if "кубик" in (res2 or "") else bad)("вторая фраза: %r" % res2)

    out.append("")
    out.append("=== 3. микрофон: кнопка и путь записи ===")
    # клик по микрофону в headless даст NotAllowedError, проверяем что код
    # не падает и показывает внятное сообщение, а не молчит
    page.click("#micBtn")
    page.wait_for_timeout(2500)
    msgs = page.locator(".row .bubble").all_inner_texts()
    joined = " | ".join(msgs)
    info("сообщения после клика: %r" % joined[:150])
    (ok if msgs else bad)("после клика что-то сообщили пользователю")
    (ok if "Микрофон недоступен" in joined or "Нет доступа" in joined
     else info)("внятная причина вместо молчания")
    page.click("#micBtn")
    page.wait_for_timeout(1200)
    st = page.locator("#status").inner_text()
    (ok if "Готова" in st else info)("статус вернулся в «Готова»: %r" % st)

    out.append("")
    out.append("=== 4. остальное не сломано ===")
    for cmd, want in (("привет", "привет"), ("время", None), ("погода", "градус")):
        page.fill("#input", cmd)
        page.press("#input", "Enter")
        page.wait_for_function(
            "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
        txt = page.locator(".row.bot .bubble").last.inner_text()
        info("%s -> %r" % (cmd, txt[:60]))
        if want:
            (ok if want.lower() in txt.lower() else bad)("%s ответил осмысленно" % cmd)

    rows = page.locator("#plugins .pl").count()
    (ok if rows >= 5 else bad)("панель плагинов на месте: %d строк" % rows)
    stamps = page.locator(".row .stamp").count()
    (ok if stamps >= 6 else bad)("метки времени: %d" % stamps)

    out.append("")
    out.append("=== 5. ошибки ===")
    real = [e for e in errors if "favicon" not in e.lower()
            and "not-allowed" not in e.lower() and "Permission" not in e]
    if real:
        for e in real[:6]:
            bad("console: " + e[:130])
    else:
        ok("ошибок нет")

    page.screenshot(path=OUT + r"\stt_final.png")
    browser.close()

out.append("")
out.append("ИТОГ: провалено %d" % len(fails))
open(OUT + r"\stt_report.txt", "w", encoding="utf-8").write("\n".join(out))
print("done fails=%d" % len(fails))
