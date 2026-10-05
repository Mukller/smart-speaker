import io
import json
import urllib.parse
import urllib.request

# Один запрос к потоковому эндпойнту, чтобы в журнале появился свежий след.
q = "кто ты"
u = ("https://antonpetnitsky.com/kolonka/api/sendTxtCmdStream?cmd="
     + urllib.parse.quote(q))
try:
    r = urllib.request.urlopen(u, timeout=30)
    print("status", r.status)
    got = 0
    while True:
        line = r.readline()
        if not line:
            break
        if line.strip():
            got += 1
            print(line.decode("utf-8", "replace")[:80])
        if got > 3:
            break
    print("чанков:", got)
except Exception as e:
    print("ошибка:", type(e).__name__, e)