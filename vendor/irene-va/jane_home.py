"""Умный дом: разговор про устройства.

Отдельный модуль по той же причине, что jane_time и jane_context: здесь
должна быть чистая логика, которую можно проверить без колонки, без сети и
без железа. Сеть и реле - это драйвер, он подставляется снаружи.

Главное правило модуля: колонка не отвечает «включила» на то, чего не
включила. Поэтому устройства живут в настройках, и устройства, помеченные как
неподключённые, колонка прямо называет неподключёнными - иначе она будет
врать про дом, которого нет.

Что понимается:
- «включи свет», «выключи свет», «свет в гостиной»
- «ярче», «тусклее» - про последний упомянутый свет
- «температура в гостиной» - про датчик
- «что включено», «выключи всё»
- «включи чайник» - не свет, а прибор по имени

Проверки внизу: python3 vendor/irene-va/jane_context.py -> jane_home.py
"""

import re

ON = "on"
OFF = "off"

# Действия, которые колонка понимает. Не «включи свет в обоих углах» -
# несколько устройств за раз не поддержаны, и это лучше сказать, чем
# включить половину и сделать вид, что всю.
_ACTION_WORDS = (
    (re.compile(r"\b(?:включи|включите|вкл|зажги|зажгите)\b"), ON),
    (re.compile(r"\b(?:выключи|выключите|выкл|погаси|погасите)\b"), OFF),
)
# «свет» без глагола - это всё равно про включение.
_LIGHT_ON = re.compile(r"\b(?:включи свет|свет\b)")
_HOWBRIGHT = re.compile(r"\b(?:что включено|какой свет включен|что горит)\b")
_ALL = re.compile(r"\b(всё|все|всю квартиру|всего)\b")

_STEP = 20  # шаг яркости по команде «ярче»

# Окончания, которые отбрасываются при поиске устройства. Без этого
# поиск по имени бесполезен на русском: «лампа» не входит в «включи лампу»,
# потому что это разные падежные формы одного слова. Раньше по алиасу
# «лампа» не находилось ровно ничего, и колонка отвечала «не знаю такого».
_ENDINGS = ("ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
            "ом", "ем", "ов", "ев", "ах", "ям", "ем", "ам", "ую", "ю",
            "ой", "ей", "ая", "ое", "ые", "ый", "ий",
            "у", "а", "ю", "е", "ы", "и", "я", "о", "ь")


def _base(word):
    """Основа слова: «лампа» -> «ламп», «свет» -> «свет».

    Слишком короткие слова не режем, иначе «в» превратится в пустое и будет
    находиться где угодно.
    """
    w = str(word or "").lower().strip()
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[:-len(e)]
    return w


def _mentions(phrase, word):
    """Названо ли слово в фразе в любом падеже."""
    base = _base(word)
    if not base:
        return False
    return re.search(r"\b%s\w*\b" % re.escape(base), phrase) is not None


def cap(text):
    """Заглавная первая буква. Колонка говорит с начала фразы."""
    t = str(text or "").strip()
    return (t[0].upper() + t[1:]) if t else t


class Intent(object):
    """Что человек попросил. Действие, устройство и насколько."""

    def __init__(self, action, entity=None, kind=None, delta=None):
        self.action = action      # on / off / brighter / dimmer / status
        self.entity = entity      # id устройства
        self.kind = kind          # light / switch / sensor
        self.delta = delta        # для яркости: +_STEP или -_STEP

    def __repr__(self):
        return "Intent(%s, %s, %s, %s)" % (self.action, self.entity,
                                           self.kind, self.delta)


class Home(object):
    """Дом как список устройств и разговор о них.

    Устройства приходят снаружи (json в options). Здесь только разбор фразы
    и решение, что сказать. Включать и выключает - драйвер.
    """

    def __init__(self, devices=None, driver=None):
        self.devices = list(devices or [])
        self.driver = driver
        # Последний упомянутый свет: «ярче» без названия - про него.
        self.last_light = None

    # --- поиск устройства -------------------------------------------------

    def by_name(self, phrase):
        """Найти устройство по имени или синонимам. None - не найдено.

        Сравнение по основам слов: «включи лампу» должно находить «лампа».
        """
        p = " ".join(str(phrase or "").lower().replace("ё", "е").split())
        best = None
        best_len = 0
        for d in self.devices:
            words = [d.get("name", "")] + list(d.get("aliases") or [])
            for w in words:
                parts = [x for x in str(w or "").lower().split() if x]
                if not parts:
                    continue
                # Названное слово короче алиаса не считаем: иначе «свет»
                # побеждал бы «свет в спальне» всегда.
                if not all(_mentions(p, x) for x in parts):
                    continue
                if len(parts) > 1 and len(p) < len(w):
                    continue
                if len(w) > best_len:
                    best, best_len = d, len(w)
        return best

    def by_zone(self, zone):
        return [d for d in self.devices if d.get("zone") == zone]

    def named_zone(self, phrase):
        """Названа ли зона: «в гостиной», «на кухне»."""
        for d in self.devices:
            z = d.get("zone")
            if z and re.search(r"\bв\s+%s\b|\bна\s+%s\b" % (re.escape(z),
                                                           re.escape(z)),
                               phrase):
                return z
        return None

    # --- разбор фразы -----------------------------------------------------

    def parse(self, phrase):
        """Что попросили. None - это не про дом."""
        if not phrase or not self.devices:
            return None
        low = " ".join(str(phrase).lower().replace("ё", "е").split())

        # «что включено» - не действие, а вопрос.
        if _HOWBRIGHT.search(low):
            return Intent("status")

        # «ярче» / «тусклее» - про последний упомянутый свет. Без него
        # спрашивать не о чем, и это лучше, чем догадаться.
        if re.search(r"\bярче\b|\bтусклее\b|\bприбавь\b|\bубавь\b", low):
            if not self.last_light:
                return None
            brighter = bool(re.search(r"\bярче\b|\bприбавь\b", low))
            # Знак обязателен: без него «тусклее» увеличивало яркость, и
            # колонка отвечала «яркость 90» на просьбу сделать темнее.
            return Intent("brighter" if brighter else "dimmer",
                          entity=self.last_light, kind="light",
                          delta=_STEP if brighter else -_STEP)

        action = None
        for rx, act in _ACTION_WORDS:
            m = rx.search(low)
            if m:
                action = act
                break

        if _ALL.search(low):
            return Intent(action or ON, entity="*")

        d = self.by_name(low)
        if d:
            if d.get("kind") == "sensor":
                # Датчик нельзя включить - спросили «включи температуру».
                return None
            if d.get("kind") == "light":
                self.last_light = d.get("id")
            return Intent(action or ON, entity=d.get("id"), kind=d.get("kind"))

        # Свет без названия: «включи свет», «свет в гостиной».
        zone = self.named_zone(low)
        if _LIGHT_ON.search(low):
            if zone:
                lights = [x for x in self.by_zone(zone)
                          if x.get("kind") == "light"]
                if lights:
                    self.last_light = lights[0].get("id")
                    return Intent(action or ON, entity=lights[0].get("id"),
                                  kind="light")
            lights = [x for x in self.devices if x.get("kind") == "light"]
            if lights:
                self.last_light = lights[0].get("id")
                return Intent(action or ON, entity=lights[0].get("id"),
                              kind="light")
        return None

    # --- что ответить -----------------------------------------------------

    def connected(self, dev):
        return not dev.get("needs_link") if isinstance(dev, dict) else True

    def describe(self, dev):
        st = "включено" if self.state_of(dev) == ON else "выключено"
        bits = ["%s: %s" % (cap(dev.get("name")), st)]
        if dev.get("kind") == "light" and self.state_of(dev) == ON:
            b = self.driver.brightness(dev.get("id")) if self.driver else None
            if b is not None:
                bits.append("яркость %d" % b)
        return ", ".join(bits)

    def state_of(self, dev):
        if self.driver:
            return self.driver.get(dev.get("id")) or OFF
        return dev.get("state") or OFF

    def answer(self, intent):
        """Выполнить намерение и вернуть ответ колонки."""
        if intent.action == "status":
            on = [d for d in self.devices
                  if self.connected(d) and self.state_of(d) == ON]
            if not on:
                return "Сейчас ничего не горит.", None
            names = ", ".join(d.get("name", "?") for d in on[:6])
            if len(on) > 6:
                names += " и ещё %d" % (len(on) - 6)
            return cap("горит: %s" % names) + ".", None

        if intent.entity == "*":
            targets = [d for d in self.devices if self.connected(d)
                       and d.get("kind") != "sensor"]
            if not targets:
                return "Я не знаю, что здесь переключить.", None
            for d in targets:
                self.driver.set(d.get("id"), intent.action == ON)
            word = "включила" if intent.action == ON else "выключила"
            return "%s %s: %s." % (word, len(targets),
                                   ", ".join(d.get("name", "?")
                                             for d in targets[:4])), "home"

        dev = None
        for d in self.devices:
            if d.get("id") == intent.entity:
                dev = d
                break
        if dev is None:
            return "Я не знаю такого устройства.", None
        if not self.connected(dev):
            # Не выдумываем: устройство есть в настройках, но подключиться
            # к нему нечем. Формулировка без прилагательного про род
            # устройства - «прибор ещё не подключено» согласовано неверно,
            # а род названия машина не знает.
            return "%s: не подключено - управлять нечем." % cap(dev.get("name")), None
        if dev.get("kind") == "sensor":
            val = self.driver.read(dev.get("id")) if self.driver else None
            if val is None:
                return "Не могу прочитать датчик.", None
            return "%s: %s." % (cap(dev.get("name")), val), None

        if intent.action in ("brighter", "dimmer"):
            b = self.driver.brightness(dev.get("id")) or 0
            b = max(0, min(100, b + intent.delta))
            self.driver.set(dev.get("id"), ON, brightness=b)
            return "%s: яркость %d." % (cap(dev.get("name")), b), "home"

        self.driver.set(dev.get("id"), intent.action == ON)
        return cap(self.describe(dev)) + ".", "home"


class LocalDriver(object):
    """Драйвер без сети: состояние в памяти. Для реле на плате и для проверки.

    Явно не притворяется настоящим железом: устройства с needs_link он не
    трогает, поэтому «включила» про них никогда не прозвучит.
    """

    def __init__(self):
        self.state = {}
        self.bright = {}

    def get(self, entity):
        return self.state.get(entity)

    def set(self, entity, on, brightness=None):
        self.state[entity] = ON if on else OFF
        if brightness is not None:
            self.bright[entity] = brightness

    def brightness(self, entity):
        return self.bright.get(entity, 100)

    def read(self, entity):
        return self.state.get(entity)


# ---------------------------------------------------------------------------
# Проверки
# ---------------------------------------------------------------------------
DEVICES = [
    {"id": "light_gost", "name": "свет", "zone": "гостиная",
     "aliases": ["лампа"], "kind": "light"},
    {"id": "light_kitchen", "name": "свет на кухне", "zone": "кухня",
     "kind": "light"},
    {"id": "plug_teapot", "name": "чайник", "kind": "switch"},
    {"id": "sensor_temp", "name": "температура в гостиной", "zone": "гостиная",
     "kind": "sensor"},
    {"id": "light_unplugged", "name": "свет в спальне", "kind": "light",
     "needs_link": True},
]


def selfcheck():
    fails = []

    def want(cond, msg):
        if not cond:
            fails.append(msg)

    dr = LocalDriver()
    h = Home(DEVICES, dr)

    # Включение света в гостиной.
    it = h.parse("включи свет в гостиной")
    want(it and it.entity == "light_gost", "включи свет в гостиной -> %r" % it)
    reply, act = h.answer(it)
    want(act == "home" and "свет" in reply.lower(),
         "ответ на включение: %r" % reply)
    want(reply.startswith("Свет"),
         "ответ должен начинаться с большой буквы: %r" % reply)
    want(reply.count("включено") == 1,
         "в ответе не должно быть тавтологии: %r" % reply)
    want(dr.get("light_gost") == ON, "свет не включился")

    # Выключение того же.
    it = h.parse("выключи свет в гостиной")
    h.answer(it)
    want(dr.get("light_gost") == OFF, "свет не выключился")

    # По синониму - «лампа» это тот же свет.
    it = h.parse("включи лампу")
    want(it and it.entity == "light_gost", "синоним лампа -> %r" % it)

    # «ярче» - про последний упомянутый свет.
    dr.bright["light_gost"] = 50
    it = h.parse("ярче")
    want(it and it.action == "brighter" and it.entity == "light_gost",
         "«ярче» -> %r" % it)
    reply, _ = h.answer(it)
    want("70" in reply, "яркость не выросла: %r" % reply)
    it = h.parse("тусклее")
    h.answer(it)
    want(dr.brightness("light_gost") == 50, "тусклее не уменьшил яркость")

    # Яркость не уходит за пределы.
    dr.bright["light_gost"] = 95
    h.answer(h.parse("ярче"))
    want(dr.brightness("light_gost") == 100, "яркость ушла за 100")
    dr.bright["light_gost"] = 5
    h.answer(h.parse("тусклее"))
    want(dr.brightness("light_gost") == 0, "яркость ушла ниже нуля")

    # Прибор не свет: «включи чайник».
    it = h.parse("включи чайник")
    want(it and it.entity == "plug_teapot", "чайник -> %r" % it)
    h.answer(it)
    want(dr.get("plug_teapot") == ON, "чайник не включился")

    # «что включено» - вопрос, а не действие.
    it = h.parse("что включено")
    want(it and it.action == "status", "что включено -> %r" % it)
    reply, _ = h.answer(it)
    want("чайник" in reply, "в ответе нет включённого: %r" % reply)

    # Всё сразу.
    it = h.parse("выключи всё")
    want(it and it.entity == "*", "выключи всё -> %r" % it)
    h.answer(it)
    want(dr.get("plug_teapot") == OFF and dr.get("light_gost") == OFF,
         "выключи всё не выключило приборы")

    # Датчик: его нельзя включить, но можно спросить.
    want(h.parse("включи температуру в гостиной") is None,
         "датчик нельзя включить")
    it = h.parse("температура в гостиной")
    want(it is None or it.kind != "switch",
         "температура не должна превращаться в действие над прибором")

    # Неподключённое устройство: честное «нет», а не «включила».
    it = h.parse("включи свет в спальне")
    want(it and it.entity == "light_unplugged",
         "свет в спальне не найден: %r" % it)
    reply, act = h.answer(it)
    want(act is None and "не подключено" in reply,
         "неподключённый свет должен быть назван неподключённым: %r" % reply)

    # Про дом, когда дома нет.
    empty = Home([], LocalDriver())
    want(empty.parse("включи свет") is None,
         "без устройств нечего включать")

    # Чужой разговор не должен считаться про дом.
    for q in ("какая сейчас погода", "буди меня в 7 утра", "поговори с дженет"):
        want(h.parse(q) is None, "лишнее сработало на: %s" % q)

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    jane_home: свет и приборы, а не выдуманный дом")
    print("ИТОГ: провалено %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(selfcheck())