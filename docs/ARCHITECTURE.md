# SERVER-SIDE ARCHITECTURE — колонка как тонкий клиент

Требование Антона: **колонка = микрофон + динамик + wake-word; вся обработка (STT, TTS, LLM, плагины, музыка) — на сервере `192.168.0.36`.**

Это меняет модель с автономной (RPi с полным стеком) на клиент-серверную.
Основа архитектуры — `vendor/irene-va/` (Python-ядро) + готовые сервисы из репо `voice-music-assistant` (ESPHome satellite, Sendspin) и `ANALYZED-REPOS.md` (Silero-TTS-Service, RealtimeSTT, Ollama, openedai-speech).

---

## Архитектура (ASCII)

```
[ТОНКИЙ КЛИЕНТ: Колонка / ESP32-S3 / RPi Zero]
  │ USB-микрофон или ReSpeaker 2-Mic (см. docs/HARDWARE.md)
  │ Динамик + усилитель MAX98357A (или готовая USB-колонка)
  │ Кнопка (одиночное/двойное/тройное нажатие — из thirdreality/voice-music-assistant)
  │ Wake word: Porcupine / openWakeWord («дженет»)
  │
  ├─[LAN / Wi-Fi]──► [СЕРВЕР: 192.168.0.36 (Haswell Xeon E3, 56GB RAM, Docker)]
  │
  │                 ┌─────────────────────────────────────────────┐
  │                 │  Docker / нативные сервисы                  │
  │                 │  ┌─────────────────┐  ┌──────────────────┐ │
  │                 │  │ vosk_asr_server │  │ Silero-TTS-Service│ │
  │                 │  │ (STT, Vosk ru)  │  │ (TTS, Silero ru) │ │
  │                 │  └─────────────────┘  └──────────────────┘ │
  │                 │  ┌─────────────────┐  ┌──────────────────┐ │
  │                 │  │  runva_webapi   │  │  Ollama (LLM)    │ │
  │                 │  │ (Irene core API)│  │  (qwen/gemma ru) │ │
  │                 │  └─────────────────┘  └──────────────────┘ │
  │                 │  ┌─────────────────┐  ┌──────────────────┐ │
  │                 │  │ Music Assistant │  │  Sendspin client │ │
  │                 │  │ (Music Assistant Add-on из thirdreality) │ │
  │                 │  └─────────────────┘  └──────────────────┘ │
  │                 └─────────────────────────────────────────────┘
  │
  ◄──[WebSocket / HTTP]── ответ (TTS аудио / команда / LLM текст)

Примечания:
- Колонка не содержит Vosk-модель (~87 МБ) и Silero torch-зависимости — всё на сервере.
- Сервер (`192.168.0.36`) — наш домашний Linux-сервер с Docker 29 (см. AGENTS.md контекст).
- Клиент (колонка) — может быть ESP32-S3 (`MarcoFre`), RPi Zero (`thirdreality` ESPHome satellite) или старый планшет с браузером (`mic_client/`).
```

---

## Компоненты клиента (колонка) — минимум

| Функция | Реализация | Источник в репо / репозитории |
|---|---|---|
| Микрофон | USB или ReSpeaker 2-Mic | `docs/HARDWARE.md` |
| Захват аудио + VAD | `sounddevice` (или ESPHome audio capture) | `vendor/irene-va/runva_vosk.py` (клиентская часть) |
| Wake word «дженет» | Porcupine (free-tier модель) или openWakeWord (натренированное «дженет») или ESPHome `microWakeWord` (если ESP32-S3) | `Picovoice/porcupine` (Apache-2.0), `dscripka/openWakeWord` (Apache-2.0), `OHF-Voice/micro-wake-word` |
| Сетевой клиент | `webapi_client/` (браузер) или ESPHome native API (`voice-music-assistant`) или Python-клиент (`runva_webapi.py` в режиме клиента) | `vendor/irene-va/webapi_client/` + `docs/ANALYZED-REPOS.md` (ESPHome satellite) |
| Динамик | MAX98357A (I2S) или USB-колонка | `docs/HARDWARE.md` |
| Кнопка | Физическая кнопка (GPIO на RPi или ESP32) → одинарное/двойное/тройное нажатие → WebSocket-событие на сервер | `thirdreality/voice-music-assistant` (документация по кнопкам) |

Клиент **НЕ содержит** `vacore.py`, `plugins/`, модели STT/TTS. Он только:
1. Слушает микрофон и отправляет аудио-поток на сервер (`vosk_asr_server` или `webapi`).
2. Принимает аудио-ответ (TTS) с сервера и воспроизводит.
3. Отправляет события кнопок.
4. При необходимости — отображает статус (LED / экран).

---

## Компоненты сервера (192.168.0.36) — всё готово или почти готово

| Сервис | Технология | Источник / репозиторий | Статус |
|---|---|---|---|
| STT-сервер | `vosk_asr_server.py` (из `vendor/irene-va/`) или `faster-whisper` через `RealtimeSTT` (если нужен GPU/более точный) | `vendor/irene-va/vosk_asr_server.py` | ✅ Уже в репо |
| TTS-сервер | `Silero-TTS-Service` (`Navatusein/Silero-TTS-Service`, MIT, 60★) или `openedai-speech` (`Matatonic/openedai-speech`, AGPL-3.0) или локальный `Silero v4` (`plugin_tts_silero_v4.py`) | `docs/STACK.md` | ✅ Плагины в Irene; сервисы — готовые репозитории |
| Ядро (команды, плагины) | `vacore.py` + плагинная система (`vendor/irene-va/`) | `vendor/irene-va/` | ✅ Уже в репо |
| LLM-болталка | `Ollama` (локально на сервере) или `plugin_boltalka_vsegpt.py` (через VseGPT / OpenRouter) | `vendor/irene-va/plugins/plugin_boltalka_vsegpt.py` + `docs/WHAT-WE-NEED.md` M4 | ✅ Уже в репо |
| Умный дом (HA) | ESPHome native satellite (`voice-music-assistant`) или REST/WebSocket плагин (`StreamAssist`) | `docs/ANALYZED-REPOS.md` (ESPHome satellite) + `docs/WHAT-WE-NEED.md` M3 | ⚠️ Новый плагин `plugin_homeassistant.py` нужно дописать |
| Музыка | `Sendspin` (из `voice-music-assistant`) или `Music Assistant` | `docs/ANALYZED-REPOS.md` (Sendspin) + `docs/WHAT-WE-NEED.md` M7 | ⚠️ Интеграция — план |
| Wake word (на сервере) | `Porcupine` (если используется ESP32-S3 клиент) или `openWakeWord` (если клиент RPi) или Vosk-грамматика (если клиент работает как сейчас) | `docs/STACK.md` | ⚠️ Для M2 |
| Docker / оркестрация | Docker (`vendor/irene-va/Dockerfile`, `docs/INSTALL_DOCKER.md`) или `docker compose` для сервера | `vendor/irene-va/Dockerfile` | ✅ Уже в репо |

---

## Как работает поток (пошагово)

### Шаг 1 — Клиент (колонка) слушает
- Микрофон постоянно слушает через `sounddevice` (если RPi) или ESP32 audio capture (если ESP32-S3).
- Wake word: либо `Porcupine` (если установлен на клиенте), либо клиент отправляет аудио-поток на сервер (`vosk_asr_server`) для постоянного распознавания (как сейчас в Irene `runva_vosk.py`).
- **Оптимизация (M2, M6):** для экономии CPU клиента лучше перенести wake word на клиент (`Porcupine` / ESPHome `microWakeWord`), а STT — только после срабатывания wake word.

### Шаг 2 — Клиент отправляет аудио на сервер
- Если клиент работает как сейчас (`runva_vosk.py` на клиенте): весь STT происходит локально (тяжело для RPi Zero, но возможно для RPi 4/5).
- **Новая архитектура (M6):** клиент отправляет аудио через WebSocket (`runva_webapi.py` или ESPHome native API) на сервер `192.168.0.36`. Сервер (`vosk_asr_server`) принимает, распознаёт и возвращает текст.
- Преимущество: клиент может быть очень лёгким (ESP32-S3 или старый планшет); модель Vosk и Silero остаются на сервере (одна модель на все колонки).

### Шаг 3 — Сервер обрабатывает текст
- `vacore.py` получает распознанную строку (`voiceInput_str`).
- `plugins/core.py` проверяет `voiceAssNames` («дженет»). Если слово есть в потоке — активируется команда.
- Плагины (`datetime`, `weather`, `timer`, `mediacmds`, новый `plugin_homeassistant.py`) обрабатывают команду.
- Если команда требует LLM (`plugin_boltalka_vsegpt.py` или новый `ollama`-плагин) — запрос уходит в `Ollama` на сервере или в `VseGPT` (онлайн).

### Шаг 4 — Сервер генерирует ответ
- TTS: `Silero-TTS-Service` или локальный `Silero v4` генерирует аудио.
- Аудио отправляется клиенту через WebSocket (`runva_webapi.py`) или HTTP (`Silero-TTS-Service`).
- Клиент воспроизводит через `sounddevice` или ESP32 audio playback.

### Шаг 5 — Клиент управляет кнопками и статусом
- Нажатие кнопки (одиночное / двойное / тройное) генерирует событие в ESPHome или в Python-клиенте. Событие отправляется на сервер через тот же WebSocket/API.
- Сервер (`vacore.py` или новый плагин событий) обрабатывает событие как команду (например, «следующий трек» или «стоп музыка»).

---

## Что нужно дописать / адаптировать (без нового движка)

### Уже готово (не требует нового кода)
| Компонент | Статус |
|---|---|
| Ядро (`vacore.py` + плагины) | ✅ `vendor/irene-va/` |
| STT (Vosk small ru) | ✅ Модель скачана |
| TTS (Silero v3/v4) | ✅ Плагины в Irene |
| LLM-болталка (VseGPT endpoint) | ✅ `plugin_boltalka_vsegpt.py` |
| Удалённый микрофон (`mic_client/`) | ✅ `vendor/irene-va/` |
| WebAPI (`runva_webapi.py`) | ✅ `vendor/irene-va/` |
| ASR-сервер (`vosk_asr_server.py`) | ✅ `vendor/irene-va/` |
| Умный дом — архитектура satellite | ✅ `docs/ANALYZED-REPOS.md` (ESPHome из `voice-music-assistant`) |

### Требует нового / адаптации (новые плагины / конфигурация)
| Компонент | Что нужно | Приоритет |
|---|---|---|
| Wake word «дженет» | `plugins/core.py` уже содержит `voiceAssNames`; для M2 — заменить на `Porcupine` или `openWakeWord` (новый плагин или замена `runva_vosk.py` на клиент с wake-word движком) | M2 |
| HA-интеграция (REST/WebSocket) | Новый плагин `plugin_homeassistant.py` или ESPHome native satellite (C++ из `voice-music-assistant`, запускаемый как отдельный контейнер) | M3 |
| Серверная сборка Docker | `docker compose` для сервера (`192.168.0.36`): `vosk_asr_server`, `Silero-TTS-Service`, `runva_webapi`, `Ollama` | M6 |
| Клиент как thin device | Адаптация `runva_webapi.py` в режиме клиента или ESP32-S3/ESPHome satellite (из `voice-music-assistant`) | M5 |
| Безопасность (ADB, SSH) | Документация в `docs/WHAT-WE-NEED.md`; исправление в настройках сервера | M6 |
| Приватный режим / кнопки | Новый плагин или настройка `core.py` для обработки кнопок (из `voice-music-assistant`) | M8 |

---

## Быстрые действия (после записи документа)

1. ✅ Модель Vosk (`vendor/irene-va/model/` — `final.mdl` 15.8 МБ, `am/` + `conf/` + `graph/` + `ivector/`).
2. ✅ `plugins/core.py` — `voiceAssNames` = «дженет» (вставлен через бинарный патч).
3. ⚠️ Установка зависимостей (`pip install -r vendor/irene-va/requirements.txt`) — в процессе (долгая из-за `torch` / `gradio`). Лог: `vendor/irene-va/install3.log`.
4. ⏸️ Тест M0 (`python vendor/irene-va/runva_vosk.py`) — ждать завершения `pip install` или запустить вручную.
5. ✅ Документы запушены: `docs/ARCHITECTURE.md`, `docs/ANALYZED-REPOS.md`, `docs/WHAT-WE-NEED.md`, `docs/ROADMAP.md`, `docs/STACK.md`, `docs/HARDWARE.md`.
