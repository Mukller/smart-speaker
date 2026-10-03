"""Напоминания: «напомни купить хлеб».

Отдельный модуль по той же причине, что остальная логика колонки: разбор
фразы проверяется без колонки, без сети и без модели.

Зачем это. «Напомни купить хлеб» уходило в языковую модель, и та
уверенно предлагала заказать хлеб в интернете. Это худший ответ из
возможных: колонка соглашается сделать то, чего не делает. Напоминание -
это ровно то, что умная колонка обязана уметь, и не умела ничего.

Разбор здесь, хранение и выдача - в приложении. Модуль отвечает на два
вопроса: что человек попросил запомнить и когда об этом сказать.

Важное решение: если время не названо, колонка спрашивает, а не выбирает
время сама. Придумывать «через пять минут» - это выдумывать обещание.

Проверки: python3 vendor/irene-va/jane_remind.py
"""

import datetime
import re

# «напомни», «напомни мне», «не забудь»
_REMIND = re.compile(
    r"\b(?:напомни|напомни мне|напомнить|напомни-кажется|напомни мне "
    r"пожалуйста|не забудь|не забывай)\b", re.I)
# Вопросы о списке.
_LIST = re.compile(
    r"\b(?:что\s+напомнить|что\s+напомнить\s+мне|какие\s+напоминания|"
    r"что\s+ты\s+должна\s+напомнить|что\s+мне\s+напомнить)\b", re.I)
# Отмена.
_FORGET = re.compile(
    r"\b(?:забудь|напоминание\s+не\s+нужно|отмени\s+напоминание|"
    r"удали\s+напоминание|напоминаний\s+не\s+нужно)\b", re.I)
# Когда. Пробел между числом и единицей обязателен: при \s* единица
# налипала на первое слово дела, и «напомни через час позвонить маме»
# превращалось в напоминание про «ь маме».
_WHEN = re.compile(
    r"\b(?:через|в\s+течение|спустя)\s+(?:(\d+|\D{1,12}?)\s+)?"
    r"(минут\w*|час\w*|ден[ьяей]|дн\w+|недел[ьюия]|недел\w*)\b", re.I)
_AT = re.compile(
    r"\b(?:в|во|на)\s+(\d{1,2})\s*(?::|ч|час)?\s*(\d{2})?\s*"
    r"(утра|утром|вечера|вечером|ночи|дня|днём|час|часа|часов)?", re.I)

_NUM = {"один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3,
        "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
        "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12,
        "пятнадцать": 15, "двадцать": 20, "тридцать": 30, "сорок": 40,
        "пятьдесят": 50, "час": 1, "часа": 2, "часов": 5,
        "минуту": 1, "минуты": 2, "минут": 5, "день": 1, "дня": 2,
        "дней": 5, "неделю": 7, "недели": 7}

# Время словами: «в семь утра». Колонка слышит слова, а не цифры,
# поэтому цифровой разбор выше для неё бесполезен.
_AT_WORD = re.compile(
    r"\b(?:в|во|на)\s+("
    + "|".join(sorted(_NUM, key=len, reverse=True)) + r")\s+"
    r"(утра|утром|вечера|вечером|ночи|дня|днём|час|часа|часов)\b",
    re.I)


def _num(token):
    t = str(token or "").strip().lower()
    if t.isdigit():
        return int(t)
    return _NUM.get(t)


def _plural(n, one, few, many):
    n = int(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _shift_for_word(hour, word):
    if not word:
        return hour
    if word in ("вечера", "вечером", "ночи", "дня", "днём"):
        return hour + 12 if 1 <= hour <= 11 else hour
    if word in ("утра", "утром"):
        return 0 if hour == 12 else hour
    return hour


def parse_reminder(phrase, now=None):
    """Что попросили. None - это не напоминание.

    Возвращает {"text": ..., "at": epoch или None}. at = None означает,
    что время не названо: колонка обязана спросить, а не угадать.
    """
    if not phrase:
        return None
    low = " ".join(str(phrase).lower().replace("ё", "е").split())
    if not _REMIND.search(low):
        return None

    # Что именно напомнить: всё после «напомни [мне]», без слов про время.
    body = re.split(_REMIND, low, maxsplit=1)[-1].strip(" ,.")
    if not body:
        body = low

    now = now or datetime.datetime.now()
    at = None
    # «через 10 минут»
    m = _WHEN.search(low)
    at = None
    if m:
        # Нет числа - значит «через час» это один час.
        n = _num(m.group(1)) if m.group(1) else 1
        unit = m.group(2)
        if n:
            if unit.startswith("час"):
                secs = n * 3600
            elif unit.startswith("минут"):
                secs = n * 60
            elif unit.startswith("ден"):
                secs = n * 86400
            elif unit.startswith("недел"):
                secs = n * 7 * 86400
            else:
                secs = n * 60
            at = now.timestamp() + secs
            body = _WHEN.sub("", body).strip(" ,.")

    # «в семь утра»
    if at is None:
        m = _AT.search(low)
        if m:
            h = _num(m.group(1))
            mi = int(m.group(2) or 0)
            word = m.group(3)
            if h is not None and 0 <= h <= 23 and mi < 60:
                h = _shift_for_word(h, word)
                target = now.replace(hour=h, minute=mi, second=0,
                                     microsecond=0)
                if target <= now:
                    target += datetime.timedelta(days=1)
                at = target.timestamp()
                body = _AT.sub("", body).strip(" ,.")
    if at is None:
        m = _AT_WORD.search(low)
        if m:
            h = _num(m.group(1))
            if h is not None:
                h = _shift_for_word(h, m.group(2))
                target = now.replace(hour=h, minute=0, second=0,
                                     microsecond=0)
                if target <= now:
                    target += datetime.timedelta(days=1)
                at = target.timestamp()
                body = _AT_WORD.sub("", body).strip(" ,.")

    body = body.strip(" ,.-")
    if not body or len(body) < 2:
        return None
    return {"text": body, "at": at}


def when_text(at, now=None):
    """Человеческое «когда» для ответа и списка.

    Минуты округляются, а не отбрасываются: иначе «напомню через час» через
    секунду звучало как «через 59 минут», и человек не понимал, что время
    почти не изменилось.
    """
    if not at:
        return "когда скажете"
    now = now or datetime.datetime.now()
    left = int(at - now.timestamp())
    if left < 45:            # меньше минуты - не «минута», а «сейчас»
        return "сейчас"
    if left < 3600:
        m = int(round(left / 60.0))
        if m >= 60:
            # Округлённые минуты доросли до часа: «через 60 минут» звучит
            # как «я не знаю, как это сказать».
            return "через час"
        return "через %d %s" % (m, _plural(m, "минуту", "минуты", "минут"))
    if left < 86400:
        h = int(round(left / 3600.0))
        return "через %d %s" % (h, _plural(h, "час", "часа", "часов"))
    return datetime.datetime.fromtimestamp(at).strftime("%d %b")


def is_list(question):
    return bool(_LIST.search(_norm(question)))


def is_forget(question):
    return bool(_FORGET.search(_norm(question)))


def _norm(t):
    return " ".join(str(t or "").lower().replace("ё", "е").split())


# ---------------------------------------------------------------------------
# Проверки
# ---------------------------------------------------------------------------
def selfcheck():
    import datetime as _d
    fails = []

    def want(cond, msg):
        if not cond:
            fails.append(msg)

    now = _dt(2026, 10, 2, 9, 0)

    # Без времени - колонка обязана спросить, а не выдумать.
    got = parse_reminder("напомни купить хлеб", now)
    want(got and got["text"] == "купить хлеб",
         "что напомнить: %r" % (got,))
    want(got and got["at"] is None,
         "без времени должно быть None, а не выдуманное время: %r" % (got,))

    # «через 10 минут».
    got = parse_reminder("напомни через 10 минут купить молоко", now)
    want(got and got["text"] == "купить молоко",
         "текст при «через»: %r" % (got,))
    want(got and got["at"] and 590 < got["at"] - _epoch(now) < 610,
         "через 10 минут: %r" % (got,))

    # Словами, а не цифрами.
    got = parse_reminder("напомни через час позвонить маме", now)
    want(got and got["at"] and 3500 < got["at"] - _epoch(now) < 3700,
         "через час: %r" % (got,))
    want(got and "маме" in got["text"], "текст при «через час»: %r" % (got,))

    # «в семь утра» - имена, а не «в семь».
    got = parse_reminder("напомни в семь утра встать", now)
    want(got and got["at"] and got["at"] > _epoch(now),
         "в семь утра должно быть в будущем: %r" % (got,))
    if got and got["at"]:
        dt = _d.datetime.fromtimestamp(got["at"])
        want(dt.hour == 7 and dt.minute == 0,
             "в семь утра -> %s" % dt)
        # 9:00 - семь утра сегодня уже прошло, ждать надо завтра.
        want(dt.date() == _dt(2026, 10, 3).date(),
             "прошедшие семь утра -> %s" % dt)

    # «в два вечера».
    got = parse_reminder("напомни в два вечера закрыть окно", now)
    if got and got["at"]:
        want(_d.datetime.fromtimestamp(got["at"]).hour == 14,
             "два вечера -> %s" % _d.datetime.fromtimestamp(got["at"]))

    # Вчерашнее время переносится на завтра.
    got = parse_reminder("напомни в семь утра встать", _dt(2026, 10, 2, 10, 0))
    if got and got["at"]:
        want(_d.datetime.fromtimestamp(got["at"]).date() ==
             _dt(2026, 10, 3).date(),
             "прошедшие семь утра -> %s" % _d.datetime.fromtimestamp(got["at"]))

    # Не напоминание.
    for q in ("какая сейчас погода", "напоминание забыть", "буди меня в 7 утра"):
        want(parse_reminder(q, now) is None,
             "лишнее сработало на: %s" % q)

    # Список и отмена.
    want(is_list("что напомнить"), "список не распознан")
    want(is_forget("забудь"), "отмена не распознана")

    # Человеческое «когда».
    want("минут" in when_text(_epoch(now) + 300, now),
         "когда через 5 минут: %r" % when_text(_epoch(now) + 300, now))
    want("час" in when_text(_epoch(now) + 7200, now),
         "когда через 2 часа: %r" % when_text(_epoch(now) + 7200, now))

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    jane_remind: напоминание запоминается, а не выдумывается")
    print("ИТОГ: провалено %d" % len(fails))
    return 1 if fails else 0


def _dt(y, mo, d, h=0, mi=0):
    import datetime as _d
    return _d.datetime(y, mo, d, h, mi)


def _dtm():
    import datetime as _d
    return _d.datetime


def _epoch(dt):
    return dt.timestamp()


if __name__ == "__main__":
    import sys
    sys.exit(selfcheck())