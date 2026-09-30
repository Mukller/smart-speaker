import os
import re
from playwright.sync_api import sync_playwright

URL = "https://antonpetnitsky.com/kolonka/"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT = os.environ.get("JANE_OUT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "out")
TRACKS = [
    "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
    "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
    "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
]

out, fails = [], []


def ok(m):
    out.append("OK    " + m)


def bad(m):
    out.append("FAIL  " + m)
    fails.append(m)


def info(m):
    out.append("      " + m)


def vol(page):
    return page.evaluate("() => document.getElementById('audio').volume")


def cur(page):
    return page.evaluate("""() => {
        const a = document.getElementById('audio');
        return {paused: a.paused, t: a.currentTime, src: a.currentSrc.slice(-24), vol: a.volume};
    }""")


with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=CHROME,
        args=["--no-sandbox", "--disable-gpu",
              "--autoplay-policy=no-user-gesture-required"])
    page = browser.new_page(viewport={"width": 1360, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector("#send", timeout=20000)
    page.wait_for_selector("#player .pl-add input", timeout=20000)
    page.wait_for_timeout(600)

    out.append("=== 1. панель плеера ===")
    rows = page.locator("#player .pl-track").count()
    info("строк плейлиста: %d" % rows)
    now = page.locator("#player .pl-now").inner_text()
    (ok if "ничего" in now.lower() else bad)("пустое состояние: %r" % now)
    page.screenshot(path=OUT + r"\player_empty.png")

    out.append("")
    out.append("=== 2. добавляем треки ссылкой ===")
    for t in TRACKS:
        page.fill("#player .pl-add input", t)
        page.press("#player .pl-add input", "Enter")
        page.wait_for_timeout(300)
    rows = page.locator("#player .pl-track").count()
    (ok if rows == len(TRACKS) else bad)("добавлено треков: %d из %d" % (rows, len(TRACKS)))
    names = page.locator("#player .pl-track").all_inner_texts()
    info("названия: " + ", ".join(n[:28] for n in names))

    out.append("")
    out.append("=== 3. команда «включи музыку» ===")
    page.fill("#input", "включи музыку")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    page.wait_for_timeout(2500)
    st = cur(page)
    info("audio: paused=%s vol=%.2f t=%.2f src=…%s" % (st["paused"], st["vol"], st["t"], st["src"]))
    (ok if not st["paused"] else bad)("плеер пошёл (paused=%s)" % st["paused"])
    (ok if st["t"] > 0 else info)("время идёт: %.2f с" % st["t"])
    replied = page.locator(".row.bot .bubble").last.inner_text()
    (ok if replied.strip() else bad)("ответ: %r" % replied)
    page.screenshot(path=OUT + r"\player_playing.png")

    out.append("")
    out.append("=== 4. громче / тише ===")
    base = await_v = vol(page)
    info("стартовая громкость: %.2f" % base)

    page.fill("#input", "громче")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    page.wait_for_timeout(400)
    v1 = vol(page)
    (ok if v1 > base else bad)("«громче»: %.2f -> %.2f" % (base, v1))

    page.fill("#input", "громче")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    page.wait_for_timeout(400)
    v2 = vol(page)
    (ok if v2 > v1 else bad)("ещё раз «громче»: %.2f -> %.2f" % (v1, v2))

    page.fill("#input", "тише")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    page.wait_for_timeout(400)
    v3 = vol(page)
    (ok if v3 < v2 else bad)("«тише»: %.2f -> %.2f" % (v2, v3))

    shown = page.locator("#player .volnum").inner_text()
    info("в панели показано: %r" % shown)
    (ok if shown.strip() not in ("", "выкл") else bad)("панель отражает громкость")

    out.append("")
    out.append("=== 5. вперёд / назад ===")
    src0 = cur(page)["src"]
    page.fill("#input", "вперёд")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    page.wait_for_timeout(900)
    src1 = cur(page)["src"]
    (ok if src1 != src0 else bad)("«вперёд» сменил трек: …%s -> …%s" % (src0, src1))

    page.fill("#input", "назад")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    page.wait_for_timeout(900)
    src2 = cur(page)["src"]
    (ok if src2 == src0 else bad)("«назад» вернул: …%s (было …%s)" % (src2, src1))

    out.append("")
    out.append("=== 6. пауза ===")
    page.fill("#input", "пауза")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    page.wait_for_timeout(600)
    (ok if cur(page)["paused"] else bad)("«пауза» остановила воспроизведение")

    out.append("")
    out.append("=== 7. остальное не сломано ===")
    # про погоду НЕ проверяем конкретное состояние неба: оно меняется по
    # погоде, и такой тест падал каждый раз, когда в Минске не солнечно.
    # берём то, что есть всегда - температуру
    for cmd, want in (("время", None), ("погода", "температура")):
        page.fill("#input", cmd)
        page.press("#input", "Enter")
        page.wait_for_function(
            "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
        t = page.locator(".row.bot .bubble").last.inner_text()
        info("%s -> %r" % (cmd, t[:60]))
        if want:
            (ok if want.lower() in t.lower() else bad)("%s работает" % cmd)

    out.append("")
    out.append("=== 8. ошибки ===")
    real = [e for e in errors if "favicon" not in e.lower()
            and "NotAllowed" not in e and "autoplay" not in e.lower()]
    if real:
        for e in real[:6]:
            bad("console: " + e[:130])
    else:
        ok("ошибок нет")

    page.screenshot(path=OUT + r"\player_final.png")
    browser.close()

out.append("")
out.append("ИТОГ: провалено %d" % len(fails))
open(OUT + r"\player_report.txt", "w", encoding="utf-8").write("\n".join(out))
print("done fails=%d" % len(fails))
