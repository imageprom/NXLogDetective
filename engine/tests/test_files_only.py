"""Визиты «только файлы» (задача #1, раунд 3): решает поведение, сеть — слабая подсказка; «Подозрительные лица» — без дел;
служебные файлы не в счёт; бэкапы — раньше всех правил."""
import json
import os
from datetime import timedelta

import synth
from test_probes import bitrix_log

UA = ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/12{}.0.0.0 Safari/537.36',
      'Mozilla/5.0 (iPhone; CPU iPhone OS 17_{} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_{}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15']
HOME = lambda i: f'95.165.{150 + i // 200}.{i % 200 + 1}'   # домашняя сеть
DC = lambda i: f'51.15.{60 + i // 200}.{i % 200 + 1}'   # дата-центр
VPN = lambda i: f'104.28.{i // 200}.{i % 200 + 1}'   # прокси-релей: ни дом, ни дата-центр
TUE = synth.T0   # 1 сентября 2026 — вторник


def _groups(res):
    G = res['sheets']['Общий анализ']['Люди и боты']
    return G, (lambda g, sg=None: int(G.loc[(G['группа'] == g) & ((G['подгруппа'].astype(str) == sg) if sg is not None else True), 'визитов'].sum()))


def _v(res, ips):
    """Визиты «Подозрительных лиц» этих IP из данных (res['suspects'])."""
    S = res['suspects']
    return S[S['ip'].astype(str).isin(set(ips))]


def test_behaviour_labels(tmp_path):
    log = synth.Log()
    log.people()
    # соседи по адресу: с IP смотрят страницы, через 10 минут другой браузер берёт только картинку без реферера — «Люди»
    for i in range(20):
        t = TUE + timedelta(days=i % 7, hours=13, minutes=i)
        log.visit(DC(100 + i), t)
        log.line(DC(100 + i), t + timedelta(minutes=10), f'/upload/iblock/7/n{i}.jpg', 200, ua=UA[1].format(i % 9))
    # реферер — страницы самого сайта (поддомен тоже): не «Свои»; дом — «Люди», дата-центр — «Подозрительные лица»
    for i in range(15):
        log.line(HOME(i), TUE + timedelta(days=i % 7, hours=2, seconds=i), f'/upload/iblock/2/s{i}.png', 200, ref='https://site.ru/catalog/', ua=UA[0].format(i % 9))
        log.line(DC(i), TUE + timedelta(days=i % 7, hours=2, seconds=i), f'/upload/iblock/2/d{i}.png', 200, ref='https://site.ru/catalog/', ua=UA[0].format(i % 9))
    # служебные файлы — не «только файлы»
    for i in range(12):
        for k, u in enumerate(('/robots.txt', '/sitemap.xml', '/favicon.ico', '/apple-touch-icon.png')):
            log.line(DC(200 + i), TUE + timedelta(days=i % 7, hours=4, seconds=k), u, 200, ua=UA[0].format(i % 9))
    # повторы: один файл снова и снова — «Боты · только файлы: скрапер»
    for k in range(6):
        log.line(HOME(300), TUE + timedelta(days=3, hours=5, minutes=40 * k), '/upload/iblock/1/same.jpg', 200, ua=UA[0].format(1))
    # почти одни 404, много с одного адреса — «…: запрашивает несуществующие файлы»; одна 404 из дома — «Люди» (старая ссылка)
    for k in range(8):
        log.line(HOME(301), TUE + timedelta(days=4, hours=6, minutes=40 * k), f'/upload/old/{k}.jpg', 404, ua=UA[0].format(2))
    for i in range(10):
        log.line(HOME(400 + i), TUE + timedelta(days=i % 7, hours=7, seconds=i), '/upload/old/gone.jpg', 404, ua=UA[0].format(i % 9))
    # офис за прокси-релеем: много браузеров с IP, будни, рабочие часы — без реферера картинка — «Люди · открыл файл по прямой ссылке»
    for j, u in enumerate(UA):
        for k, p in enumerate(('/', '/about/')):
            log.line(VPN(500), TUE + timedelta(days=1, hours=9, minutes=j, seconds=k), p, 200, ua=u.format(j))
            for a in synth.ASSETS: log.line(VPN(500), TUE + timedelta(days=1, hours=9, minutes=j, seconds=k + 1), a, 200, ua=u.format(j), ref=f'https://site.ru{p}')
    log.line(VPN(500), TUE + timedelta(days=1, hours=15), '/upload/iblock/4/office.jpg', 200, ua=UA[2].format(7))
    # медиа: видео целиком и большое — скачивание; 206 — обвес
    for i in range(5):
        log.line(HOME(600 + i), TUE + timedelta(days=i, hours=20), '/upload/video/promo.mp4', 200, ua=UA[0].format(i), size=30_000_000)
        log.line(HOME(700 + i), TUE + timedelta(days=i, hours=20), '/upload/video/promo.mp4', 206, ua=UA[0].format(i), size=30_000_000)
    res, _, _ = synth.run(log, str(tmp_path))
    G, cnt = _groups(res)
    subs = set(G['подгруппа'].astype(str))
    assert cnt('Свои') == 0 and 'свои системы' not in subs, G   # ссылка со страниц самого сайта — не «Свои»
    assert cnt('Люди', '') >= 7 * 20 + 20 + 15 + 10, G   # соседи, свой реферер из дома, старая ссылка
    sus = _v(res, [DC(i) for i in range(15)])
    assert len(sus) == 15 and (sus['evidence_bot'] == 'дата-центр').all() and (sus['evidence_people'] == '').all(), sus
    assert not any(s.startswith('только файлы: открывает') or s == 'только файлы: прочие' or s == 'через внешний сайт' for s in subs), subs
    assert cnt('Боты', 'только файлы: скрапер') >= 1, G
    assert cnt('Боты', 'только файлы: запрашивает несуществующие файлы') >= 1, G
    assert cnt('Люди', 'открыл файл по прямой ссылке') >= 1 + 5, G   # офис и 206 из дома
    assert cnt('Люди', 'скачал документ') == 5, G   # видео целиком
    # служебные файлы — не «только файлы» и не боты по ним
    assert not (set(_v(res, [DC(200 + i) for i in range(12)])['ip']))
    Pf = res['profiles'] or {}
    in_cases = {ip for d in Pf.get('дела', []) for ip in d.get('ips', [])}
    assert not in_cases & {DC(i) for i in range(15)}


ADMIN_IP, ADMIN_UA = '95.165.200.1', UA[2].format(5)
FORM = 5100


def _backup_log():
    log = bitrix_log()   # сайт на Битриксе: сотрудники — по входу в его админку
    for d in range(5):   # сотрудник работает в админке
        t = TUE + timedelta(days=d, hours=10)
        log.line(ADMIN_IP, t, '/bitrix/admin/', 200, size=FORM, ua=ADMIN_UA)
        log.line(ADMIN_IP, t + timedelta(seconds=20), '/bitrix/admin/index.php?login=yes', 302, method='POST', size=0, ua=ADMIN_UA)
        log.line(ADMIN_IP, t + timedelta(seconds=21), '/bitrix/admin/index.php', 200, size=48000 + d, ua=ADMIN_UA)
        for k in range(6):
            log.line(ADMIN_IP, t + timedelta(seconds=60 + 30 * k), '/bitrix/admin/sale_order.php', 200, size=30000 + 997 * k, ua=ADMIN_UA)
    # перенос: тем же браузером с домашнего адреса — архив частями и restore.php
    t = TUE + timedelta(days=5, hours=12)
    for k, p in enumerate(('/bitrix/backup/site_20260906.tar.gz', '/bitrix/backup/site_20260906.tar.gz.1', '/bitrix/backup/site_20260906.tar.gz.2')):
        log.line(HOME(900), t + timedelta(minutes=k), p, 200, ua=ADMIN_UA, size=(200_000_000, 199_000_000, 120_000_000)[k])
    log.line(HOME(900), t + timedelta(minutes=5), '/restore.php', 200, ua=ADMIN_UA, size=40000)
    # тот же бэкап после переноса скачали ещё три адреса — каждый в дело (свой перенос не делает бэкап «адресом сайта»)
    for i in range(3):
        log.line(HOME(960 + i), t + timedelta(hours=3 + i), '/bitrix/backup/site_20260906.tar.gz', 200, ua=UA[0].format(i), size=200_000_000)
    # разовое скачивание без связи с админкой и без поиска
    log.line(HOME(901), TUE + timedelta(days=2, hours=16), '/bitrix/backup/old_20260801.tar.gz', 200, ua=UA[0].format(3), size=150_000_000)
    # искал бэкапы по разным адресам, потом скачал
    t = TUE + timedelta(days=3, hours=3)
    for k, p in enumerate(('/backup.zip', '/site.sql', '/backup/db.sql', '/www.zip')):
        log.line(DC(901), t + timedelta(seconds=k), p, 404, ua=UA[0].format(4))
    log.line(DC(901), t + timedelta(seconds=10), '/bitrix/backup/old_20260801.tar.gz', 200, ua=UA[0].format(4), size=150_000_000)
    # один бэкап скачан многими адресами
    for i in range(3):
        log.line(HOME(950 + i), TUE + timedelta(days=4, hours=1 + i), '/backup_full.tar.gz', 200, ua=UA[1].format(i), size=90_000_000)
    return log


def test_backups(tmp_path):
    res, _, _ = synth.run(_backup_log(), str(tmp_path), '--site', 'example.com')
    assert ADMIN_IP in res['site_map']['staff_ips']
    G, cnt = _groups(res)
    B = {(b['ip'], b['файл']): b for b in res['backups']}
    own = B[(HOME(900), '/bitrix/backup/site_20260906.tar.gz')]
    assert own['категория'] == 'Свои' and 'обвинения_сняты' in own, own   # факт — в данных
    assert B[(HOME(901), '/bitrix/backup/old_20260801.tar.gz')]['категория'] == 'Подозрительные лица'
    assert B[(DC(901), '/bitrix/backup/old_20260801.tar.gz')]['категория'] == 'Боты'
    assert all(B[(HOME(950 + i), '/backup_full.tar.gz')]['категория'] == 'Боты' for i in range(3))
    assert cnt('Свои', 'скачал бэкап') >= 1 and cnt('Подозрительные лица', 'скачал бэкап') == 1, G
    assert not any('скачал документ' == s for s in G['подгруппа'].astype(str)), G   # бэкап — никогда не «скачал документ»
    Pf = res['profiles'] or {}
    in_cases = {ip for d in Pf.get('дела', []) for ip in d.get('ips', [])}
    assert HOME(900) not in in_cases and HOME(901) not in in_cases, in_cases
    assert DC(901) in in_cases and all(HOME(950 + i) in in_cases and HOME(960 + i) in in_cases for i in range(3)), in_cases
    MI = Pf.get('меры_ip')
    mi = set(MI['ip'].astype(str)) if MI is not None and len(MI) else set()
    assert not mi & {HOME(900), HOME(901)}
    assert any(x['key'].split(':')[1] == 'exposed' for x in res['findings'])   # доступность бэкапа — находка


def test_thresholds_have_to_verify():
    T = json.load(open(os.path.join(synth.ENGINE, '..', 'data', 'thresholds.json'), encoding='utf-8'))
    new = [k for k in T if k.startswith(('files_', 'backup_'))]
    assert len(new) >= 10 and all(T[k].get('to_verify') and 'value' in T[k] for k in new), new
    assert 'внешний_сайт_запросов_с_адреса_от' not in T and 'только_файлы_скрапер_от' not in T
