"""Проверка обрезки недоговорённого ответа модели.

Модель упирается в лимит токенов, и ответ обрывается на полуслове. Раньше
такой обрыв считался браком модели, и колонка отвечала «Не поняла» вместо
нормального короткого ответа.

Первая версия обрезки проверяла позицию границы в символах, и на коротком
ответе вида «Первый. Второй оборван» условие не срабатывало - обрезанный текст
проходил целиком. Это проверка, которая молча пропускает ровно то, что должна
ловить, поэтому она здесь и живёт отдельно.

Прогон: python tests/trim_to_sentence.py
"""

import os
import re
import sys

# Функцию достаём из боевого файла, а не копируем: копия разошлась бы с
# настоящей, и проверка проверяла бы не то.
SRC = None
for cand in ("/app/vendor/irene-va/runva_webapi.py",
             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "vendor", "irene-va", "runva_webapi.py")):
    if os.path.exists(cand):
        SRC = cand
        break
if SRC is None:
    raise SystemExit("не найден runva_webapi.py")

src = open(SRC, encoding="utf-8").read()
i = src.index("def _trim_to_sentence")
j = src.index("def call_ollama(", i)
ns = {"re": re}
exec(compile(src[i:j], "runva", "exec"), ns)
trim = ns["_trim_to_sentence"]

fails = []


def want(cond, msg):
    if not cond:
        fails.append(msg)


def ends_clean(t):
    return bool(re.search(r"""[.!?…»"')\]]\s*$""", t))


cases = (
    # (текст, ожидание)
    # Обрезается, потому что граница предложения есть.
    ("Первое предложение. Второе предложение оборвано на полусл", "обрезать"),
    ("Сломано. Ещё. Вот так", "обрезать"),
    # Нет границы - обрезать некуда, и ответ произносится как есть. Отрывать
    # последнее слово было бы догадкой, а короткий понятный обрыв лучше
    # отказа «Не поняла».
    ("Эхо - это повторяющийся звук, который возвращается и слышен", "как есть"),
    ("Коротко", "как есть"),
    # Целые ответы не трогаются.
    ("Погода сегодня ясная, плюс семнадцать градусов.", "как есть"),
    ("Конечно, сегодня вторник, дождя не будет.", "как есть"),
)

for got, mode in cases:
    out = trim(got)
    if mode == "обрезать":
        want(ends_clean(out),
             "после обрезки остался обрыв: %r -> %r" % (got, out))
        want(len(out) < len(got), "обрезать было нечего: %r" % got)
    else:
        want(out == got, "целый или необрезаемый ответ изменён: %r -> %r"
             % (got, out))

# Пустой и пробельный ввод не должны роняться.
for bad in (None, "", "   ", "\n"):
    try:
        trim(bad)
    except Exception as e:
        fails.append("упало на %r: %s" % (bad, e))

# Контроль в обе стороны: обрезка обязана что-то делать, иначе проверка
# ни о чём не говорит.
changed = sum(1 for got, _ in cases if trim(got) != got)
want(changed >= 1, "обрезка ни разу не сработала")

for f in fails:
    print("FAIL  " + f)
if not fails:
    print("ok    обрезка убирает недоговорённый хвост и не трогает целые ответы")
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)