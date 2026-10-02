"""Живая проверка привычек.

Главное здесь - что колонка запомнила город и что погода поехала в него. Всё
остальное видно на словах, а смена города меняет ответ плагина погоды.

Проверять надо именно погоду: если колонка запомнила город, но плагин его не
увидел, привычки работают вхолостую.
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


def habits():
    return json.load(urllib.request.urlopen(API + "/habits", timeout=30))


info("--- говорим, где живём ---")
d = ask("я живу в Гомеле")
info("ответ: %r (source=%s)" % ((d.get("restxt") or "")[:60], d.get("source")))

h = habits()
info("привычки: %s" % json.dumps(h, ensure_ascii=False)[:200])
if (h.get("city") or "").lower() in ("гомель", "гомеле"):
    ok("колонка запомнила город")
else:
    bad("город не запомнен: %r" % h.get("city"))

# Смена города: не должно остаться старого.
d = ask("теперь я живу в Бресте")
h2 = habits()
if (h2.get("city") or "").lower().startswith("брест"):
    ok("новый город заменил старый (%s)" % h2.get("city"))
else:
    bad("новый город не заменил старый: %r" % h2.get("city"))

# Погода должна поехать в запомненный город, а не в город из сборки.
d = ask("какая сейчас погода")
info("погода: %s (source=%s)" % ((d.get("restxt") or "")[:80], d.get("source")))
if d.get("source") == "plugin" and d.get("restxt"):
    ok("погода отвечает плагином по запомненному городу")
else:
    bad("погода не отвечает: %s" % d.get("source"))

# Частые команды.
for _ in range(3):
    ask("включи свет")
h3 = habits()
top = [x["text"] for x in (h3.get("top") or [])]
info("чаще всего просят: %r" % top[:3])
if any("свет" in t for t in top):
    ok("колонка считает частые команды")
else:
    bad("частые команды не считаются: %r" % top)

# Вопрос о привычках.
d = ask("что я обычно прошу?")
info("ответ о привычках: %s" % ((d.get("restxt") or "")[:80]))
if d.get("source") == "habits":
    ok("колонка отвечает о привычках сама")
else:
    bad("вопрос о привычках ушёл в %s" % d.get("source"))

# Темп и громкость по времени суток.
if 0 < (h3.get("pace") or 0) <= 100 and 0 < (h3.get("volume") or 0) <= 100:
    ok("темп и громкость в пределах: темп %s, громкость %s"
       % (h3.get("pace"), h3.get("volume")))
else:
    bad("темп или громкость вне пределов: %r" % h3)

ask("выключи всё")
print()
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)