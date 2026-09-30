#!/usr/bin/env python3
"""Прогон всех браузерных проверок с прогревом и итогом.

Раньше это был PowerShell-скрипт, и он дважды сломался: PS 5.1 читает .ps1 без
BOM как ANSI, и кириллица в сообщениях превращала файл в нечитаемый. Python
здесь только потому и живёт, что кодировка всегда одна.

Прогрев обязателен: после перезапуска контейнера первая модель (vosk TTS/STT)
грузится лениво, и проверки получают таймаут на живом приложении.

Запуск:
  python3 tests/run_all.py                 # все наборы
  python3 tests/run_all.py alarm search    # только указанные
  python3 tests/run_all.py --no-warmup
"""

import argparse
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BASE = os.environ.get("JANE_URL", "https://antonpetnitsky.com")
PREFIX = "/kolonka/api"

SUITES = [
    ("main UI", "e2e_win2.py"),
    ("voice TTS", "e2e_voice.py"),
    ("STT", "e2e_stt.py"),
    ("plugins", "e2e_plugins.py"),
    ("alarm", "e2e_alarm.py"),
    ("always-on mic", "e2e_hot.py"),
    ("music search", "e2e_search.py"),
    ("player", "e2e_player.py"),
]


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "jane-warmup"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def warmup(attempts=40, pause=5):
    for i in range(attempts):
        try:
            # tts, а не ttsHealth: модель должна реально загрузиться, иначе
            # первый настоящий запрос уйдёт в пустоту
            code = get(BASE + PREFIX + "/tts?text=test", timeout=120)
            get(BASE + PREFIX + "/sttHealth")
            if code == 200:
                print("прогрев готов сразу")
                return True
        except Exception:
            pass
        time.sleep(pause)
    print("прогрев не удался за %d попыток" % attempts)
    return False


def run(name, script):
    path = os.path.join(HERE, script)
    if not os.path.exists(path):
        print("  %-14s ФАЙЛА НЕТ" % name)
        return 1
    t0 = time.time()
    p = subprocess.run([sys.executable, path], cwd=HERE,
                       capture_output=True, text=True, errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    m = re.findall(r"fails=(\d+)", out)
    fails = int(m[-1]) if m else -1
    dt = time.time() - t0
    if fails < 0:
        # набор упал раньше, чем напечатал итог - показываем хвост вывода
        tail = " | ".join(l.strip() for l in out.strip().splitlines()[-3:])
        print("  %-14s НЕ ОТЧЁТ (%.0f с) %s" % (name, dt, tail[:150]))
        return 1
    print("  %-14s fails=%-3d %.0f с" % (name, fails, dt))
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*", help="подстроки имён наборов")
    ap.add_argument("--no-warmup", action="store_true")
    args = ap.parse_args()

    if not args.no_warmup and not warmup():
        print("без прогрева результат будет недостоверным, но продолжаю")

    chosen = SUITES
    if args.only:
        chosen = [(n, s) for n, s in SUITES
                  if any(k in n for k in args.only)]

    print("")
    total = 0
    for name, script in chosen:
        total += run(name, script)

    print("")
    print("=== ИТОГ ===")
    for name, _ in chosen:
        print("  %s" % name)
    print("всего провалено: %d" % total)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
