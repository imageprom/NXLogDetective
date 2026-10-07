"""Каталог листов (sheets.ORDERS) как страховка: на полном синтетическом прогоне все листы всех файлов — в каталоге."""
import glob
import os
import sys
from datetime import timedelta

import synth

sys.path.insert(0, synth.ENGINE)
from nxld import sheets  # noqa: E402
from nxld.brief import FILES  # noqa: E402

UA_GOOGLE = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'


def _log():
    log = synth.Log()
    log.people()
    for d in range(7):
        for k in range(30):   # поисковик, реклама и отказы защиты — чтобы строились листы 03–06
            log.line('66.249.66.10', synth.T0 + timedelta(days=d, minutes=40 * k + 2), synth.PAGES[k % len(synth.PAGES)], 403 if d == 3 else 200, ua=UA_GOOGLE)
        for k in range(5):
            log.visit(synth.RU[k], synth.T0 + timedelta(days=d, hours=18, minutes=9 * k), entry=f'/catalog/shary/?utm_source=yandex&utm_medium=cpc&utm_campaign=c{k}&yclid={d}{k}')
    return log


def _check(out, text):
    assert 'нет в каталоге оформления' not in text
    import openpyxl
    seen = 0
    for b, f in FILES.items():
        p = os.path.join(out, f)
        if not os.path.exists(p): continue
        names = openpyxl.load_workbook(p, read_only=True).sheetnames
        assert sheets.missing(b, names) == [], (f, sheets.missing(b, names))
        seen += 1
    return seen


def test_all_sheets_in_catalog(tmp_path):
    a, b, c = (os.path.join(tmp_path, x) for x in 'abc')
    for d in (a, b, c): os.makedirs(d)
    _, out, text = synth.run(_log(), a)   # все блоки
    assert _check(out, text) == 6
    snap = glob.glob(os.path.join(out, '*.snapshot.json'))[0]
    _, out, text = synth.run(_log(), b, '--prev', snap)   # повторная проверка: листы «Было → стало»
    assert _check(out, text) == 6
    _, out, text = synth.run(_log(), c, '--blocks', 'overview')   # без «Ботов»: лист «IP» — в 01
    assert _check(out, text) >= 2


def test_missing_reports_unknown():
    assert sheets.missing('Ошибки', ['Обзор', 'Проблемы', 'Мягкие ошибки', '_snapshot']) == []
    assert sheets.missing('Ошибки', ['Обзор', 'Новый лист']) == ['Новый лист']
