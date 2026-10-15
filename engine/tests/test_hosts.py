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
        assert len(off) and 'Люди' not in set(off['group'])   # нераспознанные «Люди» на хостах вне сайта в отчёт не входят
        assert (off['group'] == 'Боты').any()   # а сканеры копии и подобранных имён — распознаны и остаются (03 и 04)
        # 02: ошибки — только по адресам сайта
        from nxld.errors import site_errors
        site_err = set(site_errors(res['errors']['коды'])['адрес'])
        assert '/old-page/' in site_err and '/old-copy/' not in site_err and '/phpmyadmin/' not in site_err
        # 03 и 04 — все запросы ко всем хостам
        assert len(c.R) <= len(pd.read_pickle(os.path.join(work, 'R.pkl'))) and c.R['host_site'].astype(bool).sum() < len(c.R)   # распознанное вне сайта — в 03 и 04
        brief = json.load(open(os.path.join(work, 'brief.json'), encoding='utf-8'))
        assert brief['проверка']['хосты_вне_сайта']['хостов'] == 5 and brief['проверка']['хосты_вне_сайта']['не_распознано_визитов'] == 0   # выжимка: человек на копии вне данных вообще, остальное вне сайта распознано
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


# ---------- A3 ----------
def test_referer_from_server_ip_host_is_internal(monkeypatch):
    """Реферер http://<IP-хост из лога>/page — переход внутри сервера: не «Битые внешние» и не канал «Ссылки с сайтов»."""
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    log, _ = _log()
    for d in range(3):
        for k in range(6):   # люди приходят на сайт со страницы на IP сервера; часть адресов не найдена
            ip = f'95.170.{d}.{k + 1}'
            t = synth.T0 + timedelta(days=d, hours=11, minutes=5 * k)
            entry = '/missing-from-ip/' if k % 2 else '/catalog/'
            log.line(ip, t, entry, 404 if k % 2 else 200, ref=f'http://{IPHOST}/page', host=MAIN)
            log.line(ip, t + timedelta(seconds=1), '/local/templates/main/style.css', 200, ref=f'https://{MAIN}{entry}', host=MAIN)
            log.line(ip, t + timedelta(seconds=30), '/catalog/', 200, ref=f'https://{MAIN}{entry}', host=MAIN)
    with tempfile.TemporaryDirectory() as d:
        res, lines, work, c = _run(d, log)
        V = c.V
        ip_ref = V[V['entry_ref'].astype(str).str.contains(IPHOST, regex=False) & V['host_site'].astype(bool)]
        assert len(ip_ref) >= 18 and bool(ip_ref['entry_ref_internal'].all())
        assert 'Ссылки с сайтов' not in set(ip_ref['channel'].astype(str)) and set(ip_ref['channel'].astype(str)) == {'Внутренний переход'}
        S = res['errors']['источники']   # «сайты» — внешние источники ошибок; IP сервера среди них быть не должно
        ext = S[(S['вид'] == 'сайты') & (S['деталь'].astype(str).str.contains(IPHOST, regex=False))]
        assert not len(ext), ext


# ---------- A4 ----------
def test_off_site_visits_pass_usual_rules_and_unrecognized_are_hidden(monkeypatch):
    """Визит под браузером к IP-хосту с зондами — «сканер под браузер», а не «вне сайта»; визит, похожий на человека (страница, оформление, 301), — нигде в отчёте; счёт — в выжимке."""
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    log, _ = _log(with_extra=False)
    scan_ip, human_ip = '203.0.113.71', '203.0.113.72'
    for d in range(3):
        t = synth.T0 + timedelta(days=d, hours=4)
        log.line(scan_ip, t, '/', 200, ref='https://yandex.ru/', host=IPHOST)   # браузерный User-Agent по умолчанию: сначала похож на человека
        log.line(scan_ip, t + timedelta(seconds=1), '/local/templates/main/style.css', 200, ref=f'http://{IPHOST}/', host=IPHOST)
        for j, u in enumerate(('/.env', '/wp-login.php', '/phpinfo.php', '/.git/config', '/backup.sql')):
            log.line(scan_ip, t + timedelta(seconds=2 + j), u, 404, host=IPHOST)
        t = synth.T0 + timedelta(days=d, hours=6)
        log.line(human_ip, t, '/', 301, ref='https://yandex.ru/', host=IPHOST)
        log.line(human_ip, t + timedelta(seconds=1), '/local/templates/main/style.css', 200, ref=f'http://{IPHOST}/', host=IPHOST)
        log.line(human_ip, t + timedelta(seconds=30), '/catalog/', 301, ref=f'http://{IPHOST}/', host=IPHOST)
    with tempfile.TemporaryDirectory() as d:
        res, lines, work, c = _run(d, log)
        V = c.V
        sc = V[V['ip'].astype(str) == scan_ip]
        assert len(sc) and bool(sc['subgroup'].astype(str).str.startswith('сканер под браузер').all()) and not sc['host_site'].astype(bool).any(), sc[['group', 'subgroup']]
        assert human_ip not in set(V['ip'].astype(str))   # не «Люди» и не 04: в отчёт не входит
        off = json.load(open(os.path.join(work, 'brief.json'), encoding='utf-8'))['проверка']['хосты_вне_сайта']
        assert off['не_распознано_визитов'] == 3 and off['запросов'] == 30, off
        assert any('из них не распознано 3 визитов' in x for x in lines), lines


# ---------- A5 ----------
def test_copies_on_other_domains_are_out_of_every_block(monkeypatch):
    """Хосты с причиной «другой домен» — вне всех блоков, включая 03 и 04; IP сервера и подобранные имена — не копии (правило A4)."""
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        log, n = _log()
        res, lines, work, c = _run(d, log)
        m = json.load(open(os.path.join(work, 'site_map.json'), encoding='utf-8'))
        R_all = pd.read_pickle(os.path.join(work, 'R.pkl'))
        assert COPY not in set(R_all['vhost'].astype(str))   # копии нет в данных
        ips = set(c.V['ip'].astype(str))
        assert '203.0.113.50' not in ips and '203.0.113.7' not in ips   # сканер копии и разработчик на копии — нигде, даже в 03 и 04
        assert {'203.0.113.51', '203.0.113.52'} <= ips   # IP-хост и подобранные имена: распознанные сканеры остаются
        rows = {r['хост']: r for r in m['hosts']}
        assert rows[COPY]['причина'] == 'другой домен' and rows[COPY]['запросов'] > 0   # счёт копии — в таблице хостов
        assert m['off_site']['копии_запросов'] == rows[COPY]['запросов']   # и в сводке
        assert any('копии на других доменах' in x for x in lines), lines   # и в журнале
        brief = json.load(open(os.path.join(work, 'brief.json'), encoding='utf-8'))
        assert brief['проверка']['хосты_вне_сайта']['копии_запросов'] == rows[COPY]['запросов']


# ---------- A6 ----------
def _err(path, lines):
    with open(path, 'w') as f: f.write('\n'.join(lines) + '\n')


def test_error_log_02_only_site_hosts_03_all_but_copies(monkeypatch):
    """Error-лог: в 02 — строки только с хостов сайта; сбои и признаки торможения — весь сервер без копий; нет host — все строки."""
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    log, _ = _log()
    with tempfile.TemporaryDirectory() as d:
        path, work, errp = os.path.join(d, 'access.log'), os.path.join(d, 'work'), os.path.join(d, 'error.log')
        log.write(path)
        L = []
        for host, n in ((MAIN, 4), (MSK, 3), (COPY, 7), (IPHOST, 5), ('auth0.example.com', 2)):
            for k in range(n):
                L.append(f'2026/09/0{1 + k % 3} 10:{k:02d}:00 [error] 101#101: *{k + 1} upstream timed out (110: Connection timed out) while reading response header from upstream, client: 203.0.113.9, server: {host}, request: "GET /x{k}/ HTTP/1.1", upstream: "fastcgi://unix:/run/php.sock:", host: "{host}"')
        _err(errp, L)
        lines = []
        prepare.run([path, errp], work, log=lines.append)
        res = analyze.run(work, log=lines.append)
        m = res['site_map']
        assert m['off_site']['error_log_копии'] == 7 and m['off_site']['error_log_не_вошло_в_02'] == 7 + 5 + 2   # копии, IP-хост и подобранное имя — не в 02
        assert any('Error-лог: в 02 не вошло 14' in x for x in lines), lines
        brief = json.load(open(os.path.join(work, 'brief.json'), encoding='utf-8'))
        assert brief['проверка']['хосты_вне_сайта']['error_log_не_вошло_в_02'] == 14
        err02 = res['sheets']['Ошибки'].get('Error-лог')
        assert err02 is not None and int(err02['сообщений'].sum()) == 4 + 3   # лист «Error-лог» (02): только хосты сайта
        t = res['errors'].get('торможение') or {}
        tm = t.get('таймауты')
        assert tm is not None and int(tm.values.sum()) == 4 + 3 + 5 + 2   # торможение: весь сервер без копий (7 строк копии не в счёте)


# ---------- A7 ----------
def _ip_card(log, monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        res, lines, work, c = _run(d, log)
        return [x for x in res['findings'] if x['key'].split(':')[1] == 'ip_host_redirect']


def _ip_host_log(status):
    log, _ = _log(with_extra=False)
    for d in range(3):
        for k in range(6):   # роботы и сканеры по IP сервера
            log.line('66.249.66.11', synth.T0 + timedelta(days=d, hours=7, minutes=k), '/', status, ua='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)', host=IPHOST)
            log.line('203.0.113.80', synth.T0 + timedelta(days=d, hours=8, seconds=k), f'/x{k}.php', status, ua=SCAN_UA, host=IPHOST)
        # похожий на человека: страница и оформление по IP, потом заходит на сайт
        ip, t = f'203.0.113.9{d}', synth.T0 + timedelta(days=d, hours=9)
        log.line(ip, t, '/', status, ref='https://yandex.ru/', host=IPHOST)
        log.line(ip, t + timedelta(seconds=1), '/local/templates/main/style.css', status, ref=f'http://{IPHOST}/', host=IPHOST)
        if d == 0: log.line(ip, t + timedelta(seconds=40), '/catalog/', 200, ref=f'http://{IPHOST}/', host=MAIN)
    for j in range(3):   # подобранное имя: одно отвечает страницей
        log.line('203.0.113.52', synth.T0 + timedelta(hours=5, seconds=j), '/', 200 if j == 0 else 404, ua=SCAN_UA, host='x7q2k.example.com')
        log.line('203.0.113.52', synth.T0 + timedelta(hours=5, seconds=10 + j), '/', 404, ua=SCAN_UA, host='auth0.example.com')
    return log


def test_ip_host_card_on_redirect(monkeypatch):
    card = _ip_card(_ip_host_log(301), monkeypatch)
    assert len(card) == 1, card
    x = card[0]
    assert x['блок'] == 'Нагрузка и безопасность' and '301' in x['факты'] and 'роботы — 1' in x['факты'] and 'IP' in x['факты']
    assert 'дошли 1' in x['факты'] and 'не 403/404: 1' in x['факты'] and 'отвечать 444' in x['что_сделать'], x['факты']
    from nxld import texts
    assert texts.card('ip_host_redirect')['action'] == x['что_сделать']   # тексты — в data/locale/ru/cards.json


def test_no_ip_host_card_on_444_or_403(monkeypatch):
    assert _ip_card(_ip_host_log(403), monkeypatch) == []
    assert _ip_card(_ip_host_log(404), monkeypatch) == []
