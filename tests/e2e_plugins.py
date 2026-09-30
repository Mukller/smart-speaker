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
    page.wait_for_selector("#plugins .pl", timeout=20000)
    page.wait_for_timeout(500)

    out.append("=== 1. панель плагинов: реальные данные ===")
    total = page.locator("#plugins .pl-total").inner_text()
    info("итоговая строка: " + total)
    rows = page.locator("#plugins .pl")
    n = rows.count()
    info("строк: %d" % n)
    (ok if n >= 5 else bad)("плагинов показано: %d" % n)

    names = page.locator("#plugins .pl > span:nth-of-type(2)").all_inner_texts()
    cmds = page.locator("#plugins .pl-cmds").all_inner_texts()
    info("первые: " + ", ".join(names[:4]))
    (ok if not any("|" in c for c in cmds) else bad)(
        "синонимы разделены, сырых '|' не осталось")
    (ok if any("погода" in c for c in cmds) else bad)("видны команды погоды")
    (ok if any("привет" in c for c in cmds) else bad)("видны команды приветствия")

    out.append("")
    out.append("=== 2. раньше список был выдуманным ===")
    for fake in ("Приветствие", "Дата и время", "Кубик", "Таймер"):
        present = fake in " ".join(names)
        info("«%s» как название плагина: %s" % (fake, "есть" if present else "нет (и правильно)"))
    (ok if not any(f in " ".join(names) for f in ("Приветствие", "Кубик"))
     else bad)("выдуманные названия ушли, показываются реальные имена файлов")

    out.append("")
    out.append("=== 3. переключение погодного плагина ===")
    # находим строку погодного плагина
    idx = None
    for i, nm in enumerate(names):
        if "weather" in nm:
            idx = i
            break
    if idx is None:
        bad("не нашёл строку погодного плагина")
    else:
        row = rows.nth(idx)
        was_on = "вкл" in row.locator("small").inner_text()
        info("погода: %s, класс togglable: %s"
             % (row.locator("small").inner_text(), "togglable" in (row.get_attribute("class") or "")))
        toggles = [i for i, nm in enumerate(names) if "togglable" in (rows.nth(i).get_attribute("class") or "")]
        info("переключаемых строк: %d (ожидаем 2 - оба погодных)" % len(toggles))
        (ok if len(toggles) == 2 else info)("переключаемых: %d" % len(toggles))

        before = row.locator("small").inner_text()
        row.click()
        page.wait_for_timeout(1200)
        after = rows.nth(idx).locator("small").inner_text()
        status = page.locator("#status").inner_text()
        info("было: %r стало: %r, статус: %r" % (before, after, status))
        (ok if before != after else bad)("состояние переключилось")
        (ok if "перезапу" in status.lower() else info)("предупреждение о перезапуске: %r" % status)

        # возвращаем обратно, чтобы не оставлять сайт выключенным
        rows.nth(idx).click()
        page.wait_for_timeout(1200)
        back = rows.nth(idx).locator("small").inner_text()
        (ok if back == before else bad)("вернули обратно: %r" % back)

    out.append("")
    out.append("=== 4. остальное не сломано ===")
    page.fill("#input", "привет")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    bots = page.locator(".row.bot .bubble").all_inner_texts()
    (ok if bots else bad)("ответ: %r" % (bots[-1] if bots else None))
    stamps = page.locator(".row .stamp").count()
    (ok if stamps >= 2 else bad)("метки времени на месте: %d" % stamps)

    out.append("")
    out.append("=== 5. ошибки ===")
    real = [e for e in errors if "favicon" not in e.lower()]
    if real:
        for e in real[:6]:
            bad("console: " + e[:130])
    else:
        ok("ошибок нет")

    page.screenshot(path=OUT + r"\plugins_panel.png")
    browser.close()

out.append("")
out.append("ИТОГ: провалено %d" % len(fails))
open(OUT + r"\plugins_report.txt", "w", encoding="utf-8").write("\n".join(out))
print("done fails=%d" % len(fails))
