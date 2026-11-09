"""Ведомственные роботы: проверяющие системы Роскомнадзора (сети ФГУП «ГРЧЦ») и сканер СайберОК (СКИПА). Синтетика: IP — из сетей справочника (они не личные данные),
остальные — из 198.51.100.0/24 и 203.0.113.0/24."""
import glob
import json
import os
import pickle
import tempfile
from datetime import timedelta

import openpyxl

import synth
import test_hosts
from nxld import analyze, prepare

T0 = synth.T0
MAIN, IPHOST = test_hosts.MAIN, test_hosts.IPHOST
FF135 = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0'
UA_CYBEROK = 'CyberOKInspect/1.0 (+https://www.cyberok.ru/policy.html)'
BOT_IP, BOT2_IP, SCAN_IP, VIS_IP = '185.224.228.10', '185.224.228.11', '212.192.158.20', '194.165.22.9'
ORDER_IP = '62.76.98.7'


def _base(): return test_hosts._log(with_extra=False)[0]


def _browser_scan(log, ip=BOT_IP, day=1, hour=3, code=200, host=MAIN):
    """Снятие отпечатка: главная и favicon под браузером, без статики страницы."""
    t = T0 + timedelta(days=day, hours=hour)
    log.line(ip, t, '/', code, ua=FF135, host=host)
    log.line(ip, t + timedelta(seconds=1), '/favicon.ico', code, ua=FF135, host=host)


def _cyberok(log, ip=SCAN_IP, day=1, hour=4):
    t = T0 + timedelta(days=day, hours=hour)
    for k, u in enumerate(('/main.php', '/containers/', '/login.jsp?os_destination=%2Fa')): log.line(ip, t + timedelta(seconds=k), u, 404, ua=UA_CYBEROK, host=IPHOST)


def _visitor(log, ip=VIS_IP, day=2, hour=10, ad=True):
    """Браузер из сети ГРЧЦ: вход по клику из рекламы, страницы, статика."""
    t = T0 + timedelta(days=day, hours=hour)
    entry = '/catalog/shary/?utm_source=yandex&utm_medium=cpc&utm_campaign=c1&yclid=777' if ad else '/catalog/shary/'
    test_hosts._human(log, ip, t, MAIN, entry, n_pages=3)


def _ipredirect(log, ip=BOT_IP, day=1, hour=3):
    log.line(ip, T0 + timedelta(days=day, hours=hour, seconds=30), '/', 301, ua=FF135, host=IPHOST)


def _run(log, error_lines=None):
    os.environ['NXLD_STRICT_CATALOG'] = '1'
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        log.write(path)
        paths = [path]
        if error_lines:
            ep = os.path.join(d, 'error.log'); open(ep, 'w').write('\n'.join(error_lines) + '\n'); paths.append(ep)
        prepare.run(paths, work, log=lambda *a: None)
        dump = os.path.join(d, 'ctx.pkl')
        os.environ['NXLD_DUMP_CTX'] = dump
        try: res = analyze.run(work, log=lambda *a: None)
        finally: os.environ.pop('NXLD_DUMP_CTX', None)
        c = pickle.load(open(dump, 'rb'))[0]
        brief = json.load(open(os.path.join(work, 'brief.json'), encoding='utf-8'))
    return res, c, brief


def _v(c, ip):
    V = c.V
    return V[V['ip'].astype(str) == ip]


def _cards(res): return {x['key'].split(':')[1]: x for x in res['findings'] if x['key'].split(':')[1].startswith('gov_robots')}


def test_browser_scanner_from_grchc_network_is_bot_not_people():
    log = _base(); _browser_scan(log); _ipredirect(log)
    res, c, _ = _run(log)
    v = _v(c, BOT_IP)
    assert len(v) and set(v['group'].astype(str)) == {'Боты'} and set(v['subgroup'].astype(str)) == {'ведомственные роботы'}, v[['group', 'subgroup']]
    assert set(v['gov_kind'].astype(str)) == {'scanner_browser'} and set(v['gov_op'].astype(str)) == {'grchc'} and set(v['nettype'].astype(str)) == {'госсеть'}


def test_signed_cyberok_is_robot_security_scanner():
    log = _base(); _cyberok(log)
    res, c, _ = _run(log)
    v = _v(c, SCAN_IP)
    assert set(v['group'].astype(str)) == {'Роботы'} and set(v['subgroup'].astype(str)) == {'ведомственные роботы'}, v[['group', 'subgroup']]
    assert set(v['gov_kind'].astype(str)) == {'scanner_security'} and set(v['gov_op'].astype(str)) == {'cyberok'} and set(v['fam'].astype(str)) == {'СайберОК (СКИПА)'}
    t = res['gov_table']
    assert t[t['ip'] == SCAN_IP]['kind'].iloc[0] == 'сканер защищённости' and 'СайберОК' in t[t['ip'] == SCAN_IP]['network'].iloc[0]


def test_browser_from_grchc_with_full_behavior_is_people_marked_visitor_with_ad_click():
    log = _base(); _visitor(log)
    res, c, brief = _run(log)
    v = _v(c, VIS_IP)
    assert len(v) and set(v['group'].astype(str)) == {'Люди'} and set(v['gov_kind'].astype(str)) == {'visitor'}, v[['group', 'subgroup', 'gov_kind']]
    row = res['gov_table'].iloc[0]
    assert row['kind'] == 'посетитель из госсети' and row['origin'] == 'клик по рекламе' and 'ГРЧЦ' in row['network'] and 'AS196641' in row['network']
    assert brief['gov_robots']['visitors'] == {'visits': 1, 'ips': 1, 'ad_clicks': 1} and brief['gov_robots']['robots']['visits'] == 0


def test_visitor_from_grchc_who_placed_an_order_is_people_and_order_counted():
    import test_orders
    log = test_orders._log()
    ip, t = ORDER_IP, synth.T0 + timedelta(days=2, hours=12)
    log.visit(ip, t)
    for j in range(4): log.line(ip, t + timedelta(seconds=60 + 3 * j), test_orders.AJAX, 200, ref='https://site.ru/personal/order/make/', method='POST')
    log.line(ip, t + timedelta(seconds=400), '/personal/order/make/?ORDER_ID=2001', 200, ref='https://site.ru/personal/order/make/')
    res, c, _ = _run(log)
    v = _v(c, ip)
    assert set(v['group'].astype(str)) == {'Люди'} and set(v['gov_kind'].astype(str)) == {'visitor'} and int(v['n_conv'].sum()) == 1, v[['group', 'gov_kind', 'n_conv']]
    assert int(c.R['is_order'].sum()) == 6   # 5 заказов обычных людей и один — из госсети
    assert res['gov_table'][res['gov_table']['ip'] == ip]['kind'].iloc[0] == 'посетитель из госсети'


def test_refused_card_on_403_at_site_domain_and_not_on_301_by_ip_host():
    log = _base(); _browser_scan(log, BOT2_IP, code=403)
    res, _, _ = _run(log)
    x = _cards(res)['gov_robots_refused']
    assert x['важность'] == 'Важно' and '403' in x['факты'] and 'фильтра для сетей ГРЧЦ' in x['что_сделать'] and x['блок'] == 'Общий анализ', x
    log = _base(); _browser_scan(log); _ipredirect(log); _cyberok(log)
    res, _, _ = _run(log)
    assert 'gov_robots_refused' not in _cards(res)   # 301 по IP сервера и 404 на пробах по IP — не отказ сайта


def test_visit_card_with_who_when_and_ads():
    log = _base(); _browser_scan(log); _cyberok(log); _visitor(log)
    res, _, _ = _run(log)
    x = _cards(res)['gov_robots_visit']
    assert x['важность'] == 'К сведению' and 'ГРЧЦ' in x['что_происходит'] and 'СайберОК' in x['что_происходит'], x
    assert 'клик по рекламе: 1' in x['факты'] and 'cookie' in x['что_сделать'] and 'маркировку рекламы' in x['что_сделать']


def test_no_gov_visits_no_cards_zero_in_brief():
    res, _, brief = _run(_base())
    g = brief['gov_robots']
    assert g['came'] is False and g['visits'] == 0 and g['robots']['visits'] == 0 and g['refused']['requests'] == 0 and not _cards(res)


def test_ip_host_card_mentions_gov_robots():
    log = _base(); _browser_scan(log); _ipredirect(log)
    for k in range(3): log.line('203.0.113.51', T0 + timedelta(days=1, hours=5, seconds=k), '/', 301, ua=FF135, host=IPHOST)
    res, _, _ = _run(log)
    x = [y for y in res['findings'] if y['key'].split(':')[1] == 'ip_host_redirect'][0]
    assert 'Ведомственные роботы тоже обращаются по IP сервера' in x['факты'] and 'Сети ГРЧЦ на доменах сайта фильтром не закрывать' in x['факты']


def test_block_on_robots_sheet_with_note_and_columns(tmp_path):
    log = _base(); _browser_scan(log); _cyberok(log); _visitor(log)
    _, out, _ = synth.run(log, str(tmp_path))
    ws = openpyxl.load_workbook(glob.glob(os.path.join(out, 'NXLD_04*.xlsx'))[0])['Роботы']
    cells = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert 'ВЕДОМСТВЕННЫЕ РОБОТЫ' in cells
    for col in ('Когда', 'IP', 'Сеть и оператор', 'Тип', 'Откуда пришли', 'Что смотрели', 'Что получили', 'Запросов', 'Error-лог'): assert col in cells, col
    assert any(t.startswith('Ведомственные роботы — проверяющие системы. ГРЧЦ — предприятие Роскомнадзора') and 'сами системы себя не называют, кроме сканера СайберОК' in t for t in cells)
    assert any('по логу не различить' in t for t in cells) and 'сканер защищённости' in cells and 'сканер под браузер' in cells and 'посетитель из госсети' in cells
    assert 'госсеть, ГРЧЦ (AS61280)' in ' '.join(cells)


def test_no_block_without_gov_visits(tmp_path):
    _, out, _ = synth.run(_base(), str(tmp_path))
    wb = openpyxl.load_workbook(glob.glob(os.path.join(out, 'NXLD_04*.xlsx'))[0])
    cells = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None]
    assert 'ВЕДОМСТВЕННЫЕ РОБОТЫ' not in cells and not any('Ведомственные роботы —' in t for t in cells)


def test_error_log_column_counts_tls_probe_by_days():
    log = _base(); _browser_scan(log)
    err = []
    for d in range(3):
        for k in range(4):
            err.append(f'2026/09/0{2 + d} 03:0{k}:01 [crit] 1#1: *{d}{k} SSL_do_handshake() failed (SSL: error:0A000101:SSL routines::bad key share) while SSL handshaking, client: {BOT_IP}, server: 0.0.0.0:443')
    res, _, _ = _run(log, err)
    row = res['gov_table'][res['gov_table']['ip'] == BOT_IP].iloc[0]
    assert row['errorlog'] == 'проба TLS: 12 за 3 дня', row['errorlog']
    assert res['gov_robots']['error_log']['lines'] == 12


def test_reference_has_sources_and_to_verify_and_no_clients():
    ref = os.path.join(synth.ENGINE, '..', 'data', 'reference', 'gov_robots.json')
    d = json.load(open(ref, encoding='utf-8'))
    ops = d['operators']
    assert set(ops) == {'grchc', 'cyberok'} and ops['grchc']['asn'] == [61280, 213853, 196641]
    nets = {p['net']: p for o in ops.values() for p in o['prefixes']}
    for n in ('185.224.228.0/22', '195.209.122.0/23', '212.192.156.0/22', '2a0c:a9c7:156::/48', '2a0c:a9c7:157::/48', '2a0c:a9c7:158::/48', '62.76.98.0/24', '194.165.22.0/23', '85.142.100.0/24', '212.192.158.0/24'):
        assert n in nets and nets[n]['source'], n
    assert 'неофициальн' in nets['212.192.158.0/24']['to_verify'] and ops['cyberok']['user_agents'] == ['CyberOKInspect']
    from nxld import gov
    assert gov.operator_of('185.224.230.5') == 'grchc' and gov.operator_of('2a0c:a9c7:157::1') == 'grchc' and gov.operator_of('203.0.113.9') == '' and gov.operator_of('9.9.9.9', 213853) == 'grchc'


def test_snapshot_and_comparison_with_previous_check(tmp_path):
    a, b = str(tmp_path / 'a'), str(tmp_path / 'b')
    os.makedirs(a); os.makedirs(b)
    log = _base(); _browser_scan(log)
    _, out, _ = synth.run(log, a)
    snap = glob.glob(os.path.join(out, '*.snapshot.json'))[0]
    assert json.load(open(snap, encoding='utf-8'))['gov_robots']['robots']['visits'] == 1
    log = _base(); _browser_scan(log); _browser_scan(log, BOT2_IP, day=2)
    synth.run(log, b, '--prev', snap)
    g = json.load(open(os.path.join(b, 'work', 'brief.json'), encoding='utf-8'))['gov_robots']
    assert g['robots']['visits'] == 2 and g['compare']['robot_visits'] == {'was': 1, 'became': 2}, g['compare']
