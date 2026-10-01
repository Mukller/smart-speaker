"""Живая проверка контекста разговора.

Проверяем не то, что модуль умеет разбирать уточнения (это делает его
самопроверка), а то, что колонка реально помнит предыдущую тему.

Опасность тут в том, что почти всё может выглядеть работающим: уточнение
уйдёт в языковую модель, модель ответит связно и уверенно, и разговор будет
выглядеть живым - просто не про то. Поэтому проверяем source ответа: он
должен быть alarm, а не llm.
"""
import json, sys, urllib.parse, urllib.request

API = "https://antonpetnitsky.com/kolonka/api"
fails = []


def ok(m):   print("OK    " + m)
def bad(m):  print("FAIL  " + m); fails.append(m)
def info(m): print("      " + m)


def ask(text):
    u = API + "/sendTxtCmd?cmd=" + urllib.parse.quote(text)
    return json.load(urllib.request.urlopen(u, timeout=90))


def alarms():
    return json.load(urllib.request.urlopen(API + "/alarms", timeout=30)).get("alarms") or []


def clear():
    ask("отмени будильник")


# 1. Ставим будильник, тема запоминается
clear()
info("--- ставим будильник на 7 утра ---")
d = ask("буди меня в 7 утра")
info("ответ: %s (source=%s)" % ((d.get("restxt") or "")[:50], d.get("source")))
if d.get("source") != "alarm":
    bad("будильник не поставился")
else:
    ok("будильник на 7 утра стоит")

# 2. Уточнение про выходные - тот же час, другой повтор.
#    Ключевое: source обязан быть alarm. Если llm - уточнение ушло в модель
#    и она ответит уверенно не про то.
info("--- уточняем: а в выходные? ---")
d = ask("а в выходные?")
info("ответ: %s (source=%s)" % ((d.get("restxt") or "")[:60], d.get("source")))
if d.get("source") == "alarm" and "выходным" in (d.get("restxt") or "").lower():
    ok("«а в выходные?» осталось будильником и сохранило час")
else:
    bad("«а в выходные?» ушло не туда: source=%s" % d.get("source"))

lst = alarms()
info("будильников: %d" % len(lst))
for a in lst:
    info("  %s повтор=%s" % (a.get("label"), a.get("repeat")))
if any("07:00" in str(a.get("label")) and a.get("repeat") == "weekend"
       for a in lst):
    ok("в списке есть 07:00 по выходным")
else:
    bad("в списке нет 07:00 по выходным: %s" % lst)

# 3. Конкретный день недели.
info("--- уточняем: а в четверг? ---")
d = ask("а в четверг?")
info("ответ: %s (source=%s)" % ((d.get("restxt") or "")[:60], d.get("source")))
if d.get("source") == "alarm" and "четверг" in (d.get("restxt") or "").lower():
    ok("«а в четверг?» назвало день недели")
else:
    bad("«а в четверг?» дало source=%s" % d.get("source"))

# 4. Сдвиг часа без слова «а».
info("--- уточняем: на час позже ---")
d = ask("на час позже")
info("ответ: %s (source=%s)" % ((d.get("restxt") or "")[:60], d.get("source")))
if d.get("source") == "alarm" and "08:00" in (d.get("restxt") or ""):
    ok("«на час позже» сдвинуло 7 на 8")
else:
    bad("«на час позже» дало source=%s %r" % (d.get("source"),
                                              (d.get("restxt") or "")[:40]))

# 5. Погода и её уточнение. Плагин погоды есть, «а подробнее» должно
#    уйти в плагин, а не в модель.
info("--- погода и уточнение ---")
ask("отмени будильник")
d = ask("какая сейчас погода")
if d.get("source") == "plugin":
    ok("погода отвечает плагином")
    d2 = ask("а подробнее?")
    info("уточнение: %s (source=%s)" % ((d2.get("restxt") or "")[:50], d2.get("source")))
    if d2.get("source") == "plugin":
        ok("«а подробнее?» осталось погодой")
    else:
        bad("«а подробнее?» ушло в %s" % d2.get("source"))
else:
    bad("погода не отвечает плагином: %s" % d.get("source"))

clear()
print()
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)
