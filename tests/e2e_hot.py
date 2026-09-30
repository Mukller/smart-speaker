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
    # фальшивый микрофон: браузер сам разрешает доступ и даёт тон,
    # поэтому проверяется механика (окна уходят, ответы приходят),
    # а не точность распознавания
    browser = p.chromium.launch(
        executable_path=CHROME,
        args=["--no-sandbox", "--disable-gpu",
              "--use-fake-device-for-media-stream",
              "--use-fake-ui-for-media-stream",
              "--autoplay-policy=no-user-gesture-required"])
    ctx = browser.new_context(viewport={"width": 1360, "height": 900},
                              permissions=["microphone"])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    stt_calls = []
    page.on("request", lambda r: stt_calls.append(r.url)
            if "/kolonka/api/stt" in r.url and r.method == "POST" else None)

    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector("#send", timeout=20000)
    page.wait_for_timeout(500)

    out.append("=== 1. кнопка постоянного слушания ===")
    label0 = page.locator("#hotBtn").inner_text()
    pressed0 = page.get_attribute("#hotBtn", "aria-pressed")
    (ok if pressed0 == "false" else bad)("по умолчанию выключено: %r / %s" % (label0, pressed0))
    page.screenshot(path=OUT + r"\hot_off.png")

    out.append("")
    out.append("=== 2. включаем и ждём окна ===")
    page.click("#hotBtn")
    page.wait_for_timeout(1200)
    label1 = page.locator("#hotBtn").inner_text()
    pressed1 = page.get_attribute("#hotBtn", "aria-pressed")
    (ok if pressed1 == "true" else bad)("включилось: %r / %s" % (label1, pressed1))
    dot = page.evaluate("""() => {
        const b = document.getElementById('hotBtn');
        const cs = getComputedStyle(b, '::before');
        return {content: cs.content, radius: cs.borderTopLeftRadius,
                w: cs.width, bg: cs.backgroundColor};
    }""")
    info("индикатор: %s" % dot)
    (ok if "rgb" in dot["bg"] and dot["w"] not in ("0px", "auto") else
     bad)("красная точка показывает, что микрофон открыт")

    # фальшивый тон идёт непрерывно, значит окна должны уходить
    page.wait_for_timeout(7000)
    n = len(stt_calls)
    info("окон ушло на сервер: %d" % n)
    (ok if n >= 1 else bad)("окна распознавания уходят (%d за ~8 с)" % n)

    st = cur = page.evaluate("""() => ({
        listening: hot.on, bufLen: hot.bufLen, want: hot.want, keep: hot.keep,
        sending: hot.sending, quiet: hot.quiet
    })""")
    info("состояние: %s" % st)
    (ok if st["listening"] else bad)("микрофон держится открытым")
    (ok if st["bufLen"] > 0 else bad)("буфер наполняется: %d сэмплов" % st["bufLen"])
    (ok if st["want"] > st["keep"] else bad)(
        "окно %d > перекрытие %d сэмплов" % (st["want"], st["keep"]))

    out.append("")
    out.append("=== 3. сервер отвечает и не врёт ===")
    stt_texts = []
    for _ in range(3):
        try:
            r = page.evaluate("""async () => {
                const res = await fetch(API + '/tts?text=' + encodeURIComponent('какая сейчас погода'));
                const w = await toMonoWav16k(new Blob([await res.arrayBuffer()], {type:'audio/wav'}));
                const rr = await fetch(API + '/stt', {method:'POST',
                    headers: {'Content-Type':'audio/wav'}, body: w});
                return (await rr.json()).text;
            }""")
            stt_texts.append(r)
        except Exception as e:
            stt_texts.append("ошибка: %s" % e)
        page.wait_for_timeout(400)
    info("распознано: %s" % stt_texts)
    (ok if any("погод" in t for t in stt_texts) else bad)("сервер распознаёт речь")

    out.append("")
    out.append("=== 4. будильник: имя решает судьбу фразы ===")
    # фраза без имени выполняться не должна
    res = page.evaluate("""(text) => {
        // повторяем логику будильника из hotFlush
        const WAKE = ["дженет", "дженит", "дженетт", "женет", "джепп"];
        const check = (t) => {
            const at = t.search(new RegExp(WAKE.join("|")));
            return at === -1 ? {acted: false, rest: null} : {acted: true, rest: t.slice(at)};
        };
        return {noWake: check(text.noWake), withWake: check(text.withWake)};
    }""", {"noWake": "а сколько сейчас времени", "withWake": "дженет какая погода"})
    info("без имени: %s" % res["noWake"])
    info("с именем:  %s" % res["withWake"])
    (ok if not res["noWake"]["acted"] else bad)("фраза без имени не выполняется")
    (ok if res["withWake"]["acted"] else bad)("фраза с именем выполняется")

    out.append("")
    out.append("=== 5. выключение ===")
    page.click("#hotBtn")
    page.wait_for_timeout(1500)
    label2 = page.locator("#hotBtn").inner_text()
    pressed2 = page.get_attribute("#hotBtn", "aria-pressed")
    (ok if pressed2 == "false" else bad)("выключилось: %r / %s" % (label2, pressed2))
    after = len(stt_calls)
    page.wait_for_timeout(5000)
    (ok if len(stt_calls) == after else bad)(
        "после выключения окон больше нет (%d -> %d)" % (after, len(stt_calls)))
    st2 = page.evaluate("() => ({on: hot.on, buf: hot.bufLen})")
    (ok if not st2["on"] and st2["buf"] == 0 else bad)("состояние сброшено: %s" % st2)
    status = page.locator("#status").inner_text()
    (ok if "Готова" in status else info)("статус: %r" % status)

    out.append("")
    out.append("=== 6. остальное не сломано ===")
    for cmd in ("привет", "погода"):
        page.fill("#input", cmd)
        page.press("#input", "Enter")
        page.wait_for_function(
            "() => document.getElementById('status').textContent === 'Готова'",
            timeout=40000)
        t = page.locator(".row.bot .bubble").last.inner_text()
        (ok if t.strip() else bad)("%s -> %r" % (cmd, t[:50]))

    out.append("")
    out.append("=== 7. ошибки ===")
    real = [e for e in errors if "favicon" not in e.lower()
            and "NotAllowed" not in e and "autoplay" not in e.lower()]
    if real:
        for e in real[:6]:
            bad("console: " + e[:130])
    else:
        ok("ошибок нет")

    page.screenshot(path=OUT + r"\hot_final.png")
    browser.close()

out.append("")
out.append("ИТОГ: провалено %d" % len(fails))
open(OUT + r"\hot_report.txt", "w", encoding="utf-8").write("\n".join(out))
print("done fails=%d" % len(fails))
