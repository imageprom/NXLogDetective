"""Кто такие «Люди»: визиты без страниц, сканеры со «статикой» (задачи #1, #3)."""
import sys
from datetime import timedelta

import synth

sys.path.insert(0, synth.ENGINE)

UA_MODERN = ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/12{}.0.0.0 Safari/537.36',
             'Mozilla/5.0 (iPhone; CPU iPhone OS 17_{} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1']
UA_IMPOSSIBLE = ['Mozilla/5.0 (Windows; U; Windows 95; en-US) AppleWebKit/533.1 (KHTML, like Gecko) Chrome/12.0 Safari/533.1',
                 'Mozilla/5.0 (iPhone; U; CPU iPhone OS 3_3 like Mac OS X; en-us) AppleWebKit/531.21.10 (KHTML, like Gecko) Mobile/7B405',
                 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:115.0) Gecko/20990101 Firefox/115.0']


def hosting_ip(i):
    return f'51.15.{i // 250}.{i % 250 + 1}'   # одна хостинговая сеть


def test_impossible_ua():
    from nxld.visits import impossible_ua
    for u in UA_IMPOSSIBLE:
        assert impossible_ua(u, 2026), u
    for u in UA_MODERN + [synth.UA_CHROME, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0']:
        assert not impossible_ua(u.format(5), 2026), u


def test_files_only_visits_are_not_people(tmp_path):
    log = synth.Log()
    log.people()
    for i in range(500):   # 500 IP хостинга: по одному запросу к картинке каталога без реферера, ответ 404
        ua = (UA_IMPOSSIBLE + UA_MODERN)[i % 5].format(i % 9)
        log.line(hosting_ip(i), synth.T0 + timedelta(days=i % 7, hours=1, seconds=i), f'/upload/resize_cache/iblock/{i % 50}/500_500_1/p{i}.jpg', 404, ua=ua)
    res, _, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Общий анализ']['Люди и боты']
    people = G[G['группа'] == 'Люди']
    files = G[G['подгруппа'].astype(str).str.startswith('файлы без страниц')]
    assert int(people['визитов'].sum()) == 7 * 20, G   # в «Людях» — только обычные визиты людей (страница + ресурсы)
    assert int(files['визитов'].sum()) >= 400, G   # остальные 100 и раньше уходили в боты по другому правилу
    assert 'генератор User-Agent' in ' '.join(files['подгруппа'].astype(str))
    au = res['audience']
    assert au['страна'] == 'RU' and not au['предупреждение']


def test_audience_warning():
    """Сводка 01: доля людей из страны основной аудитории; ниже порога (data/thresholds.json) — предупреждение."""
    import pandas as pd
    from nxld.visits import audience
    V = pd.DataFrame({'group': ['Люди'] * 10 + ['Боты'] * 5, 'cc': ['RU'] * 4 + ['US'] * 3 + ['DE'] * 3 + ['RU'] * 5})
    a = audience(V)
    assert a['страна'] == 'RU' and a['доля'] == 40.0 and a['предупреждение']
    V.loc[4:6, 'cc'] = 'RU'
    assert not audience(V)['предупреждение']


# ---- задача #3: сканер со «статикой» ----
STRONG = [f'/{p}' for p in ('.env', '.git/config', '.env.local', '.env.prod', 'wp-config.php.bak', '.aws/credentials', 'phpinfo.php', '.git/HEAD',
                            'server-status', 'wp-login.php', 'xmlrpc.php', '.svn/entries', 'backup.sql', 'dump.sql', 'wp-admin/', 'phpmyadmin/')]
FOREIGN_STATIC = [f'/wp-includes/js/jquery/jquery{i}.js' for i in range(8)] + [f'/media/jui/js/bootstrap{i}.min.js' for i in range(8)]


def cloud_ip(n, net):
    return f'34.{net}.10.{n + 5}'   # облако


def scanner_visit(log, ip, t0, paths, static_ref='-', static=FOREIGN_STATIC):
    """Отпечаток визита: 256 путей-зондов + 16 «статики» чужого движка, ни одна не подгружена страницей визита."""
    k = 0
    for p in paths:
        log.line(ip, t0 + timedelta(seconds=k), p, 404); k += 1
    for s in static:
        log.line(ip, t0 + timedelta(seconds=k), s, 404, ref=static_ref); k += 1
    log.line(ip, t0 + timedelta(seconds=k), '/', 200)   # одна живая страница — «веер 404» не срабатывает


def test_scanner_with_static_is_not_people(tmp_path):
    log = synth.Log()
    log.people()
    strong = [STRONG[i % 16] if i < 16 else f'/{i}{STRONG[i % 16]}' for i in range(256)]
    unknown = [f'/components/com_{w}{i}/' for i, w in zip(range(256), ['jce', 'fabrik', 'media', 'user'] * 64)]   # чужой движок, путей нет в probes.json
    for n in range(5):   # однозначные зонды + статика без реферера-страницы
        scanner_visit(log, cloud_ip(n, 90), synth.T0 + timedelta(days=n, hours=2), strong)
    for n in range(5):   # неизвестные справочнику зонды + статика с реферером-страницей, которую визит не открывал
        scanner_visit(log, cloud_ip(n, 120), synth.T0 + timedelta(days=n, hours=4), unknown, static_ref='https://site.ru/catalog/',
                      static=[f'/media/jui/js/bootstrap{i}.min.js' for i in range(16)])   # статика Joomla — её нет в probes.json
    res, _, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Общий анализ']['Люди и боты']
    assert int(G.loc[G['группа'] == 'Люди', 'визитов'].sum()) == 7 * 20, G   # обычные люди со статикой — по-прежнему люди
    sc = G[G['подгруппа'].astype(str).str.startswith('сканер')]
    assert int(sc['визитов'].sum()) >= 5, G   # однозначные зонды — «Боты: сканер», независимо от статики
