import json
import time
import urllib.parse
import urllib.request

API = 'https://antonpetnitsky.com/kolonka/api'

CASES = (
    'кто ты',
    'что такое эхо',
    'дай совет',
    'напиши рецепт борща',
    'что ты умеешь',
    'какая сейчас погода',
)

BAD = ('не могу', 'не имею', 'не участвую', 'не способен',
       'обратитесь к оператору', 'ошибка llm')

print('%-24s %6s %-8s %s' % ('фраза', 'сек', 'исток', 'ответ'))
tot = 0.0
for q in CASES:
    t0 = time.time()
    url = API + '/sendTxtCmd?cmd=' + urllib.parse.quote(q)
    with urllib.request.urlopen(url, timeout=180) as r:
        d = json.load(r)
    dt = time.time() - t0
    tot += dt
    txt = (d.get('restxt') or '').strip()
    flag = ''
    if any(b in txt.lower() for b in BAD):
        flag = '  <-- ОТКАЗ'
    if any('\u4e00' <= c <= '\u9fff' for c in txt):
        flag += '  <-- ИЕРОГЛИФЫ'
    print('%-24s %6.1f %-8s %s%s'
          % (q, dt, d.get('source'), txt.replace(chr(10), ' ')[:44], flag))

print('--- среднее %.1f с' % (tot / len(CASES)))