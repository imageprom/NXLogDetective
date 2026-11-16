"""Эталон на богатом логе: сотни адресов с ошибками, переходы (страницы сайта, внешние сайты, скрипты, реклама, поиск), хотлинк, параметры (больше тысячи запросов,
длинные значения, атака, токен, персональные данные, рекламные метки), файлы, утёкший файл. Все файлы отчёта 01–06, лист в лист.

Эталон снят с кода до переделок круга 4c: переделки «под капотом» отчёт не меняют. Если отчёт изменён намеренно —
NXLD_GOLDEN_UPDATE=1 python3 -m pytest -q tests/test_golden_rich.py и перечислить изменившиеся листы в описании правки."""
import json, os, sys, tempfile
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import synth, report_digest

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden', 'rich_report.json')
UA_GOOGLE = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
UA_YANDEX = 'Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)'
UA_CURL = 'curl/8.4.0'
UA_SCAN = 'Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0'
DAYS = 6


def rich_log():
    L = synth.Log(seed=11)
    L.people(days=DAYS, per_day=20)
    T0 = synth.T0
    for d in range(DAYS):
        t = T0 + timedelta(days=d)
        ppl = [f'95.165.{d}.{k + 1}' for k in range(40)]
        # 320 адресов с 404: ссылки со страниц сайта, с внешних сайтов, из скриптов; их же просят роботы и сканеры
        for i in range(320):
            a = f'/old/p{i}/'
            ip = ppl[i % 40]
            ref = (f'https://site.ru/{["catalog", "news", "about"][i % 3]}/{i % 7}/' if i % 4 == 0 else f'https://example.org/links/{i % 5}/' if i % 4 == 1
                   else 'https://yandex.ru/search/?text=x' if i % 4 == 2 else '-')
            if i % 3 == d % 3 or i < 30: L.line(ip, t + timedelta(hours=9, seconds=7 * i), a, 404, ref=ref)
            if i % 5 == 0: L.line('66.249.66.1', t + timedelta(hours=3, seconds=5 * i), a, 404, ua=UA_GOOGLE)
            if i % 9 == 0: L.line('203.0.113.50', t + timedelta(hours=2, seconds=i), a, 404, ua=UA_SCAN)
        for i, u in enumerate(('/{{item.url}}', '/undefined', '/[object%20Object]', '/catalog/%7B%7Bitem.id%7D%7D/')):   # адреса-конструкты из скриптов
            for k in range(3 + i): L.line(ppl[k], t + timedelta(hours=10, minutes=i, seconds=k), u, 404, ref='https://site.ru/catalog/shary/')
        # 5xx: адреса, которые чинятся и ломаются; 499; отказы
        for i in range(40):
            a = f'/shop/item{i}/'
            code = 500 if (i % 2 == 0 and d < 3) or (i % 5 == 0) else 200
            for k in range(2): L.line(ppl[(i + k) % 40], t + timedelta(hours=11, minutes=i, seconds=k), a, code, ref='https://site.ru/catalog/')
            if i % 6 == 0: L.line(ppl[i % 40], t + timedelta(hours=12, minutes=i), a, 499, ref='https://site.ru/catalog/')
            if i % 7 == 0: L.line('203.0.113.7', t + timedelta(hours=13, seconds=i), a, 403, ua=UA_CURL)
            if i % 8 == 0: L.line('66.249.66.2', t + timedelta(hours=4, seconds=i), a, 301 if d % 2 else 200, ua=UA_GOOGLE)
            if i % 11 == 0: L.line('5.255.253.1', t + timedelta(hours=4, minutes=5, seconds=i), a, 200, ua=UA_YANDEX)
        # утёкший файл, тяжёлые файлы, хотлинк, файлы страниц
        L.line('203.0.113.60', t + timedelta(hours=1), '/backup.sql', 200 if d < 4 else 403, ua=UA_SCAN, size=5_000_000)
        for k in range(30):
            L.line(ppl[k], t + timedelta(hours=14, seconds=k), '/upload/big/video.mp4', 200, ref='https://site.ru/catalog/', size=900_000 + k * 3)
            L.line(ppl[k], t + timedelta(hours=14, seconds=40 + k), f'/upload/iblock/{k % 6}.jpg', 200 if k % 9 else 404, ref='https://site.ru/catalog/')
            L.line(f'91.{d}.{k}.9', t + timedelta(hours=15, seconds=k), f'/upload/iblock/{k % 4}.jpg', 200, ref=f'https://copy{k % 3}.example.net/post/{k}', size=400_000)
        # параметры: частые (больше тысячи запросов за период), длинные значения, атака, токен, персональные данные, рекламные метки
        for k in range(90):
            ip = ppl[k % 40]
            L.line(ip, t + timedelta(hours=16, seconds=11 * k), f'/catalog/?sort={["price", "name"][k % 2]}&order=asc&PAGEN_1={k % 12 + 1}', 200, ref='https://site.ru/catalog/')
            L.line(ip, t + timedelta(hours=16, minutes=30, seconds=11 * k), f'/catalog/shary/?filter[price][from]={k % 9 * 100}&filter[price][to]={k % 9 * 100 + 500}&brand={k % 7}', 200, ref='https://site.ru/catalog/')
        for k in range(12):
            ip = ppl[k]
            L.line(ip, t + timedelta(hours=17, seconds=k), '/akcii/?utm_source=yandex&utm_medium=cpc&utm_campaign=c%d&yclid=%d' % (k % 4, 100000 + k), 200, ref='https://yandex.ru/')
            L.line(ip, t + timedelta(hours=17, minutes=5, seconds=k), '/about/?q=' + 'длинное-значение-' * 12 + str(k), 200, ref='https://site.ru/')
            L.line(ip, t + timedelta(hours=17, minutes=9, seconds=k), f'/contacts/?phone=%2B7999111{2200 + k}&email=user{k}%40example.com', 200, ref='https://site.ru/')
            L.line(ip, t + timedelta(hours=17, minutes=11, seconds=k), f'/personal/?token=a1b2c3d4e5f6{k}a7b8c9d0&sessid={900000 + k}', 200, ref='https://site.ru/')
            L.line('203.0.113.51', t + timedelta(hours=18, seconds=k), f'/catalog/?id={k}%27%20union%20select%201', 200, ua=UA_SCAN)
            L.line('203.0.113.51', t + timedelta(hours=18, minutes=1, seconds=k), f'/index.php?file=../../../../etc/passwd&x={k}', 404, ua=UA_SCAN)
            L.line(ip, t + timedelta(hours=18, minutes=2, seconds=k), f'/catalog/?{1778857049245 + k}', 200, ref='https://site.ru/catalog/')
    return L


def test_report_matches_golden_rich():
    with tempfile.TemporaryDirectory() as d:
        _, out, _ = synth.run(rich_log(), d)
        got = {f: {s: h for s, h in ss.items() if not s.startswith('_')} for f, ss in report_digest.digest(out, mask=r'Отчёт от \d+ \S+ \d{4} · NX Log Detective [\w.\-]+').items()}
    if os.environ.get('NXLD_GOLDEN_UPDATE'):
        json.dump(got, open(GOLDEN, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    want = json.load(open(GOLDEN, encoding='utf-8'))
    changed = sorted(f'{f} · {s}' for f in set(got) | set(want) for s in set(got.get(f, {})) | set(want.get(f, {})) if got.get(f, {}).get(s) != want.get(f, {}).get(s))
    assert not changed, 'Отчёт изменился на листах: ' + '; '.join(changed)
