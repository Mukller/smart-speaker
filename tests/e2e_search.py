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


def ready(page, timeout=40000):
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('.row.bot.pending').length === 0",
            timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(150)


def wait_search(page, timeout=60000):
    """Ждём именно результатов, а не заглушку.

    Перед поиском очищаем бокс: иначе ожидание срабатывает мгновенно на
    результатах предыдущего запроса, и новый источник так и не проверяется.
    """
    page.evaluate("() => { const b = document.getElementById('searchResults');"
                  " if (b) b.innerHTML = ''; }")
    try:
        page.wait_for_function(
            "() => { const b = document.getElementById('searchResults');"
            " return b && b.querySelectorAll('.pl-track').length > 0; }",
            timeout=timeout)
    except Exception:
        pass


with sync_playwright() as p:
    b = p.chromium.launch(
        executable_path=CHROME,
        args=["--no-sandbox", "--disable-gpu",
              "--autoplay-policy=no-user-gesture-required"])
    page = b.new_page(viewport={"width": 1360, "height": 960})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    # у Request нет .status, только у Response
    page.on("response", lambda r: errors.append("HTTP %d %s" % (r.status, r.url[:90]))
            if r.status >= 400 else None)

    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector("#send", timeout=20000)
    page.wait_for_selector("#searchInput", timeout=20000)
    page.wait_for_timeout(600)

    out.append("=== 1. поиск полных треков (Internet Archive) ===")
    page.fill("#searchInput", "jazz")
    page.press("#searchInput", "Enter")
    wait_search(page)
    page.wait_for_timeout(1200)
    n = page.locator("#searchResults .pl-track").count()
    note = page.locator("#searchResults .pl-note")
    note_txt = note.inner_text() if note.count() else ""
    info("результатов: %d, заметка: %r" % (n, note_txt))
    if n:
        names = page.locator("#searchResults .pl-track").all_inner_texts()
        info("первые: " + " | ".join(x[:32] for x in names[:3]))
        urls = page.evaluate("""() => [...document.querySelectorAll('#searchResults .pl-track')]
            .map(b => b.title).slice(0, 3)""")
        for u in urls:
            info("url: " + u[:100])
        flac = [u for u in urls
                if u.rsplit("/", 1)[-1].lower().endswith(".flac")]
        (ok if not flac else bad)("непроигрываемых .flac среди результатов: %d" % len(flac))
        # правильный путь у archive.org — {server}{dir}/{файл}, а не
        # /download/{id}/{файл}, поэтому проверяем домен, а не подстроку
        (ok if all("archive.org" in u for u in urls) else bad)("ссылки ведут на archive.org")
    else:
        bad("поиск ничего не вернул")
    page.screenshot(path=OUT + r"\search_archive.png")

    out.append("")
    out.append("=== 2. проигрывание найденного ===")
    if n:
        page.locator("#searchResults .pl-track").first.click()
        page.wait_for_timeout(3500)
        st = page.evaluate("""() => {
            const a = document.getElementById('audio');
            return {paused: a.paused, t: a.currentTime, dur: a.duration,
                    src: a.currentSrc.slice(-40), err: a.error ? a.error.code : 0};
        }""")
        info("audio: paused=%s t=%.2f dur=%.1f err=%s src=…%s"
             % (st["paused"], st["t"], st["dur"] or 0, st["err"], st["src"]))
        (ok if not st["err"] else bad)("браузер не отверг файл (error=%s)" % st["err"])
        (ok if not st["paused"] or st["t"] > 0 else bad)("воспроизведение пошло")
        tracks = page.locator("#player .pl-track").count()
        (ok if tracks >= 1 else bad)("трек добавлен в плейлист: %d" % tracks)

    out.append("")
    out.append("=== 3. поиск превью (iTunes) ===")
    # кликаем по надписи, а не по позиции: селектор .chip:nth-child(2)
    # промахивался мимо кнопки и попадал в первую, поэтому источник не менялся
    page.get_by_text("Превью 30 с", exact=True).click()
    page.wait_for_timeout(300)
    src_now = page.evaluate("() => searchSrc")
    info("источник после клика: %r" % src_now)
    (ok if src_now == "itunes" else bad)("источник переключился на iTunes")
    page.fill("#searchInput", "radiohead")
    page.press("#searchInput", "Enter")
    wait_search(page)
    page.wait_for_timeout(800)
    n2 = page.locator("#searchResults .pl-track").count()
    info("результатов iTunes: %d" % n2)
    (ok if n2 > 0 else bad)("iTunes вернул результаты")
    if n2:
        t = page.locator("#searchResults .pl-track").first.inner_text()
        ttl = page.locator("#searchResults .pl-track").first.get_attribute("title") or ""
        info("например: " + t[:50])
        info("подсказка: " + ttl[:70])
        (ok if "itunes.apple.com" in ttl else bad)(
            "ссылка ведёт на iTunes, а не на archive: %r" % ttl[:60])

    out.append("")
    out.append("=== 4. команды плеера не сломались ===")
    page.fill("#input", "громче")
    page.press("#input", "Enter")
    ready(page)
    r = page.locator(".row.bot .bubble").last.inner_text()
    (ok if "ромче" in r else bad)("громче -> %r" % r)
    v1 = page.evaluate("() => document.getElementById('audio').volume")
    page.fill("#input", "тише")
    page.press("#input", "Enter")
    ready(page)
    v2 = page.evaluate("() => document.getElementById('audio').volume")
    (ok if v2 < v1 else bad)("тише: %.2f -> %.2f" % (v1, v2))

    out.append("")
    out.append("=== 5. ошибки ===")
    real = [e for e in errors if "favicon" not in e.lower()]
    if real:
        for e in real[:8]:
            bad(str(e)[:130])
    else:
        ok("ошибок и 404 нет")

    page.screenshot(path=OUT + r"\search_final.png")
    b.close()

out.append("")
out.append("ИТОГ: провалено %d" % len(fails))
open(OUT + r"\search_report.txt", "w", encoding="utf-8").write("\n".join(out))
print("done fails=%d" % len(fails))
