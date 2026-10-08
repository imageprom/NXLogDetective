"""Сеть (откуда): «дата-центр» с названием компании вместо «хостинг/облако» — в данных, листах и правилах (задача #1)."""
import glob
import os
import sys
from datetime import timedelta

import synth

sys.path.insert(0, synth.ENGINE)


def test_dc_label_unit():
    from nxld.ipdb import nettype, is_dc, lookup
    T = lookup(['51.15.10.10', '66.249.66.10', '95.165.10.20'])
    nt = dict(zip(T['ip'], T['nettype']))
    assert nt['51.15.10.10'].startswith('дата-центр (') and is_dc(nt['51.15.10.10']), nt   # с названием компании
    assert is_dc(nt['66.249.66.10']) and not is_dc(nt['95.165.10.20']), nt
    assert nettype(15169, '', 'US') == 'дата-центр'   # компании нет — просто «дата-центр»


def test_no_hosting_label_in_reports(tmp_path):
    log = synth.Log()
    log.people()
    for k in range(30):   # парсер из дата-центра
        log.line('51.15.10.10', synth.T0 + timedelta(days=1, hours=2, seconds=5 * k), f'/catalog/item-{k}/', 200)
    res, out, _ = synth.run(log, str(tmp_path))
    import openpyxl
    seen_dc = False
    for f in glob.glob(os.path.join(out, '*.xlsx')):
        for ws in openpyxl.load_workbook(f, read_only=True).worksheets:
            for row in ws.iter_rows(values_only=True):
                for v in row:
                    if isinstance(v, str):
                        assert 'хостинг/облако' not in v, (os.path.basename(f), ws.title, v)
                        seen_dc |= 'дата-центр (' in v
    assert seen_dc   # подпись с названием компании видна в отчёте
