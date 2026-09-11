# REUSE-MAP — что берём из Irene VA и от кого

Вендореная копия: `vendor/irene-va/` (MIT, © Vladislav Janvarev 2021–2022, © EnjiRouz 2020).
Оригинал: https://github.com/janvarev/Irene-Voice-Assistant — 1157+ звёзд, активный проект,
статьи на Хабре (595855, 660715, 725066), группа Telegram t.me/irene_va.

Всё заимствование — по MIT с сохранением копирайта (см. NOTICE и LICENSE).

## Ядро (используем как есть)

| Файл | Назначение | Автор |
|---|---|---|
| `vacore.py` | Ядро: инициализация плагинов, маршрутизация фраз, контексты, таймеры, кэш TTS | Vladislav Janvarev |
| `jaa.py` | Загрузчик плагинов | Vladislav Janvarev |
| `runva_vosk.py` | Точка входа: микрофон → Vosk → ядро | Vladislav Janvarev |
| `runva_settings_manager.py` | GUI-менеджер настроек плагинов | Vladislav Janvarev |
| `runva_webapi.py` | WEB-API (удалённый клиент через браузер) | Vladislav Janvarev |
| `vosk_asr_server.py` | ASR-сервер Vosk по сети | Vladislav Janvarev |

## STT — русская модель

- `model/README.md` — метрики русской small-модели Vosk (WER 11.79 на golos_crowd и т.д.).
- Бинарники НЕ в гите: скачать с https://alphacephei.com/vosk/models, распаковать в
  `vendor/irene-va/model`. Модель Vosk — Alpha Cephei (Apache-2.0).

## TTS — русская озвучка (вот это и есть «говорит по-русски»)

| Файл | Назначение | Автор |
|---|---|---|
| `plugins/plugin_tts_silero_v3.py` | Silero v3 (torch), русский нейро-голос | Vladislav Janvarev |
| `plugins/plugin_tts_silero_v4.py` | Silero v4 (больше голосов) | Vladislav Janvarev |
| `plugins/plugin_tts_pyttsx.py` | Системный TTS (быстрый старт) | Vladislav Janvarev |
| `plugins/plugin_tts_vosk.py` | TTS через vosk-tts | Vladislav Janvarev |
| `plugins/plugin_tts_elevenlabs.py` | ElevenLabs (онлайн) | Vladislav Janvarev |
| `plugins/plugin_tts_console.py` | Вывод в консоль (отладка) | Vladislav Janvarev |

## Русский язык — парсинг и нормализация

| Файл | Назначение | Автор |
|---|---|---|
| `lingua_franca/` (вся) | Числа/даты/время, парсинг ru (parse_ru.py, format_ru.py) | Mycroft AI, vendored (Apache-2.0) |
| `utils/num_to_text_ru.py` | Числа словами по-русски | Vladislav Janvarev |
| `utils/all_num_to_text.py` | Универсальный num→text | Vladislav Janvarev |
| `plugins/plugin_normalizer_runorm.py` | Нормализация текста через runorm для TTS | Vladislav Janvarev |
| `plugins/plugin_normalizer_numbers.py`, `plugin_normalizer_prepare.py` | Нормализация чисел | Vladislav Janvarev |

## Скиллы (готовые плагины)

| Файл | Что умеет |
|---|---|
| `plugins/core.py` | Базовые настройки: имя ассистента (`voiceAssNames` → «дженет»), TTS-движок, логи |
| `plugins/plugin_datetime.py` | Дата/время/день недели |
| `plugins/plugin_timer.py` | Голосовые таймеры |
| `plugins/plugin_weatherowm.py` | Погода OpenWeatherMap (нужен ключ) |
| `plugins/plugin_weather_wttr.py` | Погода wttr.in (без ключа) |
| `plugins/plugin_yandex_rasp.py` | Расписания Яндекса (нужен ключ) |
| `plugins/plugin_greetings.py` | Приветствия |
| `plugins/plugin_gamemoreless.py` | Игра «больше-меньше» |
| `plugins/plugin_random.py` | Случайные числа/монетка/кубик |
| `plugins/plugin_mediacmds.py` | Медиа-команды |
| `plugins/plugin_mpchcmult.py` + `mpcapi/` | Управление MPC-HC плеером (mpcapi © Alexandr
  Borzykh, см. mpcapi/docs/LICENSE.txt) |
| `plugins/plugin_playwav_*.py` | Воспроизведение WAV разными движками |
| `plugins/plugin_boltalka_vsegpt.py` | Диалог с LLM (VseGPT/OpenAI-совместимый) — база для M4 |
| `plugins/plugin_voiceover.py`, `plugin_vasi.py`, `plugins_vasi/` | Расширенная озвучка/VASI |
| `plugins_inactive/` | Запас: RHVoice TTS, Wikipedia, YouTube, Яндекс.Музыка |

## Удалённый микрофон / клиент

| Файл | Назначение |
|---|---|
| `mic_client/` | Браузерный микрофон (recorder.js + WebSocket) |
| `webapi_client/` | Полный веб-клиент ассистента (модель вырезана, качается отдельно) |
| `runva_webapi.py` | Сервер WEB-API |

## Исключено из вендоринга (и почему)

| Исключено | Причина |
|---|---|
| `model/*` (91 МБ) | Бинарная STT-модель — качается отдельно, README сохранён |
| `webapi_client/model.tar.gz` (52 МБ) | Бинарная модель веб-клиента |
| `eng_to_ipa/resources/CMU_dict.json`, `CMU_source_files/` (20 МБ) | Англо-словарь IPA, для русского не нужен |
| `localhost.crt`, `localhost.key` | Секреты/сертификаты в гит не попадают |
| `.github/` | Funding-конфиг апстрима |
| `media/timer.wav` оставлен | Нужен для таймеров |

## Что пишем сами (новый код проекта)

- Плагин Home Assistant (свет/сценарии/датчики) — M3.
- Wake word «дженет» поверх Porcupine/openWakeWord — M2.
- Docker-сервисы ASR/TTS на домашнем сервере — M6.
- Корпус/железо — M5.