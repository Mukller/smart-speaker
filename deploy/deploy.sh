#!/usr/bin/env bash
# =============================================================================
#  smart-speaker ("колонка") — deploy + verify
#
#  Запуск (с сервера, из любой директории):
#     bash /home/anton/smart-speaker/deploy/deploy.sh
#
#  Что делает (каждый шаг идемпотентен, можно гонять повторно):
#     1. синхронизирует код из локального клона в рабочий каталог
#     2. применяет настройки ассистента в options/core.json (бэкап перед записью)
#     3. копирует патченные файлы внутрь контейнера
#     4. перезапускает контейнер и ждёт готовности API
#     5. проверяет nginx, сайт, маршрутизацию команд и отсутствие ошибок TTS
#
#  Переменные окружения:
#     REPO_DIR   каталог проекта на сервере   (default /home/anton/smart-speaker)
#     CONTAINER  имя контейнера               (default setup-irene-core-1)
#     DOMAIN     внешний домен                (default antonpetnitsky.com)
#     EXT_IP     внешний IP                   (default 46.216.19.51)
#     ASSISTANT  имя ассистента                (default дженет)
#     NO_RESTART=1  не перезапускать контейнер
# =============================================================================
set -uo pipefail

REPO_DIR="${REPO_DIR:-/home/anton/smart-speaker}"
CONTAINER="${CONTAINER:-setup-irene-core-1}"
DOMAIN="${DOMAIN:-antonpetnitsky.com}"
EXT_IP="${EXT_IP:-46.216.19.51}"
ASSISTANT="${ASSISTANT:-дженет}"
VENDOR="$REPO_DIR/vendor/irene-va"
API="http://127.0.0.1:5003"

say()  { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; }
die()  { printf '  \033[31mABORT\033[0m %s\n' "$*"; exit 1; }

[ -d "$VENDOR" ] || die "каталог не найден: $VENDOR (задай REPO_DIR=)"

# -----------------------------------------------------------------------------
say "1/5 настройки ассистента (options/core.json)"
# core.json лежит в docker-volume, поэтому переживает пересборку контейнера.
#  voiceAssNames    — имя, на которое откликается ассистент
#  ttsEngineId      — console: silero/pyttsx требуют звукового стека, которого
#                     в контейнере нет (/dev/snd отсутствует). Озвучку в
#                     веб-интерфейсе делает браузер (Web Speech API).
#  playWavEngineId  — consolewav: 'audioplayer' требует модуль gi, которого нет,
#                     из-за чего был зависший ответ и ошибка инициализации.
python3 - "$CONTAINER" "$ASSISTANT" <<'PY'
import json, shutil, subprocess, sys, time
container, assistant = sys.argv[1], sys.argv[2]
path = "/app/vendor/irene-va/options/core.json"
raw = subprocess.run(["docker", "exec", container, "cat", path],
                     capture_output=True)
if raw.returncode != 0:
    sys.exit("cannot read " + path)
cfg = json.loads(raw.stdout.decode("utf-8"))
want = {"voiceAssNames": assistant, "ttsEngineId": "console",
        "playWavEngineId": "consolewav"}
changed = {k: (cfg.get(k), v) for k, v in want.items() if cfg.get(k) != v}
if not changed:
    print("    уже актуально, запись не требуется")
    sys.exit(0)
shutil.copy(path, path + ".bak." + str(int(time.time())))
cfg.update(want)
with open(path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=4)
for k, (old, new) in changed.items():
    print("    %-15s %r -> %r" % (k, old, new))
PY
[ $? -eq 0 ] || die "не удалось применить core.json"
ok "core.json"

# -----------------------------------------------------------------------------
say "2/5 файлы внутри контейнера"
# Файлы НЕ монтируются в контейнер (в compose только том options), поэтому
# каждый раз копируем вручную, иначе контейнер продолжит отдавать старый код.
for rel in webapi_client/index.html plugins/plugin_greetings.py \
           voice_profiles.json runva_webapi.py; do
    [ -f "$VENDOR/$rel" ] || { warn "нет файла $rel — пропускаю"; continue; }
    docker cp "$VENDOR/$rel" "$CONTAINER:/app/vendor/irene-va/$rel" \
        || die "docker cp не удался: $rel"
    ok "$rel"
done

# -----------------------------------------------------------------------------
say "3/5 целостность веб-интерфейса"
docker exec "$CONTAINER" python3 - <<'PY' || die "JS сломан"
import re, sys
h = "/app/vendor/irene-va/webapi_client/index.html"
src = open(h, encoding="utf-8").read()
js = src[src.find("<script>"):src.find("</script>")]
problems = []
if src.count("function addMsg(") != 1:
    problems.append("addMsg должен быть ровно один (иначе рекурсия RangeError)")
if "originalAddMsg" in src:
    problems.append("originalAddMsg вызывает сам себя — бесконечная рекурсия")
if src.count("function renderPluginStatus(") != 1:
    problems.append("renderPluginStatus должен быть ровно один")
for fn in ("sendQuick", "toggleTheme", "initTheme", "startVoiceEnroll",
           "exportSession", "initSpeakerUI", "sendCommand", "addMsg"):
    if "function %s(" % fn not in js and "async function %s(" % fn not in js:
        problems.append("нет функции %s" % fn)
if js.count("{") != js.count("}"):
    problems.append("не сбалансированы скобки в JS")
if problems:
    for p in problems:
        print("    - " + p)
    sys.exit(1)
print("    addMsg=1, renderPluginStatus=1, скобки сбалансированы, функции на месте")
PY
ok "index.html валиден"

# -----------------------------------------------------------------------------
say "4/5 перезапуск и готовность"
if [ "${NO_RESTART:-0}" = "1" ]; then
    warn "NO_RESTART=1 — пропускаю"
else
    docker restart "$CONTAINER" >/dev/null || die "не перезапустился"
    ready=""
    for _ in $(seq 1 120); do
        if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$API/webapi_client/" || true)" = "200" ]; then
            ready=1; break
        fi
        sleep 2
    done
    [ -n "$ready" ] || die "API не поднялся за 4 минуты"
    ok "API готов"
    sleep 3
fi

# -----------------------------------------------------------------------------
say "5/5 проверки"
fails=0

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
       --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/kolonka/" || echo 000)
[ "$code" = "200" ] && ok "сайт /kolonka/ -> 200" || { bad "сайт /kolonka/ -> $code"; fails=1; }

cc=$(curl -sI --max-time 20 --resolve "$DOMAIN:443:127.0.0.1" \
     "https://$DOMAIN/kolonka/" | tr -d '\r' | grep -ci 'no-store' || true)
[ "${cc:-0}" -ge 1 ] && ok "кеш браузера отключён" || { bad "нет no-store — браузер будет кэшировать старый JS"; fails=1; }

sudo -n nginx -t >/dev/null 2>&1 \
  && ok "nginx -t" \
  || { sudo nginx -t >/dev/null 2>&1 && ok "nginx -t" || { bad "nginx -t не прошёл"; fails=1; }; }

enc() { python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$1"; }
call() { curl -s --max-time 120 "$API/sendTxtCmd?cmd=$(enc "$1")"; }

r=$(call "привет")
echo "$r" | grep -q '"source": *"plugin"' \
  && ok "привет -> плагин ($(echo "$r" | head -c 60))" \
  || { bad "привет не ушёл в плагин: $(echo "$r" | head -c 60)"; fails=1; }

r=$(call "время")
echo "$r" | grep -q '"source": *"plugin"' \
  && ok "время -> плагин" \
  || { bad "время не ушло в плагин: $(echo "$r" | head -c 60)"; fails=1; }

r=$(call "$ASSISTANT привет")
echo "$r" | grep -q 'Привет\|привет' \
  && ok "обращение по имени ($ASSISTANT) работает" \
  || { bad "имя не подставляется: $(echo "$r" | head -c 60)"; fails=1; }

errs=$(docker logs "$CONTAINER" --since 3m 2>&1 \
       | grep -c 'Ошибка инициализации плагина' || true)
[ "${errs:-0}" -eq 0 ] && ok "ошибок инициализации TTS/playWav нет" \
                      || { bad "ошибок инициализации: $errs"; fails=1; }

name=$(docker logs "$CONTAINER" --since 3m 2>&1 | grep -i 'Assistant names' | tail -1)
echo "$name" | grep -q "$ASSISTANT" \
  && ok "ассистент: $ASSISTANT" \
  || { bad "в логе: $name"; fails=1; }

printf '\n'
if [ "$fails" -eq 0 ]; then
    printf '\033[32mВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\033[0m — https://%s/kolonka/\n' "$DOMAIN"
else
    printf '\033[31mЕСТЬ ПРОВАЛЕННЫЕ ПРОВЕРКИ\033[0m — смотри выше\n'
    exit 1
fi
