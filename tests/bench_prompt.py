"""Замер промпта колонки: с системным промптом и без него.

Проверяет ровно одно утверждение: колонка без указания роли пишет эссе и
отвечает медленно. Измеряется это на живом сервере, потому что на глаз
разницу в десяток секунд не увидеть.

Прогон: python tests/bench_prompt.py with_system  qwen2.5:0.5b-instruct
        python tests/bench_prompt.py without_system qwen2.5:0.5b-instruct
"""

import json
import os
import sys
import time
import urllib.request

for _cand in ("/app/vendor/irene-va",
              os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "vendor", "irene-va")):
    if os.path.exists(os.path.join(_cand, "jane_guard.py")):
        sys.path.insert(0, _cand)
        break
else:
    raise SystemExit("не найден jane_guard: запускать из репозитория")

import jane_guard as G

URL = "http://172.17.0.1:11434/api/generate"

# Тот же текст, что в runva_webapi. Дублируется намеренно: если он разойдётся
# с боевым, замер перестанет мерить то, что надо, и это надо будет заметить.
SYSTEM = (
    "Ты - голосовая колонка Дженет. Говоришь по-русски, живым голосом.\n"
    "Отвечай одним-двумя короткими предложениями. Без вступлений, без "
    "списков, без повторов вопроса, без «конечно» и «чем могу помочь».\n"
    "Ты не человек и не ассистент веб-страницы. Ты - колонка, которая "
    "слышит, считает время, помнит просьбы и управляет домом.\n"
    "Не называй себя моделью, нейросетью или разработчиком. Не упоминай "
    "компании и модели.\n"
    "Если не знаешь ответа - скажи это одной фразой и предложи, что умеешь."
)

PROBES = (
    "что такое эхо",
    "расскажи анекдот",
    "напиши рецепт борща",
    "дай совет",
    "как дела",
    "напиши стихотворение",
    "что такое фотосинтез",
    "почему небо голубое",
    "кто ты",
    "что ты умеешь",
)

MODE = sys.argv[1] if len(sys.argv) > 1 else "with_system"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "qwen2.5:0.5b-instruct"
TOKENS = int(os.environ.get("BENCH_TOKENS", "120") or 120)


def ask(prompt, tokens):
    body = json.dumps({
        "model": MODEL, "stream": False, "keep_alive": -1,
        "prompt": (SYSTEM + "\n\n" + prompt) if MODE == "with_system" else prompt,
        "options": {"temperature": 0.3, "num_predict": tokens},
    }).encode("utf-8")
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.loads(r.read().decode("utf-8"))
    return out.get("response", ""), time.time() - t0


def main():
    # Прогрев обязателен: без keep_alive модель выгружается между запросами,
    # и в замере оказывается не ответ, а её загрузка с диска.
    try:
        ask("прогрев", 16)
    except Exception as e:
        print("прогрев не удался: %s" % e)
        return 1

    times, bad = [], 0
    print("=== режим %s, модель %s, лимит %d токенов" % (MODE, MODEL, TOKENS))
    for q in PROBES:
        txt, dt = ask(q, TOKENS)
        times.append(dt)
        why = G.reason_to_reject(txt) or "ок"
        if why != "ок":
            bad += 1
        print("  [%-22s] %5.1f с  %s"
              % (why[:22], dt, txt.replace("\n", " ")[:54]))

    ordered = sorted(times)
    print("--- отказов/мусора: %d из %d" % (bad, len(PROBES)))
    print("--- медиана %.1f с, среднее %.1f с, максимум %.1f с"
          % (ordered[len(ordered) // 2], sum(times) / len(times), max(times)))
    return 0


if __name__ == "__main__":
    sys.exit(main())