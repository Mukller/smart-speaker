"""Проверка, что дела будильника действительно выполняются.

Ждать минуту ради этой проверки дорого, но по-другому не узнать: можно
собрать будильник с делом, видеть его в /alarms и так и не выяснить, что
колонка в семь утра так и не включит свет.

Поэтому будильник ставится на ближайшую минуту, а проверка ждёт звонка и
смотрит состояние устройства.
"""
import json, sys, time, urllib.parse, urllib.request

API = "https://antonpetnitsky.com/kolonka/api"
fails = []


def ok(m):   print("OK    " + m)
def bad(m):  print("FAIL  " + m); fails.append(m)
def info(m): print("      " + m)


def ask(text):
    u = API + "/sendTxtCmd?cmd=" + urllib.parse.quote(text)
    return json.load(urllib.request.urlopen(u, timeout=90))


def home_state(name):
    j = json.load(urllib.request.urlopen(API + "/home", timeout=30))
    for d in j.get("devices") or []:
        if d.get("name") == name:
            return d.get("state")
    return None


# Выключаем свет заранее, чтобы «включился» было однозначно.
ask("выключи свет")
ask("отмени будильник")
if home_state("свет") != "off":
    bad("свет не удалось выключить заранее: %s" % home_state("свет"))
    sys.exit(1)
ok("свет выключен заранее")

# Будильник на ближайшую минуту. jane_time умеет цифровое время «6:30»,
# поэтому берём то же для своей минуты.
now = time.localtime()
soon = time.localtime(time.time() + 70)
when = "%02d:%02d" % (soon.tm_hour, soon.tm_min)
info("сейчас %02d:%02d, ставлю будильник на %s"
     % (now.tm_hour, now.tm_min, when))

d = ask("буди в %s и включи свет" % when)
info("ответ: %s" % (d.get("restxt") or "")[:80])
if d.get("source") != "alarm":
    bad("будильник не поставился: %s" % d.get("source"))
    sys.exit(1)

# Ждём звонка. Терпение ограничено: если не позвонило за 2 минуты -
# это тоже результат, просто не тот, который нужен.
deadline = time.time() + 150
lit = False
while time.time() < deadline:
    time.sleep(5)
    if home_state("свет") == "on":
        lit = True
        info("свет включился на %.0f с" % (time.time() - (deadline - 150)))
        break

if lit:
    ok("будильник сработал и включил свет")
else:
    bad("будильник не включил свет за две минуты")

ask("отмени будильник")
ask("выключи всё")
print()
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)