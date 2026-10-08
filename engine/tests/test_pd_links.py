"""@ и «email=» внутри внешней ссылки goto= — не персональные данные; открытый редирект — своя карточка (задача #4)."""
from datetime import timedelta

import synth

UA_BOT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
SPAM = '/bitrix/redirect.php?goto=https://example.com/@channel?ref=a&email=promo@example.net'   # параметры чужого адреса — не наши


def _log(redirect_302=True):
    log = synth.Log()
    log.people()
    for i in range(300):   # боты: тот же адрес с разных IP хостинга с разницей в секунду, ответы 403/404
        ip = f'51.15.{i // 100}.{i % 100 + 1}'
        log.line(ip, synth.T0 + timedelta(days=i % 7, hours=5, seconds=i), SPAM, 403 if i % 2 else 404, ua=UA_BOT)
    if redirect_302:
        log.line('51.15.9.9', synth.T0 + timedelta(days=2, hours=6), '/bitrix/redirect.php?goto=https://example.org/landing', 302, ua=UA_BOT)
    t = synth.T0 + timedelta(days=3, hours=11)   # человек отправил форму методом GET с почтой
    log.visit(synth.RU[0], t, entry='/feedback/')
    log.line(synth.RU[0], t + timedelta(seconds=120), '/feedback/?name=Ivan&email=ivan@example.com', 200, ref='https://site.ru/feedback/')
    return log


def test_link_params_not_pd(tmp_path):
    res, _, _ = synth.run(_log(), str(tmp_path))
    keys = {x['key'].split(':')[1]: x for x in res['findings']}
    pd_ = keys.get('pd_in_get')
    assert pd_ is not None, 'человек с email= в GET — карточка ПД остаётся'
    assert pd_['главная_цифра'] == 1 and 'redirect.php' not in pd_['факты'], pd_
    od = keys.get('open_redirect')
    assert od and od['блок'] == 'Нагрузка и безопасность' and '/bitrix/redirect.php' in od['факты'], od


def test_no_open_redirect_without_3xx(tmp_path):
    res, _, _ = synth.run(_log(redirect_302=False), str(tmp_path))
    assert not any(x['key'].split(':')[1] == 'open_redirect' for x in res['findings'])


def test_has_pd_skips_links():
    import sys
    sys.path.insert(0, synth.ENGINE)
    from nxld.recon import has_pd
    assert not has_pd('goto=https://example.com/@channel?ref=a&email=promo@example.net')
    assert not has_pd('url=https%3A%2F%2Fexample.com%2Fuser%40example.net')
    assert not has_pd('backurl=//example.com/x?mail=a@example.net')
    assert has_pd('name=Ivan&email=ivan@example.com')
    assert has_pd('email=ivan@example.com&goto=https://example.com/')


def test_mask_still_hides_email_in_links():
    """В отчёте почта внутри чужой ссылки по-прежнему маскируется (детектор карточки её не считает, маскировка — да)."""
    import sys
    sys.path.insert(0, synth.ENGINE)
    from openpyxl import Workbook
    from nxld.report_tables import mask_pd_cells
    wb = Workbook()
    wb.active['A1'] = SPAM
    mask_pd_cells(wb)
    assert 'promo@example.net' not in wb.active['A1'].value and 'goto=https://example.com/@channel' in wb.active['A1'].value
