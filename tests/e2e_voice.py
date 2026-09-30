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


# перехватываем создание Audio до загрузки страницы
INIT = """
window.__audio = {created: 0, played: 0, resolved: 0, rejected: [], src: []};
const RealAudio = window.Audio;
window.Audio = function (src) {
  window.__audio.created++;
  window.__audio.src.push(String(src).slice(0, 24));
  const a = new RealAudio(src);
  const realPlay = a.play.bind(a);
  a.play = function () {
    window.__audio.played++;
    return realPlay().then(
      () => { window.__audio.resolved++; },
      (e) => { window.__audio.rejected.push(String(e && e.name)); throw e; }
    );
  };
  return a;
};
window.Audio.prototype = RealAudio.prototype;
window.__speech = {spoken: 0};
if (window.speechSynthesis) {
  const realSpeak = window.speechSynthesis.speak.bind(window.speechSynthesis);
  window.speechSynthesis.speak = function (u) { window.__speech.spoken++; return realSpeak(u); };
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=CHROME,
        args=["--no-sandbox", "--disable-gpu",
              "--autoplay-policy=no-user-gesture-required"])
    page = browser.new_page(viewport={"width": 1280, "height": 860})
    page.add_init_script(INIT)

    tts_calls, errors = [], []
    page.on("request", lambda r: tts_calls.append(r.url)
            if "/kolonka/api/tts?" in r.url else None)
    page.on("response", lambda r: info("tts -> %d %s" % (r.status, r.headers.get("content-type", "")))
            if "/kolonka/api/tts?" in r.url else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_selector("#send", timeout=20000)

    out.append("=== 1. кнопка голоса ===")
    label = page.locator("#voiceBtn").inner_text()
    pressed = page.get_attribute("#voiceBtn", "aria-pressed")
    (ok if pressed == "true" else bad)("голос включён по умолчанию: %r / %s" % (label, pressed))

    out.append("")
    out.append("=== 2. ответ произносится ===")
    page.fill("#input", "привет")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    # ждём синтез
    try:
        page.wait_for_function("() => window.__audio.played > 0", timeout=40000)
    except Exception:
        pass
    page.wait_for_timeout(1200)

    a = page.evaluate("window.__audio")
    if tts_calls:
        ok("запрос /kolonka/api/tts сделан (%d шт)" % len(tts_calls))
        dec = re.sub(r"cmd=.*|&text=.*", lambda mm: mm.group(0)[:40], tts_calls[0])
        info("URL: " + tts_calls[0][:90])
    else:
        bad("запроса к /kolonka/api/tts не было — голос не синтезировался")

    info("Audio создано: %d, play(): %d, разрешилось: %d, отклонено: %s"
         % (a["created"], a["played"], a["resolved"], a["rejected"] or "нет"))
    info("blob-src: %s" % (a["src"][:1] if a["src"] else "-"))
    if a["played"] == 0:
        bad("аудио не запускалось")
    elif a["rejected"]:
        bad("play() отклонён: %s" % a["rejected"])
    elif a["resolved"] == 0:
        bad("аудио не начало играть (pending)")
    else:
        ok("голос реально зазвучал через серверный TTS")

    sp = page.evaluate("window.__speech.spoken")
    info("SpeechSynthesis использован: %d (ожидаем 0 при успешном серверном TTS)" % sp)
    if sp and a["resolved"] == 0:
        bad("серверный TTS не сработал, сработал браузерный фоллбэк")

    out.append("")
    out.append("=== 3. выключение голоса ===")
    page.click("#voiceBtn")
    page.wait_for_timeout(200)
    label2 = page.locator("#voiceBtn").inner_text()
    pressed2 = page.get_attribute("#voiceBtn", "aria-pressed")
    (ok if pressed2 == "false" else bad)("кнопка переключилась: %r / %s" % (label2, pressed2))

    before = len(tts_calls)
    page.fill("#input", "время")
    page.press("#input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('status').textContent === 'Готова'", timeout=40000)
    page.wait_for_timeout(1500)
    (ok if len(tts_calls) == before else bad)(
        "при выключенном голосе синтеза нет (%d -> %d)" % (before, len(tts_calls)))

    out.append("")
    out.append("=== 4. кнопка «Озвучить ответ» ===")
    page.click("#voiceBtn")            # снова включаем
    page.wait_for_timeout(200)
    before = len(tts_calls)
    page.click("#ttsBtn")
    page.wait_for_timeout(4000)
    (ok if len(tts_calls) > before else bad)("повторное озвучивание сработало (%d -> %d)"
                                            % (before, len(tts_calls)))

    out.append("")
    out.append("=== 5. ошибки ===")
    if errors:
        for e in errors[:6]:
            bad("console: " + e[:130])
    else:
        ok("ошибок в консоли нет")

    page.screenshot(path=OUT + r"\voice_on.png")
    browser.close()

out.append("")
out.append("ИТОГ: провалено %d" % len(fails))
open(OUT + r"\voice_report.txt", "w", encoding="utf-8").write("\n".join(out))
print("done fails=%d" % len(fails))
