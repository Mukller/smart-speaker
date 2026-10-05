"""Разведка: что колонка умеет из обычного.

Проверка функций не выдумывает сценарии, а спрашивает то, что человек говорит
колонке в первую очередь. Каждая строка - проверка не только ответа, но и
источника: если «какой таймер» ушёл в языковую модель, значит таймеры не
поддержаны, даже если модель что-то ответила.

Прогон: python tests/audit_everyday.py [url]
"""

import json
import sys
import time
import urllib.parse
import urllib.request

DEFAULT = "https://antonpetnitsky.com/kolonka/api"

# (фраза, источник, ключевое слово в ответе, ожидаемое действие)
# Таймеры и музыка идут через маршрут плеера: он возвращает действие для
# страницы, а не ответ колонки. Первая версия проверки ждала отдельный
# источник «timer», которого в проекте нет, и объявляла исправную колонку
# неисправной девять раз подряд. Проверять надо действие.
CASES = (
    # Таймеры: без них колонка разбивает посуду.
    ("поставь таймер на 5 минут", "player", "таймер", None),
    ("поставь таймер на чай", "plugin", None, None),
    ("какой таймер", "player", None, "timers_status"),
    ("сколько осталось", "player", None, "timers_status"),
    ("отмени таймер", "player", "отмен", "cancel_timers"),
    ("таймеры", "player", None, "timers_status"),
    # Музыка.
    ("включи музыку", "player", None, "play"),
    ("что играет", "player", None, "now_playing"),
    # Ключевой случай: «выключи музыку» раньше включала музыку, потому что
    # в списке «включить» стояло голое существительное «музыку».
    ("выключи музыку", "player", None, "pause"),
    ("переключи", "player", None, "next"),
    ("громче", "control", None, None),
    ("стоп", "control", None, None),
    # Точное время и дата.
    ("который час", "when", None, None),
    ("какая сегодня дата", "when", None, None),
    # Погода.
    ("какая сейчас погода", "plugin", None, None),
    ("погода в Гомеле", "plugin", None, None),
    # Дом.
    ("включи свет", "home", None, None),
    ("выключи свет", "home", None, None),
    # Будильники и напоминания.
    ("буди меня в 7 утра", "alarm", None, None),
    ("напомни купить хлеб", "remind", None, None),
    ("что ты умеешь", "about", None, None),
    ("кто ты", "about", None, None),
    # Фразы, которые обязаны уйти в языковую модель. Добавлены после того,
    # как аудит с двадцатью двумя детерминированными фразами показал ноль
    # ошибок при полностью сломанной ветке модели: 500 на /sendTxtCmd.
    # Проверка функций обязана накрывать все ветки, а не только те, что
    # отвечают быстро.
    ("почему небо голубое", "llm", None, None),
    ("что такое эхо", "llm", None, None),
)


def ask(api, q, timeout=180):
    url = api + "/sendTxtCmd?cmd=" + urllib.parse.quote(q)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def main():
    api = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT).rstrip("/")
    rows, bad = [], 0

    for q, want_src, keyword, want_action in CASES:
        t0 = time.time()
        try:
            d = ask(api, q)
        except Exception as e:
            print("%-24s ОШИБКА %s" % (q, e))
            bad += 1
            continue
        dt = time.time() - t0
        txt = (d.get("restxt") or "").strip()
        src = d.get("source")
        action = d.get("action")
        ok = (want_src is None or src == want_src)
        if keyword:
            ok = ok and (keyword in txt.lower())
        if want_action:
            ok = ok and (action == want_action)
        if not ok:
            bad += 1
        rows.append((q, src, dt, txt, ok, action))

    print("%-24s %-9s %5s %-10s %-32s %s"
          % ("фраза", "исток", "сек", "действие", "ответ", "итог"))
    for q, src, dt, txt, ok, action in rows:
        print("%-24s %-9s %5.1f %-10s %-32s %s"
              % (q, src, dt, action or "-", txt.replace("\n", " ")[:32],
                 "ок" if ok else "НЕ ТАК"))

    print("--- расхождений: %d из %d" % (bad, len(CASES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())