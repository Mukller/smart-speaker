"""Замер: две модели на одних и тех же фразах.

Разговор с колонкой - это в первую очередь русский язык и отказ отвечать там,
где отказываться нечего. Обе вещи измеряются прямо здесь, на живом сервере,
а не оцениваются на глаз.

Меряем три вещи:
  1. доля отказов - колонка не должна отказывать на вопросы без причины;
  2. мусор - чужая разработка, чужой язык, обрыв на полуслове;
  3. время ответа - для голоса это тоже качество.

Запуск: python tests/bench_llm.py
"""

import json
import os
import sys
import time
import urllib.request

# Модуль фильтра ищем и рядом с тестом, и в контейнере - запуск бывает и
# из /tmp, и из репозитория.
for _cand in (os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "vendor", "irene-va"),
              "/app/vendor/irene-va"):
    if os.path.exists(os.path.join(_cand, "jane_guard.py")):
        sys.path.insert(0, _cand)
        break
else:
    raise SystemExit("не найден jane_guard: запускать из репозитория")

import jane_guard as G

OLLAMA = "http://172.17.0.1:11434/api/generate"
MODELS = ("qwen2.5:0.5b-instruct", "qwen2.5:1.5b-instruct")

PROBES = (
    "что такое эхо",
    "расскажи анекдот",
    "напиши рецепт борща",
    "дай совет",
    "как дела",
    "напиши стихотворение",
    "что такое фотосинтез",
    "почему небо голубое",
)

# Отказы: колонка обязана уметь это, отказ здесь - неверный ответ.
_REFUSAL = ("не могу", "не имею", "не участвую", "не способен",
            "обратитесь к оператору", "не в состоянии")


def ask(model, prompt, timeout=180):
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        # keep_alive обязателен: без него модель выгружается между запросами,
        # и в замере оказывается не ответ модели, а её загрузка с диска.
        # Первую строку сверху смотрим как прогрев и в счёт не берём.
        "keep_alive": -1,
        "options": {"temperature": 0.2, "num_predict": 700},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode("utf-8"))
    return out.get("response", ""), time.time() - t0


def score(txt):
    low = txt.lower()
    if any(b in low for b in _REFUSAL):
        return "отказ"
    why = G.reason_to_reject(txt)
    # Обрыв, вызванный лимитом токенов, - это вина замера, а не модели.
    # Отличаем: режем хвост до последней полной фразы и смотрим, осталось ли
    # что оценивать. Иначе длинный хороший ответ всегда помечается мусором.
    trimmed = trim_partial(txt)
    if why == "обрыв на полуслове" and len(trimmed) > 40:
        why = G.reason_to_reject(trimmed)
    return why or "ок"


def trim_partial(txt):
    """Отбросить недописанный хвост, чтобы не судить модель за наш лимит."""
    t = (txt or "").strip()
    if G._TAIL_OK.search(t):
        return t
    cut = max(t.rfind(". "), t.rfind("! "), t.rfind("? "),
              t.rfind(".\n"), t.rfind("!\n"), t.rfind("?\n"))
    return t[:cut + 1].strip() if cut > 0 else ""


def main():
    results = {}
    for model in MODELS:
        rows = []
        try:
            ask(model, "прогрев")     # модель грузится до замера, не в нём
        except Exception as e:
            print("! прогрев %s: %s" % (model, e))
        for q in PROBES:
            try:
                txt, dt = ask(model, q)
            except Exception as e:
                # Причину показываем: молчаливый "ОШИБКА" в таблице означал бы
                # ровно то, от чего мы весь день лечим колонку.
                print("  ! %s: %s" % (type(e).__name__, e))
                rows.append((q, "ОШИБКА: " + str(e)[:40], 0.0, ""))
                continue
            rows.append((q, score(txt), dt, txt))
        results[model] = rows
        print("=== %s" % model)
        for q, verdict, dt, txt in rows:
            print("  [%-22s] %5.1f с  %s" % (verdict[:22], dt,
                                            txt.replace("\n", " ")[:56]))
        print()

    # Сводка.
    print("--- сводка ---")
    for model, rows in results.items():
        bad = [r for r in rows if r[1] != "ок"]
        avg = sum(r[2] for r in rows if isinstance(r[2], float)) / max(len(rows), 1)
        print("%-26s мусор/отказов: %d из %d, среднее %.1f с"
              % (model, len(bad), len(rows), avg))
    return 0


if __name__ == "__main__":
    sys.exit(main())