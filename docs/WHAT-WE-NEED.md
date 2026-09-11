# ЧТО НАМ НУЖНО — полный план сборки умной колонки

На основе анализа 11 репозиториев (см. docs/ANALYZED-REPOS.md) + нашей вендоренной базы Irene VA.

## Принцип: «берём готовое, адаптируем под себя, указываем авторов»

Никаких «с нуля». Каждый компонент уже существует в одном из проанализированных репо.
Наш вклад — сборка, адаптация под русский язык и интеграция.

---

## Компоненты колонки и источники

### Ядро (уже в репо)
| Компонент | Источник в репо / репозитории | Что делать |
|---|---|---|
| STT (русский) | `vendor/irene-va/` (Vosk) + модель с alphacephei.com | Скачать модель, проверить WER |
| TTS (русский) | `vendor/irene-va/plugins/` (Silero v3/v4) + `rhasspy/piper` (резерв) | Выбрать основной голос, протестировать на живых фразах |
| Понимание команд | `vendor/irene-va/` (Irene core + lingua_franca ru) | Добавить `voiceAssNames` = «дженет» |
| Плагины (погода, таймеры, медиа) | `vendor/irene-va/plugins/` | Оставить, проверить API-ключи через `.env` |
| Удалённый микрофон | `vendor/irene-va/mic_client/` + `runva_webapi.py` | Работает через браузер или клиент |

### Интеграция с умным домом (M3)
| Компонент | Источник | Что брать / как использовать |
|---|---|---|
| ESPHome satellite для HA Voice | `thirdreality/voice-music-assistant` (C++ linux-voice-assistant-cpp) + `OHF-Voice/linux-voice-assistant` | Берём архитектуру: ESPHome native API, satellite обнаруживается HA как голосовой помощник. Не копируем C++ в Python-проект — используем как референс или запускаем как отдельный контейнер/устройство. |
| HA REST/WebSocket плагин | `AlexxIT/StreamAssist` (MIT, 388 звёзд) | Новый плагин `plugin_homeassistant.py` в Irene — REST/WebSocket к HA. Берём идеи из StreamAssist (камера + колонка) и документацию ESPHome satellite. |

### LLM-болталка (M4)
| Компонент | Источник | Что брать / как использовать |
|---|---|---|
| OpenAI-совместимый endpoint | `vendor/irene-va/plugins/plugin_boltalka_vsegpt.py` (Vladislav Janvarev) + `Olney1/ChatGPT-OpenAI-Smart-Speaker` (архитектура) + `xuan2261/r1-xiaozhi` (LLM-ассистент) | Оставляем плагин VseGPT, добавляем Ollama-опцию (локальный LLM на `192.168.0.36`). Для полного оффлайна — Ollama (qwen2.5, gemma) на домашнем сервере. |

### Музыка (M7)
| Компонент | Источник | Что брать / как использовать |
|---|---|---|
| Протокол потоковой передачи | `thirdreality/voice-music-assistant` (Sendspin) | Берём Sendspin как протокол (не копируем весь C++ firmware, а используем готовые библиотеки или сервисы). Для Python-ядра можно использовать HTTP/WebSocket или готовый Sendspin-клиент, если он существует в репозитории. Или просто интегрировать через Music Assistant (готовый Add-on в репо thirdreality). |
| Music Assistant | `thirdreality/voice-music-assistant` (документация + Add-on) | Добавляем Music Assistant в Docker на домашнем сервере; колонка подключается как плеер Sendspin. |

### Wake word (M2)
| Компонент | Источник | Что делать |
|---|---|---|
| Базовый вариант (уже работает) | `vendor/irene-va/plugins/core.py` (`voiceAssNames`) | Меняем имя на «дженет» через settings manager. Работает, но жрёт CPU (постоянный полный STT). |
| Улучшенный вариант | `Picovoice/porcupine` (Apache-2.0, RU-поддержка) или `dscripka/openWakeWord` (Apache-2.0) | Для M2: заменить или дополнить Vosk-грамматику готовым wake-word движком. Porcupine требует бесплатного API-ключа для моделей; openWakeWord — тренировка своего слова «дженет». |

### Железо (M5)
| Компонент | Источник / пример | Решение |
|---|---|---|
| Вычислительный блок | `thirdreality/voice-music-assistant` (Amlogic / Linux buildroot) + `MarcoFre/ESP32-S3...` (ESP32-S3) | Основной вариант: Raspberry Pi 4/5 или любой mini-PC x86 (наш ноутбук Ryzen 7 5800U для прототипа, домашний сервер 192.168.0.36 для бэкенда). Резерв: ESP32-S3 для очень компактной версии. Не берём Amlogic-специфичную прошивку. |
| Микрофон | `thirdreality/voice-music-assistant` (USB или встроенный массив) + `sapperxl/Dual-Speaker...` (двойной микрофон) | USB-микрофон или ReSpeaker 2-Mics HAT. Для улучшения — двойной микрофон с AEC (берём идею из sapperxl). |
| Звук | `thirdreality/voice-music-assistant` (динамик + усилитель) | MAX98357A (I2S) + динамик 2-3 Вт или готовая колонка. |
| Корпус / кнопки | `thirdreality/voice-music-assistant` (документация по кнопкам) + `nevo`, `st7712/nexo` | 3D-печать (CoreXY под рукой), схема кнопок из репо thirdreality: одинарный/двойной/тройной клик для управления. |
| Питание / сетевое подключение | `thirdreality/voice-music-assistant` (Wi-Fi через BLE-настройку, ESPHome) | Для RPi — стандартное питание 5V 3A. Wi-Fi настройка через ESPHome или через webapi_client (браузер). |

### Безопасность и инфраструктура (M6)
| Компонент | Грабля из репо / решение |
|---|---|
| ADB TCP (`5555`) | В репо `voice-music-assistant` слушает на `0.0.0.0:5555` без авторизации. Решение: отключить TCP (`ADB_TCP_PORT=`) или слушать только localhost. |
| SSH (`hello3r`) | Пароль известен. Решение: сменить пароль или перейти на ключи. |
| API-ключи | В репо `Irene` (`plugin_weatherowm.py`, `plugin_boltalka_vsegpt.py`) — пустые заглушки. Решение: никогда не коммитить `.env` или заполненные ключи; хранить в настройках (`core.json`, `runva_settings_manager.py`) или в `.env` на устройстве. |
| Docker / сервер | `vendor/irene-va/Dockerfile` + `docs/INSTALL_DOCKER.md` | Для M6: Docker на `192.168.0.36` с `vosk_asr_server.py`, `Silero-TTS-Service`, `openedai-speech` или `Ollama`. |

---

## Синтез — как всё собирается в одну колонку (без написания нового движка)

1. **Основа:** `vendor/irene-va/` (Irene VA) — Python-ядро, плагины, русский парсинг.
2. **STT:** Vosk small ru (`model/README.md` — скачать модель) → работает на CPU → M0 готов.
3. **TTS:** Silero v3 или v4 → `plugin_tts_silero_*.py` в Irene → голос звучит по-русски → M1 готов.
4. **Wake word:** Vosk-имя «дженет» через `core.py` (быстро, но CPU) или Porcupine/openWakeWord (M2) → экономия CPU, лучше для постоянной работы.
5. **LLM-болталка:** `plugin_boltalka_vsegpt.py` + VseGPT / OpenRouter (M4) или Ollama на сервере → полный оффлайн.
6. **Умный дом:** новый плагин `plugin_homeassistant.py` + ESPHome satellite (референс `voice-music-assistant` + `StreamAssist`) → управление светом/датчиками голосом (M3).
7. **Музыка:** Sendspin (из `voice-music-assistant`) или плагин для плеера (`plugin_mediacmds.py`, `mpcapi/`) → M7.
8. **Железо:** RPi (M5) или mini-PC; корпус по `voice-music-assistant` (перфорированная панель); кнопки по документации репо; микрофон USB или ReSpeaker.
9. **Безопасность:** исправить грабли ADB/SSH; ключи в `.env` / `core.json`.
10. **Дополнения (M8):** идентификация говорящего (`EuleMitKeule`), стерео/двойной микрофон (`sapperxl`), ESP32-клиент (`MrBuddyCasino`, `MarcoFre`), приватный режим (`VGCH`).

---

## Что делать прямо сейчас (после записи файла)

1. Скачать русскую модель Vosk small (`vendor/irene-va/model/README.md` содержит ссылку и метрики).
2. Протестировать `python vendor/irene-va/runva_vosk.py` на ноутбуке Антона (Ryzen 7 5800U) с `voiceAssNames` = «дженет».
3. Выбрать TTS-голос (Silero v4 предпочтителен) и протестировать `plugin_tts_silero_v4.py`.
4. Начать M3: новый плагин Home Assistant (референс `StreamAssist` и архитектура ESPHome satellite из `voice-music-assistant`).
