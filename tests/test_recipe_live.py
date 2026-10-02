"""Живая проверка будильника с делами.

Проверяем, что «буди в ... и включи свет» это один будильник с делами, а не
два разговора, и что дела переживают сохранение: будильник лежит в файле, и
колонка перезапускается вместе с контейнером.

Само срабатывание не ждём - ждать минуту ради проверки дорого, поэтому
проверяем то, что можно проверить сразу: разбор фразы, состав дел и то, что
они сохранены в том виде, в котором их потом выполнит колонка.
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


ask("отмени будильник")

# 1. Рецепт: время плюс дела.
info("--- буди в 6:30 по будням и включи свет ---")
d = ask("буди в 6:30 по будням и включи свет")
info("ответ: %s" % (d.get("restxt") or "")[:90])
if d.get("source") == "alarm":
    ok("рецепт ушёл в будильник")
else:
    bad("рецепт ушёл в %s" % d.get("source"))
txt = (d.get("restxt") or "").lower()
if "свет" in txt:
    ok("колонка подтвердила, что включит свет")
else:
    bad("в подтверждении нет света: %r" % (d.get("restxt") or "")[:70])

lst = alarms()
info("будильников: %d" % len(lst))
found = None
for a in lst:
    info("  id=%s %s повтор=%s дела=%s"
         % (a.get("id"), a.get("label"), a.get("repeat"), a.get("actions")))
    if a.get("actions"):
        found = a

if found:
    ok("дела сохранены вместе с будильником")
    acts = found["actions"]
    want_on = any(x.get("kind") == "device" and "свет" in (x.get("target") or "")
                  for x in acts)
    if want_on:
        ok("дело «включить свет» сохранено и переживёт перезапуск")
    else:
        bad("дела не то: %r" % acts)
else:
    bad("у будильника нет дел в /alarms")

# 2. Дело «сказать».
info("--- буди в 7 утра и скажи доброе утро ---")
d = ask("буди в 7 утра и скажи доброе утро")
info("ответ: %s" % (d.get("restxt") or "")[:90])
txt = (d.get("restxt") or "").lower()
if "доброе утро" in txt and "скажу" in txt:
    ok("колонка подтвердила, что скажет слова")
else:
    bad("подтверждение не содержит слов: %r" % (d.get("restxt") or "")[:70])

say_alarms = [a for a in alarms()
              if any(x.get("kind") == "say"
                     and "доброе" in (x.get("text") or "") for x in
                     (a.get("actions") or []))]
if say_alarms:
    ok("слова сохранены в деле будильника")
else:
    bad("слова не сохранились: %r" % alarms())

# 3. Несколько дел через «и».
info("--- буди в 8 и включи свет и чайник ---")
d = ask("буди в 8 утра и включи свет и чайник")
info("ответ: %s" % (d.get("restxt") or "")[:90])
multi = [a for a in alarms() if len(a.get("actions") or []) >= 2]
if multi:
    ok("оба прибора попали в одно дело")
    tg = [x.get("target") for x in multi[0]["actions"]]
    info("дела: %r" % tg)
else:
    bad("второй прибор потерялся: %r" % alarms())

# 4. Дела без времени - это не будильник. Колонка не должна обещать подъём
#    в шесть утра, если об этом не просили.
ask("отмени будильник")
d = ask("включи свет и чайник")
info("без времени: %s (source=%s)" % ((d.get("restxt") or "")[:50], d.get("source")))
if not alarms():
    ok("без времени будильник не ставится")
else:
    bad("будильник поставился без времени: %r" % alarms())

ask("отмени будильник")
print()
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)