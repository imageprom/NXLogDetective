"""#22: для магазина основная конверсия — заказ: разные номера на странице успеха оформления. Пересчёты оформления, проверка подписки, кабинет и админка — не цели."""
import os
import tempfile
from datetime import timedelta

import pandas as pd

import synth
from nxld import analyze, prepare

AJAX = '/bitrix/components/bitrix/sale.order.ajax/ajax.php'
SUBSCRIBE = '/bitrix/components/bitrix/catalog.product.subscribe/ajax.php'
OK = 'https://site.ru/personal/order/make/'


def _log(shop=True, calls=(3, 7, 10, 4, 5)):
    log = synth.Log()
    for k in range(30):   # люди: движок определяется по 20 и больше IP
        ip = f'95.165.{k // 200}.{k + 1}'
        log.visit(ip, synth.T0 + timedelta(hours=8, minutes=9 * k), ref='https://yandex.ru/')
    for k in range(4):   # форма обратной связи — цель, как раньше
        ip = f'95.166.0.{k + 1}'
        t = synth.T0 + timedelta(days=1, hours=9, minutes=5 * k)
        log.visit(ip, t)
        log.line(ip, t + timedelta(seconds=100), '/contacts/send/', 200, ref='https://site.ru/contacts/', method='POST')
    if not shop: return log
    for n, calls_ in enumerate(calls, 1):   # 5 заказов: на каждый 3–10 пересчётов оформления, проверки подписки, кабинет
        ip = f'95.167.0.{n}'
        t = synth.T0 + timedelta(days=2, hours=10, minutes=20 * n)
        log.visit(ip, t)
        for j in range(calls_): log.line(ip, t + timedelta(seconds=60 + 3 * j), AJAX, 200, ref='https://site.ru/personal/order/make/', method='POST')
        log.line(ip, t + timedelta(seconds=40), SUBSCRIBE, 200, ref='https://site.ru/catalog/', method='POST')
        log.line(ip, t + timedelta(seconds=400), f'/personal/order/make/?ORDER_ID={1000 + n}', 200, ref='https://site.ru/personal/order/make/')
        log.line(ip, t + timedelta(seconds=460), f'/personal/order/make/?ORDER_ID={1000 + n}', 200, ref='https://site.ru/personal/order/make/')   # обновил страницу успеха
        log.line(ip, t + timedelta(seconds=520), '/personal/order/', 200, ref='https://site.ru/', method='POST')   # кабинет
    return log


def _prepare(log):
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        log.write(path)
        prepare.run([path], work, log=lambda *a: None)
        return pd.read_pickle(os.path.join(work, 'R.pkl')), pd.read_pickle(os.path.join(work, 'V.pkl'))


def test_orders_counted_by_number():
    R, V = _prepare(_log())
    g = R['goal'].astype(str)
    assert int(R['is_order'].sum()) == 5   # пять номеров, обновление страницы успеха не считается
    assert int((g == '/contacts/send/').sum()) == 4 and int(g.str.contains('sale.order.ajax|subscribe|/personal/order/$|admin', regex=True).sum()) == 0   # форма — цель; шаги, подписка, кабинет — нет
    assert int(R['goal_success'].sum()) == 9   # 5 заказов + 4 заявки
    assert int(V['n_conv'].sum()) == 9 and int(V['n_goal'].sum()) == 9
    assert int(R['order_step'].sum()) == 3 + 7 + 10 + 4 + 5   # шаги оформления отмечены для карточки о потерянных заявках


def test_order_counted_once_in_first_visit():
    log = _log(calls=(3,) * 5)
    ip = '95.167.0.1'
    log.line(ip, synth.T0 + timedelta(days=5, hours=10), '/personal/order/make/?ORDER_ID=1001', 200, ref='-')   # позже тот же номер из другого визита
    R, V = _prepare(log)
    assert int(R['is_order'].sum()) == 5
    first = R.loc[R['is_order'], 'vid']
    assert first.is_unique   # по заказу — свой визит, номер в позднем визите не посчитан


def test_shop_without_orders_and_forms_as_before():
    """Сайт без магазина: нет страниц успеха заказа — цели только по формам, как раньше."""
    R, V = _prepare(_log(shop=False))
    assert int(R['is_order'].sum()) == 0 and int(R['goal_success'].sum()) == 4 and int(V['n_conv'].sum()) == 4


def test_analyze_accepted_count_follows_orders(monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        _log().write(path)
        prepare.run([path], work, log=lambda *a: None)
        res = analyze.run(work, log=lambda *a: None)
        s = res['summary']['Общий анализ']
        assert s['Принято от людей'] == 9 and s['Отправок целей всего'] == 9, s
