"""Проверка панели дома на живой странице.

Браузер открыть нечем, поэтому проверяем ровно то, что получает человек:
страницу с прода. Если панель есть в ответе сервера, она есть у посетителя.

Плюс сама панель не должна быть пустой: /home обязан отдавать устройства,
иначе панель покажет «устройства не описаны».
"""
import json, re, sys, urllib.request

PAGE = "https://antonpetnitsky.com/kolonka/"
API = "https://antonpetnitsky.com/kolonka/api"
fails = []


def ok(m):   print("OK    " + m)
def bad(m):  print("FAIL  " + m); fails.append(m)
def info(m): print("      " + m)


html = urllib.request.urlopen(PAGE, timeout=60).read().decode("utf-8",
                                                               "replace")
info("страница: %d байт" % len(html))

if "<h2>Дом</h2>" in html:
    ok("панель дома есть в живой странице")
else:
    bad("панели дома на странице нет")

if "function pollHome" in html:
    ok("опрос устройств есть в живой странице")
else:
    bad("опрос устройств в странице нет")

if "setInterval(pollHome" in html:
    ok("панель обновляется сама")
else:
    bad("панель не обновляется: один раз и забыла")

# Разметка не должна разъехаться: без этого клики перестают работать.
for tag in ("div", "section", "aside", "main", "script"):
    o = len(re.findall(r"<%s[\s>]" % tag, html))
    c = len(re.findall(r"</%s>" % tag, html))
    if o != c:
        bad("теги <%s>: открыто %d, закрыто %d" % (tag, o, c))
if not fails:
    ok("разметка сбалансирована")

# Панель будет пустой, если /home не отдаёт устройства.
j = json.load(urllib.request.urlopen(API + "/home", timeout=30))
devs = j.get("devices") or []
if devs:
    ok("устройств для панели: %d" % len(devs))
    for d in devs[:4]:
        info("  %s (%s): %s" % (d.get("name"), d.get("kind"),
                                d.get("state") if d.get("kind") != "sensor"
                                else d.get("value")))
else:
    bad("устройств нет - панель будет пустой")

# Привычки тоже видны: колонка не должна прятать, что она запомнила.
h = json.load(urllib.request.urlopen(API + "/habits", timeout=30))
if h.get("city") is not None or h.get("asked"):
    ok("привычки видны: город %r, команд %s" % (h.get("city"),
                                                 h.get("asked")))
else:
    info("привычки пока пустые - это нормально")

print()
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)