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
#     CITY       город для плагина погоды       (default Minsk)
#     NO_RESTART=1  не перезапускать контейнер
# =============================================================================
set -uo pipefail

REPO_DIR="${REPO_DIR:-/home/anton/smart-speaker}"
CONTAINER="${CONTAINER:-setup-irene-core-1}"
DOMAIN="${DOMAIN:-antonpetnitsky.com}"
EXT_IP="${EXT_IP:-46.216.19.51}"
ASSISTANT="${ASSISTANT:-дженет}"
CITY="${CITY:-Minsk}"
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
python3 - "$CONTAINER" "$ASSISTANT" "$CITY" <<'PY'
import json, shutil, subprocess, sys, time
container, assistant, city = sys.argv[1], sys.argv[2], sys.argv[3]
base = "/app/vendor/irene-va/options"

# wttr.in needs no API key (openweathermap does), just activation + a city,
# so 'погода' is answered by the plugin instead of falling through to the LLM.
targets = {
    "core.json": {"voiceAssNames": assistant, "ttsEngineId": "console",
                  "playWavEngineId": "consolewav"},
    "plugin_weather_wttr.json": {"is_active": True, "location": city},
    "plugin_weatherowm.json": {"is_active": False},
}
for name, want in targets.items():
    path = "%s/%s" % (base, name)
    raw = subprocess.run(["docker", "exec", container, "cat", path],
                         capture_output=True)
    if raw.returncode != 0:
        print("    WARN: не читается %s" % name)
        continue
    cfg = json.loads(raw.stdout.decode("utf-8"))
    changed = {k: (cfg.get(k), v) for k, v in want.items() if cfg.get(k) != v}
    if not changed:
        print("    %-28s уже актуально" % name)
        continue
    shutil.copy(path, path + ".bak." + str(int(time.time())))
    cfg.update(want)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
    for k, (old, new) in changed.items():
        print("    %-28s %r -> %r" % (name, old, new))
PY
[ $? -eq 0 ] || die "не удалось применить options"
ok "core.json + погода"

say "1b/5 свободная память (без неё контейнер зависает на старте)"
avail=$(free -m | awk '/^Mem:/{print $7}')
if [ "${avail:-0}" -lt 1500 ]; then
    warn "доступно ${avail} МБ — контейнер может не подняться."
    warn "Основные потребители: voice-notes pipeline (~3.7 ГБ, простаивает),"
    warn "ollama runner (~1.6 ГБ), java-серверы Minecraft (~5.7 ГБ)."
    warn "Освободи память вручную либо останови voice-notes:"
    warn "  pkill -f 'app/pipeline.py --watch'   # поднимет cron, если он включён"
else
    ok "доступно ${avail} МБ"
fi

say "1c/5 модель голоса для TTS (volum irene_models, ~116 МБ)"
# Голос нужен, чтобы колонка звучала, а не печатала текст в консоль: в
# контейнере нет /dev/snd, поэтому синтезируем WAV и отдаём его браузеру.
# Модель кладём в отдельный том, иначе она стирается при пересоздании.
TTS_URL="https://alphacephei.com/vosk/models/vosk-model-tts-ru-0.4-irina.zip"
TTS_MD5="4d799f050ef931c45b522b6323c172bf"
TTS_HOST="$REPO_DIR/.tts-model"
if [ -d "$TTS_HOST/vosk-model-tts-ru-0.4-irina" ]; then
    ok "модель уже скачана на хосте"
else
    say "качаю vosk-model-tts-ru-0.4-irina (~116 МБ), это один раз"
    mkdir -p "$TTS_HOST"
    if curl -sL --max-time 900 -o "$TTS_HOST/tts.zip" "$TTS_URL"; then
        got=$(md5sum "$TTS_HOST/tts.zip" | cut -d' ' -f1)
        if [ "$got" = "$TTS_MD5" ]; then
            ( cd "$TTS_HOST" && unzip -q -o tts.zip && rm -f tts.zip )
            ok "модель скачана и распакована"
        else
            bad "md5 не совпал (ожидали $TTS_MD5, получили $got) — модель не тронута"
        fi
    else
        warn "не удалось скачать модель голоса — колонка останется без звука"
    fi
fi

if [ -d "$TTS_HOST/vosk-model-tts-ru-0.4-irina" ]; then
    timeout 300 docker exec "$CONTAINER" mkdir -p /models/tts 2>/dev/null
    if timeout 600 docker cp "$TTS_HOST/vosk-model-tts-ru-0.4-irina/." "$CONTAINER:/models/tts/"; then
        ok "модель загружена в контейнер"
    else
        warn "модель не скопировалась в контейнер"
    fi
fi

# -----------------------------------------------------------------------------
say "1d/5 плагины, которые не могут работать в контейнере"
# mediacmds тянет pyautogui, которому нужен X-дисплей (в контейнере его нет
# и появиться не может), audioplayer требует PyGObject (gi) и звуковую
# карту. Оба падают при каждом старте и засоряют лог, поэтому выключаем.
# is_active они не читают - единственный способ убрать их из загрузки.
timeout 120 docker exec "$CONTAINER" sh -c '
  for p in plugin_mediacmds plugin_playwav_audioplayer; do
    if [ -f "/app/vendor/irene-va/plugins/$p.py" ]; then
      mv -f "/app/vendor/irene-va/plugins/$p.py" \
            "/app/vendor/irene-va/plugins_inactive/$p.py" && echo "    выключен: $p"
    fi
  done' 2>&1 | sed 's/^/  /'

# -----------------------------------------------------------------------------
say "2/5 файлы внутри контейнера"
# Файлы НЕ монтируются в контейнер (в compose только том options), поэтому
# каждый раз копируем вручную, иначе контейнер продолжит отдавать старый код.
if ! timeout 60 docker inspect "$CONTAINER" >/dev/null 2>&1; then
    warn "контейнера $CONTAINER нет — пересоздаю из compose"
    ( cd "$REPO_DIR/setup" && timeout 900 docker compose up -d ) 2>&1 | tail -3
    for _ in $(seq 1 60); do
        [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$API/webapi_client/" || true)" = "200" ] && break
        sleep 5
    done
fi
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

# Обращение по имени не должно уходить в LLM. Формулировку приветствия не
# проверяем: с голосовым профилем плагин здоровается «Рада тебя видеть, Антон!»,
# а без него — «Привет! Чем могу помочь?». Проверяем маршрутизацию.
r=$(call "$ASSISTANT привет")
if [ -n "$r" ] && echo "$r" | grep -q '"restxt"'; then
    if echo "$r" | grep -q '"source": *"plugin"'; then
        ok "обращение по имени ($ASSISTANT) -> плагин"
    else
        bad "обращение по имени ушло не в плагин: $(echo "$r" | head -c 60)"; fails=1
    fi
else
    bad "обращение по имени не ответило: $(echo "$r" | head -c 60)"; fails=1
fi

r=$(call "погода")
echo "$r" | grep -q '"source": *"plugin"' \
  && ok "погода -> плагин ($(echo "$r" | head -c 60))" \
  || { bad "погода ушла в LLM вместо плагина: $(echo "$r" | head -c 60)"; fails=1; }

# wttr.in ищет город по названию и молча подставляет одноимённую деревню, если
# название неоднозначно: «Insk» вернул Постниково (Кировская обл., Россия), а
# «Insk,Belarus» — Berezenka (Могилёвская обл.). Поэтому сверяем, куда город
# реально распознался, а не доверяем строке в конфиге.
say "город погоды: проверяю, что он распознан верно"
loc=$(timeout 30 docker exec "$CONTAINER" python3 -c "
import json
print(json.load(open('/app/vendor/irene-va/options/plugin_weather_wttr.json')).get('location',''))" 2>/dev/null)
case "$loc" in
    *.*,*)  # координаты «lat,lon» — сверять нечего
        ok "город задан координатами ($loc), неоднозначности нет"
        ;;
    *)
        resolved=$(timeout 30 curl -s --max-time 25 \
            "https://wttr.in/$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$loc")?format=j1" \
            | python3 -c "
import json,sys
try:
    a=(json.load(sys.stdin).get('nearest_area') or [{}])[0]
    print('%s / %s / %s' % (a.get('areaName',[{}])[0].get('value','?'),
                            a.get('region',[{}])[0].get('value','?'),
                            a.get('country',[{}])[0].get('value','?')))
except Exception:
    print('?')" 2>/dev/null)
        want=$(printf '%s' "$loc" | sed 's/,.*//' | tr -d '[:upper:]')
        got=$(printf '%s' "$resolved" | tr -d '[:upper:]')
        case "$got" in
            *"$want"*) ok "«$loc» -> $resolved" ;;
            *) bad "«$loc» распознан как $resolved — это не тот город."
               bad "  Уточни CITY (например CITY='Insk,Belarus') или передай координаты."
               fails=1 ;;
        esac
        ;;
esac

avail=$(free -m | awk '/^Mem:/{print $7}')
[ "${avail:-0}" -ge 800 ] \
  && ok "свободной памяти ${avail} МБ" \
  || { bad "свободно только ${avail} МБ — контейнер может зависнуть снова"; fails=1; }

# Маршруты nginx для колонки. Их правили руками на сервере, и однажды конфиг
# разъехался с шаблоном сайта antonpetnitsky.com — блок /api/ исчез, и каталог
# начал отдавать 404. Теперь сверяемся с каждым деплоем.
say "маршруты nginx для колонки"
NGINX_CONF=/etc/nginx/sites-available/antonpetnitsky.com
if sudo -n /usr/bin/cat "$NGINX_CONF" > /tmp/kolonka_nginx.conf 2>/dev/null; then
  missing=""
  for route in "location /kolonka/" "location /kolonka/sendTxtCmdStream" \
               "location = /kolonka/tts" "location = /kolonka/plugins" \
               "location = /kolonka/plugin/toggle"; do
    grep -qF "$route" /tmp/kolonka_nginx.conf || missing="$missing [$route]"
  done
  if [ -z "$missing" ]; then
    ok "все маршруты колонки на месте"
  else
    bad "в nginx отсутствуют:$missing"
    bad "  источник истины - deploy.sh репозитория antonpetnitsky.com, примени его"
    fails=1
  fi
else
  warn "не читается $NGINX_CONF, маршруты не проверил"
fi

# голос: эндпоинт должен отдать настоящий WAV (сигнатура RIFF), а не пустоту
r=$(curl -s -o /tmp/kolonka_tts.wav -w '%{http_code}' --max-time 180 \
  "$API/tts?text=$(python3 -c 'import urllib.parse;print(urllib.parse.quote("Привет, это проверка голоса"))')")
if [ "$r" = "200" ]; then
    magic=$(head -c 4 /tmp/kolonka_tts.wav)
    size=$(wc -c < /tmp/kolonka_tts.wav)
    if [ "$magic" = "RIFF" ] && [ "$size" -gt 10000 ]; then
        ok "TTS отдаёт WAV ($size байт)"
    else
        bad "TTS ответил, но не WAV: magic='$magic' size=$size"
        head -c 120 /tmp/kolonka_tts.wav | sed 's/^/      /'; echo
        fails=1
    fi
else
    bad "TTS вернул HTTP $r: $(head -c 160 /tmp/kolonka_tts.wav | tr -d '\0')"
    fails=1
fi

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
