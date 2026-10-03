"""Проверка ответов о времени на живом сервере.

Главное - что ответ приходит от колонки, а не от модели. На «который час»
модель отвечает правдоподобно и неверно, и выглядит это хорошо, поэтому
смотрим на source.

И что в ответе нет цифр: колонка должна говорить словами, иначе синтезатор
прочитает «10:47» как «десять: сорок семь».
"""
import json, re, sys, urllib.parse, urllib.request

API = "https://antonpetnitsky.com/kolonka/api"
fails = []


def ok(m):   print("OK    " + m)
def bad(m):  print("FAIL  " + m); fails.append(m)
def info(m): print("      " + m)


def ask(text):
    u = API + "/sendTxtCmd?cmd=" + urllib.parse.quote(text)
    return json.load(urllib.request.urlopen(u, timeout=120))


qs = ["который час", "сколько времени", "какое время",
      "сколько сейчас времени", "какое сегодня число",
      "какой сегодня день недели", "что за день", "какой сейчас год"]

for q in qs:
    d = ask(q)
    txt = (d.get("restxt") or "")
    info("%-26s [%s] %s" % (q, d.get("source"), txt[:60]))
    if d.get("source") not in ("when", "clock"):
        bad("«%s» ушло в %s, а не в часы" % (q, d.get("source")))
        continue
    if re.search(r"\d", txt):
        bad("«%s»: в ответе цифры - %r" % (q, txt))
        continue
    ok("«%s» - точно и словами" % q)

# Часы должны называть примерно верное время. Сверяем с машиной, у которой
# часовой пояс тот же.
import datetime
local = datetime.datetime.now()
print()
info("на ПК сейчас: %s" % local.strftime("%H:%M"))
d = ask("который час")
info("колонка: %s" % (d.get("restxt") or ""))
if d.get("source") in ("when", "clock"):
    ok("колонка отвечает по своим часам, а не по модели")
else:
    bad("ответ на «который час» пришёл из %s" % d.get("source"))

print()
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)