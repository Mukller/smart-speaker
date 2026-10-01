#!/usr/bin/env python3
"""Будильник на время суток: ставим, смотрим список, отменяем.

Проверяем на живом проде, потому что разбор фраз уже проверен отдельно, а
здесь важно другое: команда должна уйти в будильник, а не в модель.
"""
import json, urllib.parse, urllib.request

API = "https://antonpetnitsky.com/kolonka/api"
fails = []

def ok(m):   print("OK    " + m)
def bad(m):  print("FAIL  " + m); fails.append(m)
def info(m): print("      " + m)

def ask(text):
    u = API + "/sendTxtCmd?cmd=" + urllib.parse.quote(text)
    return json.load(urllib.request.urlopen(u, timeout=90))

def alarms():
    return json.load(urllib.request.urlopen(API + "/alarms", timeout=30))

# сначала убираем всё, что могло остаться
ask("отмени будильник")

print("=== ставим на время суток ===")
for phrase in ("поставь будильник на 7 утра",
               "буди меня в 21:40",
               "поставь будильник на 6 утра по будням"):
    d = ask(phrase)
    info("%-38s -> %s" % (phrase, (d.get("restxt") or "")[:48]))
    if d.get("source") == "alarm":
        ok("%-38s ушёл в будильник" % phrase)
    else:
        bad("%-38s ушёл в %s, а не в будильник" % (phrase, d.get("source")))

print()
print("=== список ===")
lst = alarms().get("alarms") or []
info("всего: %d" % len(lst))
for a in lst:
    info("  id=%s на %s повтор=%s через %s с"
         % (a.get("id"), a.get("label"), a.get("repeat") or "-", a.get("left")))
if lst:
    ok("будильники видны через /alarms и пережили проверку")
else:
    bad("список пуст")

print()
print("=== отмена ===")
if lst:
    d = ask("отмени будильник")
    info("ответ: %s" % (d.get("restxt") or "")[:60])
    after = alarms().get("alarms") or []
    if not after:
        ok("отмена убрала будильники")
    else:
        bad("после отмены осталось %d" % len(after))
else:
    bad("нечего отменять")

print()
print("ИТОГ: провалено %d" % len(fails))