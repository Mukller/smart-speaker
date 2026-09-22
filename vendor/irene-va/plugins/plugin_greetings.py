# Приветствие (и демо-плагин)
# author: Vladislav Janvarev (inspired by EnjiRouz)

import random
import os
from vacore import VACore

PROFILE_FILE = os.path.join(os.path.dirname(__file__), '..', 'voice_profiles.json')

def get_speaker_name():
    try:
        import json
        with open(PROFILE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        profiles = data.get('profiles', {})
        default = data.get('default_speaker', 'anton')
        if default in profiles:
            return profiles[default].get('name', 'Антон')
        # Fallback: any profile name
        for k, v in profiles.items():
            return v.get('name', 'Антон')
    except Exception:
        return 'Антон'

# функция на старте
def start(core:VACore):
    manifest = { # возвращаем настройки плагина - словарь
        "name": "Привет", # имя
        "version": "1.0", # версия
        "require_online": False, # требует ли онлайн?

        "description": "Демонстрационный плагин\n"
                       "Голосовая команда: привет|доброе утро",

        "commands": { # набор скиллов. Фразы скилла разделены | . Если найдены - вызывается функция
            "привет|доброе утро": play_greetings,
        }
    }
    return manifest

def play_greetings(core:VACore, phrase: str):
    speaker = get_speaker_name()
    # Кусок с voice profiles: иногда обращаемся к собеседнику по имени
    greetings = [
        f"И тебе привет, {speaker}!",
        f"Привет, {speaker}! Как дела?",
        f"Рада тебя видеть, {speaker}!",
        "И тебе привет!",
        "Привет! Чем могу помочь?",
    ]
    greet_str = greetings[random.randint(0, len(greetings) - 1)]
    print(f"- Сейчас я скажу фразу {greet_str}...\nЕсли вы её не услышите, значит, у вас проблемы с TTS или выводом звука и их надо настроить через менеджер настроек.")
    core.play_voice_assistant_speech(greet_str)
    print(f"- Я сказала фразу {greet_str} (говорящий: {speaker})")


