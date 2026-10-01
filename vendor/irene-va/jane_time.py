"""Разбор фраз будильника на время суток.

Отдельный модуль по той же причине, что и jane_audio: runva_webapi при импорте
тянет vosk и fastapi и в обычной среде падает на конфликте версий click, то
есть проверить логику можно было только в контейнере руками. Здесь нужен
только datetime.

Часовые слова нужны свои, а не num_to_text: у того «утро» - это время, а не
количество, и «в 3 ночи» не должно превращаться в «на 180 минут».

Проверки внизу файла: python3 vendor/irene-va/jane_time.py
"""

import datetime
import re

# Час по слову. «полдень» и «полночь» вынесены: это не час, а конкретное
# время, и «в полдень» в тринадцать не превращается.
_HOUR_WORDS = {
    "утра": 7, "утром": 7, "утром": 7, "утро": 7,
    "ночи": 23, "ночью": 23, "ночь": 23,
    "вечера": 19, "вечером": 19, "вечер": 19,
    "дня": 13, "днём": 13, "днем": 13, "день": 13,
}

# Слова-числа для часа: колонка слышит «в семь утра», а не «в 7 утра»
_WORD_NUM = {
    "ноль": 0, "половина": 0,
    "один": 1, "одну": 1, "одна": 1, "первый": 1,
    "два": 2, "две": 2, "второй": 2,
    "три": 3, "третий": 3,
    "четыре": 4, "четвертый": 4,
    "пять": 5, "пятый": 5,
    "шесть": 6, "шестой": 6,
    "семь": 7, "седьмой": 7,
    "восемь": 8, "восьмой": 8,
    "девять": 9, "девятый": 9,
    "десять": 10, "десятый": 10,
    "одиннадцать": 11, "одиннадцатый": 11,
    "двенадцать": 12, "двенадцатый": 12,
    "час": 1, "два часа": 2, "три часа": 3, "четыре часа": 4,
    "пять часов": 5, "шесть часов": 6, "семь часов": 7,
    "восемь часов": 8, "девять часов": 9, "десять часов": 10,
}

_DAY_WORDS = ("завтра", "послезавтра")
_REPEAT = (
    (re.compile(r"\bкаждый\s+день\b|\bежедневно\b"), "daily"),
    (re.compile(r"\bпо\s+будням\b|\bв\s+будни\b|\bрабочие\s+дни\b"), "weekdays"),
    (re.compile(r"\bпо\s+выходным\b|\bв\s+выходные\b|\bвыходные\b"), "weekend"),
    (re.compile(r"\bкаждую\s+неделю\b|\bеженедельно\b"), "weekly"),
)
# «понедельник» ... «воскресенье»
_WEEKDAY = {
    "понедельник": 0, "вторник": 1, "среда": 2, "среду": 2,
    "четверг": 3, "четверга": 3, "пятница": 4, "пятницу": 4,
    "суббота": 5, "субботу": 5, "воскресенье": 6, "воскресенья": 6,
    "вс": 6, "вс": 6,
}
_DOW = ("понедельник", "вторник", "среда", "четверг", "пятница",
        "суббота", "воскресенье")

# Из чего собирается будильник. «в» и «на» равнозначны: люди говорят оба.
_HEAD = re.compile(
    r"(?:поставь|поставить|заведи|завести|поставьте|включи|включить|"
    r"сделай|сделать|напомни|напомнить|буди|разбуди)\s+"
    r"(?:(?:мне|меня|себе)\s*)?"
    r"(?:колонку\s*)?"
    r"(?:(?:будильник|будильник\w*|звонок|звонка|ал)\s*)?"
    r"(?:на|в|к|во)?\s*(.*)$"
)
_NUM_RE = re.compile(r"^(\d{1,2})\s*(?::|ч|час)\s*(\d{2})?\s*(.*)$")
_NUM_ONLY = re.compile(r"^(\d{1,2})\s+(утра|утром|ночи|ночью|вечера|вечером|"
                       r"дня|днём|днем|час|часа|часов)?(.*)$")


def _shift_for_word(hour, word):
    """«9 вечера» - это 21:00, а не 19:00.

    Час без слова стоит как есть, а со словем времени суток приводится к
    вечеру или ночи. Слово не нужно трогать, если час и так вечерний:
    «7 вечера» человек всё равно имеет в виду 19.
    """
    if not word:
        return hour
    if word in ("вечера", "вечером", "вечер"):
        return hour + 12 if 1 <= hour <= 11 else hour
    if word in ("ночи", "ночью", "ночь"):
        return hour + 12 if 1 <= hour <= 11 else hour
    if word in ("дня", "днём", "днем", "день"):
        return hour + 12 if 1 <= hour <= 11 else hour
    if word in ("утра", "утром", "утро"):
        # утром «1» - это час ночи, но 12 утра остаётся 12
        return 0 if hour == 12 else hour
    return hour


def _find_hour(text):
    """Час и минуты из куска фразы, либо (None, None)."""
    text = text.strip()
    m = _NUM_RE.match(text)
    if m:
        return int(m.group(1)), int(m.group(2) or 0)
    m = _NUM_ONLY.match(text)
    if m:
        h = int(m.group(1))
        word = (m.group(2) or "").strip()
        if word in _HOUR_WORDS:
            return _shift_for_word(h, word), 0
        return h, 0
    # «в семь утра», «в полдень»
    for word, val in sorted(_WORD_NUM.items(), key=lambda kv: -len(kv[0])):
        if text.startswith(word):
            rest = text[len(word):].strip()
            for marker in ("утра", "утром", "вечера", "вечером",
                           "ночи", "ночью", "дня", "днём", "днем"):
                if rest.startswith(marker):
                    return _shift_for_word(val, marker), 0
            if rest == "" or rest.startswith("часа") or rest.startswith("часов"):
                return val, 0
    if text.startswith("полдень"):
        return 12, 0
    if text.startswith("полночь") or text.startswith("полночи"):
        return 0, 0
    return None, None


def parse_alarm_phrase(text, now=None):
    """Возвращает (epoch, подпись, повтор) или None.

    Время, которое уже прошло, переносится на завтра: сказать «в 7 утра» в
    10 утра должно значить будильник на следующее утро, а не «в прошлом».
    """
    if not text:
        return None
    low = " ".join(str(text).lower().replace("ё", "е").split())
    # Двоеточие убирать нельзя: им записано время «7:05», и без него фраза
    # превращалась в «7 05», то есть в 7:00. Об этом уже всплыло.
    low = re.sub(r"[,.!?;]+", " ", low)
    m = _HEAD.match(low)
    if not m:
        return None
    rest = m.group(1).strip()

    hour = minute = None
    for w in _DAY_WORDS:
        if rest.startswith(w):
            rest = rest[len(w):].strip()
            break
    for wd in _WEEKDAY:
        if rest.startswith(wd):
            rest = rest[len(wd):].strip()
            break
    # после «завтра» остаётся «в 8 утра»: предлог уходит вместе с названием
    # дня, и его надо снять ещё раз, иначе разбор ждёт цифру в начале
    rest = re.sub(r"^(?:на|в|к|во)\s+", "", rest).strip()
    hour, minute = _find_hour(rest)
    if hour is None:
        return None
    if hour > 23 or minute > 59:
        return None

    repeat = None
    for rx, name in _REPEAT:
        if rx.search(low):
            repeat = name
            break

    now = now or datetime.datetime.now()
    base = datetime.datetime(now.year, now.month, now.day, hour, minute)
    delta = 0
    for w in _DAY_WORDS:
        if w in low:
            delta = _DAY_WORDS.index(w) + 1
    target = base + datetime.timedelta(days=delta)

    # Время, которое уже прошло, переносим на следующий подходящий день -
    # и для повторяющегося тоже. Раньше перенос стоял под условием
    # «повтора нет», и «по будням на 6 утра» в десять утра получал время в
    # прошлом: будильник показывался с отрицательным остатком и срабатывал
    # сразу, вместо того чтобы ждать следующего понедельника.
    if delta == 0 and target <= now:
        target += datetime.timedelta(days=1)
    if repeat == "weekdays":
        while target.weekday() >= 5:
            target += datetime.timedelta(days=1)
    elif repeat == "weekend":
        while target.weekday() < 5:
            target += datetime.timedelta(days=1)
    return int(target.timestamp()), "%02d:%02d" % (hour, minute), repeat


def describe_repeat(repeat):
    return {"daily": "каждый день", "weekdays": "по будням",
            "weekend": "по выходным", "weekly": "еженедельно"}.get(repeat, "")


# ---------------------------------------------------------------------------
# Проверки
# ---------------------------------------------------------------------------
def selfcheck():
    fails = []
    import datetime as _dt

    def at(y, mo, d, h, mi=0):
        return _dt.datetime(y, mo, d, h, mi)

    cases = [
        # фраза, сейчас, ожидаемое смещение в днях, ожидаемое время
        ("поставь будильник на 7 утра", at(2026, 10, 1, 6, 0), 0, "07:00"),
        ("поставь будильник на 7 утра", at(2026, 10, 1, 8, 0), 1, "07:00"),
        ("буди меня в 7:30", at(2026, 10, 1, 6, 0), 0, "07:30"),
        ("поставь будильник на 9 вечера", at(2026, 10, 1, 12, 0), 0, "21:00"),
        ("буди меня завтра в 8 утра", at(2026, 10, 1, 12, 0), 1, "08:00"),
        ("поставь будильник в полдень", at(2026, 10, 1, 9, 0), 0, "12:00"),
        ("поставь будильник на 23 ночи", at(2026, 10, 1, 12, 0), 0, "23:00"),
        ("включи будильник на 7:05", at(2026, 10, 1, 6, 0), 0, "07:05"),
    ]
    for phrase, now, days, label in cases:
        got = parse_alarm_phrase(phrase, now)
        if not got:
            fails.append("не разобрали: %s" % phrase)
            continue
        epoch, lab, rep = got
        if lab != label:
            fails.append("%s -> время %s, ждали %s" % (phrase, lab, label))
            continue
        # сверяем дату и время отдельно: просто «сейчас плюс дни» неверно,
        # потому что в цели меняется и час, и из-за этого проверка ругалась
        # сама на себя, выдавая 0 дней вместо 0
        got_dt = _dt.datetime.fromtimestamp(epoch)
        want_day = (now + datetime.timedelta(days=days)).date()
        if got_dt.date() != want_day:
            fails.append("%s -> дата %s, ждали %s"
                         % (phrase, got_dt.date(), want_day))
        if got_dt.strftime("%H:%M") != label:
            fails.append("%s -> в момент срабатывания %s, ждали %s"
                         % (phrase, got_dt.strftime("%H:%M"), label))

    for phrase in ("какое сегодня время", "напомни купить хлеб",
                   "поставь будильник", "температура дома"):
        if parse_alarm_phrase(phrase, at(2026, 10, 1, 12, 0)):
            fails.append("лишнее сработало на: %s" % phrase)

    got = parse_alarm_phrase("поставь будильник на 7 утра каждый день",
                             at(2026, 10, 1, 6, 0))
    if not got or got[2] != "daily":
        fails.append("повтор «каждый день» не распознан: %r" % (got,))
    got = parse_alarm_phrase("поставь будильник на 8 утра по будням",
                             at(2026, 10, 1, 6, 0))
    if not got or got[2] != "weekdays":
        fails.append("повтор «по будням» не распознан: %r" % (got,))

    # 1 октября 2026 - четверг. В десять утра «по будням на 6 утра» должно
    # ждать пятницы, а не показывать время в прошлом: сдвиг назад давал
    # отрицательный остаток и мгновенный звонок.
    got = parse_alarm_phrase("поставь будильник на 6 утра по будням",
                             at(2026, 10, 1, 10, 0))
    if got:
        epoch = got[0]
        when = _dt.datetime.fromtimestamp(epoch)
        if when <= at(2026, 10, 1, 10, 0):
            fails.append("повторяющийся будильник остался в прошлом: %s" % when)
        elif when.weekday() >= 5:
            fails.append("повтор «по будням» попал на выходной: %s" % when)
        elif when.hour != 6:
            fails.append("время сдвинулось: %s" % when)

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    jane_time: будильник на время суток разбирается верно")
    print("ИТОГ: провалено %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    sys.exit(selfcheck())