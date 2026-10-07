"""Мягкие ошибки (02): адреса без косой черты отдают другую страницу одного размера — одна группа, «что это», карточка."""
import os
import random
from datetime import timedelta

import synth

N = 600   # карточка — от 500 адресов в группе (в листе — от 200)


def test_soft_errors_no_slash(tmp_path):
    log = synth.Log()
    log.people()
    for i in range(N):
        ip = synth.RU[i % len(synth.RU)]
        t = synth.T0 + timedelta(days=i % 7, hours=14, minutes=(i // 7) % 600 // 10, seconds=i % 60)
        a = f'/catalog/x/item-{i}'
        log.line(ip, t, a, 200, ref='https://yandex.ru/', size=17000 + random.randint(0, 80))           # без «/» — одна и та же короткая страница
        log.line(ip, t + timedelta(seconds=20), a + '/', 200, ref=f'https://site.ru{a}', size=23000 + random.randint(0, 300))   # со «/» — настоящая
    res, out, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Ошибки']['Идентичные ответы']
    g = G[G['примеры'].str.contains('/catalog/x/item-')]
    assert len(g) == 1, G[['размер', 'разных_адресов']]
    r = g.iloc[0]
    assert r['разных_адресов'] >= N and '–' in r['размер']
    assert r['что_это'].startswith('Адреса без косой черты в конце')
    assert not G['размер'].str.startswith('23').any()   # страницы со «/» — разные адреса, но не группа «мягких ошибок»
    x = [x for x in res['findings'] if x['key'].split(':')[1] == 'soft_errors']
    assert len(x) == 1 and x[0]['блок'] == 'Ошибки' and x[0]['важность'] == 'Важно'
    assert x[0]['key'] == f"Ошибки:soft_errors:{r['_от']}"
    assert 'переадресация 301 на адрес с косой чертой' in x[0]['что_сделать'].lower()
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(out, 'NXLD_02_Errors.xlsx'))
    assert 'Мягкие ошибки' in wb.sheetnames and 'Пустые ответы' not in wb.sheetnames and 'Одинаковые ответы' not in wb.sheetnames
    vals = [v for row in wb['Мягкие ошибки'].iter_rows(values_only=True) for v in row if v]
    assert 'ИДЕНТИЧНЫЕ ОТВЕТЫ' in vals and 'МЯГКИЕ ОШИБКИ' in vals   # заголовки листа и блока — прописными
    ov = [v for row in wb['Обзор'].iter_rows(values_only=True) for v in row if isinstance(v, str)]
    assert any(v.startswith('Мягкие ошибки') for v in ov)


def test_soft_errors_no_slash_partial_pairs(tmp_path):
    """Пара со «/» есть только у 40% адресов без «/» (как на живом логе): правило решает по найденным парам."""
    log = synth.Log()
    log.people()
    for i in range(N):
        ip = synth.RU[i % len(synth.RU)]
        t = synth.T0 + timedelta(days=i % 7, hours=14, minutes=(i // 7) % 600 // 10, seconds=i % 60)
        a = f'/catalog/y/item-{i}'
        log.line(ip, t, a, 200, ref='https://yandex.ru/', size=17000 + random.randint(0, 80))
        if i % 10 < 4:   # 40% адресов — со «/» и настоящей страницей
            log.line(ip, t + timedelta(seconds=20), a + '/', 200, ref=f'https://site.ru{a}', size=23000 + random.randint(0, 300))
    res, _, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Ошибки']['Идентичные ответы']
    r = G[G['примеры'].str.contains('/catalog/y/item-')].iloc[0]
    assert r['что_это'].startswith('Адреса без косой черты в конце')
    x = [x for x in res['findings'] if x['key'] == f"Ошибки:soft_errors:{r['_от']}"]
    assert x and 'переадресация 301 на адрес с косой чертой' in x[0]['что_сделать'].lower()


UA_AHREFS = 'Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)'


def test_soft_errors_shares_four_groups(tmp_path):
    """Доли «кому отдаётся» — четыре: людям, поисковым, прочим роботам, ботам; вместе 100%, прочие роботы видны."""
    log = synth.Log()
    log.people()
    for i in range(300):
        t = synth.T0 + timedelta(days=i % 7, hours=14, minutes=(i // 7) % 600 // 10, seconds=i % 60)
        a = f'/catalog/z/item-{i}'
        log.line(synth.RU[i % len(synth.RU)], t, a, 200, ref='https://yandex.ru/', size=17000 + random.randint(0, 80))
        log.line('54.36.148.10', t + timedelta(seconds=7), a, 200, ua=UA_AHREFS, size=17000 + random.randint(0, 80))   # прочий робот
    for d in range(7):   # подлинный поисковик — обычный фон лога (случай «у всех роботов подлинность пуста» — в test_empty_data)
        log.line('66.249.66.10', synth.T0 + timedelta(days=d, hours=5), '/', 200, ua='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)')
    res, out, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Ошибки']['Идентичные ответы']
    r = G[G['примеры'].str.contains('/catalog/z/item-')].iloc[0]
    assert r['прочим_%'] > 0
    assert abs(r['людям_%'] + r['поисковым_%'] + r['прочим_%'] + r['ботам_%'] - 100) < 0.5
    import openpyxl
    ws = openpyxl.load_workbook(os.path.join(out, 'NXLD_02_Errors.xlsx'))['Мягкие ошибки']
    hdr = [c.value for c in ws[4] if c.value]
    sh = [h for h in hdr if h.endswith(', %')]
    assert sh == ['Людям, %', 'Поисковым роботам, %', 'Прочим роботам, %', 'Ботам, %']
