"""#23: тип хоста (сайт / не сайт) считается в prepare и хранится в данных; блоки «сайт» (01, 02, 05, 06) и «всё» (03, 04) берут запросы по одному правилу."""
import json
import os
import pickle
import tempfile
from datetime import timedelta

import pandas as pd
import pytest

import synth
from nxld import analyze, hosts, prepare

MAIN, MSK, SPB = 'example.com', 'msk.example.com', 'spb.example.com'
COPY, IPHOST = 'dev.example-copy.net', '198.51.100.9'
GUESS = ('auth0.example.com', 'dev.example.com', 'x7q2k.example.com')
SCAN_UA = 'Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0'


def _human(log, ip, t, host, entry, n_pages=2):
    """Человек: страница, оформление, ещё несколько страниц — на одном хосте."""
    ref = f'https://{MAIN}/'
    log.line(ip, t, entry, 200, ref='https://yandex.ru/', host=host)
    log.line(ip, t + timedelta(seconds=1), '/local/templates/main/style.css', 200, ref=f'https://{host}{entry}', host=host)
    for k in range(n_pages): log.line(ip, t + timedelta(seconds=30 * (k + 1)), f'/catalog/shary/?PAGEN_1={k + 2}', 200, ref=ref, host=host)
    if host != COPY: log.line(ip, t + timedelta(seconds=120), '/old-page/', 404, ref=f'https://{host}{entry}', host=host)   # ошибка сайта у человека


def _log(with_extra=True):
    log = synth.Log()
    n = {MAIN: 0, MSK: 0, SPB: 0, COPY: 0}
    for d in range(5):
        for k in range(10):   # люди на основном домене и на двух региональных поддоменах
            for host in (MAIN, MSK, SPB) if k < 4 else (MAIN,):
                ip = f'95.165.{d}.{k + 1}' if host == MAIN else f'95.165.{d + 10}.{k + 1}' if host == MSK else f'95.165.{d + 20}.{k + 1}'
                _human(log, ip, synth.T0 + timedelta(days=d, hours=8, minutes=7 * k), host, synth.PAGES[(k + d) % len(synth.PAGES)])
                n[host] += 1
        if not with_extra: continue
        # копия сайта на чужом домене: человек из браузера (разработчик) и сканер
        _human(log, '203.0.113.7', synth.T0 + timedelta(days=d, hours=15), COPY, '/')
        log.line('203.0.113.7', synth.T0 + timedelta(days=d, hours=15, minutes=3), '/old-copy/', 404, ref=f'https://{COPY}/', host=COPY)   # ошибка копии у человека
        n[COPY] += 1
        for j, u in enumerate(('/.env', '/.git/config', '/phpmyadmin/', '/old-copy/')):
            log.line('203.0.113.50', synth.T0 + timedelta(days=d, hours=3, seconds=j), u, 404 if j == 3 else 200, ua=SCAN_UA, host=COPY)
        for j, u in enumerate(('/', '/admin/', '/wp-login.php')):   # IP вместо имени
            log.line('203.0.113.51', synth.T0 + timedelta(days=d, hours=4, seconds=j), u, 404, ua=SCAN_UA, host=IPHOST)
        for g_ in GUESS:   # подобранные имена: только 404
            for j in range(4): log.line('203.0.113.52', synth.T0 + timedelta(days=d, hours=5, seconds=j), '/', 404, ua=SCAN_UA, host=g_)
    return log, n


def _run(tmp, log, **kw):
    path, work = os.path.join(tmp, 'access.log'), os.path.join(tmp, 'work')
    log.write(path)
    lines = []
    prepare.run([path], work, log=lines.append, **kw)
    dump = os.path.join(tmp, 'ctx.pkl')
    os.environ['NXLD_DUMP_CTX'] = dump
    try: res = analyze.run(work, log=lines.append)
    finally: os.environ.pop('NXLD_DUMP_CTX', None)
    return res, lines, work, (pickle.load(open(dump, 'rb'))[0] if os.path.exists(dump) else None)


def test_host_kinds_and_site_hosts(monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        log, n = _log()
        res, lines, work, c = _run(d, log)
        m = json.load(open(os.path.join(work, 'site_map.json'), encoding='utf-8'))
        kind = {r['хост']: r['тип'] for r in m['hosts']}
        assert {h: kind[h] for h in (MAIN, MSK, SPB)} == {MAIN: 'сайт', MSK: 'сайт', SPB: 'сайт'}
        assert {kind[h] for h in (COPY, IPHOST, *GUESS)} == {'не сайт'}, kind
        assert all(not hosts.is_ip(h) for h in m['site_hosts']), m['site_hosts']   # site_hosts — только имена
        off = m['off_site']
        assert off['хостов'] == 5 and off['запросов'] > 0
        assert any('хостов вне сайта: 5' in x for x in lines), lines   # журнал запуска


def test_people_and_errors_only_for_site_hosts(monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        log, n = _log()
        res, lines, work, c = _run(d, log)
        V = c.V
        people = V[V['group'] == 'Люди']
        assert bool(people['host_site'].all()) and len(people) >= n[MAIN] + n[MSK] + n[SPB] - 3   # люди — только визиты к хостам сайта
        off = V[~V['host_site'].astype(bool)]
        assert len(off) and 'Люди' not in set(off['group'])   # сканер и разработчик на копии — не «Люди»
        assert (off['group'] == 'Боты').any()
        # 02: ошибки — только по адресам сайта
        from nxld.errors import site_errors
        site_err = set(site_errors(res['errors']['коды'])['адрес'])
        assert '/old-page/' in site_err and '/old-copy/' not in site_err and '/phpmyadmin/' not in site_err
        # 03 и 04 — все запросы ко всем хостам
        assert len(c.R) == len(pd.read_pickle(os.path.join(work, 'R.pkl')))
        assert c.R['host_site'].astype(bool).sum() < len(c.R)
        brief = json.load(open(os.path.join(work, 'brief.json'), encoding='utf-8'))
        assert brief['проверка']['хосты_вне_сайта']['хостов'] == 5   # выжимка
        # реестр обращающихся: для 04 — все запросы, для «Активности» 01 — только сайт
        g_all, g_site = res['actors']['группы'], res['actors_site']['группы']
        assert int(g_all['визитов'].sum()) == len(c.V) and int(g_site['визитов'].sum()) == int(c.V['host_site'].astype(bool).sum()) < len(c.V)


def test_without_extra_hosts_nothing_changes(monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        log, n = _log(with_extra=False)
        res, lines, work, c = _run(d, log)
        R = pd.read_pickle(os.path.join(work, 'R.pkl'))
        assert bool(R['host_site'].all())
        assert 'хосты_вне_сайта' not in json.load(open(os.path.join(work, 'brief.json'), encoding='utf-8'))['проверка']
        assert not any('вне сайта' in x for x in lines)


def test_map_override_site_hosts_add_and_not_site_remove(monkeypatch):
    """Поправки: site_hosts добавляет домен сайта, not_site_hosts убирает."""
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        log, n = _log()
        res, lines, work, c = _run(d, log, map_override={'not_site_hosts': [SPB], 'site_hosts': [COPY]})
        m = json.load(open(os.path.join(work, 'site_map.json'), encoding='utf-8'))
        kind = {r['хост']: r['тип'] for r in m['hosts']}
        assert kind[SPB] == 'не сайт' and kind[COPY] == 'сайт' and kind[MSK] == 'сайт'


# ---------- A1, A2 ----------
def test_subdomain_crawled_only_by_robots_is_site(monkeypatch):
    """Поддомен, который обходят только роботы (≥ 10 страниц с 200), — сайт; имя с одними 403/404 — не сайт."""
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    log, _ = _log(with_extra=False)
    ROBOT = 'nsk.example.com'
    for d in range(3):
        for k in range(6):   # 18 страниц с 200 для Googlebot и robots.txt
            log.line('66.249.66.10', synth.T0 + timedelta(days=d, hours=6, minutes=k), synth.PAGES[k % len(synth.PAGES)], 200, ua='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)', host=ROBOT)
        log.line('66.249.66.10', synth.T0 + timedelta(days=d, hours=6, minutes=30), '/robots.txt', 200, ua='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)', host=ROBOT)
        for j in range(4): log.line('203.0.113.52', synth.T0 + timedelta(days=d, hours=5, seconds=j), '/', 403 if j % 2 else 404, ua=SCAN_UA, host='auth0.example.com')
    with tempfile.TemporaryDirectory() as d:
        res, lines, work, c = _run(d, log)
        kind = {r['хост']: r['тип'] for r in json.load(open(os.path.join(work, 'site_map.json'), encoding='utf-8'))['hosts']}
        assert kind[ROBOT] == 'сайт' and kind['auth0.example.com'] == 'не сайт', kind


def test_dash_host_is_unrecorded_name_and_site(monkeypatch):
    """Хост «-» (пустой запрос) — «имя хоста не записано» → сайт, а не «другой домен»."""
    assert hosts.normalize('-') == ''
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    log, _ = _log(with_extra=False)
    for j in range(5): log.line('203.0.113.60', synth.T0 + timedelta(hours=1, seconds=j), '/', 400, ua=SCAN_UA, host='-')
    with tempfile.TemporaryDirectory() as d:
        res, lines, work, c = _run(d, log)
        rows = {r['хост']: r for r in json.load(open(os.path.join(work, 'site_map.json'), encoding='utf-8'))['hosts']}
        assert rows['(не записан)']['тип'] == 'сайт' and rows['(не записан)']['причина'] == 'имя хоста не записано', rows
        assert '-' not in rows
