# ----------

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from fastapi import FastAPI, HTTPException, Request
import uvicorn
from multiprocessing import Process
import os
import re
import threading
import time

from starlette.responses import HTMLResponse, FileResponse, Response, StreamingResponse
from termcolor import cprint
import json
import re
from starlette.websockets import WebSocket
from starlette.concurrency import run_in_threadpool

# try:
#     from fastapi_utils.tasks import repeat_every
# except Exception as e:
#     cprint("Пожалуйста, установите fastapi-utils: pip install fastapi-utils","red")
#     exit(-1)
#from pydantic import BaseModel

from fastapi_utils_tasks import repeat_every


from vacore import VACore
import time

# ------------------- main loop ------------------

webapi_options = None

core = None
model = None # vosk model
#rec = None # vosk recognizer

# persistent session for Ollama (keep-alive + retries)
_ollama_session = requests.Session()
_retry = Retry(total=3, backoff_factor=2, status_forcelist=[502, 503, 504])
_ollama_session.mount("http://", HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=_retry))

# --------------- loading options ----------

# move options from old file
import os
if not os.path.exists('runva_webapi.json'):
    if os.path.exists('options/webapi.json'):
        os.rename('options/webapi.json','runva_webapi.json')

# loading options
from jaa import load_options

default_options={
    "host": "127.0.0.1",
    "port": 5003,
    "log_level": "info",
    "use_ssl": False
}
webapi_options = load_options(py_file=__file__,default_options=default_options)
use_ssl = webapi_options["use_ssl"]

# try:
#     with open('options/webapi.json', 'r', encoding="utf-8") as f:
#         s = f.read(1000000)
#         f.close()
#     webapi_options = json.loads(s)
#     use_ssl = webapi_options["use_ssl"]
# except Exception as e:
#     core = VACore()
#     core.init_with_plugins()
#     core.init_plugin("webapi")
#     cprint("Настройки созданы; пожалуйста, перезапустите этот файл", "red")
#     exit(-1)




"""
returnFormat Варианты:
- "none" (TTS реакции будут на сервере) (звук на сервере)
- "saytxt" (сервер вернет текст, TTS будет на клиенте) (звук на клиенте)
- "saywav" (TTS на сервере, сервер отрендерит WAV и вернет клиенту, клиент его проиграет) (звук на клиенте) **наиболее универсальный для клиента**
"""
def runCmd(cmd:str,returnFormat:str):
    if core.logPolicy == "cmd" or core.logPolicy == "all":
        print("Running cmd: ",cmd)

    tmpformat = core.remoteTTS
    core.remoteTTS = returnFormat
    core.remoteTTSResult = ""
    core.lastSay = ""
    core.execute_next(cmd,core.context)
    core.remoteTTS = tmpformat

def call_ollama(prompt, model="qwen2.5:0.5b-instruct", stream=False):
    url = "http://172.17.0.1:11434/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": stream, "keep_alive": -1}
    for attempt in range(1, 4):
        try:
            if stream:
                r = _ollama_session.post(url, json=payload, stream=True, timeout=300)
                return r  # return raw response for streaming caller
            else:
                r = _ollama_session.post(url, json=payload, timeout=300)
                data = r.json()
                return data.get("response", "")
        except Exception as e:
            if attempt == 3:
                return "Ошибка LLM: " + str(e)
            time.sleep(2 ** attempt)


def stream_ollama(prompt, model="qwen2.5:0.5b-instruct"):
    """Generator yielding (thinking, response) chunks from Ollama streaming."""
    url = "http://172.17.0.1:11434/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": True, "keep_alive": -1}
    try:
        r = _ollama_session.post(url, json=payload, stream=True, timeout=300)
        for line in r.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            token = data.get("response", "")
            thinking = data.get("thinking", "")
            yield token, thinking
    except Exception as e:
        yield "", "Ошибка LLM: " + str(e)

app = FastAPI()
is_running = True

from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

app.mount("/webapi_client", StaticFiles(directory="webapi_client", html = True), name="webapi_client")

app.mount("/mic_client", StaticFiles(directory="mic_client", html = True), name="mic_client")

@app.websocket("/wsrawtext")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("New WebSocket text connection")
    while True:
        data = await websocket.receive_text()

        data_json = None
        try:
            data_json = json.loads(str(data))
        except:
            print("Can't parse json from websocket: ", data)

        if data_json is not None:
            # r = process_chunk(rec,data,"saytxt,saywav")
            r = sendRawTxtOrig(data_json.get("txt",""), data_json.get("returnFormat", "none"))
            await websocket.send_text(str(r))




@app.websocket("/wsrawtextcmd")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("New WebSocket text cmd connection")
    while True:
        data = await websocket.receive_text()
        data_json = None
        try:
            data_json = json.loads(str(data))
        except:
            print("Can't parse json from websocket: ", data)

        if data_json is not None:
            # r = process_chunk(rec,data,"saytxt,saywav")
            r = sendSimpleTxtCmd(data_json.get("txt",""), data_json.get("returnFormat", "none"))
            await websocket.send_text(str(r))


@app.websocket("/wsmic")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if model != None:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(model, 48000)
        print("New WebSocket microphone recognition")
        while True:
            data = await websocket.receive_bytes()
            r = process_chunk(rec,data,"saytxt,saywav")
            await websocket.send_text(r)
    else:
        print("Can't accept WebSocket microphone recognition - no Model (seems to be no VOSK at startup)")

@app.websocket("/wsmic_48000_none")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if model != None:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(model, 48000)
        print("New WebSocket microphone recognition wsmic_48000_none")
        while True:
            data = await websocket.receive_bytes()
            r = process_chunk(rec,data,"none")
            await websocket.send_text(r)
    else:
        print("Can't accept WebSocket microphone recognition - no Model (seems to be no VOSK at startup)")

@app.websocket("/wsmic_22050_none")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if model != None:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(model, 22050)
        print("New WebSocket microphone recognition wsmic_22050_none")
        while True:
            data = await websocket.receive_bytes()
            r = process_chunk(rec,data,"none")
            await websocket.send_text(r)
    else:
        print("Can't accept WebSocket microphone recognition - no Model (seems to be no VOSK at startup)")

@app.websocket("/wsmic_44100_none")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if model != None:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(model, 44100)
        print("New WebSocket microphone recognition wsmic_44100_none")
        while True:
            data = await websocket.receive_bytes()
            r = process_chunk(rec,data,"none")
            await websocket.send_text(r)
    else:
        print("Can't accept WebSocket microphone recognition - no Model (seems to be no VOSK at startup)")


def process_chunk(rec,message,returnFormat):
    # with open('temp/asr_server_test.wav', 'wb') as the_file:
    #     the_file.write(message)

    if message == '{"eof" : 1}':
        return rec.FinalResult()
    elif rec.AcceptWaveform(message):
        res2 = "{}"
        res = rec.Result()
        #print("Result:",res)
        resj = json.loads(res)
        if "text" in resj:
            voice_input_str = resj["text"]
            #print(restext)
            import requests

            if voice_input_str != "" and voice_input_str != None:
                print(voice_input_str)
                #ttsFormatList = ["saytxt"]
                #res2 = sendRawTxtOrig(voice_input_str,"none,saytxt")
                res2 = sendRawTxtOrig(voice_input_str, returnFormat)
                # saywav not supported due to bytes serialization???


                if res2 != "NO_VA_NAME":
                    res3:dict = res2
                    if res3.get("wav_base64") is not None: # converting bytes to str
                        res3["wav_base64"] = res2["wav_base64"].decode("utf-8")
                    res2 = json.dumps(res3)
                else:
                    res2 = "{}"

        else:
            #print("2",rec.PartialResult())
            pass

        return res2
    else:
        res = rec.PartialResult()
        #print("Part Result:",res)
        return rec.PartialResult()


@app.get("/", response_class=HTMLResponse)
async def main_page():
    from vacore import version
    html_content = f"""
    <html>
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>Irene Voice Assistant</title>
            <link rel="stylesheet" href="/webapi_client/chota.min.css">
        </head>
        <body>
            <div id="top" class="container" role="document">
                <h1>Irene Voice Assistant {version}</h1>

                <a href="/webapi_client" class="button">Web interface (simple, STT in browser)</a><br /><br />
                
                <a href="/mic_client" class="button">Web interface (simple, only microphone listen)</a><br /><br />

                <a href="/docs" class="button">API and docs</a><br /><br />

                <a href="https://github.com/janvarev/Irene-Voice-Assistant" class="button" target="_blank">Github</a><br /><br />
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


@app.on_event("startup")
async def startup_event():
    global core
    core = VACore()
    core.fastApiApp = app
    core.init_with_plugins()

    from vacore import version

    print(f"WEB api for VoiceAssistantCore {version} (remote control)")

    url = ""
    if webapi_options["use_ssl"]:
        url = "https://{0}:{1}/".format("localhost",webapi_options["port"])
    else:
        url = "http://{0}:{1}/".format("localhost",webapi_options["port"])

    print("Web client URL (main page): ", url )
    print("Web client URL (VOSK in browser): ", url+"webapi_client/")
    print("Mic client URL (experimental, sends WAV bytes to server): ", url+"mic_client/")

    try:
        import vosk
        from vosk import Model, SpkModel, KaldiRecognizer
        global model
        model = Model("model")
    except Exception as e:
        print("Can't init VOSK - no websocket speech recognition in WEBAPI. Can be skipped")
        import traceback
        traceback.print_exc()





# рендерит текст в wav
@app.get("/ttsWav") # получение рендеренного WAV на клиенте
async def ttsWav(text:str):
    #runCmd(cmd,returnFormat)
    tmpformat = core.remoteTTS
    core.remoteTTS = "saywav"
    core.play_voice_assistant_speech(text)
    core.remoteTTS = tmpformat
    return core.remoteTTSResult

@app.get("/ttsSay") # озвучка выбранного текста на сервере
async def ttsSay(text:str):
    #runCmd(cmd,returnFormat)
    tmpformat = core.remoteTTS
    core.remoteTTS = "none"
    core.play_voice_assistant_speech(text)
    core.remoteTTS = tmpformat
    return ""


# ---------------------------------------------------------------------------
# Собственный TTS: WAV отдаётся в браузер.
#
# Готовые /ttsWav и /ttsSayWav не работают: ядро при ttsEngineId="console"
# только печатает текст и не создаёт temp/vacore_N.wav, поэтому эндпоинты
# падают с 500 (FileNotFoundError). В контейнере нет /dev/snd, звук наружу
# не вывести, поэтому синтезируем WAV и отдаём его клиенту.
# vosk-tts лёгкий: onnxruntime, без torch, модель ~116 МБ.
# ---------------------------------------------------------------------------
TTS_MODEL_DIR = os.environ.get("TTS_MODEL_DIR", "/models/tts")
_tts = {"loaded": False, "model": None, "synth": None, "err": None}


def _tts_ready():
    """Ленивая загрузка: модель ~116 МБ, грузим при первом запросе, а не на старте."""
    if _tts["loaded"]:
        return True
    if _tts["err"]:
        return False
    try:
        from vosk_tts import Model, Synth

        if not os.path.isdir(TTS_MODEL_DIR):
            _tts["err"] = "модель голоса не установлена: " + TTS_MODEL_DIR
            return False
        m = Model(model_path=TTS_MODEL_DIR)
        _tts["model"] = m
        _tts["synth"] = Synth(m)
        _tts["loaded"] = True
        return True
    except Exception as e:
        _tts["err"] = "%s: %s" % (type(e).__name__, e)
        return False


def _tts_wav_bytes(text, speaker_id=0):
    """Синтез в WAV-байты. Используется и /tts, и озвучкой будильника."""
    import io
    import wave
    import numpy as np

    if not _tts_ready():
        raise HTTPException(503, "TTS недоступен (%s)" % (_tts["err"] or "причина неизвестна"))
    try:
        # synth(text, oname) у vosk_tts пишет файл и возвращает None, поэтому
        # берём synth_audio() и собираем WAV сами — без временных файлов.
        audio = _tts["synth"].synth_audio(text, speaker_id)
    except AttributeError:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            name = tf.name
        _tts["synth"].synth(text, name, speaker_id)
        with open(name, "rb") as f:
            return f.read()

    data = np.asarray(audio)
    if np.issubdtype(data.dtype, np.floating):
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        if peak > 0:
            data = data / peak * 0.9     # тихие фразы иначе почти не слышны
        pcm = (data * 32767.0).astype("<i2")
    else:
        pcm = data.astype("<i2")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)   # жёстко зашито в vosk_tts Synth.synth
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


@app.get("/tts")
async def tts(text: str, speaker_id: int = 0):
    if not _rate_limit("tts", RL_LIMIT_TTS):
        raise HTTPException(429, "слишком много запросов синтеза, подожди минуту")
    text = (text or "").strip()
    if not text:
        raise HTTPException(400, "пустой текст")
    if len(text) > 2000:
        text = text[:2000]
    from starlette.responses import Response
    try:
        wav = _tts_wav_bytes(text, speaker_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, "синтез не удался: %s" % e)
    return Response(content=wav, media_type="audio/wav",
                    headers={"Cache-Control": "no-store"})


# Таймеры живут в памяти ядра, поэтому перезапуск контейнера их убивал:
# будильник молча исчезал, и единственный след - его не стало. Храним
# активные таймеры в томе опций и восстанавливаем при старте.
HERE_DIR = os.path.dirname(os.path.abspath(__file__))
OPTIONS_DIR = os.path.join(HERE_DIR, "options")
TIMER_STATE = os.path.join(OPTIONS_DIR, "webapi_timers.json")
# Таймер, истёкший пока контейнер лежал, поднимаем только если это свежее:
# иначе после возвращения через сутки звонок сработал бы немедленно.
RESTORE_GRACE = 3600
_timer_state_blob = [None]
_timer_restored = [False]
# ковши ограничителя: ключ (корзина, IP) -> (запросов, время окна)
_rl = {}
_rl_lock = threading.Lock()
# лимиты в запросов в минуту на IP; 0 отключает ограничение
RL_LIMIT_CMD = int(os.environ.get("JANE_RL_CMD", "30") or 30)
RL_LIMIT_TTS = int(os.environ.get("JANE_RL_TTS", "60") or 60)
RL_LIMIT_STT = int(os.environ.get("JANE_RL_STT", "60") or 60)
RL_LIMIT_MUSIC = int(os.environ.get("JANE_RL_MUSIC", "20") or 20)
# Потолок веера по метаданным на один поиск: каждый документ из ответа Solr
# требует своего обращения к archive.org, и 40 запросов на один клик по
# чужому сервису - это невежливо.
META_FANOUT = int(os.environ.get("JANE_META_FANOUT", "12") or 12)
META_TTL = 3600.0
META_MAX = 400
_meta_cache = {}
# Кэш всего ответа поиска. Метаданные кэшируются по identifier, но основное
# время съедает сам запрос к advancedsearch: повтор того же поиска стоил столько
# же, сколько первый. Списком делится один и тот же текст.
SEARCH_TTL = 300.0
SEARCH_MAX = 100
_search_cache = {}


def _search_cached(key):
    hit = _search_cache.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > SEARCH_TTL:
        _search_cache.pop(key, None)
        return None
    return val


def _search_store(key, val):
    if len(_search_cache) >= SEARCH_MAX:
        for k in sorted(_search_cache, key=lambda x: _search_cache[x][0])[:40]:
            _search_cache.pop(k, None)
    _search_cache[key] = (time.time(), val)


def _meta_cached(ident):
    hit = _meta_cache.get(ident)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > META_TTL:
        _meta_cache.pop(ident, None)
        return None
    return val


def _meta_store(ident, val):
    if len(_meta_cache) >= META_MAX:
        for k in sorted(_meta_cache, key=lambda x: _meta_cache[x][0])[:100]:
            _meta_cache.pop(k, None)
    _meta_cache[ident] = (time.time(), val)


def _persist_timers():
    """Пишем только при изменении: иначе диск пишется каждые две секунды."""
    try:
        slots = list(getattr(core, "timers", []) or [])
        durs = list(getattr(core, "timersDuration", []) or [])
        active = []
        for i, end in enumerate(slots):
            if end and end > 0:
                d = int(durs[i]) if i < len(durs) and durs[i] else 0
                active.append({"i": i, "at": int(end), "total": d})
        blob = json.dumps({"saved": int(time.time()), "active": active})
        if blob != _timer_state_blob[0]:
            with open(TIMER_STATE, "w", encoding="utf-8") as f:
                f.write(blob)
            _timer_state_blob[0] = blob
    except Exception:
        pass


def _restore_timers():
    """Возвращает таймеры, пережившие перезапуск. Вызывается один раз."""
    if _timer_restored[0]:
        return 0
    _timer_restored[0] = True
    try:
        with open(TIMER_STATE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0
    now = time.time()
    try:
        slots = list(getattr(core, "timers", []) or [])
        durs = list(getattr(core, "timersDuration", []) or [])
    except Exception:
        return 0
    while len(slots) < 8:
        slots.append(0)
    while len(durs) < 8:
        durs.append(0)
    n = 0
    for item in data.get("active") or []:
        try:
            i, at = int(item.get("i", -1)), int(item.get("at", 0))
        except Exception:
            continue
        if not (0 <= i < len(slots)) or at <= 0:
            continue
        if at + RESTORE_GRACE < now:
            continue          # протух, пока лежали - молчаливый звонок
        slots[i] = at
        if item.get("total"):
            durs[i] = int(item["total"])
        n += 1
    if n:
        core.timers = slots
        core.timersDuration = durs
    return n


def _rate_limit(bucket, limit):
    """Простейший ковш токенов по IP. Возвращает True, если запрос прошёл.

    Зачем при живом приложении: API колонки открыт в интернет, и без
    ограничения любой может вызывать sendTxtCmd и жечь LLM-кредиты из
    core.json, а /tts и /stt нагружать процессор. Секрет во фронтенде от
    этого не спасает - он виден в исходнике страницы, поэтому ограничиваем
    ущерб, а не прячем функциональность.
    """
    try:
        client = request.client.host if request else "-"
    except Exception:
        client = "-"
    key = (bucket, client)
    try:
        limit = int(limit)
    except Exception:
        limit = 0
    if limit <= 0:
        return True
    now = time.time()
    with _rl_lock:
        n, t0 = _rl.get(key, (0, now))
        if now - t0 >= 60.0:
            n, t0 = 0, now
        n += 1
        _rl[key] = (n, t0)
    return n <= limit



# ---------------------------------------------------------------------------
# Будильники на время суток.
#
# Таймер из плагина умеет только относительное «на N минут», а это даже не у
# каждой колонки: будильник на семь утра - базовая вещь. Разбор фраз живёт в
# jane_time, чтобы его можно было проверять без контейнера.
#
# Своё хранилище, а не core.timers: там слоты живут минуты и ядро гасит их
# самим. Будильник на утро должен пережить перезапуск, поэтому он лежит в томе
# опций рядом с таймерами.
# ---------------------------------------------------------------------------
ALARM_STATE = os.path.join(OPTIONS_DIR, "webapi_alarms.json")
_alarms = []
_alarm_seq = [0]

try:
    from jane_time import parse_alarm_phrase as _parse_alarm_phrase
except ImportError:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from jane_time import parse_alarm_phrase as _parse_alarm_phrase


def _alarms_save():
    try:
        blob = json.dumps({"alarms": _alarms}, ensure_ascii=False)
        tmp = ALARM_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(blob)
        os.replace(tmp, ALARM_STATE)
    except Exception as e:
        print("alarms save failed: %s: %s" % (type(e).__name__, e), flush=True)


def _alarms_load():
    global _alarms
    try:
        with open(ALARM_STATE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _alarms = data.get("alarms") or []
        for a in _alarms:
            try:
                _alarm_seq[0] = max(_alarm_seq[0], int(a.get("id", 0)))
            except Exception:
                pass
    except Exception:
        _alarms = []


def _alarms_public():
    now = time.time()
    out = []
    for a in _alarms:
        try:
            left = int(float(a.get("at", 0)) - now)
        except Exception:
            continue
        out.append({"id": a.get("id"), "at": int(float(a.get("at", 0))),
                    "label": a.get("label"), "repeat": a.get("repeat"),
                    "left": left})
    return sorted(out, key=lambda x: x["at"])


def _alarm_set(phrase):
    got = _parse_alarm_phrase(phrase)
    if not got:
        return None
    at, label, repeat = got
    _alarm_seq[0] += 1
    _alarms.append({"id": _alarm_seq[0], "at": at, "label": label,
                    "repeat": repeat, "fired": 0})
    _alarms_save()
    rep = {"daily": " каждый день", "weekdays": " по будням",
           "weekend": " по выходным", "weekly": " еженедельно"}.get(repeat, "")
    return ("Будильник на %s%s." % (label, rep),
            "Будильник на %s%s" % (label, rep))


def _alarm_cancel(phrase):
    # Все ветки возвращают кортеж (текст, действие). Одна ветка отдавала
    # голую строку, и распаковка падала: «отмени будильник» давал 500.
    p = (phrase or "").lower().replace("ё", "е")
    if not _alarms:
        return "Будильник не задан.", None
    # «отмени будильник» без времени - весь будильник сразу
    if not any(ch.isdigit() for ch in p):
        n = len(_alarms)
        del _alarms[:]
        _alarms_save()
        return ("Отменила все будильники, их было %d." % n, None)
    for i in range(len(_alarms) - 1, -1, -1):
        lab = str(_alarms[i].get("label") or "")
        for part in lab.split(":"):
            if part and part in p:
                a = _alarms.pop(i)
                _alarms_save()
                return ("Будильник на %s отменён." % lab, None)
    return "Не нашла будильник на это время.", None


def _alarms_check():
    """Проверяет будильники и поднимает счётчик звонков.

    Повторяющийся будильник не тратится, а переносится на следующий день: он
    для того и повторяющийся. Просроченный разовый - тоже: иначе после
    возвращения через сутки колонка звонила бы немедленно, и не один раз.
    """
    global _alarms
    now = time.time()
    fired = []
    keep = []
    for a in _alarms:
        at = float(a.get("at", 0) or 0)
        if at > now:
            keep.append(a)
            continue
        fired.append(a)
        if a.get("repeat"):
            nxt = at + 86400
            while nxt <= now:
                nxt += 86400
            a["at"] = nxt
            a["fired"] = int(a.get("fired", 0)) + 1
            keep.append(a)
    if fired:
        _alarms = keep
        _alarms_save()
        _fired_count[0] += len(fired)
        _fired_last[0] = int(now)
        for a in fired:
            print("alarm fired: id=%s label=%s repeat=%s"
                  % (a.get("id"), a.get("label"), a.get("repeat")), flush=True)
    return len(fired)


@app.get("/alarms")
async def alarms():
    _alarms_load()
    return {"alarms": _alarms_public(), "count": len(_alarms)}



@app.get("/audioHealth")
def audioHealth():
    """Что колонка может проигрывать и что нужно, чтобы проигрывала.

    Сделано для переноса на Raspberry Pi: там есть карта и aplay, здесь
    сервер без звука и всё играет браузер. Разница видна только на словах,
    поэтому состояние спрашивается явно и с конкретной причиной, а не
    «звук работает».
    """
    import shutil
    import subprocess

    out = {"backend": "browser", "playWavEngineId": None, "alsa": {},
           "tts": {}, "available_engines": [], "recommendation": None}

    try:
        opt = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "options", "core.json")
        with open(opt, "r", encoding="utf-8") as f:
            out["playWavEngineId"] = json.load(f).get("playWavEngineId")
    except Exception as e:
        out["options_error"] = "%s: %s" % (type(e).__name__, e)

    def probe(cmd):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            return (p.stdout or p.stderr or "").strip()
        except Exception as e:
            return "%s: %s" % (type(e).__name__, e)

    aplay = shutil.which("aplay")
    out["alsa"] = {
        "dev_snd": os.path.isdir("/dev/snd"),
        "aplay": aplay or None,
        "arecord": shutil.which("arecord") or None,
    }
    if aplay:
        out["alsa"]["cards"] = probe([aplay, "-l"]).splitlines()[:6]
        if out["alsa"]["arecord"]:
            out["alsa"]["capture"] = probe(["arecord", "-l"]).splitlines()[:6]

    # Движок считается доступным, если есть его файл и та утилита, без
    # которой он не заработает. Импортом проверять нельзя: плагины лежат в
    # соседнем каталоге и не обязаны быть в sys.path, и проверка врала бы.
    here = os.path.dirname(os.path.abspath(__file__))
    need = {"aplay": "aplay", "consolewav": None, "simpleaudio": None,
            "sounddevice": None}
    for name, tool in need.items():
        f = os.path.join(here, "plugins", "plugin_playwav_%s.py" % name)
        if not os.path.isfile(f):
            continue
        if tool and not shutil.which(tool):
            continue
        out["available_engines"].append(name)

    out["tts"] = {
        "engine": "vosk", "rate": 22050, "channels": 1, "sample_width": 2,
        "format": "s16le", "ready": _tts["loaded"], "error": _tts["err"],
        "aplay_args": ["-q", "-f", "S16_LE", "-c", "1", "-r", "22050"],
    }

    if out["alsa"]["dev_snd"] and aplay:
        out["backend"] = "local"
        out["recommendation"] = ("ALSA есть: можно играть локально, "
                                 "поставь playWavEngineId=aplay")
    else:
        missing = []
        if not out["alsa"]["dev_snd"]:
            missing.append("нет /dev/snd")
        if not aplay:
            missing.append("не установлен alsa-utils (aplay)")
        out["recommendation"] = "звук играет браузер"
        if missing:
            out["recommendation"] += "; для локального звука: " + ", ".join(missing)
    return out


@app.get("/ttsHealth")
async def ttsHealth():
    return {"ready": _tts["loaded"], "model": TTS_MODEL_DIR,
            "error": _tts["err"],
            "present": os.path.isdir(TTS_MODEL_DIR)}


# ---------------------------------------------------------------------------
# Распознавание речи на сервере (vosk).
#
# Раньше микрофон работал только через браузерный SpeechRecognition: он есть
# лишь в Chrome/Safari, требует сеть до серверов Google и открытой страницы.
# Vosk работает локально, поэтому колонка понимает голос в любом браузере.
# Проверено сквозным циклом TTS -> WAV -> STT: 4 фразы из 4 распознаны точно.
# ---------------------------------------------------------------------------
STT_MODEL_DIR = os.environ.get("STT_MODEL_DIR", "/models/stt")
_stt = {"loaded": False, "model": None, "err": None}
# Модель vosk не потокобезопасна, а в постоянном режиме окна распознавания
# приходят одно за другим - без замка они бы наезжали друг на друга.
_stt_lock = threading.Lock()
STT_MAX_BYTES = 12 * 1024 * 1024   # 12 МБ, больше нечего принимать


def _recognize_wav(data, rate):
    """Синхронное распознавание. Запускается в пуле потоков, иначе vosk
    занимает event loop и весь сервер подтормаживает на время распознавания
    (замер: /plugins отвечал 91 мс вместо единиц)."""
    from vosk import KaldiRecognizer
    import json as _json

    with _stt_lock:
        rec = KaldiRecognizer(_stt["model"], rate)
        rec.SetWords(True)
        parts = []
        step = 4000
        for i in range(0, len(data), step):
            if rec.AcceptWaveform(data[i:i + step]):
                txt = _json.loads(rec.Result()).get("text", "")
                if txt:
                    parts.append(txt)
        txt = _json.loads(rec.FinalResult()).get("text", "")
        if txt:
            parts.append(txt)
    return " ".join(parts).strip()


def _stt_ready():
    if _stt["loaded"]:
        return True
    if _stt["err"]:
        return False
    try:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        if not os.path.isdir(STT_MODEL_DIR):
            _stt["err"] = "модель распознавания не установлена: " + STT_MODEL_DIR
            return False
        _stt["model"] = Model(STT_MODEL_DIR)
        _stt["loaded"] = True
        return True
    except Exception as e:
        _stt["err"] = "%s: %s" % (type(e).__name__, e)
        return False


@app.post("/stt")
async def stt(request: Request):
    if not _rate_limit("stt", RL_LIMIT_STT):
        raise HTTPException(429, "слишком много запросов распознавания, подожди минуту")
    body = await request.body()
    if not body:
        raise HTTPException(400, "пустой аудиопоток")
    if len(body) > STT_MAX_BYTES:
        raise HTTPException(413, "аудио больше %d МБ" % (STT_MAX_BYTES // 1024 // 1024))
    if not _stt_ready():
        raise HTTPException(503, "распознавание недоступно (%s)"
                            % (_stt["err"] or "причина неизвестна"))
    try:
        import io
        import wave
        from starlette.concurrency import run_in_threadpool

        with wave.open(io.BytesIO(body), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError("нужен моно PCM 16 бит")
            rate = w.getframerate()
            data = w.readframes(w.getnframes())
    except Exception as e:
        raise HTTPException(400, "не читается WAV: %s" % e)

    if not data:
        raise HTTPException(400, "в WAV нет сэмплов")

    try:
        text = await run_in_threadpool(_recognize_wav, data, rate)
    except Exception as e:
        raise HTTPException(500, "распознавание не удалось: %s" % e)

    return {"text": text,
            "seconds": round(len(data) / 2 / float(rate or 16000), 2),
            "rate": rate}


@app.get("/sttHealth")
async def sttHealth():
    return {"ready": _stt["loaded"], "model": STT_MODEL_DIR,
            "error": _stt["err"], "present": os.path.isdir(STT_MODEL_DIR)}


# ---------------------------------------------------------------------------
# Канал устройства: непрерывный поток аудио на вход, текст и звук на выход.
#
# Зачем он, если есть /stt: браузер присылает нарезки по кнопке, а колонка
# должна слушать всегда. Плата (а позже и ESP32) держит одно соединение и
# шлёт куски PCM, сервер сам понимает, где человек закончил говорить, и
# отвечает голосом. Никакой кнопки и никакой вкладки.
#
# Первым кадром плата обязана прислать hello с частотой: {"type":"hello",
# "rate":16000,"wake":"дженет"}. Ключ wake необязателен - без него колонка
# отвечает на любую речь, как и сейчас в браузере.
# ---------------------------------------------------------------------------
STT_RATE = 16000
# Логика пересчёта частоты и детекции конца фразы живёт в jane_audio:
# там только numpy, поэтому её можно проверять без контейнера, без сети и
# без модели. Копия здесь была бы второй версией одного и того же, и
# проверялся бы не тот код, который работает в колонке.
try:
    from jane_audio import (pcm_resample as _pcm_resample,
                            frame_rms_peak as _rms_peak,
                            SpeechGate as _SpeechGate,
                            VAD_FRAME as DEV_VAD_FRAME,
                            VAD_HANGOVER as DEV_VAD_HANGOVER,
                            VAD_MAX_FRAMES as DEV_VAD_MAX_FRAMES)
except ImportError:  # путь колонки не всегда в sys.path
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from jane_audio import (pcm_resample as _pcm_resample,
                            frame_rms_peak as _rms_peak,
                            SpeechGate as _SpeechGate,
                            VAD_FRAME as DEV_VAD_FRAME,
                            VAD_HANGOVER as DEV_VAD_HANGOVER,
                            VAD_MAX_FRAMES as DEV_VAD_MAX_FRAMES)
DEV_WAKE_DEFAULT = "дженет"

_dev_clients = {}
_dev_seq = [0]
# на сколько ушли звонки будильника: счётчик растёт, а отправлять надо один раз
_fired_sent = [0]


def _wake_ok(text, wake):
    """Снимает будильниковое слово. Пустое будильниковое слово означает
    «реагировать на всё»."""
    t = (text or "").strip().lower()
    if not wake:
        return True, text or ""
    for w in (wake if isinstance(wake, list) else [wake]):
        w = (w or "").strip().lower()
        if w and t.startswith(w):
            return True, t[len(w):].strip()
    return False, text or ""


@app.get("/wsDevices")
async def wsDevices():
    """Кто подключён. Плата полезна тем же, что и страница: видно, что
    канал жив, даже если вкладки нет."""
    return {"devices": [{"id": k, "rate": v.get("rate"),
                         "wake": v.get("wake"), "since": v.get("since")}
                        for k, v in _dev_clients.items()],
            "count": len(_dev_clients)}


@app.websocket("/ws/device")
async def ws_device(ws: WebSocket):
    await ws.accept()
    _dev_seq[0] += 1
    dev_id = _dev_seq[0]
    rate = STT_RATE
    wake = DEV_WAKE_DEFAULT
    gate = None
    try:
        await ws.send_text(json.dumps({
            "type": "ready", "stt": _stt["loaded"], "tts": _tts["loaded"],
            "id": dev_id, "want_rate": STT_RATE}))
        stt_ok = _stt_ready()
        print("device ws %d: ready отправлен, stt_ready=%s loaded=%s err=%s"
              % (dev_id, stt_ok, _stt["loaded"], _stt["err"]), flush=True)
        if not stt_ok:
            await ws.send_text(json.dumps(
                {"type": "error", "message": "распознавание не загружено"}))
            print("device ws %d: выход - stt не готов" % dev_id, flush=True)
            return

        while True:
            msg = await ws.receive()
            kind = msg.get("type")
            if kind == "websocket.disconnect":
                print("device ws %d: клиент отключился" % dev_id, flush=True)
                break
            if kind == "websocket.connect":
                continue
            data = msg.get("bytes")
            if kind == "websocket.receive" and data:
                if gate is None:
                    await ws.send_text(json.dumps(
                        {"type": "error", "message": "сначала пришли hello"}))
                    continue
                pcm = _pcm_resample(data, rate, STT_RATE)
                if not gate.push(pcm):
                    continue
                segment = gate.take()
                if not segment:
                    continue
                text = await run_in_threadpool(_recognize_wav, segment, STT_RATE)
                if not text:
                    continue
                ok, cmd = _wake_ok(text, wake)
                await ws.send_text(json.dumps(
                    {"type": "heard", "text": text, "wake": ok, "loud": True}))
                if not ok or not cmd:
                    continue
                reply, source, action = await run_in_threadpool(
                    _answer_text, cmd)
                await ws.send_text(json.dumps(
                    {"type": "text", "text": reply, "source": source,
                     "action": action, "heard": cmd}))
                try:
                    wav = await run_in_threadpool(_tts_wav_bytes, reply)
                    await ws.send_bytes(wav)
                except Exception as e:
                    await ws.send_text(json.dumps(
                        {"type": "error", "message": "нет голоса: %s" % e}))
                continue

            if kind == "websocket.receive" and msg.get("text"):
                raw = (msg.get("text") or "").strip()
                try:
                    hello = json.loads(raw)
                except Exception:
                    await ws.send_text(json.dumps(
                        {"type": "error", "message": "hello должен быть json"}))
                    continue
                t = hello.get("type")
                if t == "hello":
                    try:
                        rate = max(8000, min(int(hello.get("rate") or STT_RATE), 48000))
                    except Exception:
                        rate = STT_RATE
                    wake = hello.get("wake", DEV_WAKE_DEFAULT)
                    gate = _SpeechGate()
                    _dev_clients[dev_id] = {"ws": ws, "rate": rate,
                                            "wake": wake,
                                            "since": int(time.time())}
                    await ws.send_text(json.dumps({
                        "type": "hello-ok", "id": dev_id, "want_rate": STT_RATE,
                        "frame": DEV_VAD_FRAME * 2}))
                elif t == "bye":
                    break
                else:
                    await ws.send_text(json.dumps(
                        {"type": "error", "message": "неизвестный тип: %s" % t}))
    except Exception as e:
        # Раньше тут стоял пустой pass, и канал молча закрывался сразу после
        # ready: ошибка была не видна нигде, и выглядело это как поломка
        # nginx, хотя рукопожатие проходило.
        print("device ws error: %s: %s" % (type(e).__name__, e), flush=True)
    finally:
        _dev_clients.pop(dev_id, None)


# ---------------------------------------------------------------------------
# Плеер: список своих файлов и отдача их потоком.
# В контейнере нет /dev/snd, звук играет браузер, поэтому сервер отдаёт файл,
# а управление (громче/тише/вперёд/назад) приходит командами ассистента.
# ---------------------------------------------------------------------------
MUSIC_DIR = os.environ.get("MUSIC_DIR", "/music")
# Только то, что браузер действительно играет. Раньше сюда попадали .flac,
# .wav и .wma: файл показывался в плейлисте, а <audio> молча отказывался его
# воспроизводить - трек выглядел рабочим и не звучал.
MUSIC_EXT = (".mp3", ".m4a", ".aac", ".ogg", ".opus")
# Прочие аудиоформаты показываем отдельным списком: не отдаём, но и не
# прячем, чтобы пользователь понял, почему файл не в плейлисте.
MUSIC_SKIP_EXT = (".flac", ".wav", ".wma", ".aiff", ".m4b")
# имя не должно вылезать за пределы папки
MUSIC_NAME_RE = re.compile(r"^[^/\\]{1,180}$")
# снимок активных таймеров: чтобы отличить «истёк» от «его не было»
_timer_seen = {}
# ядро не заполняет timersDuration, поэтому длительность помним сами
_timer_total = {}
# счётчик срабатываний: клиент присылает, сколько уже видел, поэтому
# пропущенный звонок не теряется при закрытой вкладке
_fired_count = [0]
_fired_last = [0]


def _list_music():
    out = []
    skipped = []
    try:
        for n in sorted(os.listdir(MUSIC_DIR)):
            low = n.lower()
            if low.startswith("."):
                continue
            if low.endswith(MUSIC_SKIP_EXT):
                skipped.append(n)
                continue
            if not low.endswith(MUSIC_EXT):
                continue
            try:
                size = os.path.getsize(os.path.join(MUSIC_DIR, n))
            except OSError:
                continue
            out.append({"name": n, "size": size,
                        "title": os.path.splitext(n)[0].replace("_", " ")})
    except Exception as e:
        return {"error": str(e), "tracks": [], "skipped": []}
    return {"tracks": out, "count": len(out), "dir": MUSIC_DIR,
            "skipped": skipped, "skipped_count": len(skipped)}


_RU_NUM = {
    "одна": 1, "один": 1, "одну": 1, "одного": 1, "одной": 1,
    "две": 2, "два": 2, "двенадцать": 12,
    "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7,
    "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11,
    "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    "сто": 100, "полтора": 1.5, "пару": 2,
}
_UNIT_SEC = ("секунд", "секунда", "секунду", "секунды", "секундочек", "сек")
_UNIT_MIN = ("минут", "минута", "минуту", "минуты", "мин")
_UNIT_HOUR = ("час", "часа", "часов", "ч")


def _parse_ru_number(word):
    w = (word or "").strip().lower().replace("ё", "е")
    if w.isdigit():
        return int(w)
    if w in _RU_NUM:
        return _RU_NUM[w]
    # составные: "двадцать пять", "двадцать5" склеим по словам
    parts = w.split()
    if len(parts) == 2 and parts[0] in _RU_NUM and parts[1] in _RU_NUM:
        base = _RU_NUM[parts[0]]
        tail = _RU_NUM[parts[1]]
        if base % 10 == 0 and 1 <= tail <= 9:
            return base + tail
    return None


def _flat(v):
    """Archive отдаёт creator списком или строкой - приводим к строке."""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v[:2])
    return str(v or "")


def _parse_duration(text):
    """Секунды из фразы: "на 5 минут", "через 30 секунд", "1 минуту 30 секунд".

    Число ищем самое длинное ("двадцать пять", а не "пять") и все единицы
    складываем ("1 минуту 30 секунд" = 90).
    """
    toks = re.findall(r"[\w]+", (text or "").lower().replace("ё", "е"))
    total = 0
    found = False
    for i, t in enumerate(toks):
        if t in _UNIT_SEC:
            mult = 1
        elif t in _UNIT_MIN:
            mult = 60
        elif t in _UNIT_HOUR:
            mult = 3600
        else:
            continue
        num = None
        for back in (3, 2, 1):
            if i - back < 0:
                continue
            nums = [_parse_ru_number(c) for c in toks[i - back:i]]
            if not nums or any(n is None for n in nums):
                continue
            if len(nums) == 1:
                num = nums[0]
            else:
                base, tail = nums[0], nums[1:]
                if all(base % 10 == 0 and 1 <= n <= 9 for n in tail):
                    num = base + sum(tail)
            if num:
                break
        if num and num > 0:
            total += int(num) * mult
            found = True
    return total if found and total > 0 else None


def _check_fired():
    """Ловит момент срабатывания таймера.

    Важно: это д��лжно происходить на серверном цикле, а не в опросе
    клиента. Ядро гасит слот сам - по своему циклу раз в 2 секунды. Если
    переход «был активен -> стал пуст» наблюдать только при обращении
    клиента, то звонок, случившийся при закрытой вкладке, не отмечался
    вовсе: между срабатыванием и следующим запросом состояние уже
    «неактивно» и сравнивать не с чем. Счётчик рос через раз.
    """
    try:
        slots = list(getattr(core, "timers", []) or [])
    except Exception:
        return
    for i, end in enumerate(slots):
        was = _timer_seen.get(i)
        if was and (not end or end <= 0):
            _fired_count[0] += 1
            _fired_last[0] = int(time.time())
    _timer_seen.clear()
    _timer_total.clear()
    for i, end in enumerate(slots):
        if end and end > 0:
            _timer_seen[i] = end


@app.get("/timers")
async def timers(seen: int = 0):
    """Активные таймеры и звонки, которые клиент ещё не видел.

    Звонок считается «просмотренным» по номеру: клиент хранит у себя
    последний обработанный номер. Так пропущенный звонок переживает
    закрытую вкладку - сервер помнит счётчик, а не последний запрос.
    """
    now = time.time()
    active = []
    try:
        slots = list(getattr(core, "timers", []) or [])
    except Exception:
        slots = []
    for i, end in enumerate(slots):
        if end and end > 0:
            dur = 0
            try:
                dur = int((getattr(core, "timersDuration", []) or [0] * 8)[i] or 0)
            except Exception:
                dur = 0
            active.append({"id": i, "left": int(end - now),
                           "total": dur or int(_timer_total.get(i, 0))})

    # звонок засчитывает серверный цикл, но проверяем и здесь: если слот
    # погас между тиками, покажем это текущему клиенту сразу
    _check_fired()
    for i, end in enumerate(list(getattr(core, "timers", []) or [])):
        if end and end > 0:
            try:
                dur = int((getattr(core, "timersDuration", []) or [0] * 8)[i] or 0)
            except Exception:
                dur = 0
            _timer_total.setdefault(i, dur)

    missed = []
    if int(seen or 0) < _fired_count[0]:
        missed = [{"n": _fired_count[0], "at": _fired_last[0]}]

    return {"active": active, "missed": missed, "fired": missed,
            "fired_count": _fired_count[0], "now": int(now)}


@app.get("/timerwav")
async def timerwav():
    """Звонок будильника: отдаём wav, который проиграет браузер."""
    path = "/app/vendor/irene-va/media/timer.wav"
    if not os.path.isfile(path):
        raise HTTPException(404, "нет файла звонка: %s" % path)
    return FileResponse(path, media_type="audio/wav",
                        headers={"Accept-Ranges": "bytes"})


@app.get("/music/search")
async def music_search(q: str = "", source: str = "archive", limit: int = 12):
    # Поиск ходит на archive.org и iTunes. Без ограничения через открытый
    # API можно было бы положить и чужой сервис, и процессор.
    """Поиск музыки в бесплатных источниках без ключей.

    Spotify, Yandex Music и SoundCloud бесплатного открытого API для
    потоковой передачи не имеют: то, что гуглится как «API», это
    реверс-инжиниринг приватных эндпоинтов, он нарушает условия сервисов и
    ломается на каждом их обновлении. Поэтому используем честные источники.

    Internet Archive - полные треки, mp3/ogg, без ключа.
    iTunes Search API - превью 30 секунд, без ключа.
    Поиск идёт с сервера: браузеру не нужен CORS, а главное - мы отсекаем
    .flac, который в браузере не играет.
    """
    q = (q or "").strip()
    if len(q) < 2:
        raise HTTPException(400, "запрос слишком короткий")
    limit = max(1, min(int(limit or 12), 25))
    # Лимит после проверки запроса: пустые и заведомо ошибочные обращения
    # не должны расходовать ковш.
    if not _rate_limit("music", RL_LIMIT_MUSIC):
        raise HTTPException(429, "слишком много поисков, подожди минуту")
    key = (source, q.lower(), limit)
    cached = _search_cached(key)
    if cached is not None:
        out = dict(cached)
        out["cached"] = True
        return out
    ses = _ollama_session          # переиспользуем сессию с повторами

    def _get(url, params=None, timeout=12):
        try:
            r = ses.get(url, params=params, timeout=timeout,
                        headers={"User-Agent": "kolonka/1.0"})
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    out = []
    scanned_info = {}
    if source == "itunes":
        d = _get("https://itunes.apple.com/search",
                 {"term": q, "media": "music", "limit": limit})
        for r in ((d or {}).get("results") or []):
            url = r.get("previewUrl")
            if not url:
                continue
            out.append({
                "title": r.get("trackName") or r.get("collectionName") or "",
                "artist": r.get("artistName", ""),
                "url": url, "kind": "preview",
                "note": "превью 30 секунд",
            })
    else:
        # Минимальный запрос: только identifier. Раньше добавлял fl[]=title и
        # sort[]=downloads, и Solr возвращал numFound, но у документов
        # identifier был null - поля отдавались пустыми. Название и автор
        # берём из метаданных, которые всё равно запрашиваем.
        d = _get("https://archive.org/advancedsearch.php", {
            "q": 'mediatype:audio AND collection:audio_music AND (%s)' % q,
            "fl[]": "identifier", "rows": limit * 4, "output": "json"})
        scanned = 0
        skipped = 0
        # Веер по метаданным ограничен: на каждый документ из ответа Solr
        # уходит свой запрос на archive.org, а документов бывает limit*4.
        # Без потолка один поиск означал десятки обращений к чужому сервису.
        # Метаданные забираем пачкой параллельно: по одному archive.org
        # отвечает по полторы-две секунды, и последовательный обход двенадцати
        # документов растягивал поиск на 20-30 секунд.
        docs = [x for x in ((d or {}).get("response", {}).get("docs") or [])
                if x.get("identifier")]
        scanned = len(docs)
        docs = docs[:max(limit * 4, META_FANOUT)]

        fresh = []
        need = []
        for doc in docs:
            ident = doc["identifier"]
            hit = _meta_cached(ident)
            if hit is not None:
                fresh.append((doc, hit))
            else:
                need.append(ident)
        need = need[:META_FANOUT]
        if need:
            def grab(ident):
                return ident, _get("https://archive.org/metadata/" + ident,
                                   timeout=10)
            try:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=6) as ex:
                    for ident, meta in ex.map(grab, need):
                        _meta_store(ident, meta)
                        fresh.append(({"identifier": ident}, meta))
            except Exception:
                for ident in need:
                    meta = _get("https://archive.org/metadata/" + ident,
                                timeout=10)
                    _meta_store(ident, meta)
                    fresh.append(({"identifier": ident}, meta))

        for doc, meta in fresh:
            if len(out) >= limit:
                break
            ident = doc.get("identifier")
            if not meta:
                skipped += 1
                continue
            files = meta.get("files") or []
            # .flac браузер не играет, поэтому только mp3/ogg/m4a.
            # Поле size у mp3 часто отсутствует, поэтому на него не опираемся:
            # требование size > N отсекало вообще всё и поиск был пуст.
            playable = [f for f in files
                        if str(f.get("name", "")).lower().endswith(
                            (".mp3", ".ogg", ".m4a"))]
            if not playable:
                skipped += 1
                continue
            # сперва крупные (обычно полная версия), при равенстве - mp3
            playable.sort(key=lambda f: -(int(f.get("size") or 0)))
            best = playable[0]
            # Путь строим как {server}{dir}/{name}, а не /download/{id}/{name}:
            # если файл лежит в подкаталоге (disc1/...), вторая форма даёт 404
            # и браузер получает HTML вместо звука. Проверено на реальном
            # треке: правильная форма отдаёт 206 с ID3, неправильная - 404.
            url = "https://%s%s/%s" % (
                meta.get("server") or "archive.org",
                meta.get("dir") or ("/download/" + ident),
                requests.utils.quote(best["name"]))
            out.append({
                "title": (meta.get("metadata") or {}).get("title") or doc.get("title") or ident,
                "artist": _flat((meta.get("metadata") or {}).get("creator")),
                "url": url, "kind": "full",
                "note": "полный трек",
            })
        scanned_info = {"scanned": scanned, "skipped": skipped,
                        "found": ((d or {}).get("response", {}) or {}).get("numFound")}

    result = {"source": source, "query": q, "count": len(out), "results": out,
              "diag": scanned_info, "cached": False}
    _search_store(key, result)
    return result


@app.get("/music")
async def music():
    return _list_music()

@app.get("/music/file")
async def music_file(name: str, request: Request):
    if not MUSIC_NAME_RE.match(name or ""):
        raise HTTPException(400, "недопустимое имя файла: %r" % name)
    path = os.path.join(MUSIC_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "нет такого файла: %s" % name)

    ext = os.path.splitext(name)[1].lower()
    if ext in MUSIC_SKIP_EXT:
        # Отказ внятнее молчания: файл в плейлисте не зазвучит, и без
        # объяснения это выглядит как поломка плеера.
        raise HTTPException(415, "браузер не играет %s - сконвертируй в mp3 "
                                   "или ogg (ffmpeg -i '%s' -b:a 192k out.mp3)"
                                   % (ext, name))
    if not ext.endswith(MUSIC_EXT):
        raise HTTPException(415, "неподдерживаемый формат: %s" % ext)
    mime = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
            ".ogg": "audio/ogg", ".opus": "audio/ogg"}.get(ext, "application/octet-stream")

    size = os.path.getsize(path)
    # <audio> просит Range, без него не работает перемотка
    rng = request.headers.get("range", "")
    m = re.match(r"bytes=(\d*)-(\d*)", rng) if rng else None
    if m:
        start = int(m.group(1)) if m.group(1) else 0
        end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            return Response(status_code=416,
                            headers={"Content-Range": "bytes */%d" % size})
        length = end - start + 1
        def chunks(fp=path, s=start, l=length):
            with open(fp, "rb") as f:
                f.seek(s)
                left = l
                while left > 0:
                    b = f.read(min(65536, left))
                    if not b:
                        break
                    left -= len(b)
                    yield b
        return StreamingResponse(chunks(), status_code=206, media_type=mime,
                                 headers={"Content-Range": "bytes %d-%d/%d" % (start, end, size),
                                          "Accept-Ranges": "bytes",
                                          "Content-Length": str(length)})

    return FileResponse(path, media_type=mime,
                        headers={"Accept-Ranges": "bytes"})


# ---------------------------------------------------------------------------
# Реальный список того, что колонка умеет.
# Раньше интерфейс показывал выдуманные пять плагинов из localStorage, что
# расходилось с сервером. Источник истины - core.plugin_commands: туда ядро
# само регистрирует команды всех загруженных плагинов.
# ---------------------------------------------------------------------------
OPTIONS_DIR = "/app/vendor/irene-va/options"
PLUGIN_NAME_RE = re.compile(r"^plugin_[a-z0-9_]{1,60}$")


def _plugin_states():
    """is_active из options. У большинства плагинов ключа нет вовсе —
    читает его только погодный, поэтому absent = None, а не False."""
    states = {}
    try:
        for n in os.listdir(OPTIONS_DIR):
            if n.startswith("plugin_") and n.endswith(".json"):
                try:
                    with open(os.path.join(OPTIONS_DIR, n), encoding="utf-8") as f:
                        states[n[:-5]] = json.load(f).get("is_active")
                except Exception:
                    states[n[:-5]] = None
    except Exception:
        pass
    return states


@app.get("/plugins")
async def plugins():
    items = []
    try:
        pc = getattr(core, "plugin_commands", {}) or {}
        for name, cmds in pc.items():
            if isinstance(cmds, dict):
                raw = [str(k) for k in cmds.keys()]
            elif isinstance(cmds, (list, tuple, set)):
                raw = [str(c) for c in cmds]
            else:
                raw = [str(cmds)]
            # в манифестах синонимы записаны одним ключом через "|"
            # ("привет|доброе утро"), для человека это нечитаемо
            keys = []
            for r in raw:
                for part in r.split("|"):
                    part = part.strip()
                    if part and part not in keys:
                        keys.append(part)
            items.append({"name": str(name), "count": len(keys),
                          "commands": keys[:24]})
    except Exception as e:
        return {"error": "не удалось прочитать plugin_commands: %s" % e,
                "plugins": [], "states": _plugin_states()}

    items.sort(key=lambda x: -x["count"])
    names = _first_assistant_name()
    return {
        "plugins": items,
        "states": _plugin_states(),
        "assistant": names,
        "total_commands": sum(i["count"] for i in items),
    }


@app.get("/plugin/toggle")
async def plugin_toggle(name: str, active: bool = True):
    # Пишущий эндпоинт: имя проверяем строго, иначе через name=../../etc/passwd
    # можно было бы записать произвольный файл в options.
    if not PLUGIN_NAME_RE.match(name or ""):
        raise HTTPException(400, "недопустимое имя плагина: %r" % name)
    path = os.path.join(OPTIONS_DIR, name + ".json")
    cfg = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            raise HTTPException(500, "не читается %s: %s" % (path, e))
    old = cfg.get("is_active")
    cfg["is_active"] = bool(active)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except Exception as e:
        raise HTTPException(500, "не записался %s: %s" % (path, e))
    # is_active читает только погодный плагин и делает это при старте,
    # поэтому без перезапуска контейнера состояние не изменится.
    return {"ok": True, "name": name, "was": old, "is_active": bool(active),
            "needsRestart": True}


# Выполняет команду ассистента через систему плагинов (VACore).
# Классические плагины (привет/время/погода/...) работают мгновенно и точно.
# LLM используется только как фоллбэк, если ни один плагин не подошёл.
def _first_assistant_name():
    try:
        names = core.voiceAssNames
        if isinstance(names, str):
            return names.split("|")[0]
        return list(names)[0]
    except Exception:
        return ""


def _with_call_name(cmd):
    """VACore требует имя ассистента первым словом: "дженет привет"."""
    cmd = (cmd or "").strip()
    if not cmd:
        return cmd
    try:
        names = core.voiceAssNames
        names = names.split("|") if isinstance(names, str) else list(names)
    except Exception:
        names = []
    first = cmd.split(" ")[0]
    if first in names:
        return cmd
    name = _first_assistant_name()
    return (name + " " + cmd) if name else cmd


def _try_plugins(cmd):
    """Возвращает текст ответа плагина или None, если плагин не сработал."""
    try:
        saved_tts = core.remoteTTS
        saved_res = core.remoteTTSResult
        core.remoteTTS = "saytxt,none"
        core.remoteTTSResult = {}
        ran = core.run_input_str(_with_call_name(cmd))
        result = (core.remoteTTSResult or {}).get("restxt", "")
        core.remoteTTS = saved_tts
        core.remoteTTSResult = saved_res
        text = str(result).strip() if result else ""
        if not ran or not text:
            return None
        # Классическая система при несовпадении команды отвечает
        # настроенным "не поняла" вместо фоллбэка в LLM - считаем это
        # отсутствием совпадения, чтобы уйти в LLM.
        not_found = str(getattr(core, "replyNoCommandFound", "") or "").strip()
        if not_found and text == not_found:
            return None
        if text.lower().startswith("извини, я не поняла"):
            return None
        return text
    except Exception:
        import traceback
        traceback.print_exc()
    return None


def _player_command(cmd):
    """Команды управления плеером. Возвращает (текст, действие) или None.

    Обрабатываются здесь, а не плагином: действие должно попасть в ответ
    структурно (поле action), чтобы интерфейс исполнил его, и срабатывать
    мгновенно, не дожидаясь подбора команды плагинами.
    Порядок важен - сначала самые длинные формулировки, иначе "следующий"
    перехватит "следующий трек".
    """
    text = (cmd or "").strip().lower().replace("ё", "е")
    # убираем имя ассистента, если его произнесли
    name = _first_assistant_name().lower()
    if name and text.startswith(name):
        text = text[len(name):].strip()

    table = [
        # (подстроки, ответ, действие)
        (("следующий трек", "следующую песню", "дальше по музыке",
          "следующий", "далее", "вперед", "вперёд", "переключи", "next"),
         "Следующий трек", "next"),
        (("предыдущий трек", "предыдущую песню", "предыдущий",
          "назад", "назад по музыке", "предыдущая", "back", "rewind"),
         "Предыдущий трек", "prev"),
        (("громче", "погромче", "добавь громкости", "прибавь звук",
          "громкость выше", "louder", "volume up"),
         "Громче", "volume_up"),
        (("тише", "потише", "убавь громкости", "уменьши звук",
          "громкость ниже", "quieter", "volume down"),
         "Тише", "volume_down"),
        (("выключи звук", "без звука", "заглуши", "mute"), "Звук выключен", "mute"),
        (("включи звук", "звук включи", "unmute"), "Звук включён", "unmute"),
        (("пауза", "подожди", "стой", "остановись", "хватит", "pause", "стоп музыку"),
         "Пауза", "pause"),
        (("следующая станция", "другая станция", "следующее радио"),
         "Следующая станция", "next"),
        (("включи музыку", "включи радио", "поставь музыку", "играй музыку",
          "включи песню", "играй", "давай музыку", "play", "музыку"),
         "Включаю", "play"),
        (("что играет", "что звучит", "что за музыка"),
         "Сейчас играет", "now_playing"),
        (("отмени таймер", "отмени будильник", "сними таймер",
          "отменить таймер", "отменить будильник", "выключи таймер"),
         "Таймер отменён", "cancel_timers"),
        (("сколько осталось", "сколько до таймера", "таймер сколько"),
         "Таймер", "timers_status"),
    ]
    for words, reply, action in table:
        if any(w in text for w in words):
            if action == "cancel_timers":
                try:
                    core.clear_timers()
                    _timer_seen.clear()
                    _timer_total.clear()
                except Exception as e:
                    return "Не смогла отменить: %s" % e, None
            return reply, action

    # таймер ставим сами: разбор чисел в плагине ненадёжен
    # ("на 2 секунды" превращалось в 2 минуты, "на 5 минут" не срабатывало)
    if re.search(r"таймер|будильник|alarm", text) and \
            re.search(r"поставь|поставить|включи|заряди|поставьте|через|через\s|постав", text):
        secs = _parse_duration(text)
        if secs and secs > 0:
            try:
                core.clear_timers()          # новый таймер заменяет старый
                slot = core.set_timer(secs, lambda *a, **k: None)
                _timer_seen.clear()
                _timer_total.clear()
                if slot is None or slot < 0:
                    return "Не получилось поставить таймер.", None
                _timer_total[slot] = secs
                return _human_duration(secs), "timer_set"
            except Exception as e:
                return "Не получилось поставить таймер: %s" % e, None
    return None


def _human_duration(secs):
    if secs < 60:
        word = "секунду" if secs == 1 else "секунды" if secs < 5 else "секунд"
        return "Поставлю таймер на %d %s" % (secs, word)
    if secs < 3600:
        m = secs // 60
        word = "минуту" if m == 1 else "минуты" if m < 5 else "минут"
        return "Поставлю таймер на %d %s" % (m, word)
    h = secs // 3600
    word = "час" if h == 1 else "часа" if h < 5 else "часов"
    return "Поставлю таймер на %d %s" % (h, word)


def _answer_text(cmd):
    """Единый путь ответа: будильник, плеер, плагины, модель.

    Будильник проверяется первым: «поставь будильник на семь утра» не должно
    уходить в модель, которая ответит что-то вроде «не могу запомнить», и тем
    более в плагин таймера, который ждёт только относительное «на N минут».

    Возвращается кортеж (текст, источник, действие).

    Единый путь нужен, чтобы канал устройства и браузер отвечали одинаково:
    пока каждый держал свою копию, правки расходились - в одном месте команда
    появлялась, в другом нет.
    """
    low = (cmd or "").lower().replace("ё", "е")
    if any(w in low for w in ("отмени будильник", "отменить будильник",
                              "отмени звонок", "отмени будильники")):
        reply, action = _alarm_cancel(low)
        return reply, "alarm", action
    got = _parse_alarm_phrase(cmd)
    if got:
        res = _alarm_set(cmd)
        if res:
            return res[0], "alarm", res[1]

    player = _player_command(cmd)
    if player is not None:
        reply, action = player
        return reply, "player", action
    plugin_answer = _try_plugins(cmd)
    if plugin_answer is not None:
        return plugin_answer, "plugin", None
    return call_ollama(cmd), "llm", None


@app.get("/sendTxtCmd")
async def sendSimpleTxtCmd(cmd:str,returnFormat:str = "saytxt"):
    if not _rate_limit("cmd", RL_LIMIT_CMD):
        raise HTTPException(429, "слишком много команд, подожди минуту")
    reply, source, action = await run_in_threadpool(_answer_text, cmd)
    return {"restxt": reply, "source": source, "action": action}

# Streaming endpoint: returns thinking + response as Server-Sent Events
@app.get("/sendTxtCmdStream")
async def sendSimpleTxtCmdStream(cmd:str, model:str = "qwen2.5:0.5b-instruct"):
    from starlette.responses import StreamingResponse
    import asyncio

    if not _rate_limit("cmd", RL_LIMIT_CMD):
        raise HTTPException(429, "слишком много команд, подожди минуту")

    async def event_generator():
        # Плеер: действие возвращаем структурно, интерфейс его выполнит
        player = _player_command(cmd)
        if player is not None:
            reply, action = player
            yield "data: " + json.dumps({"response": reply, "source": "player",
                                         "action": action}) + "\n\n"
            yield "data: [DONE]\n\n"
            return
        # Плагин отвечает мгновенно и без "размышлений" - отдаём его сразу.
        plugin_answer = _try_plugins(cmd)
        if plugin_answer is not None:
            yield "data: " + json.dumps({"response": plugin_answer, "source": "plugin"}) + "\n\n"
            yield "data: [DONE]\n\n"
            return
        thinking_parts = []
        response_parts = []
        try:
            for token, thinking in stream_ollama(cmd, model=model):
                if thinking:
                    thinking_parts.append(thinking)
                if token:
                    response_parts.append(token)
                # Send every chunk as SSE
                payload = json.dumps({"model": model, "thinking": "".join(thinking_parts), "response": "".join(response_parts)})
                yield f"data: {payload}\n\n"
                await asyncio.sleep(0)
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# TTS: возвращает WAV-файл с озвучкой ответа
@app.get("/ttsSayWav")
async def ttsSayWav(text:str):
    from starlette.responses import Response
    import base64

    tmpformat = core.remoteTTS
    core.remoteTTS = "saywav"
    core.play_voice_assistant_speech(text)
    core.remoteTTS = tmpformat
    wav_b64 = core.remoteTTSResult.get("wav_base64", "")
    if wav_b64:
        wav_bytes = base64.b64decode(wav_b64)
        return Response(content=wav_bytes, media_type="audio/wav")
    return Response(content=b"", media_type="audio/wav")

# Посылает распознанный текстовый ввод. Если в нем есть имя помощника, выполняется команда.
# Пример: ирина погода, раз два
@app.get("/sendRawTxt")
async def sendRawTxt(rawtxt:str,returnFormat:str = "none"):
    return sendRawTxtOrig(rawtxt,returnFormat)

def sendRawTxtOrig(rawtxt:str,returnFormat:str = "saytxt"):
    result = call_ollama(rawtxt)
    return {"restxt": result}

@app.on_event("shutdown")
def app_shutdown():
    global is_running
    cprint("Ctrl-C pressed, exiting Irene.", "yellow")
    is_running = False

@app.on_event("startup")
@repeat_every(seconds=2)
async def app_timers():
    if core != None:
        #print("update timers")
        core._update_timers()
        # здесь срабатывание происходит по-настоящему, поэтому ловим его
        # здесь, а не когда клиент откроет страницу
        _check_fired()
        # таймер, переживший перезапуск, возвращаем до того, как ядро
        # начнёт гасить слоты, иначе он сгорит как просроченный
        _restore_timers()
        _persist_timers()
        _alarms_check()
        # Звонок будильника уходит подключённой плате. Раньше звучал только
        # браузер, и колонка без вкладки была беззвучной: будильник, ради
        # которого всё затевалось, молчал именно там, где колонка нужна.
        # Рассылка тут, в асинхронном цикле: слать из _check_fired нельзя,
        # он синхронный.
        if _fired_count[0] > _fired_sent[0]:
            _fired_sent[0] = _fired_count[0]
            await _ring_devices()
        elif _fired_count[0] < _fired_sent[0]:
            _fired_sent[0] = _fired_count[0]   # перезапуск обнулил счётчик


async def _ring_devices():
    """Отправляет подключённым устройствам сигнал будильника и его звук."""
    if not _dev_clients:
        return
    note = json.dumps({"type": "alarm", "at": _fired_last[0],
                       "fired": _fired_count[0]})
    wav = None
    try:
        wav = await run_in_threadpool(_tts_wav_bytes, "Будильник!")
    except Exception:
        wav = None
    for dev_id, dev in list(_dev_clients.items()):
        ws = dev.get("ws")
        if ws is None:
            continue
        try:
            await ws.send_text(note)
            if wav:
                await ws.send_bytes(wav)
        except Exception:
            _dev_clients.pop(dev_id, None)

if __name__ == "__main__":



    # p = Process(target=core_update_timers_http, args=(False,))
    # p.start()
    if webapi_options["use_ssl"]:
        uvicorn.run("runva_webapi:app",
                    host=webapi_options["host"], port=webapi_options["port"],
                    ssl_keyfile="localhost.key",
                    ssl_certfile="localhost.crt",
                    log_level=webapi_options["log_level"])
    else:
        uvicorn.run("runva_webapi:app",
                    host=webapi_options["host"], port=webapi_options["port"],
                    log_level=webapi_options["log_level"])