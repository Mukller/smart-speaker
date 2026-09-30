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
say "0/5 контейнер"
# Всё дальше делается через docker exec/cp, поэтому контейнер должен быть
# жив. Раньше это проверялось только на шаге 2, и скрипт падал на шаге 1.
if ! timeout 60 docker inspect "$CONTAINER" >/dev/null 2>&1; then
    warn "контейнера $CONTAINER нет — пересоздаю из compose"
    ( cd "$REPO_DIR/setup" && timeout 900 docker compose up -d ) 2>&1 | tail -3 | sed 's/^/    /'
elif ! timeout 60 docker exec "$CONTAINER" sh -c 'test -d /models && test -d /music' 2>/dev/null; then
    # контейнер старше compose с томами irene_models/music: пересоздаём,
    # иначе модели некуда класть, а музыка не видна
    warn "том моделей или музыки не подключён — пересоздаю контейнер"
    ( cd "$REPO_DIR/setup" && timeout 900 docker compose up -d --force-recreate ) 2>&1 \
        | tail -3 | sed 's/^/    /'
else
    ok "контейнер на месте, тома подключены"
fi

for _ in $(seq 1 60); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$API/webapi_client/" || true)" = "200" ] \
        && break
    timeout 60 docker start "$CONTAINER" >/dev/null 2>&1 || true
    sleep 5
done
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$API/webapi_client/" || true)
[ "$code" = "200" ] && ok "API отвечает" || die "API не поднялся (код $code)"

# -----------------------------------------------------------------------------
say "1/5 настройки ассистента (options/core.json)"
# core.json лежит в docker-volume, поэтому переживает пересборку контейнера.
#  voiceAssNames    — имя, на которое откликается ассистент
#  ttsEngineId      — vosk: модель синтеза лежит в томе irene_models, ключей и
#                     звуковой карты не нужно. Раньше стоял console, и ядро
#                     просто печатало текст, голоса не было вовсе.
#  playWavEngineId  — выбирается автоматически выше: aplay, если на машине
#                     есть карта, иначе consolewav. 'audioplayer' требует
#                     модуль gi, которого в контейнере нет, из-за чего был
#                     зависший ответ и ошибка инициализации.
#
# Звук выбираем по машине, а не жёстко. На Raspberry Pi есть карта и aplay,
# и колонка должна говорить сама; на этом сервере звука нет, и всё играет
# браузер. AUDIO_BACKEND можно задать явно.
#
# Проверяем именно В КОНТЕЙНЕРЕ, а не на хосте: этот конфиг читает ядро
# внутри контейнера. На этом сервере ALSA есть у хоста, но в контейнере её
# нет, и выбор по хосту включал aplay там, где aplay не запустится.
if [ "${AUDIO_BACKEND:-auto}" = "auto" ]; then
    if timeout 60 docker exec "$CONTAINER" sh -c \
        '[ -d /dev/snd ] && command -v aplay >/dev/null 2>&1'; then
        playwav=aplay
    else
        playwav=consolewav
    fi
else
    playwav="$AUDIO_BACKEND"
fi
echo "    звук: playWavEngineId=$playwav"

# ВАЖНО: правка идёт внутри контейнера (docker exec -i), потому что файлы
# options лежат в volume контейнера, а не на хосте. Раньше скрипт читал их
# через docker exec, а писал по тому же пути на хосте — и падал с
# FileNotFoundError, как только требовалось что-то изменить.
docker exec -i "$CONTAINER" python3 - "$ASSISTANT" "$CITY" "$playwav" <<'PY'
import json, os, shutil, sys, time
assistant, city, playwav = sys.argv[1], sys.argv[2], sys.argv[3]
base = "/app/vendor/irene-va/options"

# wttr.in needs no API key (openweathermap does), just activation + a city,
# so 'погода' is answered by the plugin instead of falling through to the LLM.
targets = {
    "core.json": {"voiceAssNames": assistant, "ttsEngineId": "vosk",
                  "playWavEngineId": playwav},
    "plugin_weather_wttr.json": {"is_active": True, "location": city},
    "plugin_weatherowm.json": {"is_active": False},
}
for name, want in targets.items():
    path = os.path.join(base, name)
    if not os.path.exists(path):
        print("    WARN: нет файла %s" % name)
        continue
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
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

say "1c2/5 модель распознавания речи (volum irene_models, ~88 МБ)"
# Распознавание локальное (vosk), а не браузерное: работает в любом браузере
# и не требует сети до Google.
STT_URL="https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
STT_MD5="d1759dc83eb8fd87850129afbd9f4b7b"
STT_HOST="$REPO_DIR/.stt-model"
if [ -d "$STT_HOST/vosk-model-small-ru-0.22" ]; then
    ok "модель распознавания уже скачана"
else
    say "качаю vosk-model-small-ru-0.22 (~44 МБ), это один раз"
    mkdir -p "$STT_HOST"
    if curl -sL --max-time 900 -o "$STT_HOST/stt.zip" "$STT_URL"; then
        got=$(md5sum "$STT_HOST/stt.zip" | cut -d' ' -f1)
        if [ "$got" = "$STT_MD5" ]; then
            ( cd "$STT_HOST" && unzip -q -o stt.zip && rm -f stt.zip )
            ok "модель распознавания скачана и распакована"
        else
            bad "md5 не совпал (ожидали $STT_MD5, получили $got)"
        fi
    else
        warn "не удалось скачать модель распознавания — останется браузерный ввод"
    fi
fi

if [ -d "$STT_HOST/vosk-model-small-ru-0.22" ]; then
    timeout 300 docker exec "$CONTAINER" mkdir -p /models/stt 2>/dev/null
    if timeout 600 docker cp "$STT_HOST/vosk-model-small-ru-0.22/." "$CONTAINER:/models/stt/"; then
        ok "модель распознавания загружена в контейнер"
    else
        warn "модель распознавания не скопировалась"
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

# Плеер: папка с музыкой монтируется из хоста, файлы кладёт пользователь.
# Пустая папка - не ошибка, поэтому только предупреждаем, если её нет вовсе.
if timeout 60 docker exec "$CONTAINER" test -d /music 2>/dev/null; then
    n=$(timeout 60 docker exec "$CONTAINER" sh -c \
        'ls -1 /music 2>/dev/null | grep -icE "\.(mp3|m4a|aac|ogg|opus|flac|wav|wma)$"' 2>/dev/null)
    ok "папка музыки подключена (файлов: ${n:-0})"
else
    warn "папка музыки не смонтирована — плеер будет пустым"
fi

# -----------------------------------------------------------------------------
say "2/5 файлы внутри контейнера"
# Файлы НЕ монтируются в контейнер (в compose только тома options и models),
# поэтому каждый раз копируем вручную, иначе контейнер продолжит отдавать
# старый код.
for rel in webapi_client/index.html webapi_client/manifest.json \
           webapi_client/icon.svg \
           plugins/plugin_greetings.py \
           voice_profiles.json runva_webapi.py; do
    [ -f "$VENDOR/$rel" ] || { warn "нет файла $rel — пропускаю"; continue; }
    docker cp "$VENDOR/$rel" "$CONTAINER:/app/vendor/irene-va/$rel" \
        || die "docker cp не удался: $rel"
    ok "$rel"
done

# Плагины. Раньше в гит попадал только plugin_greetings.py, а остальные
# жили исключительно в контейнере: их нельзя было ни прочитать, ни починить,
# ни воспроизвести при пересоздании. Копируем каталог целиком; удалять
# ничего не будем, docker cp только перезаписывает, поэтому файл, которого
# в репозитории нет, в контейнере сохранится.
if [ -d "$VENDOR/plugins" ]; then
    n=$(find "$VENDOR/plugins" -maxdepth 1 -name '*.py' | wc -l)
    if [ "$n" -gt 0 ]; then
        if timeout 180 docker cp "$VENDOR/plugins/." \
                "$CONTAINER:/app/vendor/irene-va/plugins/"; then
            ok "плагинов скопировано: $n"
        else
            bad "плагины не скопированы"
        fi
        # Шаг 1d/5 отключает эти плагины, но он отрабатывает ДО копирования,
        # и копия возвращает их на место. Из-за этого в логе появлялись две
        # ошибки загрузки. Повторяем отключение здесь, чтобы порядок шагов
        # не влиял на результат.
        timeout 120 docker exec "$CONTAINER" sh -c '
          for p in plugin_mediacmds plugin_playwav_audioplayer; do
            if [ -f "/app/vendor/irene-va/plugins/$p.py" ]; then
              mkdir -p /app/vendor/irene-va/plugins_inactive
              mv -f "/app/vendor/irene-va/plugins/$p.py" \
                    "/app/vendor/irene-va/plugins_inactive/$p.py" \
                    && echo "    выключен после копирования: $p"
            fi
            # Переноса исходника мало: в __pycache__ остаётся .pyc, и ядро
            # грузит плагин именно оттуда - ошибка загрузки возвращалась
            # при каждом старте, хотя .py в plugins/ уже не было.
            rm -f "/app/vendor/irene-va/plugins/__pycache__/$p."*.pyc
          done
          rm -rf /app/vendor/irene-va/plugins/__pycache__' 2>&1 | sed 's/^/  /'
    else
        bad "в plugins/ нет ни одного .py"
    fi
fi

# Секрет канала будильника лежит только на сервере и в гит не попадает.
# Копируем отдельно и только если файл есть: колонка обязана работать и без
# Telegram, просто тогда будильник слышен исключительно в браузере.
TG_SRC="$REPO_DIR/.telegram"
if [ -f "$TG_SRC" ]; then
    docker cp "$TG_SRC" "$CONTAINER:/app/.telegram" \
        && ok "канал будильника в Telegram настроен" \
        || bad "канал будильника не скопирован - звонок будет только в браузере"
else
    warn "нет .telegram - будильник будет звонить только в браузере"
fi

# проверяем, что секрет не утёк в код
if grep -rqE '[0-9]{8,10}:[A-Za-z0-9_-]{30,}' "$VENDOR/runva_webapi.py" 2>/dev/null; then
    bad "в runva_webapi.py похож на токен - секрет не должен быть в коде"
else
    ok "токена в коде нет"
fi

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

# Плагины читаются при старте ядра, поэтому о ошибках узнаём только сейчас.
# Раньше это проверялось вручную, а поломка выглядела как «плагин молча
# исчез»: список сокращался, и в логе деплоя не оставалось ни следa.
# Считаем ошибки только с момента ТЕКУЩЕГО старта: окно в 5 минут захватывало
# лог предыдущего запуска и показывало уже исправленные ошибки - проверка
# врала ровно тогда, когда всё было починено.
started=$(timeout 60 docker inspect -f '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null || echo "")
if [ -n "$started" ]; then
    pj=$(timeout 60 docker logs "$CONTAINER" --since "$started" 2>&1 \
         | grep -c 'JAA PLUGIN ERROR' || true)
    [ "${pj:-0}" -eq 0 ] && ok "ошибок загрузки плагинов нет" \
        || { bad "ошибок загрузки плагинов: $pj"; fails=1; }
else
    warn "не удалось узнать время старта контейнера - пропускаю проверку плагинов"
fi

pc=$(curl -s --max-time 20 "$API/plugins" | tr ',' '\n' | grep -c '"name"' || true)
[ "${pc:-0}" -ge 8 ] && ok "плагинов в списке: $pc" \
    || { bad "плагинов в списке всего $pc - часть выпала"; fails=1; }

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
  for route in "location /kolonka/" "location /kolonka/api/" \
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

# распознавание: скармливаем TTS-озвучку в STT. Фраза «какая сейчас погода»
# и ответ «сегодня солнечно» намеренно различаются, поэтому сверяем с
# ожиданием именно исходную фразу.
SAY="какая сейчас погода"
curl -s -o /tmp/kolonka_stt_in.wav --max-time 180 \
  "$API/tts?text=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$SAY")"
heard=$(curl -s --max-time 240 -X POST --data-binary @/tmp/kolonka_stt_in.wav \
        -H "Content-Type: audio/wav" "$API/stt" \
        | python3 -c "
import json,sys
try:
    print(json.load(sys.stdin).get('text',''))
except Exception as e:
    print('<не разобрал ответ: %s>' % e)" 2>/dev/null)
case "$(echo "$heard" | tr 'A-Z' 'a-z')" in
  *погод*)
    ok "распознавание работает: «$SAY» -> «$heard»"
    ;;
  *)
    bad "STT не узнал фразу «$SAY» (получил: «${heard:-пусто}»)"
    bad "  без этого останется только браузерное распознавание"
    fails=1
    ;;
esac

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
