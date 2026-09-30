#!/usr/bin/env python3
"""Проверка того, что интерфейс и тесты говоривают с сервером по одним путям.

Случай из практики: интерфейс перевели на единый префикс /kolonka/api/,
а три теста продолжали считать запросы по старым путям /kolonka/tts,
/kolonka/stt и /kolonka/timerwav. Тесты падали, хотя приложение было живо:
curl отдавал 200 за 165 мс. Три набора показывали провал, и это выглядело как
регрессия. Настоящая причина - тесты смотрели не туда.

Именно поэтому проверка живёт в репозитории и запускается на каждый коммит:
молчаливое расхождение путей обязано валить сборку.

Что проверяем:
  1. index.html не использует точные пути в обход префикса.
  2. Ни один тест не упоминает /kolonka/<x>, где x - не api/.
  3. Все пути, которые дёргает интерфейс, реально отвечают (нужен --live).

Запуск:
  python3 tests/check_routes.py            # только статика, быстро
  python3 tests/check_routes.py --live     # плюс проверка живым запросом
"""

import argparse
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
INDEX = os.path.join(REPO, "vendor", "irene-va", "webapi_client", "index.html")
WEBAPI = os.path.join(REPO, "vendor", "irene-va", "runva_webapi.py")
BASE = os.environ.get("JANE_URL", "https://antonpetnitsky.com")
PREFIX = "/kolonka/"

# Эти пути не проходят через префикс /kolonka/api/ - они либо сама страница,
# либо статика, которая отдаётся nginx как есть.
NO_API = {"", "api", "manifest.json", "icon.svg", "favicon.ico", "kolonka"}


def fail(msg):
    print("FAIL  %s" % msg)
    return 1


def ok(msg):
    print("ok    %s" % msg)
    return 0


def ui_paths():
    """Пути, которые интерфейс дёргает через константу API."""
    src = open(INDEX, encoding="utf-8").read()
    m = re.search(r'const\s+API\s*=\s*["\']([^"\']+)["\']', src)
    if not m:
        raise SystemExit("FAIL  в index.html нет константы API")
    api = m.group(1)
    if not api.rstrip("/").endswith("/api"):
        print("FAIL  API = %r, ожидался префикс, оканчивающийся на /api" % api)
    else:
        ok("API = %s" % api)
    # fetch(API + "/tts"), fetch(API + '/timers?seen=' + h) и подобное
    rel = re.findall(r'API\s*\+\s*["\'](/[^"\'?]+)', src)
    return api, sorted(set(rel))


def exact_paths():
    """Прямые обращения к /kolonka/... в обход префикса."""
    src = open(INDEX, encoding="utf-8").read()
    bad = []
    for m in re.finditer(r'["\'`](/kolonka/[^"\'`\s]*)["\'`]', src):
        p = m.group(1)
        rest = p[len(PREFIX):]
        if rest.split("/")[0] in NO_API:
            continue
        bad.append(p)
    return sorted(set(bad))


def stale_test_paths():
    """Тесты, ссылающиеся на путь, которого больше нет."""
    bad = []
    for name in sorted(os.listdir(HERE)):
        if not name.startswith("e2e_") or not name.endswith(".py"):
            continue
        src = open(os.path.join(HERE, name), encoding="utf-8").read()
        for m in re.finditer(r'["\'`](/kolonka/[A-Za-z0-9_.\-]+)', src):
            p = m.group(1)
            rest = p[len(PREFIX):]
            if rest.split("/")[0] in NO_API:
                continue
            bad.append((name, p))
    return bad


def live(rel):
    url = BASE.rstrip("/") + rel
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "jane-route-check"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, "HTTPError"
    except Exception as e:
        return 0, "%s: %s" % (type(e).__name__, e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="дополнительно спросить каждый путь живым запросом")
    args = ap.parse_args()

    errors = 0
    api, rels = ui_paths()

    direct = exact_paths()
    if direct:
        for p in direct:
            errors += fail("index.html обращается напрямую, минуя API: %s" % p)
    else:
        ok("index.html нигде не идёт в обход префикса")

    stale = stale_test_paths()
    if stale:
        for name, p in stale:
            errors += fail("%s ждёт устаревший путь %s" % (name, p))
    else:
        ok("тесты используют актуальные пути")

    if args.live:
        for r in rels:
            code, err = live(api.rstrip("/") + r)
            if code == 0:
                errors += fail("живой запрос %s не дошёл: %s" % (r, err))
            elif code == 404:
                errors += fail("живой запрос %s -> 404" % r)
            else:
                ok("%s%s -> %d" % (api, r, code))
    else:
        print("info   интерфейс дёргает: %s" % ", ".join(rels))
        print("info   для проверки живым запросом добавь --live")

    print("")
    if errors:
        print("ИТОГ: проблем %d" % errors)
        return 1
    print("ИТОГ: все пути согласованы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
