"""«Свои» (сотрудник) — по успешному входу и работе в админке, а не по форме входа, которую сервер отдаёт любому (задача #5)."""
from datetime import timedelta

import synth
from test_probes import bitrix_log

SPAM_IP, STAFF_IP = '203.0.113.50', '95.165.200.1'
UAS = ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/12{}.0.0.0 Safari/537.36',
       'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_{}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15']
FORM = 5100   # размер формы входа в админку


def _log():
    log = bitrix_log()
    for j in range(10):   # несколько раз в сутки: redirect.php?goto=<спам> → 302 → форма входа в админку (200, ~5 КБ), POST нет, UA меняется
        t = synth.T0 + timedelta(days=j % 7, hours=6 + j % 3, minutes=j)
        ua = UAS[j % 2].format(j % 7)
        log.line(SPAM_IP, t, f'/bitrix/redirect.php?goto=https://example.org/spam{j}', 302, ua=ua)
        log.line(SPAM_IP, t + timedelta(seconds=1), '/bitrix/admin/index.php', 200, ua=ua, size=FORM + j)
    for d in range(5):   # сотрудник: форма → POST-вход → рабочий стол → заказы и инфоблоки
        t = synth.T0 + timedelta(days=d, hours=10)
        log.line(STAFF_IP, t, '/bitrix/admin/', 200, size=FORM)
        log.line(STAFF_IP, t + timedelta(seconds=20), '/bitrix/admin/index.php?login=yes', 302, method='POST', size=0)
        log.line(STAFF_IP, t + timedelta(seconds=21), '/bitrix/admin/index.php', 200, size=48000 + d)
        for k in range(6):
            log.line(STAFF_IP, t + timedelta(seconds=60 + 30 * k), '/bitrix/admin/sale_order.php' if k % 2 else '/bitrix/admin/iblock_list_admin.php', 200, size=30000 + 997 * k)
    return log


def test_staff_by_login_not_by_form(tmp_path):
    res, _, _ = synth.run(_log(), str(tmp_path), '--site', 'example.com')
    staff = res['site_map']['staff_ips']
    assert STAFF_IP in staff, staff
    assert SPAM_IP not in staff, staff


def test_staff_rule_unit():
    import sys
    import pandas as pd
    sys.path.insert(0, synth.ENGINE)
    from nxld.recon import admin_staff
    rows = [(SPAM_IP, '/bitrix/admin/index.php', 'GET', 200, FORM + j) for j in range(10)]
    rows += [(STAFF_IP, '/bitrix/admin/', 'GET', 200, FORM), (STAFF_IP, '/bitrix/admin/index.php', 'POST', 302, 0), (STAFF_IP, '/bitrix/admin/index.php', 'GET', 200, 48000)]
    rows += [('198.51.100.7', '/bitrix/admin/sale_order.php', 'GET', 200, 30000 + 900 * k) for k in range(6)]   # работа без входа в этом логе (сессия раньше)
    A = pd.DataFrame(rows, columns=['ip', 'base', 'method', 'status', 'bytes'])
    s = admin_staff(A, '^/bitrix/admin/')
    assert set(s) == {STAFF_IP, '198.51.100.7'}, s
