# DEPLOY-SERVER — развёртывание на `192.168.0.36`

Сервер: домашний Linux (`192.168.0.36`, Haswell Xeon E3, Docker 29, 56 ГБ ОЗУ, доступ по `antonpetnitsky.com` через SSH-ключ `archrice_ed25519`).

---

## Шаги (автономно, без вопросов)

1. Клонировать репо на сервер:
   ```bash
   git clone https://github.com/Mukller/smart-speaker.git ~/smart-speaker-server
   cd ~/smart-speaker-server
   git pull (обновления)
   ```

2. Скачать модель Vosk (если отсутствует на сервере):
   ```bash
   wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
   unzip vosk-model-small-ru-0.22.zip -d vendor/irene-va/model/
   rm vosk-model-small-ru-0.22.zip
   ```

3. Установить базовые зависимости на сервере (если не установлены):
   ```bash
   sudo apt-get install -y python3-pip python3-venv docker.io docker-compose
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r vendor/irene-va/requirements.txt --quiet
   ```

4. Запустить серверные сервисы (`setup/docker-compose.yml`):
   ```bash
   docker-compose -f setup/docker-compose.yml up -d vosk-stt silero-tts core-api ollama
   ```

5. Проверить порты:
   - `vosk-stt`: `2700` (TCP, STT)
   - `silero-tts`: `5002` (TTS)
   - `core-api`: `8000` (WebSocket/REST, ядро Irene)
   - `ollama`: `11434` (LLM, M4)

6. Безопасность (исправить грабли из `ANALYZED-REPOS.md`):
   ```bash
   # Отключить ADB TCP (если используется Amlogic-образ из thirdreality)
   echo 'ADB_TCP_PORT=' | sudo tee /etc/default/adbd  # или эквивалент в Docker/env
   # Сменить SSH-пароль (`hello3r` → свой) или использовать ключи
   sudo passwd root  # или настроить authorized_keys
   ```

7. Клиент (колонка) — тонкий режим:
   - ESP32-S3 (`MarcoFre/ESP32-S3-AI-Smart-Speaker` как референс) или RPi Zero с `sounddevice` + `Porcupine` wake word.
   - Клиент подключается к `192.168.0.36:8000` через WebSocket (`runva_webapi.py`).
   - Команда для запуска клиента (если Python-клиент на колонке):
     ```bash
     python -c "
     import websockets, sounddevice, numpy
     # Референс: mic_client/script.js (WebSocket клиент) или ESPHome satellite (C++)
     # Для Python-клиента: отправлять pcm16 аудио на ws://192.168.0.36:8000/stt
     # Принимать base64 mp3 с сервера и воспроизводить через sounddevice
     "
     ```
   - Для ESP32-S3: использовать `buildroot` из `voice-music-assistant` (ESPHome native API) или написать минимальный ESP32-клиент (`esp-idf` + `microWakeWord` + WebSocket).

---

## Быстрая проверка сервера

```bash
# На сервере (192.168.0.36)
curl -s http://localhost:8000/health || echo 'core-api not running yet'
curl -s http://localhost:2700/health || echo 'vosk-stt not running yet'
# Тест STT (через Python-клиент или curl с аудио-файлом)
python vendor/irene-va/runva_vosk.py  # это клиентская версия; для сервера — vosk_asr_server.py
```

---

## Что осталось сделать (после деплоя)

- M2: заменить wake word на `Porcupine` или `openWakeWord` («дженет»).
- M3: дописать `plugin_homeassistant.py` для HA REST/WebSocket или использовать ESPHome satellite из `voice-music-assistant`.
- M4: подключить `ollama` (`11434`) или `vsegpt` через `plugin_boltakka_vsegpt.py`.
- M5/M7: корпус + кнопки (референс `voice-music-assistant` кнопки) + музыка (`Sendspin` / `Music Assistant`).
