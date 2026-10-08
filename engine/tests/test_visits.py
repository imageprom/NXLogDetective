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
    files = G[G['подгруппа'].astype(str).str.startswith('только файлы: ')]
    assert int(people['визитов'].sum()) == 7 * 20, G   # в «Людях» — только обычные визиты людей (страница + ресурсы)
    assert int(files['визитов'].sum()) >= 400, G   # остальные 100 и раньше уходили в боты по другому правилу
    subs = set(files['подгруппа'].astype(str))
    assert 'только файлы: выдуманный браузер' in subs, subs
    assert not any(w in ' '.join(G['подгруппа'].astype(str)) for w in ('файлы без страниц', 'скрапер с хостинга', 'генератор User-Agent'))
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


# ---- задача #1, уточнения: поиск по картинкам и хотлинк ----
def test_image_search_is_people(tmp_path):
    """Визит из одних файлов с реферером поисковика — человек из поиска по картинкам: «Люди»; 404 на такие файлы —
    карточка «Люди приходят на несуществующие страницы: Поиск» остаётся."""
    log = synth.Log()
    log.people()
    for i in range(300):
        ip = f'95.165.{100 + i // 200}.{i % 200 + 1}'
        log.line(ip, synth.T0 + timedelta(days=i % 7, hours=15, seconds=i), f'/upload/iblock/{i % 40}/photo{i}.jpg', 404 if i % 3 == 0 else 200,
                 ref='https://yandex.ru/images/search?text=example', ua=UA_MODERN[i % 2].format(i % 9))
    res, _, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Общий анализ']['Люди и боты']
    img = G[(G['группа'] == 'Люди') & (G['подгруппа'].astype(str) == 'из поиска по картинкам')]
    assert int(img['визитов'].sum()) == 300, G
    assert any(x['key'] == 'Ошибки:404_entry:Поиск' for x in res['findings'])


DC_IP = lambda i: f'51.15.{60 + i // 200}.{i % 200 + 1}'   # дата-центр
HOME_IP = lambda i: f'95.165.{150 + i // 200}.{i % 200 + 1}'   # домашняя сеть
VPN_IP = lambda i: f'104.28.{i // 200}.{i % 200 + 1}'   # прокси-релей (признаков не хватает)


def test_hotlink_categories(tmp_path):
    """Хотлинк (реферер — внешний сайт): браузеры из домашних сетей — «Люди · хотлинк»; сервер внешнего сайта (дата-центр,
    ровный темп, много с одного адреса) — «Боты · через внешний сайт»; признаков не хватает — «Внешние сайты · хотлинк».
    Хотлинк-посетители не попадают в дела и «Меры по IP»; групп «Чужой сайт» нет."""
    log = synth.Log()
    log.people()
    for i in range(120):   # разные люди из домашних сетей
        log.line(HOME_IP(i), synth.T0 + timedelta(days=i % 7, hours=16, seconds=i), f'/upload/iblock/{i % 40}/photo{i}.jpg', 200,
                 ref='https://blog.example.org/post-1', ua=UA_MODERN[i % 2].format(i % 9))
    for k in range(60):   # сервер внешнего сайта: один адрес дата-центра, ровно раз в 2 секунды
        log.line(DC_IP(0), synth.T0 + timedelta(days=2, hours=3, seconds=2 * k), f'/upload/iblock/9/item{k}.jpg', 200, ref='https://shop.example.net/catalog/', ua=UA_MODERN[0].format(3))
    for i in range(30):   # прокси-релей: не дом и не дата-центр — признаков не хватает
        log.line(VPN_IP(i), synth.T0 + timedelta(days=i % 7, hours=18, seconds=i), f'/upload/iblock/{i % 40}/p{i}.jpg', 200,
                 ref='https://forum.example.com/t/1', ua=UA_MODERN[1].format(i % 9))
    res, _, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Общий анализ']['Люди и боты']
    cnt = lambda g, sg: int(G.loc[(G['группа'] == g) & (G['подгруппа'].astype(str) == sg), 'визитов'].sum())
    assert cnt('Люди', 'хотлинк') == 120, G
    assert cnt('Боты', 'через внешний сайт') >= 1, G
    assert cnt('Внешние сайты', 'хотлинк') == 30, G
    assert 'Чужой сайт' not in set(G['группа']), G
    Pf = res['profiles'] or {}
    hot = {HOME_IP(i) for i in range(120)} | {VPN_IP(i) for i in range(30)}
    in_cases = {ip for d in Pf.get('дела', []) for ip in d.get('ips', [])}
    MI = Pf.get('меры_ip')
    in_mi = set(MI['ip'].astype(str)) if MI is not None and len(MI) else set()
    assert not (in_cases | in_mi) & hot


def test_files_only_direct_link_and_own(tmp_path):
    """Без реферера: из домашней сети — «Люди · открыл файл по прямой ссылке»; из дата-центра — «Боты · только файлы:
    открывает файлы по прямой ссылке» или «…: скрапер» (много файлов с адреса). Реферер — свои системы (own_hosts) — «Свои»."""
    import json, os
    log = synth.Log()
    log.people()
    for i in range(50):   # ссылку на файл прислали в мессенджере
        log.line(HOME_IP(i), synth.T0 + timedelta(days=i % 7, hours=20, seconds=i), f'/upload/docs/price{i % 5}.pdf', 200, ua=UA_MODERN[i % 2].format(i % 9))
    for i in range(20):   # один файл из дата-центра
        log.line(DC_IP(i + 10), synth.T0 + timedelta(days=i % 7, hours=21, seconds=i), '/upload/docs/price1.pdf', 200, ua=UA_MODERN[0].format(i % 9))
    for k in range(10):   # много файлов с одного адреса дата-центра
        log.line(DC_IP(5), synth.T0 + timedelta(days=4, hours=22, minutes=k), f'/upload/iblock/3/pic{k}.jpg', 200, ua=UA_MODERN[0].format(2))
    for i in range(15):   # письма и CRM: реферер — свой хост (копия сайта, почта)
        log.line(HOME_IP(300 + i), synth.T0 + timedelta(days=i % 7, hours=11, seconds=i), '/upload/mail/logo.png', 200, ref='https://crm.example-own.ru/deal/1', ua=UA_MODERN[0].format(1))
    ovr = os.path.join(str(tmp_path), 'map.json')
    json.dump({'own_hosts': ['crm.example-own.ru']}, open(ovr, 'w'))
    res, _, _ = synth.run(log, str(tmp_path), '--map-override', ovr)
    G = res['sheets']['Общий анализ']['Люди и боты']
    cnt = lambda g, sg: int(G.loc[(G['группа'] == g) & (G['подгруппа'].astype(str) == sg), 'визитов'].sum())
    assert cnt('Люди', 'открыл файл по прямой ссылке') == 50, G
    assert cnt('Боты', 'только файлы: открывает файлы по прямой ссылке') == 20, G
    assert cnt('Боты', 'только файлы: скрапер') >= 1, G
    assert cnt('Свои', 'свои системы') == 15, G


def test_page_parser_class(tmp_path):
    """Класс ботов «парсер страниц» (бывший «парсер»): много страниц без единого файла оформления."""
    log = synth.Log()
    log.people()
    for k in range(30):
        log.line(DC_IP(1), synth.T0 + timedelta(days=1, hours=2, seconds=5 * k), f'/catalog/item-{k}/', 200, ua=UA_MODERN[0].format(4))
    res, _, _ = synth.run(log, str(tmp_path))
    K = res['sheets']['Боты']['Боты: классы']
    assert 'парсер страниц' in set(K['класс']) and 'парсер' not in set(K['класс']), K
