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


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def contrast(fg, bg):
    """WCAG 2.x contrast ratio."""
    f = re.findall(r"[\d.]+", fg or "")[:3]
    b = re.findall(r"[\d.]+", bg or "")[:3]
    if len(f) < 3 or len(b) < 3:
        return 0.0
    L1 = 0.2126 * _lin(float(f[0])) + 0.7152 * _lin(float(f[1])) + 0.0722 * _lin(float(f[2]))
    L2 = 0.2126 * _lin(float(b[0])) + 0.7152 * _lin(float(b[1])) + 0.0722 * _lin(float(b[2]))
    hi, lo = max(L1, L2), min(L1, L2)
    return (hi + 0.05) / (lo + 0.05)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME,
                                args=["--no-sandbox", "--disable-gpu"])
    page = browser.new_page(viewport={"width": 1280, "height": 860})

    errors, failed, notfound = [], [], []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("requestfailed", lambda r: failed.append(r.url + " " + str(r.failure)))
    page.on("response", lambda r: notfound.append("%s -> %d" % (r.url, r.status))
            if r.status >= 400 else None)

    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector("#send", timeout=20000)

    out.append("=== 1. загрузка ===")
    ok("открылась, композер на месте")
    ok("подсказка: " + page.locator("#empty").inner_text().strip()[:50])
    info("чипы: " + " | ".join(page.locator("#chips button").all_inner_texts()))

    out.append("")
    out.append("=== 2. отправка и ожидание ответа ===")
    page.fill("#input", "привет")
    page.press("#input", "Enter")
    page.wait_for_selector(".row.bot:not(.pending) .bubble", timeout=30000)
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=20000)
    users = page.locator(".row.user .bubble").all_inner_texts()
    bots = page.locator(".row.bot .bubble").all_inner_texts()
    (ok if users else bad)("ввод: %r" % (users[0] if users else None))
    (ok if bots else bad)("ответ: %r" % (bots[-1] if bots else None))
    info("поле ввода очищено: %r" % page.input_value("#input"))

    out.append("")
    out.append("=== 3. контраст времени (WCAG, порог 4.5:1) ===")

    def stamp_pair():
        return page.evaluate("""() => {
            const s = document.querySelector('.row .stamp');
            if (!s) return null;
            let bg = 'rgba(0, 0, 0, 0)', e = s;
            while (e && bg === 'rgba(0, 0, 0, 0)') {
                bg = getComputedStyle(e).backgroundColor; e = e.parentElement;
            }
            const cs = getComputedStyle(s);
            return {color: cs.color, bg: bg, size: cs.fontSize,
                    text: s.textContent.trim()};
        }""")

    for theme, label in (("dark", "тёмная"), ("light", "светлая")):
        cur = page.evaluate("document.documentElement.getAttribute('data-theme')")
        if cur != theme:
            page.click("#themeBtn")
            page.wait_for_timeout(350)
        c = stamp_pair()
        if not c:
            bad("%s: метка не найдена" % label)
            continue
        r = contrast(c["color"], c["bg"])
        info("%s: %s на %s, %s, %r" % (label, c["color"], c["bg"], c["size"], c["text"]))
        (ok if r >= 4.5 else bad)("%s тема: контраст времени x%.2f" % (label, r))
        page.screenshot(path=OUT + ("\\e2e_dark.png" if theme == "dark"
                                    else "\\e2e_light.png"))

    if page.evaluate("document.documentElement.getAttribute('data-theme')") != "dark":
        page.click("#themeBtn")
        page.wait_for_timeout(350)

    # заголовки панели — тоже мелкий текст
    out.append("")
    out.append("=== 4. контраст заголовков панели ===")
    for theme, label in (("dark", "тёмная"), ("light", "светлая")):
        cur = page.evaluate("document.documentElement.getAttribute('data-theme')")
        if cur != theme:
            page.click("#themeBtn")
            page.wait_for_timeout(300)
        c = page.evaluate("""() => {
            const h = document.querySelector('#side h2');
            const cs = getComputedStyle(h);
            let bg = 'rgba(0, 0, 0, 0)', e = h;
            while (e && bg === 'rgba(0, 0, 0, 0)') {
                bg = getComputedStyle(e).backgroundColor; e = e.parentElement;
            }
            return {color: cs.color, bg: bg, size: cs.fontSize};
        }""")
        r = contrast(c["color"], c["bg"])
        info("%s: %s на %s, %s" % (label, c["color"], c["bg"], c["size"]))
        (ok if r >= 4.5 else bad)("%s заголовки: x%.2f" % (label, r))
    if page.evaluate("document.documentElement.getAttribute('data-theme')") != "dark":
        page.click("#themeBtn")
        page.wait_for_timeout(300)

    out.append("")
    out.append("=== 5. погода ===")
    page.fill("#input", "погода")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=30000)
    w = page.locator(".row.bot .bubble").last.inner_text().strip()
    (ok if w else bad)("погода: " + w[:80])

    out.append("")
    out.append("=== 6. ввод во время ответа не теряется ===")
    # отправляем запрос и сразу печатаем ещё текст — он обязан остаться в поле
    page.fill("#input", "назови три овоща")
    page.press("#input", "Enter")
    page.wait_for_timeout(350)
    disabled = page.evaluate("document.getElementById('send').disabled")
    (ok if disabled else bad)("кнопка «Отправить» заблокирована на время ответа")
    page.fill("#input", "мой черновик")
    page.press("#input", "Enter")
    page.wait_for_timeout(250)
    kept = page.input_value("#input")
    status_now = page.locator("#status").inner_text()
    info("в поле: %r, статус: %r" % (kept, status_now))
    (ok if kept == "мой черновик" else bad)("черновик не потерян")
    (ok if "занята" in status_now.lower() else bad)("показано объяснение: %r" % status_now)
    page.fill("#input", "")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=60000)
    ok("ответ дождался и статус вернулся в «Готова»")

    out.append("")
    out.append("=== 7. заполненная лента и прокрутка ===")
    for w in ["дата", "время", "брось кубик", "таймер 3 минуты"]:
        page.fill("#input", w)
        page.press("#input", "Enter")
        page.wait_for_function(
            "() => document.getElementById('status').textContent === 'Готова'", timeout=30000)
    page.wait_for_timeout(400)
    m = page.evaluate("""() => {
        const c = document.getElementById('chat');
        return {sh: c.scrollHeight, ch: c.clientHeight, top: c.scrollTop};
    }""")
    (ok if m["sh"] > m["ch"] else bad)(
        "лента прокручивается: scrollHeight=%d clientHeight=%d" % (m["sh"], m["ch"]))
    (ok if m["top"] > 0 else bad)("автоскролл к последнему: scrollTop=%d" % m["top"])

    empties = page.evaluate("""() => {
        const b = [...document.querySelectorAll('.row.bot .bubble')];
        return b.filter(x => !x.textContent.trim()).length;
    }""")
    (ok if empties == 0 else bad)("пустых пузырей нет: %d" % empties)

    pend = page.locator(".row.bot.pending").count()
    (ok if pend == 0 else bad)("зависших «печатает…» нет: %d" % pend)

    page.screenshot(path=OUT + r"\e2e_filled.png")

    out.append("")
    out.append("=== 8. ошибки и битые запросы ===")
    if notfound:
        for f in notfound[:8]:
            bad("HTTP >=400: " + f[:130])
    else:
        ok("ни одного ответа >= 400")
    real = [e for e in errors if "404" not in e or True]
    if real:
        for e in real[:8]:
            info("console: " + e[:130])
    if failed:
        for f in failed[:5]:
            info("requestfailed: " + f[:130])

    browser.close()

out.append("")
out.append("ИТОГ: провалено %d" % len(fails))
open(OUT + r"\e2e_report.txt", "w", encoding="utf-8").write("\n".join(out))
print("done fails=%d" % len(fails))
