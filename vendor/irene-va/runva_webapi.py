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

from starlette.responses import HTMLResponse, FileResponse, Response, StreamingResponse
from termcolor import cprint
import json
import re
from starlette.websockets import WebSocket

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


@app.get("/tts")
async def tts(text: str, speaker_id: int = 0):
    text = (text or "").strip()
    if not text:
        raise HTTPException(400, "пустой текст")
    if len(text) > 2000:
        text = text[:2000]
    if not _tts_ready():
        raise HTTPException(503, "TTS недоступен (%s)" % (_tts["err"] or "причина неизвестна"))
    try:
        # synth(text, oname) у vosk_tts пишет файл и возвращает None, поэтому
        # берём synth_audio() и собираем WAV сами — без временных файлов.
        import numpy as np
        audio = _tts["synth"].synth_audio(text, speaker_id)
    except AttributeError:
        import tempfile
        import wave as _wave
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            name = tf.name
        _tts["synth"].synth(text, name, speaker_id)
        with open(name, "rb") as f:
            return Response(content=f.read(), media_type="audio/wav",
                            headers={"Cache-Control": "no-store"})
    except Exception as e:
        raise HTTPException(500, "синтез не удался: %s" % e)

    from starlette.responses import Response
    import io
    import wave

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
    return Response(content=buf.getvalue(), media_type="audio/wav",
                    headers={"Cache-Control": "no-store"})


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
# Плеер: список своих файлов и отдача их потоком.
# В контейнере нет /dev/snd, звук играет браузер, поэтому сервер отдаёт файл,
# а управление (громче/тише/вперёд/назад) приходит командами ассистента.
# ---------------------------------------------------------------------------
MUSIC_DIR = os.environ.get("MUSIC_DIR", "/music")
MUSIC_EXT = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav", ".wma")
# имя не должно вылезать за пределы папки
MUSIC_NAME_RE = re.compile(r"^[^/\\]{1,180}$")


def _list_music():
    out = []
    try:
        for n in sorted(os.listdir(MUSIC_DIR)):
            if n.lower().endswith(MUSIC_EXT) and not n.startswith("."):
                try:
                    size = os.path.getsize(os.path.join(MUSIC_DIR, n))
                except OSError:
                    continue
                out.append({"name": n, "size": size,
                            "title": os.path.splitext(n)[0].replace("_", " ")})
    except Exception as e:
        return {"error": str(e), "tracks": []}
    return {"tracks": out, "count": len(out), "dir": MUSIC_DIR}


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
    mime = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
            ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac",
            ".wav": "audio/wav", ".wma": "audio/x-ms-wma"}.get(ext, "application/octet-stream")

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
    ]
    for words, reply, action in table:
        if any(w in text for w in words):
            return reply, action
    return None


@app.get("/sendTxtCmd")
async def sendSimpleTxtCmd(cmd:str,returnFormat:str = "saytxt"):
    player = _player_command(cmd)
    if player is not None:
        reply, action = player
        return {"restxt": reply, "source": "player", "action": action}
    plugin_answer = _try_plugins(cmd)
    if plugin_answer is not None:
        return {"restxt": plugin_answer, "source": "plugin"}
    return {"restxt": call_ollama(cmd), "source": "llm"}

# Streaming endpoint: returns thinking + response as Server-Sent Events
@app.get("/sendTxtCmdStream")
async def sendSimpleTxtCmdStream(cmd:str, model:str = "qwen2.5:0.5b-instruct"):
    from starlette.responses import StreamingResponse
    import asyncio

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