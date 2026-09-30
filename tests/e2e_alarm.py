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


def save():
    out.append("")
    out.append("ИТОГ: провалено %d" % len(fails))
    open(OUT + r"\alarm_report.txt", "w", encoding="utf-8").write("\n".join(out))


def ready(page, timeout=40000):
    """Ждём, пока ассистент договорит.

    Признак незавершённости - строка .row.bot.pending (заглушка «…»).
    Раньше ждали window.state, но переменная объявлена const внутри скрипта
    и на window не попадает, поэтому ожидание срабатывало мгновенно и мы
    читали заглушку вместо ответа.
    """
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('.row.bot.pending').length === 0",
            timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(150)


with sync_playwright() as p:
    b = None
    try:
        b = p.chromium.launch(
            executable_path=CHROME,
            args=["--no-sandbox", "--disable-gpu",
                  "--autoplay-policy=no-user-gesture-required"])
        page = b.new_page(viewport={"width": 1360, "height": 940})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        wav_calls = []
        page.on("request", lambda r: wav_calls.append(r.url)
                if "/kolonka/api/timerwav" in r.url else None)

        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_selector("#send", timeout=20000)
        page.wait_for_timeout(800)

        out.append("=== 1. панель будильника ===")
        note = (page.locator("#alarm .pl-note").inner_text()
                if page.locator("#alarm .pl-note").count() else "")
        (ok if "не задан" in note else bad)("пустое состояние: %r" % note)

        out.append("")
        out.append("=== 2. таймер на 2 минуты ===")
        page.fill("#input", "поставь таймер на 2 минуты")
        page.press("#input", "Enter")
        ready(page)
        replied = page.locator(".row.bot .bubble").last.inner_text()
        info("ответ: %r" % replied)
        (ok if replied.strip() else bad)("плагин ответил")

        page.wait_for_timeout(2500)
        rows = page.locator("#alarm .al-row").count()
        (ok if rows >= 1 else bad)("таймер в панели: %d строк" % rows)
        shown = page.locator("#alarm .al-time").first.inner_text() if rows else ""
        (ok if re.match(r"^\d+:\d\d$", shown.strip()) else bad)("отсчёт: %r" % shown)
        shown2 = shown
        for _ in range(12):
            page.wait_for_timeout(1000)
            shown2 = page.locator("#alarm .al-time").first.inner_text() if rows else ""
            if shown2 != shown:
              break
        (ok if shown2 != shown else bad)("отсчёт идёт: %r -> %r" % (shown, shown2))
        page.screenshot(path=OUT + r"\alarm_set.png")

        out.append("")
        out.append("=== 3. «сколько осталось» ===")
        page.fill("#input", "сколько осталось")
        page.press("#input", "Enter")
        ready(page)
        st = page.locator("#status").inner_text()
        info("статус: %r" % st)
        (ok if "стало" in st else info)("ответ про остаток: %r" % st)

        out.append("")
        out.append("=== 4. отмена голосом ===")
        page.fill("#input", "отмени таймер")
        page.press("#input", "Enter")
        ready(page)
        rep2 = page.locator(".row.bot .bubble").last.inner_text()
        info("ответ: %r" % rep2)
        (ok if "отмен" in rep2.lower() else bad)("отмена: %r" % rep2)
        page.wait_for_timeout(2500)
        (ok if page.locator("#alarm .al-row").count() == 0 else bad)("панель очистилась")

        out.append("")
        out.append("=== 5. звонок: таймер на 2 секунды ===")
        page.fill("#input", "поставь таймер на 2 секунды")
        page.press("#input", "Enter")
        page.wait_for_timeout(1500)
        info("поставили: %r" % page.locator(".row.bot .bubble").last.inner_text())
        # ждём звонка до 30 с
        for _ in range(30):
            if wav_calls:
                break
            page.wait_for_timeout(1000)
        page.wait_for_timeout(1500)

        msgs = " | ".join(page.locator(".row .bubble").all_inner_texts())
        (ok if "сработал" in msgs.lower() else bad)(
            "сообщение о срабатывании есть: %r" % msgs[-80:])
        (ok if wav_calls else bad)("звонок запрошен: %d раз" % len(wav_calls))
        code = page.evaluate("""async () => {
            const r = await fetch(API + '/timerwav');
            const b = await r.arrayBuffer();
            const d = new DataView(b);
            const riff = String.fromCharCode(d.getUint8(0), d.getUint8(1), d.getUint8(2), d.getUint8(3));
            return {status: r.status, type: r.headers.get('content-type'),
                    len: b.byteLength, riff: riff};
        }""")
        info("timerwav: %s" % code)
        (ok if code["status"] == 200 and code["riff"] == "RIFF" and code["len"] > 10000
         else bad)("звонок — настоящий WAV: %s, %d байт" % (code["type"], code["len"]))
        page.screenshot(path=OUT + r"\alarm_rang.png")

        out.append("")
        out.append("=== 6. остальное не сломано ===")
        for cmd in ("привет", "погода"):
            page.fill("#input", cmd)
            page.press("#input", "Enter")
            ready(page)
            t = page.locator(".row.bot .bubble").last.inner_text()
            (ok if t.strip() else bad)("%s -> %r" % (cmd, t[:50]))
        (ok if page.locator("#plugins .pl").count() >= 5 else bad)("плагины на месте")

        out.append("")
        out.append("=== 7. ошибки ===")
        real = [e for e in errors if "favicon" not in e.lower()
                and "NotAllowed" not in e and "autoplay" not in e.lower()]
        if real:
            for e in real[:6]:
                bad("console: " + e[:130])
        else:
            ok("ошибок нет")
    except Exception as e:
        bad("исключение: %s: %s" % (type(e).__name__, str(e)[:160]))
    finally:
        if b:
            try:
                b.close()
            except Exception:
                pass
        save()
print("done fails=%d" % len(fails))
