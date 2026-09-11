# smart-speaker — своя умная колонка, которая говорит по-русски

Идея и рабочее пространство проекта: собрать **свою домашнюю умную колонку** с полностью
русским голосом, работающую оффлайн (или с опциональным LLM-бэкендом), из проверенных
открытых компонентов — **не изобретая с нуля**.

Главный принцип проекта: **максимальное заимствование готового с указанием авторов**.
Основа уже найдена и вендорена в этот репозиторий.

## Ключевое требование — русский язык

- **STT** (распознавание): Vosk с русской моделью (оффлайн, CPU, ~50 МБ).
- **TTS** (озвучка): Silero TTS (нейро-голоса: aidar/baya/kseniya/xenia/eugene) как основной,
  Piper ru_RU / RHVoice / edge-tts как альтернативы.
- **Понимание команд**: ядро интентов Irene VA + `lingua_franca` с русским парсингом чисел/дат/времени.
- **Разговор**: LLM-болталка (VseGPT / OpenRouter / локальная Ollama) — по-русски.

## Что уже лежит в репозитории

[`vendor/irene-va/`](vendor/irene-va) — полная копия исходников
**Irene-Voice-Assistant** (МIТ, © 2021–2022 Vladislav Janvarev, © 2020 EnjiRouz) —
русского оффлайн голосового ассистента с плагинной архитектурой:

- `runva_vosk.py` — точка входа: микрофон → Vosk → ядро;
- `vacore.py` — ядро: контексты, таймеры, маршрутизация команд в плагины;
- `plugins/` — TTS (Silero v3/v4, vosk, pyttsx, elevenlabs), погода (OpenWeatherMap/wttr),
  таймеры, дата-время, расписания Яндекса, медиа-команды (MPC-HC), болталка с LLM
  (VseGPT/OpenAI-совместимый), нормализаторы текста для русского TTS;
- `lingua_franca/` — русский парсинг чисел и дат (исходно Mycroft AI, Apache-2.0);
- `mic_client/`, `webapi_client/`, `vosk_asr_server.py` — удалённый микрофон и ASR-сервер;
- `model/README.md` — параметры русской модели Vosk (сами бинарники не в гите, скачиваются).

Из вендореного вырезаны: бинарные модели (91 МБ + 52 МБ), англо-словарь CMU (20 МБ),
локальные сертификаты `localhost.crt/.key` (секреты в гит не попадают никогда).
Подробная карта «файл → зачем → автор» — [docs/REUSE-MAP.md](docs/REUSE-MAP.md).

## Архитектура (цель)

```
микрофон → VAD → wake word («дженет») → STT (Vosk ru) → ядро интентов (Irene)
                                                          ├── оффлайн-скиллы (погода, таймер, медиа...)
                                                          ├── умный дом (Home Assistant)
                                                          └── LLM-болталка (VseGPT / Ollama)
                                                    ← TTS (Silero ru) → динамик
```

## Быстрый старт прототипа (на ПК, Windows/Linux)

```bash
cd vendor/irene-va
pip install -r requirements.txt
# скачать русскую модель vosk small и распаковать в vendor/irene-va/model
# (см. https://alphacephei.com/vosk/models, параметры в model/README.md)
python runva_vosk.py
```

Имя ассистента задаётся опцией `voiceAssNames` (плагин `core`, запускается через
`runva_settings_manager.py`). В этом проекте хотим имя **«дженет»**.

## Документы

- [docs/ROADMAP.md](docs/ROADMAP.md) — план от прототипа до железной колонки.
- [docs/STACK.md](docs/STACK.md) — выбор STT/TTS/wake-word/LLM для русского.
- [docs/HARDWARE.md](docs/HARDWARE.md) — варианты железа и корпуса.
- [docs/SIMILAR-PROJECTS.md](docs/SIMILAR-PROJECTS.md) — обзор аналогов на GitHub
  и правила легального заимствования по лицензиям.
- [docs/REUSE-MAP.md](docs/REUSE-MAP.md) — что берём из Irene и от кого.

## Лицензии

- Наш код и документы — MIT (см. [LICENSE](LICENSE)).
- Вендоренный код Irene VA — MIT, авторство сохранено в [NOTICE](NOTICE) и шапках файлов.
- Сторонние модели (Vosk, Silero, Piper) не хранятся в гите; лицензии — в
  [docs/STACK.md](docs/STACK.md) и [docs/SIMILAR-PROJECTS.md](docs/SIMILAR-PROJECTS.md).
