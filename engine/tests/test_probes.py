"""Страница входа движка (/auth/ на Битриксе) — не зонд; /wp-login.php на том же сайте — зонд (задача #2)."""
from datetime import timedelta

import synth

BX = ['/bitrix/templates/shop/style.css', '/bitrix/js/main/core/core.js', '/upload/iblock/a1/item.jpg']
UA_SCAN = 'Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0'
SCAN = ('/wp-login.php', '/.env', '/wp-admin/', '/xmlrpc.php', '/.git/config', '/wp-login.php?action=register',
        '/administrator/', '/phpmyadmin/', '/wp-content/plugins/x/readme.txt', '/config.php.bak', '/backup.zip', '/.env.bak')


def bitrix_log():
    """Сайт на Битриксе (example.com): люди с карточек товара переходят на /auth/?backurl=… и получают 200 одного размера;
    за IP мобильной сети — много покупателей; сканер перебирает /wp-login.php и прочее."""
    log = synth.Log()
    for d in range(7):
        for k in range(40):
            ip = f'95.165.{k}.{d + 10}'
            t = synth.T0 + timedelta(days=d, hours=9, minutes=15 * k)
            item = f'/catalog/item-{k % 25}/'
            log.line(ip, t, item, 200, ref='https://yandex.ru/', size=40000 + k)
            for a in BX: log.line(ip, t + timedelta(seconds=1), a, 200, ref=f'https://example.com{item}')
            log.line(ip, t + timedelta(seconds=40), f'/auth/?backurl={item}', 200, ref=f'https://example.com{item}', size=5100)
            for a in BX: log.line(ip, t + timedelta(seconds=41), a, 200, ref='https://example.com/auth/')
            if k % 4 == 0: log.line(ip, t + timedelta(seconds=90), '/auth/index.php?forgot_password=yes', 200, ref='https://example.com/auth/', size=5300)
        for j, u in enumerate(SCAN):
            log.line('185.220.101.5', synth.T0 + timedelta(days=d, hours=3, seconds=j), u, 404, ua=UA_SCAN)
    for j in range(12):   # IP мобильной сети: каждый раз карточка товара и страница входа
        t = synth.T0 + timedelta(days=j % 7, hours=13, minutes=7 * j)
        item = f'/catalog/item-{j}/'
        log.line('176.59.40.10', t, item, 200, ref='https://yandex.ru/', size=40100)
        for a in BX: log.line('176.59.40.10', t + timedelta(seconds=1), a, 200, ref=f'https://example.com{item}')
        log.line('176.59.40.10', t + timedelta(seconds=30), f'/auth/?backurl={item}', 200, ref=f'https://example.com{item}', size=5100)
        log.line('176.59.40.10', t + timedelta(seconds=35), '/auth/', 200, ref=f'https://example.com/auth/?backurl={item}', size=5100)
    return log


def test_engine_login_page_is_not_probe(tmp_path):
    res, _, _ = synth.run(bitrix_log(), str(tmp_path), '--site', 'example.com')
    assert any(e['движок'] == '1С-Битрикс' for e in res['site_map']['engines'])
    charges = [(d['кличка'], o['что']) for d in res['profiles']['дела'] for o in d['обвинения'] if o['id'] == 'recon']
    assert not any('/auth' in what for _, what in charges), charges   # «Разведка» — не за страницу входа
    assert any('/wp-login.php' in what for _, what in charges), charges   # сканер с /wp-login.php — по-прежнему зонд
    T = res['security']['сканеры'][0]
    assert int(T['страницы_сайта'].sum()) == 0, T   # /auth/ не среди целей сканеров
    P = {p['ключ']: p['группа'] for p in res['params']}
    assert P.get('backurl') != 'Атаки и зонды' and P.get('forgot_password') != 'Атаки и зонды'


def test_login_page_not_probe_in_02_03(tmp_path):
    """#7: одно правило «зонд = VULN и не страница сайта / вход движка» и в сводке 03, и в «Статистике» 03, и в «Серверном
    фильтре»: запросы людей к /auth/ — не сканеры; отказ людям 403 на /auth/ виден в фильтре."""
    log = bitrix_log()
    for k in range(30):   # люди с карточки товара на /auth/ получают 403
        ip, t = f'198.51.100.{k + 1}', synth.T0 + timedelta(days=k % 7, hours=14, minutes=k)
        log.line(ip, t, '/catalog/item-1/', 200, ref='https://yandex.ru/', size=40000)
        for a in BX[:2]: log.line(ip, t + timedelta(seconds=1), a, 200, ref='https://example.com/catalog/item-1/')
        log.line(ip, t + timedelta(seconds=30), '/auth/?backurl=/catalog/item-1/', 403, ref='https://example.com/catalog/item-1/', size=500)
    res, _, _ = synth.run(log, str(tmp_path), '--site', 'example.com')
    n_scan = 7 * len(SCAN)   # только сканер 185.220.101.5
    assert res['summary']['Нагрузка и безопасность']['Запросов сканеров'] == n_scan, res['summary']['Нагрузка и безопасность']
    J = res['security']['журнал']
    assert int(J.loc[J['день'] == 'Итого', 'Сканеры|Запросов'].iloc[0]) == n_scan, J[['день', 'Сканеры|Запросов']]
    Fl = res['security']['фильтр']['таблица']
    assert len(Fl) and ((Fl['группа'] == 'Люди') & (Fl['код'] == 403) & (Fl['пример'].astype(str).str.startswith('/auth/'))).any(), Fl
    VQ = res['sheets']['Нагрузка и безопасность']['Сканеры: что искали']
    assert int(VQ['запросов'].sum()) == n_scan, VQ
