"""Привычки колонки: что она запомнила о вас.

Отдельный модуль по той же причине, что и остальная логика колонки: это
чистый код, и он должен проверяться без колонки, без сети и без модели.

Что колонка запоминает:
- город, в котором вы живёте: «я живу в Гомеле», и погода уже про него;
- что вы часто просите, чтобы можно было сказать «ты обычно просишь X»;
- как с вами говорить: ночью тише и медленнее, иначе колонка будит.

Правило, которому это подчинено: колонка не должна впадать в восторг от
того, что она запомнила. Привычки - это молчаливое удобство. Если человек
сказал «живу в Гомеле» один раз, колонка не должна благодарить его за это при
каждом ответе.

Чего модуль не делает: не отправляет ничего наружу и никуда не напихивает
профиль. Всё лежит в одном файле рядом с настройками.

Проверки: python3 vendor/irene-va/jane_habits.py
"""

import json
import os
import re
import time

# «я живу в Гомеле», «я из Минска», «город - Гомель»
_CITY = re.compile(
    r"\b(?:я\s+)?(?:живу|живёшь|переехал|переехала|нахожусь|из)\s+"
    r"(?:в|во|из|из\s+города)?\s*([а-яё-]{3,})\b"
    r"|\bгород\s*[-—:]?\s*([а-яё-]{3,})", re.I)
# Что вы обычно просите.
_WHAT = re.compile(
    r"\bчто\s+я\s+(?:обычно|чаще всего|люблю|любишь)\s+(.+)", re.I)
# Не подтверждаем привычки, а просто пользуемся ими.
_ACK = re.compile(
    r"\b(?:запомни|запомнила|запомнилось|понял|поняла|хорошо|спасибо|"
    r"было\s+за\s+ранее)\b", re.I)

# Слова про город не считаем городом.
_NOT_CITY = {
    "тебя", "меня", "себя", "нас", "вас", "там", "тут", "здесь", "домой",
    "к себе", "с работы", "в офис", "в банк", "в магазин", "в школу",
    "в университет", "в туалет", "в душ", "в душе", "за хлебом",
    "за молоком", "в гости", "домой из", "душ", "дом",
}


# Города, где приведение к именительному невозможно без словаря склонений.
# «я живу в Москве» - самая частая фраза после Минска, а по правилам
# вышло бы «москв».
_CITY_FIX = {
    "москв": "москва", "моск": "москва", "спи": "санкт-петербург",
    "спб": "санкт-петербург", "питер": "санкт-петербург",
    "петербург": "санкт-петербург", "мск": "москва",
    "могилев": "могилев", "могилёв": "могилев",
}


def nominative(word):
    """«Минска» -> «Минск», «Гомеле» -> «Гомель».

    Без словаря склонений это в общем случае неразрешимо: по правилам
    «Москве» превратилась бы в «москв», а «Смоленске» - в «смоленскь».
    Поэтому однозначные окончания срезаются, а города, где правило вредит,
    закрыты таблицей. Ошибка тут означает лишь «погода не нашлась»: колонка
    об этом говорит прямо, а не выдумывает город.
    """
    w = _norm(word)
    if len(w) < 3:
        return w
    for tail in ("ах", "ях", "ам", "ям", "ами", "ыми"):
        if w.endswith(tail) and len(w) - len(tail) >= 3:
            w = w[:-len(tail)]
            break
    if w.endswith(("а", "ы", "и", "у", "ю")) and len(w) > 3:
        w = w[:-1]
    elif w.endswith("е"):
        base = w[:-1]
        # «Гомеле» -> «Гомель». Мягкий знак ставим там, где он вероятен.
        w = base + "ь" if base[-1:] in ("л", "ь", "н", "м", "р") else base
    w = w.rstrip("ь") if w in _CITY_FIX else w
    return _CITY_FIX.get(w, w)


def _norm(text):
    return " ".join(str(text or "").lower().replace("ё", "е").split())


def _cap(text):
    t = str(text or "").strip()
    return (t[0].upper() + t[1:]) if t else t


class Habits(object):
    """Запомненное о пользователе. Один объект на колонку."""

    def __init__(self, path=None, now=None):
        self.path = path
        self._now = now
        self.city = None
        # Счётчики частых команд: что -> сколько раз просили.
        self.counts = {}
        self.asked = 0
        self.spoke = 0
        self.changed_at = 0

    def _clock(self):
        n = self._now
        if n is None:
            return time.time()
        return n() if callable(n) else n

    # --- сохранение --------------------------------------------------------

    def load(self):
        if not self.path or not os.path.exists(self.path):
            return self
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.city = d.get("city") or None
            self.counts = dict(d.get("counts") or {})
            self.asked = int(d.get("asked") or 0)
            self.spoke = int(d.get("spoke") or 0)
        except Exception:
            # Привычки - не то, из-за которого колонка не должна
            # подниматься. Сломанный файл просто игнорируется.
            self.city, self.counts = None, {}
        return self

    def save(self):
        if not self.path:
            return
        try:
            d = {"city": self.city, "counts": self.counts,
                 "asked": self.asked, "spoke": self.spoke,
                 "changed_at": self.changed_at}
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # --- что сказали --------------------------------------------------------

    def note_city(self, phrase):
        """Город из фразы, если он назван. None - если не про город."""
        m = _CITY.search(str(phrase or ""))
        if not m:
            return None
        raw = (m.group(1) or m.group(2) or "").strip().lower()
        # Стоп-слова проверяем до нормализации: иначе «домой» превращается
        # в «дом» и проходит как город.
        if not raw or raw in _NOT_CITY or len(raw) < 3:
            return None
        city = nominative(raw)
        if not city or city in _NOT_CITY:
            return None
        if self.city != city:
            self.city = city
            self.changed_at = self._clock()
        return city

    def note_command(self, phrase):
        """Засчитать команду в частые."""
        p = _norm(phrase)
        if len(p) < 3:
            return None
        self.asked += 1
        self.counts[p] = self.counts.get(p, 0) + 1
        self.changed_at = self._clock()
        return p

    def note_spoke(self):
        self.spoke += 1

    # --- частые -------------------------------------------------------------

    def top(self, n=3):
        """Что просят чаще всего: [(фраза, раз), ...]."""
        return sorted(self.counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    # Склонение числительных для «раз»: 1 раз, 2-4 раза, 5 и дальше раз.
    def plural(self, n, one, few, many):
        n = int(n)
        if n % 10 == 1 and n % 100 != 11:
            return one
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return few
        return many

    def describe_top(self, n=3):
        top = self.top(n)
        if not top:
            return "Пока ничего не просили."
        parts = []
        for ph, c in top:
            # Раньше всегда печаталось «раз», и выходило «3 раз». По-русски
            # после трёх идёт «раза», после пяти - снова «раз».
            parts.append("«%s» %d %s"
                         % (ph, c, self.plural(c, "раз", "раза", "раз")))
        return "Чаще всего просите: %s." % ", ".join(parts)

    # --- как говорить -------------------------------------------------------

    def pace(self, hour=None):
        """Темп речи по числу 0-100. Ночью медленнее.

        Раньше темп был один на все часы, и колонка в три часа ночи
        тараторила тем же темпом, что и утром.
        """
        if hour is None:
            hour = time.localtime(self._clock()).tm_hour
        if hour < 6 or hour >= 23:
            return 85      # ночь: медленнее и тише
        if hour < 9:
            return 95      # утро: бодро, но не громко
        if hour >= 22:
            return 88
        return 100

    def volume(self, hour=None):
        """Громкость 0-100."""
        if hour is None:
            hour = time.localtime(self._clock()).tm_hour
        if hour < 6 or hour >= 23:
            return 70      # ночью будить надо тише
        return 100


# ---------------------------------------------------------------------------
# Проверки
# ---------------------------------------------------------------------------
def selfcheck():
    fails = []

    def want(cond, msg):
        if not cond:
            fails.append(msg)

    clock = [1000.0]
    h = Habits(now=lambda: clock[0])

    # Город из фразы.
    want(h.note_city("я живу в Гомеле") == "гомель",
         "город из «я живу в Гомеле»")
    want(h.note_city("я из Минска") == "минск", "город из «я из Минска»")
    want(h.note_city("город - Брест") == "брест", "город из «город - Брест»")

    # Не всякое слово про город - город.
    for bad_phrase in ("я иду в магазин", "я живу в душе", "иди домой",
                       "что ты умеешь"):
        want(h.note_city(bad_phrase) is None,
             "«%s» не должно считаться городом" % bad_phrase)

    # Частые команды.
    for _ in range(3):
        h.note_command("какая сейчас погода")
    h.note_command("включи чайник")
    want(h.top(1)[0][0] == "какая сейчас погода",
         "чаще всего должно быть то, что просили чаще: %r" % h.top(2))
    want("погода" in h.describe_top(), "описание привычек: %r"
         % h.describe_top())

    # Ночью тише и медленнее.
    want(h.pace(hour=3) < h.pace(hour=13), "ночью темп должен быть ниже")
    want(h.volume(hour=3) < h.volume(hour=13),
         "ночью громкость должна быть ниже")
    want(h.pace(hour=13) == 100, "днём обычный темп")

    # Пустая история - не выдумываем.
    fresh = Habits(now=lambda: clock[0])
    want("ничего" in fresh.describe_top(),
         "без истории колонка не должна выдумывать привычки")

    # Круг суток не должен ломать разговор.
    for hh in range(24):
        want(0 < fresh.pace(hour=hh) <= 100 and 0 < fresh.volume(hour=hh) <= 100,
             "темп вне пределов на %d часах" % hh)

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    jane_habits: колонка помнит, но не хвастается")
    print("ИТОГ: провалено %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(selfcheck())