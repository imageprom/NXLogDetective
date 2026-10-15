"""Магазин на Битриксе всё сразу: регионы-поддомены, копия на чужом домене, IP-хост, подобранные имена, заказы с пересчётами оформления и ошибкой 504 перед заказом."""
import json
import os
import tempfile
from datetime import timedelta

import synth
from nxld import analyze, prepare

MAIN, MSK, COPY, IPH = 'example.com', 'msk.example.com', 'dev.example-copy.net', '198.51.100.9'
AJAX = '/bitrix/components/bitrix/sale.order.ajax/ajax.php'
UA_SCAN = 'Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0'


def _log():
    log = synth.Log()
    ref = f'https://{MAIN}/'
    def visit(ip, t, host, entry='/catalog/shary/'):
        log.line(ip, t, entry, 200, ref='https://yandex.ru/', host=host)
        log.line(ip, t + timedelta(seconds=1), '/local/templates/main/style.css', 200, ref=f'https://{host}{entry}', host=host)
        log.line(ip, t + timedelta(seconds=30), '/catalog/', 200, ref=ref, host=host)
    for k in range(30):   # люди на основном домене и региональном поддомене
        visit(f'95.165.0.{k + 1}', synth.T0 + timedelta(hours=8, minutes=9 * k), MAIN if k % 3 else MSK)
    buyers = []
    for n in range(1, 6):   # 5 заказов: 3–10 пересчётов оформления, проверка подписки, кабинет; обновление страницы успеха
        ip, host = f'95.167.0.{n}', MAIN if n % 2 else MSK
        t = synth.T0 + timedelta(days=1, hours=10, minutes=20 * n)
        visit(ip, t, host)
        for j in range(3 + n): log.line(ip, t + timedelta(seconds=60 + 3 * j), AJAX, 200, ref=f'https://{host}/personal/order/make/', method='POST', host=host)
        log.line(ip, t + timedelta(seconds=300), SUBSCRIBE_URL, 200, ref=ref, method='POST', host=host)
        log.line(ip, t + timedelta(seconds=400), f'/personal/order/make/?ORDER_ID={1000 + n}', 200, ref=f'https://{host}/personal/order/make/', host=host)
        log.line(ip, t + timedelta(seconds=460), f'/personal/order/make/?ORDER_ID={1000 + n}', 200, ref=f'https://{host}/personal/order/make/', host=host)
        log.line(ip, t + timedelta(seconds=520), '/personal/order/', 200, ref=ref, method='POST', host=host)
        buyers.append(ip)
    for k in range(3):   # ошибка 504 на оформлении: у двоих заказ в течение часа, у третьего нет
        ip = f'95.168.0.{k + 1}'
        t = synth.T0 + timedelta(days=2, hours=10, minutes=30 * k)
        visit(ip, t, MAIN)
        log.line(ip, t + timedelta(seconds=60), AJAX, 504, ref=f'https://{MAIN}/personal/order/make/', method='POST', host=MAIN)
        if k < 2:   # вернулся через 40 минут и оформил заказ
            visit(ip, t + timedelta(minutes=40), MAIN)
            log.line(ip, t + timedelta(minutes=41), f'/personal/order/make/?ORDER_ID={2000 + k}', 200, ref=f'https://{MAIN}/personal/order/make/', host=MAIN)
    for d in range(3):   # копия сайта: человек и сканер; заказ на копии не считается
        visit('203.0.113.7', synth.T0 + timedelta(days=d, hours=15), COPY)
        log.line('203.0.113.7', synth.T0 + timedelta(days=d, hours=15, minutes=5), f'/personal/order/make/?ORDER_ID={9000 + d}', 200, ref=f'https://{COPY}/', host=COPY)
        for j, u in enumerate(('/.env', '/.git/config')): log.line('203.0.113.50', synth.T0 + timedelta(days=d, hours=3, seconds=j), u, 200, ua=UA_SCAN, host=COPY)
        for j, u in enumerate(('/', '/admin/')): log.line('203.0.113.51', synth.T0 + timedelta(days=d, hours=4, seconds=j), u, 404, ua=UA_SCAN, host=IPH)
        for g_ in ('auth0.example.com', 'dev.example.com', 'x7q2k.example.com'):
            for j in range(4): log.line('203.0.113.52', synth.T0 + timedelta(days=d, hours=5, seconds=j), '/', 404, ua=UA_SCAN, host=g_)
    return log


SUBSCRIBE_URL = '/bitrix/components/bitrix/catalog.product.subscribe/ajax.php'


def test_shop_everything_at_once(monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        _log().write(path)
        lines = []
        prepare.run([path], work, log=lines.append)
        res = analyze.run(work, log=lines.append)
        m = json.load(open(os.path.join(work, 'site_map.json'), encoding='utf-8'))
        kind = {r['хост']: r['тип'] for r in m['hosts']}
        assert kind[MAIN] == kind[MSK] == 'сайт' and {kind[COPY], kind[IPH], kind['auth0.example.com'], kind['dev.example.com'], kind['x7q2k.example.com']} == {'не сайт'}
        s = res['summary']['Общий анализ']
        assert s['Принято от людей'] == 7, s   # 5 заказов + 2 заказа после ошибки; заказы на копии не в счёте; пересчёты, подписка, кабинет — не цели
        card = [x for x in res['findings'] if x['key'].split(':')[1] == 'lost_leads']
        assert len(card) == 1 and card[0]['главная_цифра'] == 1 and 'Ошибок всего 3, из них закончились заказом 2, без заказа 1' in card[0]['факты']   # «потеряно 1 из 3»
        assert not res.get('сбои_блоков'), res.get('сбои_блоков')
