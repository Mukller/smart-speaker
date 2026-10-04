"""Живая проверка честности ответов колонки.

Фильтр `jane_guard` проверяется на строковых примерах локально, а здесь он
проверяется на настоящей колонке, потому что модель каждый раз придумывает
новую форму отказа. Список ниже - не выдумка: это ответы, которые колонка
давала в разные дни.

Проверка жёсткая по одной причине: колонка, которая отказывается отвечать на
то, что умеет, выглядит сломанной хуже, чем молчащая.

Прогон: python tests/test_guard_live.py [url]
"""

import json
import sys
import urllib.parse
import urllib.request

DEFAULT = "https://antonpetnitsky.com/kolonka/api"

# (фраза, ожидаемый источник). None - источник не важен, важно лишь, чтобы
# ответ не был отказом и не содержал чужого языка.
CASES = (
    ("какая сегодня дата", "when"),
    ("кто ты", "about"),
    ("что ты умеешь", "about"),
    ("какая сейчас погода", "plugin"),
    ("который час", "when"),
    ("напомни купить хлеб", "remind"),
)

# Фразы, где модель исторически отказывала или путала язык.
HOSTILE = (
    "напиши рецепт борща",
    "расскажи анекдот",
    "что ты умеешь",
    "какая сегодня дата",
)

_BAD = ("не могу", "не имею", "не участвую", "обратитесь к оператору",
        "не в состоянии", "недоступно для меня")


def ask(api, q, timeout=120):
    url = api + "/sendTxtCmd?cmd=" + urllib.parse.quote(q)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def main():
    api = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT).rstrip("/")
    fails = []

    for q, want_src in CASES:
        d = ask(api, q)
        txt = (d.get("restxt") or "").strip()
        src = d.get("source")
        print("[%-7s] %-26s %s" % (src, q, txt.replace("\n", " ")[:56]))
        if src != want_src:
            fails.append("источник для %r: ожидали %s, получили %s"
                         % (q, want_src, src))
        if not txt:
            fails.append("пустой ответ на %r" % q)
            continue
        for b in _BAD:
            if b in txt.lower():
                fails.append("отказ на %r: %r" % (q, txt[:60]))
                break
        if any("\u4e00" <= ch <= "\u9fff" for ch in txt):
            fails.append("иероглифы в ответе на %r" % q)

    # Враждебные фразы: ответ вправе быть любым по смыслу, но не отказом.
    for q in HOSTILE:
        d = ask(api, q)
        txt = (d.get("restxt") or "").strip()
        low = txt.lower()
        print("[%s] %-26s %s" % (d.get("source"), q,
                                 txt.replace("\n", " ")[:56]))
        for b in _BAD:
            if b in low:
                fails.append("отказ на %r: %r" % (q, txt[:60]))
                break

    for f in fails:
        print("FAIL  " + f)
    if not fails:
        print("ok    колонка отвечает на то, что умеет, и не отказывается")
    print("ИТОГ: провалено %d" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())