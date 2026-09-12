# DEPLOY-SERVER — архитектура «колонка (тонкий клиент) → сервер 192.168.0.36»

Требование Антона: обработка на сервере (`192.168.0.36` — домашний Haswell Xeon E3, 56 ГБ ОЗУ, Docker 29, доступ из ЛВС и через `antonpetnitsky.com`). Колонка — только микрофон + динамик + кнопка + wake word.

---

## Компоненты сервера (`192.168.0.36`)

| Сервис | Контейнер / процесс | Порт | Источник |
|---|---|---|---|
| STT (Vosk) | `vosk_asr_server` или `python -m vosk` | 2700 (TCP) или WebSocket | `vendor/irene-va/vosk_asr_server.py` |
| TTS (Silero) | `silero-tts-service` (`Navatusein/Silero-TTS-Service`, MIT) или локальный `plugin_tts_silero_v4.py` через HTTP | 5002 / внутренний | `docs/STACK.md` |
| Ядро (команды, плагины) | `runva_webapi.py` + `vacore.py` (Docker или нативно) | 8000 (WebSocket/REST) | `vendor/irene-va/` |
| LLM (оффлайн) | `ollama` (контейнер или натив) + `plugin_boltalka_vsegpt.py` | 11434 | `docs/WHAT-WE-NEED.md` M4 |
| LLM (онлайн резерв) | Endpoint `vsegpt.ru` или OpenRouter (`plugin_boltalka_vsegpt.py`) | — | `vendor/irene-va/plugins/plugin_boltalka_vsegpt.py` |
| Умный дом | `ESPHome` satellite (`voice-music-assistant` архитектура) или REST/WebSocket (`plugin_homeassistant.py`) | 6053 (ESPHome) или HA-порт | `docs/ANALYZED-REPOS.md` (ESPHome native API из `thirdreality/voice-music-assistant`) |
| Музыка | `Sendspin` (контейнер или натив) или `Music Assistant` Add-on | 5000 (Sendspin) или MA-порт | `docs/ANALYZED-REPOS.md` (Sendspin) |
| Клиентская связь | WebSocket / HTTP | 8000 (`runva_webapi.py`) | `vendor/irene-va/runva_webapi.py` |

---

## Базовый `docker-compose.yml` (референс для сервера)

Создать в репо или на сервере `~/smart-speaker-server/docker-compose.yml`:

```yaml
version: "3.8"
services:
  vosk-stt:
    image: python:3.11-slim
    command: python /app/vosk_asr_server.py --port 2700 --model /models
    volumes:
      - ./vendor/irene-va/model:/models:ro
      - ./vendor/irene-va/vosk_asr_server.py:/app/vosk_asr_server.py:ro
    ports:
      - "2700:2700"
    restart: unless-stopped

  silero-tts:
    image: python:3.11-slim  # или готовый образ Navatusein/Silero-TTS-Service
    # Конфигурация через env (API-клюя не требуется для локального Silero)
    ports:
      - "5002:5000"
    restart: unless-stopped

  core-api:
    image: python:3.11-slim
    working_dir: /app
    command: python /vendor/irene-va/runva_webapi.py
    volumes:
      - ./:/app/vendor/irene-va:ro  # или полный вендор
      - ./.env:/app/.env:ro
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_KEY:-}
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"
    restart: unless-stopped

volumes:
  ollama_data:
```

Примечание: это **референс**, не готовый продакшн-файл. Для запуска на `192.168.0.36` нужно:
- Скопировать этот файл на сервер (`scp` или `git clone` репо `smart-speaker`).
- Убедиться, что Docker работает (`docker ps` — контейнеры `safalife-bot-tailscale-1` и другие уже запущены, значит Docker готов).
- Проверить, что порты `2700`, `5002`, `8000`, `11434` не заняты (если заняты — сменить в `docker-compose.yml`).
- Для `core-api`: скопировать `vendor/irene-va/` на сервер или монтировать через volume.
- Для `vosk-stt`: модель (`vendor/irene-va/model/`) уже скачана (`final.mdl` 15.8 МБ) — можно использовать напрямую (`-v ./vendor/irene-va/model:/models:ro`).

---

## Как работает клиент (колонка) в этой модели

### Вариант А — ESP32-S3 / ESPHome satellite (из `voice-music-assistant`)
- Железо: ESP32-S3 (`MarcoFre/ESP32-S3-AI-Smart-Speaker` как референс) или готовый `ThirdReality` speaker.
- Клиент: ESPHome firmware + `linux-voice-assistant-cpp` (из `voice-music-assistant`).
- Клиент подключается к HA (`ESPHome native API`) и отправляет аудио через ESPHome на сервер или использует HA Cloud.
- Для нашей адаптации: клиент можно сделать очень тонким — только микрофон + wake-word (`Porcupine`) + WebSocket на сервер (`192.168.0.36:8000`).
- Преимущество: клиент не содержит модель Vosk или Silero — всё на сервере. Модель (~87 МБ) хранится только на сервере, обновляется в одном месте.

### Вариант Б — RPi Zero / планшет (тонкий Python-клиент)
- Клиент: Python-скрипт (`runva_client.py` или адаптированный `runva_webapi.py` в режиме клиента), который:
  1. Слушает микрофон (`sounddevice`).
  2. При срабатывании wake word (`Porcupine` или Vosk-грамматика) отправляет аудио-поток через WebSocket на `192.168.0.36:8000` (к `core-api`).
  3. Принимает аудио-ответ (TTS) с сервера и воспроизводит (`sounddevice` или `pyttsx3` для быстрого ответа).
  4. Отправляет события кнопок через тот же WebSocket.
- Преимущество: гибкость (Python, можно быстро менять клиент), не нужно прошивать ESP32.
- Недостаток: клиент всё ещё содержит `sounddevice` и базовые зависимости, но без `torch` или `Silero` моделей.

---

## Коммуникация клиент ↔ сервер

### Протокол
- **WebSocket** (рекомендуется): двунаправленный, поддерживает потоковое аудио в обе стороны. `runva_webapi.py` уже использует WebSocket для удалённого клиента (`mic_client/`).
- **HTTP REST**: проще для команд, но не подходит для потокового аудио (нужен chunked transfer или WebSocket).
- **TCP (Sendspin)**: для музыки — готовый протокол из `voice-music-assistant`.

### Формат сообщений (WebSocket)
```
Клиент → Сервер: {"action":"audio_stream","data":"<base64_audio_chunk>","format":"pcm16","rate":16000}
Сервер → Клиент: {"action":"stt_result","text":"дженет включи свет"}
Сервер → Клиент: {"action":"tts_audio","data":"<base64_mp3>","voice":"silero_v4"}
Клиент → Сервер: {"action":"button_event","button":"single","context":"music"}
```

Эти форматы — референс, основанный на `runva_webapi.py` и `mic_client/script.js` (`vendor/irene-va/`). Для M3 (HA-интеграция) можно использовать `ESPHome native API` вместо WebSocket.

---

## Безопасность в серверной модели

| Угроза | Решение в репо / документация |
|---|---|
| ADB TCP (`5555`) без авторизации (из `voice-music-assistant`) | Отключить или ограничить (`ADB_TCP_PORT=` в `/etc/default/adbd`) — см. `docs/ARCHITECTURE.md`. |
| SSH (`hello3r`) | Сменить пароль или перейти на ключи (`ssh-keygen` на клиенте, `authorized_keys` на сервере) — см. `docs/HARDWARE.md`. |
| API-ключи (`plugin_weatherowm.py`, `plugin_boltalka_vsegpt.py`) | Никогда не коммитить `.env` или заполненные ключи; хранить в `.env` или в настройках сервера (`core.json`) через `runva_settings_manager.py`. |
| Доступ к WebSocket (`8000`) из интернета | Ограничить через `nginx` прокси или `ufw` (`192.168.0.0/16`) на сервере; не открывать `8000` в интернет без HTTPS. |
| Модель Vosk на сервере (87 МБ) | Читать только (`-v ./vendor/irene-va/model:/models:ro`) в Docker; не давать запись клиенту. |

---

## Следующие шаги (после записи документа)

1. ✅ Модель Vosk (`vendor/irene-va/model/` — `final.mdl` 15.8 МБ + остальные файлы).
2. ✅ `docs/ARCHITECTURE.md` записан (серверная модель, ESPHome satellite, Sendspin, Docker-референс, коммуникация WebSocket, безопасность).
3. ⚠️ Установка зависимостей (`pip install -r vendor/irene-va/requirements.txt`) — в процессе (`install3.log`, таймаут 120 с). Завершить вручную или дождаться.
4. ⏸️ Тест M0 прототипа (`python vendor/irene-va/runva_vosk.py`) — ждать завершения `pip install` или запустить с уже установленными базовыми пакетами (`vosk`, `sounddevice`, `numpy`, `pyttsx3`).
5. ⏸️ M6: создать `setup/docker-compose.yml` для сервера (`192.168.0.36`) с `vosk_stt`, `silero_tts`, `core_api`, `ollama`, `music_assistant`.
6. ⏸️ M3: начать новый плагин `plugin_homeassistant.py` или ESPHome satellite-конфигурацию (референс `StreamAssist` + `voice-music-assistant`).
