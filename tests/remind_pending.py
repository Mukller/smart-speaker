"""Проверка того, что незаконченный вопрос не съедает новую команду.

Найдено разведкой: после «напомни купить хлеб» колонка спрашивает «Когда
напомнить?», и следующая фраза «поставь таймер на 5 минут» перехватывалась
незавершённым вопросом. В итоге создавалось напоминание «купить хлеб
поставь таймер на 5 минут» через четыре часа, а человек просил таймер.

Правила проверяются тут, без колонки и без сети: обе функции чистые.

Прогон: python tests/remind_pending.py
"""

import os
import re
import sys

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
# Режем ровно нужное: списки отдельно, функции отдельно. Общий срез до
# _answer_text затягивал код, которому нужен объект приложения, и проверка
# падала не по своей причине.
ns = {"re": re}
end_of_other = '    return any(w in p for w in _RE_OTHER_CMD)'
j = src.index(end_of_other) + len(end_of_other)
for a, b in (("_RE_TIME_WORDS", "def _is_time_answer"),
             ("def _is_time_answer", end_of_other)):
    i = src.index(a)
    k = j if b == end_of_other else src.index(b)
    exec(compile(src[i:k], "runva", "exec"), ns)
is_time = ns["_is_time_answer"]
is_other = ns["_is_other_command"]

fails = []


def want(cond, msg):
    if not cond:
        fails.append(msg)


# Уточнения времени обязаны проходить.
for cmd in ("через час", "через 10 минут", "в семь утра", "завтра утром",
            "вечером", "ночью", "через полчаса"):
    want(is_time(cmd) and not is_other(cmd),
         "уточнение не прошло: %s (время=%s, другая=%s)"
         % (cmd, is_time(cmd), is_other(cmd)))

# Команды, которые звучат как время, но командами и остаются.
for cmd in ("поставь таймер на 5 минут", "буди меня в 7 утра", "таймер",
            "включи музыку", "выключи свет", "громче", "стоп", "повтори"):
    want(is_other(cmd), "не опознана как своя команда: %s" % cmd)
    want(not (is_time(cmd) and not is_other(cmd)),
         "команда прошла как уточнение: %s" % cmd)

# Пустое и бессмысленное не считается уточнением.
for cmd in ("", "   ", None, "а", "ну", "хмм"):
    want(not is_time(cmd), "пустое принято за уточнение: %r" % cmd)

# Контроль в обе стороны: обе функции обязаны что-то возвращать, иначе
# проверка ни о чём не говорит.
want(any(is_time(c) for c in ("через час", "в семь")), "время не ловится")
want(not any(is_time(c) for c in ("включи свет", "стоп")),
     "постороннее ловится как время")

for f in fails:
    print("FAIL  " + f)
if not fails:
    print("ok    незаконченный вопрос не съедает новую команду")
print("ИТОГ: провалено %d" % len(fails))
sys.exit(1 if fails else 0)