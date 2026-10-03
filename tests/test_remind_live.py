"""Живая проверка напоминаний.

Проверяем то, ради чего всё затевалось: колонка не обещает сделать то, чего
не делает. Если «напомни купить хлеб» уходит в модель, модель ответит
связно и неверно - и это будет выглядеть как работающая напоминалка.
"""
import json, sys, urllib.parse, urllib.request

API = "https://antonpetnitsky.com/kolonka/api"
fails = []


def ok(m):   print("OK    " + m)
def bad(m):  print("FAIL  " + m); fails.append(m)
def info(m): print("      " + m)


def ask(text):
    u = API + "/sendTxtCmd?cmd=" + urllib.parse.quote(text)
    return json.load(urllib.request.urlopen(u, timeout=120))


def items():
    return json.load(urllib.request.urlopen(API + "/reminders", timeout=30))


def clear():
    ask("забудь напоминание")


clear()

# 1. Без времени колонка обязана спросить, а не выдумать.
info("--- напомни купить хлеб ---")
d = ask("напомни купить хлеб")
info("ответ: %s (source=%s)" % ((d.get("restxt") or "")[:70], d.get("source")))
if d.get("source") != "remind":
    bad("напоминание ушло в %s - колонка обещает то, чего не делает"
        % d.get("source"))
else:
    ok("напоминание не ушло в модель")
if "когда" in (d.get("restxt") or "").lower():
    ok("колонка спросила время, а не придумала его")
else:
    bad("время не спросено: %r" % (d.get("restxt") or "")[:60])

# 2. Уточнение времени создаёт напоминание.
info("--- уточняем: через час ---")
d = ask("через час")
info("ответ: %s (source=%s)" % ((d.get("restxt") or "")[:70], d.get("source")))
lst = items().get("items") or []
info("напоминаний: %r" % lst)
if lst and "хлеб" in lst[0].get("text", ""):
    ok("напоминание создано по уточнению: %s (%s)"
       % (lst[0].get("text"), lst[0].get("when")))
else:
    bad("уточнение не создало напоминание: %r" % lst)

# 3. Со временем сразу.
info("--- напомни через 10 минут купить молоко ---")
d = ask("напомни через 10 минут купить молоко")
info("ответ: %s" % (d.get("restxt") or "")[:70])
lst = items().get("items") or []
if any("молоко" in (x.get("text") or "") for x in lst):
    ok("напоминание со временем создано")
else:
    bad("не создано: %r" % lst)

# 4. Список.
d = ask("что напомнить")
info("список: %s" % ((d.get("restxt") or "")[:80]))
if d.get("source") == "remind" and ("хлеб" in (d.get("restxt") or "")
                                   or "молоко" in (d.get("restxt") or "")):
    ok("колонка перечисляет напоминания")
else:
    bad("список не работает: [%s] %r" % (d.get("source"),
                                         (d.get("restxt") or "")[:60]))

# 5. Отмена.
clear()
d = ask("что напомнить")
if not items().get("items"):
    ok("отмена очистила напоминания")
else:
    bad("после отмены остались: %r" % items().get("items"))

print()
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)