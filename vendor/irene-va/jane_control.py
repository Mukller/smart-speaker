"""Управление колонкой: повтори, громче, тише, стоп.

Отдельный модуль по той же причине, что остальная логика: разбор фразы
проверяется без колонки, без сети и без модели.

Зачем это. Три самые частые вещи, которые говорят колонке, и на которые она
не отвечала:

- «повтори» - услышала плохо или отвлаивалась;
- «громче» и «тише» - не слышно или слишком громко;
- «стоп» - она говорит не то, что нужно, или музыка не нужна.

Это про колонку, а не про умный дом и не про время, поэтому живёт отдельно:
иначе «громче» попало бы к лампам.

Громкость хранится в настройках и переживает перезапуск: колонка, которую
убавили до 30, не должна после перезагрузки снова кричать.

Проверки: python3 vendor/irene-va/jane_control.py
"""

import os
import re

# Повтор.
_REPEAT = re.compile(
    r"\b(?:повтори|повторить|ещё раз|еще раз|опять|как ты сказала|"
    r"что ты сказала|что ты ответила)\b")
# Громкость. «Громче» - это про колонку, а не про свет: разные дела.
_LOUDER = re.compile(
    r"\b(?:громче|громко|громче\s+скажи| louder| louder)\b", re.I)
_SOFTER = re.compile(
    r"\b(?:тише|тихо|потише|не\s+так\s+громко|не\s+кричи)\b", re.I)
# Остановка.
_STOP = re.compile(
    r"\b(?:стоп|стоп\s+хватит|хватит|замолчи|стоп\s+говори|отмена|"
    r"отмени|остановись|достаточно)\b")

_MIN_VOL = 10
_MAX_VOL = 100
_STEP = 15


def _norm(text):
    return " ".join(str(text or "").lower().replace("ё", "е").split())


class Control(object):
    """Громкость и последняя сказанная фраза."""

    def __init__(self, path=None, volume=70, speak=None):
        self.path = path
        self.volume = int(volume)
        self._speak = speak
        self.last_reply = None

    def set_speaker(self, speak):
        """Функция, которая умеет говорить (у нас это синтез)."""
        self._speak = speak

    def load(self):
        if not self.path or not os.path.exists(self.path):
            return self
        try:
            import json
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            v = int(d.get("volume") or 0)
            if MIN_VOL <= v <= _MAX_VOL:
                self.volume = v
        except Exception:
            pass
        return self

    def save(self):
        if not self.path:
            return
        try:
            import json
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"volume": self.volume}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def remember(self, text):
        """Запомнить, что было сказано в ответ."""
        t = str(text or "").strip()
        # Слишком длинное «последнее сказанное» бесполезно для повтора.
        if t and len(t) < 600:
            self.last_reply = t

    # --- разбор ------------------------------------------------------------

    def parse(self, phrase):
        """Что попросили. None - это не про управление колонкой."""
        p = _norm(phrase)
        if not p:
            return None
        # Порядок важен: «повтори, но тише» - это и повтор, и громкость,
        # и спросили в первую очередь про громкость.
        if _SOFTER.search(p):
            return "softer"
        if _LOUDER.search(p):
            return "louder"
        if _REPEAT.search(p):
            return "repeat"
        if _STOP.search(p):
            return "stop"
        return None

    # --- действие ----------------------------------------------------------

    def apply(self, what):
        """Что сказать. None - действие не наше (стоп обрабатывает плеер)."""
        if what == "louder":
            self.volume = min(_MAX_VOL, self.volume + _STEP)
            self.save()
            return "Громче."
        if what == "softer":
            self.volume = max(_MIN_VOL, self.volume - _STEP)
            self.save()
            return "Тише."
        if what == "repeat":
            if not self.last_reply:
                return "Я ничего не говорила."
            return self.last_reply
        return None


# ---------------------------------------------------------------------------
# Проверки
# ---------------------------------------------------------------------------
def selfcheck():
    fails = []

    def want(cond, msg):
        if not cond:
            fails.append(msg)

    c = Control(volume=70)

    # Повтор.
    want(c.parse("повтори") == "repeat", "повтори не распознано")
    want(c.parse("ещё раз") == "repeat", "«ещё раз» не распознано")
    want(c.parse("что ты сказала") == "repeat", "«что ты сказала» не распознано")
    c.remember("В Гомеле сейчас плюс пять.")
    want(c.apply("repeat") == "В Гомеле сейчас плюс пять.",
         "повтор: %r" % c.apply("repeat"))

    # Пустое не повторяется.
    want(Control().apply("repeat") == "Я ничего не говорила.",
         "повтор без истории должен честно сказать об этом")

    # Громкость.
    want(c.parse("громче") == "louder", "громче не распознано")
    want(c.parse("тише") == "softer", "тише не распознано")
    want(c.parse("не кричи") == "softer", "«не кричи» не распознано")
    c.apply("louder")
    want(c.volume == 85, "громче: %s" % c.volume)
    c.apply("softer")
    c.apply("softer")
    want(c.volume == 55, "тише: %s" % c.volume)

    # Громкость не выходит за края.
    for _ in range(20):
        c.apply("louder")
    want(c.volume == _MAX_VOL, "громкость ушла выше 100: %s" % c.volume)
    for _ in range(30):
        c.apply("softer")
    want(c.volume == _MIN_VOL, "громкость ушла ниже минимума: %s" % c.volume)

    # Стоп.
    want(c.parse("стоп") == "stop", "стоп не распознано")
    want(c.parse("хватит") == "stop", "«хватит» не распознано")
    want(c.apply("stop") is None, "стоп должен обрабатываться вне модуля")

    # Громкость не путается со светом: «сделай свет ярче» - это умный дом,
    # и колонка не должна считать это своей громкостью.
    want(c.parse("сделай свет ярче") is None,
         "«сделай свет ярче» не должно быть про громкость")

    # Чужой разговор.
    for q in ("какая сейчас погода", "буди меня в 7 утра", "привет"):
        want(c.parse(q) is None, "лишнее сработало на: %s" % q)

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    jane_control: повтори, громче, тише, стоп")
    print("ИТОГ: провалено %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(selfcheck())