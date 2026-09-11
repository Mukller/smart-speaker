# SIMILAR PROJECTS — похожие проекты на GitHub

Обзор аналогов (звёзды и лицензии проверены 2026-09-11 через GitHub API).
Назначение таблицы: понимать, что уже сделано, и откуда можно брать код/идеи.

## Правила легального заимствования

- **MIT / Apache-2.0** — можно копировать свободно при сохранении авторства
  (добавляем в NOTICE, шапки файлов не удаляем). Это путь проекта.
- **GPL / AGPL** — код брать нельзя в MIT-репо (заразные лицензии).
  Только идеи и архитектура.
- **NOASSERTION / кастомная лицензия** — читать LICENSE в самом репо перед
  копированием (например, у Silero и Porcupine лицензии на модели отдельные).
- Всегда сохраняем копирайт и указание автора в NOTICE.

## Ядро и архитектура

| Проект | Звёзды | Лицензия | Зачем смотреть |
|---|---|---|---|
| [janvarev/Irene-Voice-Assistant](https://github.com/janvarev/Irene-Voice-Assistant) | 1157 | MIT | Наша база — уже вендорено в `vendor/irene-va` |
| [synesthesiam/rhasspy](https://github.com/synesthesiam/rhasspy) | 952 | MIT | Оффлайн-ассистент для home automation, зрелые идеи пайплайна |
| [openvoiceos/ovos-core](https://github.com/openvoiceos/ovos-core) | 287 | Apache-2.0 | Наследник Mycroft; идеи skill-системы |
| [Priler/jarvis](https://github.com/Priler/jarvis) | 2927 | кастомная (см. репо) | Оффлайн-ассистент на Rust, WIP — архитектурные идеи |
| [m15-ai/Local-Voice](https://github.com/m15-ai/Local-Voice) | 21 | MIT | Очень близкий стек: Vosk + Piper + Ollama, realtime, RPi |
| [AlexandreSajus/JARVIS](https://github.com/AlexandreSajus/JARVIS) | 527 | GPL-3.0 | Только идеи (voice→LLM→speech web-UI) |

## STT / распознавание

| Проект | Звёзды | Лицензия | Зачем смотреть |
|---|---|---|---|
| [alphacep/vosk-api](https://github.com/alphacephei/vosk-api) | 15125 | Apache-2.0 | Наш STT: оффлайн, русские модели |
| [KoljaB/RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) | 10124 | MIT | VAD + wake word + instant transcription поверх whisper |

## TTS / озвучка русского

| Проект | Звёзды | Лицензия | Зачем смотреть |
|---|---|---|---|
| [snakers4/silero-models](https://github.com/snakers4/silero-models) | 6098 | кастомная (см. репо) | Нейро-TTS русского, основной голос колонки |
| [rhasspy/piper](https://github.com/rhasspy/piper) | 11279 | MIT | Лёгкий TTS для RPi, ru_RU голоса |
| [rany2/edge-tts](https://github.com/rany2/edge-tts) | 11916 | кастомная (см. репо) | Бесплатные MS-голоса онлайн |
| [Navatusein/Silero-TTS-Service](https://github.com/Navatusein/Silero-TTS-Service) | 60 | MIT | Silero как сервис для HA/Rhasspy — готовый паттерн для M6 |
| [twirapp/silero-tts-api-server](https://github.com/twirapp/silero-tts-api-server) | 21 | см. репо | Silero по HTTP |
| [daswer123/silero-tts-enhanced](https://github.com/daswer123/silero-tts-enhanced) | 24 | см. репо | Удобная обёртка Silero |
| [denisxab/speakerpy](https://github.com/denisxab/speakerpy) | 60 | см. репо | Озвучка чисел/английских слов через Silero |
| [Matatonic/openedai-speech](https://github.com/matatonic/openedai-speech) | 859 | AGPL-3.0 | Только идеи (OpenAI-совместимый TTS-сервер) |
| [rsxdalv/TTS-WebUI](https://github.com/rsxdalv/TTS-WebUI) | 3258 | MIT | Свисток из всех TTS-моделей; полигон для сравнения голосов |
| [fluxions-ai/vui](https://github.com/fluxions-ai/vui) | 760 | кастомная (см. репо) | Малый контекстный TTS + realtime assistant, новое |

## Wake word

| Проект | Звёзды | Лицензия | Зачем смотреть |
|---|---|---|---|
| [Picovoice/porcupine](https://github.com/Picovoice/porcupine) | 4935 | Apache-2.0 (SDK) | Готовое RU wake-слово, модели под free-tier |
| [dscripka/openWakeWord](https://github.com/dscripka/openWakeWord) | 2762 | Apache-2.0 | Тренировка своего слова «дженет» |
| [MycroftAI/mycroft-precise](https://github.com/MycroftAI/mycroft-precise) | 964 | Apache-2.0 | Проверенный классический вариант |
| [OHF-Voice/micro-wake-word](https://github.com/OHF-Voice/micro-wake-word) | 930 | Apache-2.0 | Для ESP32 в перспективе |
| [Picovoice/picovoice](https://github.com/Picovoice/picovoice) | 706 | Apache-2.0 (SDK) | Полный on-device стек |

## Умный дом / интеграции

| Проект | Звёзды | Лицензия | Зачем смотреть |
|---|---|---|---|
| [AlexxIT/StreamAssist](https://github.com/AlexxIT/StreamAssist) | 388 | MIT | Русскоязычный автор; камера+колонка → ассистент в HA |
| [jxlarrea/voice-satellite-card-integration](https://github.com/jxlarrea/voice-satellite-card-integration) | 773 | AGPL-3.0 | Только идеи (планшет/браузер как сателлит) |
| [nerdaxic/glados-voice-assistant](https://github.com/nerdaxic/glados-voice-assistant) | 348 | см. репо | Fun-референс: свой голос персонажа |
| [espressif/esp-va-sdk](https://github.com/espressif/esp-va-sdk) | 316 | см. репо | Если когда-нибудь пойдём в сторону ESP32 |

## DIY-железо (референсы корпуса/сборки)

| Проект | Звёзды | Зачем смотреть |
|---|---|---|
| [ericick/open-voicebox-pi](https://github.com/ericick/open-voicebox-pi) | 7 | Близкая архитектура RPi-колонки (Porcupine+whisper.cpp+TTS) |
| [marek1and/ai-smart-speaker](https://github.com/marek1and/ai-smart-speaker) | 1 | Ретрофит готовой колонки: ReSpeaker XVF3800 + I2S DAC |
| [st7712/nexo](https://github.com/st7712/nexo) | 2 | Свои усилители + RPi |
| [tingkts/DIY-SmartSpeaker-on-RaspberryPi3](https://github.com/tingkts/DIY-SmartSpeaker-on-RaspberryPi3) | 0 | Классика AVS |

## Выводы для проекта

1. Стек «Vosk + Silero + Irene» — рабочая и проверенная связка для русского, уникальной
   ниши «своя колонка по-русски оффлайн» с готовой сборкой нет — есть все части.
2. Ближайший аналог по духу — m15-ai/Local-Voice (MIT), можно подсматривать в детали
   realtime-пайплайна без копирования.
3. Для серверного варианта (M6) готовые паттерны уже есть: vosk_asr_server в Irene,
   Silero-TTS-Service, openedai-speech.