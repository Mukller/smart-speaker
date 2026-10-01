#!/usr/bin/env python3
"""Плагин погоды должен ловить живую речь, а не только слово-команду.

Проверяем на естественных формулировках: именно они приходят с микрофона,
и раньше они уходили в модель, которая выдумывала прогноз.
"""
import json, urllib.parse, urllib.request

API = "https://antonpetnitsky.com/kolonka/api"
fails = []

def ask(text):
    u = API + "/sendTxtCmd?cmd=" + urllib.parse.quote(text)
    return json.load(urllib.request.urlopen(u, timeout=90))

def ok(m):  print("OK    " + m)
def bad(m): print("FAIL  " + m); fails.append(m)

# Формулировки, которые на самом деле говорит человек
PHRASES = [
    "погода",
    "какая погода",
    "какая сейчас погода",
    "что с погодой",
    "как с погодой",
    "погода на улице",
    "какая там погода",
]

for p in PHRASES:
    d = ask(p)
    src = d.get("source")
    txt = (d.get("restxt") or "")
    if src == "plugin":
        ok("%-22s -> плагин: %s" % (p, txt[:44]))
    else:
        bad("%-22s -> %s: %s" % (p, src, txt[:44]))

print("")
print("ИТОГ: провалено %d из %d" % (len(fails), len(PHRASES)))