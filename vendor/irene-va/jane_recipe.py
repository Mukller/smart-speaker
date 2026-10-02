"""Что колонка делает, когда будильник сработал.

Отдельный модуль по той же причине, что остальная логика: разбор фразы
должен проверяться без колонки, без сети и без железа.

Будильник сам по себе бесполезен - он звонит, а дальше всё равно вставать
в темноте. Поэтому у будильника есть действия: «буди в 6:30 по будням и
включи свет» - это один будильник с двумя делами, а не две команды, о
которых надо помнить.

Поддерживаются действия, которые колонка действительно умеет:
- свет или прибор: включается и выключается по названию;
- «и скажи ...» / «и поздравь ...» - произносится текст;
- музыка - включается, если колонка её умеет.

Чего модуль не делает: не выдумывает. Если в «буди в 7 и включи свет» нет
часа - это не будильник. Если свет не подключён - действие выполнится
частично, и колонка скажет про это, а не промолчит.

Проверки: python3 vendor/irene-va/jane_recipe.py
"""

import re

# Глаголы действия: «включи свет», «выключи чайник», «запусти музыку».
_ACT = re.compile(
    r"\b(?:включи|включите|вкл|зажги|выключи|выключите|выкл|погаси|"
    r"поставь|запусти|запустите|воспроизведи)\s+(.+?)(?=$|[,;.!?]|\s+и\s+|$)",
    re.I)
_SAY = re.compile(
    r"\b(?:и\s+)?(?:скажи|скажите|произнеси|зачитай|поздравь)\s+(.+?)$", re.I)
# «буди в 6:30 по будням и включи свет» - хвост после времени.
_TAIL = re.compile(r"\bи\s+(включи|выключи|зажги|погаси|поставь|запусти|"
                   r"скажи|произнеси|поздравь)\b", re.I)
_MUSIC = re.compile(r"^(?:музыку|музыка|песню|плейлист|радио|шансон|рок)$", re.I)


class Action(object):
    """Одно дело: что включить или что сказать."""

    def __init__(self, kind, target="", text=""):
        self.kind = kind      # device / say
        self.target = target  # что включить
        self.text = text      # что сказать

    def as_dict(self):
        return {"kind": self.kind, "target": self.target, "text": self.text}

    @staticmethod
    def from_dict(d):
        return Action(d.get("kind") or "say", d.get("target") or "",
                      d.get("text") or "")

    def __repr__(self):
        return "Action(%s, %r, %r)" % (self.kind, self.target, self.text)


class Recipe(object):
    """Будильник с делами."""

    def __init__(self, at=0, label="", repeat=None, actions=None):
        self.at = at
        self.label = label
        self.repeat = repeat
        self.actions = list(actions or [])

    def as_dict(self):
        return {"at": self.at, "label": self.label, "repeat": self.repeat,
                "actions": [a.as_dict() for a in self.actions]}

    def describe(self):
        """Что сказать вслух про этот рецепт."""
        if not self.actions:
            return self.label
        bits = []
        for a in self.actions:
            if a.kind == "say":
                bits.append("скажу: %s" % a.text)
            elif a.kind == "device":
                bits.append(a.target)
        return "%s, %s" % (self.label, ", ".join(bits))


def parse_actions(text):
    """Что попросили сделать. Список Action, возможно пустой."""
    acts = []
    if not text:
        return acts
    low = text.strip()
    m = _SAY.search(low)
    if m:
        say = m.group(1).strip(" ,.!?")
        if say:
            acts.append(Action("say", text=say))
        return acts
    # Устройства. Несколько - через «и»: «включи свет и чайник». Глагол
    # относится ко всем перечисленным, поэтому «чайник» без своего глагола
    # берёт глагол предыдущего куска. Раньше он просто терялся, и
    # «включи свет и чайник» включал только свет.
    verb_seen = ""
    for chunk in re.split(r"\s+и\s+", low):
        chunk = chunk.strip(" ,.!?")
        # Ведущее «и» - не глагол, а разделитель.
        chunk = re.sub(r"^и\s+", "", chunk).strip()
        if not chunk:
            continue
        m = _ACT.match(chunk)
        if m:
            verb_seen = (chunk.split()[0] or "").lower()
            target = m.group(1).strip(" ,.!?")
        elif verb_seen:
            # Продолжение перечисления без повтора глагола.
            target = chunk
        else:
            continue
        if not target:
            continue
        if _MUSIC.match(target):
            acts.append(Action("device", target="музыка"))
            continue
        a = Action("device", target=target)
        a.verb = verb_seen
        acts.append(a)
    return acts


def split_recipe(text):
    """Отделить время будильника от дел.

    Возвращает (хвост_дел, остаток) или (None, текст). Нужно, потому что
    «буди в 6:30 по будням и включи свет» - это время плюс дела, а
    «включи свет» - только дела и не будильник вовсе.
    """
    if not text:
        return None, text
    low = str(text).lower().replace("ё", "е")
    m = _TAIL.search(low)
    if not m:
        return None, text
    # Дела начинаются с первого «и <глагол>».
    start = m.start()
    return text[start:].strip(), text[:start].strip()


# ---------------------------------------------------------------------------
# Проверки
# ---------------------------------------------------------------------------
def selfcheck():
    fails = []

    def want(cond, msg):
        if not cond:
            fails.append(msg)

    tail, rest = split_recipe("буди в 6:30 по будням и включи свет")
    want(rest == "буди в 6:30 по будням", "время отделено неверно: %r" % rest)
    want(tail and "включи свет" in tail, "хвост с делами: %r" % tail)

    acts = parse_actions(tail)
    want(len(acts) == 1 and acts[0].kind == "device"
         and acts[0].target == "свет",
         "разбор действия включения: %r" % acts)

    # Два прибора через «и».
    acts = parse_actions("включи свет и чайник")
    want(len(acts) == 2, "два прибора: %r" % acts)
    want([a.target for a in acts] == ["свет", "чайник"],
         "порядок приборов: %r" % [a.target for a in acts])

    # Сказать.
    acts = parse_actions("скажи доброе утро")
    want(len(acts) == 1 and acts[0].kind == "say"
         and acts[0].text == "доброе утро",
         "разбор просьбы сказать: %r" % acts)

    acts = parse_actions("и скажи счастливого дня")
    want(len(acts) == 1 and acts[0].kind == "say",
         "«и скажи» должно работать так же: %r" % acts)

    # Музыка - это тоже устройство, но названное особым словом.
    acts = parse_actions("запусти музыку")
    want(len(acts) == 1 and acts[0].target == "музыка",
         "музыка: %r" % acts)

    # Без дел - пусто, а не выдумка.
    want(parse_actions("") == [], "пустая фраза не должна давать действий")
    want(parse_actions("свет") == [],
         "одно слово без глагола - не действие")
    want(split_recipe("буди в 7 утра") == (None, "буди в 7 утра"),
         "будильник без дел не должен ломаться")

    # Рецепт целиком.
    r = Recipe(at=1, label="06:30", repeat="weekdays",
               actions=parse_actions("включи свет"))
    want("свет" in r.describe(), "описание рецепта: %r" % r.describe())
    back = Recipe(**{})  # пустой, чтобы проверить as_dict/from_dict
    a = Action("device", "свет")
    want(Action.from_dict(a.as_dict()).target == "свет",
         "действие не переживает сохранение")

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    jane_recipe: будильник умеет дела, а не только звонить")
    print("ИТОГ: провалено %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(selfcheck())