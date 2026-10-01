"""Живая проверка умного дома.

Проверяем, что разговор про устройства не уходит в языковую модель. Это
главное: на «включи свет» модель ответит что-нибудь связное про свет, и
всё будет выглядеть работающим - просто колонка ничего не включила.

Поэтому смотрим на source ответа и на то, что прибор действительно поменял
состояние через /home.
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


def home():
    try:
        return json.load(urllib.request.urlopen(API + "/home", timeout=30))
    except Exception as e:
        return {"error": str(e)}


def state(name):
    for d in home().get("devices") or []:
        if d.get("name") == name:
            return d.get("state")
    return None


# 1. Разговор про дом не должен уходить в модель.
info("--- включаем свет в гостиной ---")
d = ask("включи свет в гостиной")
info("ответ: %s (source=%s)" % ((d.get("restxt") or "")[:60], d.get("source")))
if d.get("source") == "home":
    ok("«включи свет в гостиной» ушло в умный дом, а не в модель")
else:
    bad("ушло в %s - колонка отвечает моделью вместо дома" % d.get("source"))
if state("свет") == "on":
    ok("состояние света в гостиной: включено")
else:
    bad("состояние света не поменялось: %s" % state("свет"))

# 2. Выключение.
info("--- выключаем ---")
d = ask("выключи свет в гостиной")
info("ответ: %s (source=%s)" % ((d.get("restxt") or "")[:60], d.get("source")))
if state("свет") == "off":
    ok("свет выключен")
else:
    bad("свет не выключился: %s" % state("свет"))

# 3. Падеж: «лампу» - это тот же свет. Без этого колонка не понимает
#    половину живых фраз.
info("--- «включи лампу», а не «включи лампа» ---")
d = ask("включи лампу")
info("ответ: %s (source=%s)" % ((d.get("restxt") or "")[:60], d.get("source")))
if d.get("source") == "home" and state("свет") == "on":
    ok("падеж понята: «лампу» это тот же свет")
else:
    bad("«включи лампу» -> source=%s, состояние %s"
        % (d.get("source"), state("свет")))

# 4. Прибор, а не свет.
info("--- включаем чайник ---")
d = ask("включи чайник")
if d.get("source") == "home" and state("чайник") == "on":
    ok("чайник включился")
else:
    bad("чайник: source=%s, состояние %s" % (d.get("source"), state("чайник")))

# 5. Яркость тусклее - знак должен уменьшать, а не увеличивать.
info("--- яркость ---")
ask("включи свет в гостиной")
d = ask("ярче")
info("ярче: %s" % ((d.get("restxt") or "")[:50]))
b1 = None
for x in home().get("devices") or []:
    if x.get("name") == "свет":
        b1 = x.get("brightness")
d = ask("тусклее")
info("тусклее: %s" % ((d.get("restxt") or "")[:50]))
b2 = None
for x in home().get("devices") or []:
    if x.get("name") == "свет":
        b2 = x.get("brightness")
if b1 and b2 is not None and b2 < b1:
    ok("«тусклее» уменьшило яркость: %s -> %s" % (b1, b2))
else:
    bad("«тусклее» не уменьшило яркость: %s -> %s" % (b1, b2))

# 6. Что включено.
d = ask("что включено")
info("что включено: %s" % ((d.get("restxt") or "")[:70]))
if d.get("source") == "home":
    ok("«что включено» - вопрос про дом, а не про погоду")
else:
    bad("«что включено» ушло в %s" % d.get("source"))

# 7. Неподключённый прибор: честное «нет», а не «включила».
d = ask("включи прибор")
info("прибор: %s (source=%s)" % ((d.get("restxt") or "")[:60], d.get("source")))
if d.get("source") != "home" or "не подключено" in (d.get("restxt") or "").lower():
    ok("неподключённый прибор назван неподключённым")
else:
    bad("колонка сказала «включила» про то, что подключать нечем: %r"
        % (d.get("restxt") or "")[:50])

# 8. Погода не должна уехать в дом.
d = ask("какая сейчас погода")
if d.get("source") == "plugin":
    ok("погода осталась погодой")
else:
    bad("погода ушла в %s" % d.get("source"))

# 9. Убрать за собой.
ask("выключи всё")
d = ask("что включено")
info("после «выключи всё»: %s" % ((d.get("restxt") or "")[:60]))

print()
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)