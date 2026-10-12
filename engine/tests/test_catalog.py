"""Каталог структуры отчёта data/locale/ru/report_structure.json (задача #8): состав, порядок, статусы, вкладки и заголовки листов."""
import glob
import json
import os
import re
import sys
from datetime import timedelta

import openpyxl
import synth

sys.path.insert(0, synth.ENGINE)
from nxld import catalog, sheets  # noqa: E402

UA_GOOGLE = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
UA_SCAN = 'Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0'
CAT = os.path.join(synth.ENGINE, '..', 'data', 'locale', 'ru', 'report_structure.json')
LINK = re.compile(r"^(?P<file>[^#]*)#'(?P<sheet>(?:[^']|'')+)'!\S+$")
SEO_TABS = ('Поисковые ошибки', 'Органика', 'Паразитные адреса', 'ИИ-роботы', 'ИИ-видимость', 'Обход поисковиками')


def _log():
    log = synth.Log()
    log.people()
    for d in range(7):
        for k in range(30):   # поисковик, реклама и отказы защиты — чтобы строились листы 03–06
            log.line('66.249.66.10', synth.T0 + timedelta(days=d, minutes=40 * k + 2), synth.PAGES[k % len(synth.PAGES)], 403 if d == 3 else 200, ua=UA_GOOGLE)
        for k in range(5):
            log.visit(synth.RU[k], synth.T0 + timedelta(days=d, hours=18, minutes=9 * k), entry=f'/catalog/shary/?utm_source=yandex&utm_medium=cpc&utm_campaign=c{k}&yclid={d}{k}')
        for j, u in enumerate(('/.env', '/wp-login.php', '/phpinfo.php', '/.git/config', '/backup.sql')):
            log.line('198.51.100.7', synth.T0 + timedelta(days=d, hours=2, seconds=j), u, 404, ua=UA_SCAN)
    return log


def _books(out):
    return {os.path.basename(p): openpyxl.load_workbook(p) for p in glob.glob(os.path.join(out, 'NXLD_*.xlsx'))}


def _dead_links(books):
    bad = []
    for f, wb in books.items():
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if c.hyperlink is None: continue
                    m = LINK.match(c.hyperlink.location or c.hyperlink.target or '')
                    if not m: continue
                    tf, sh = m.group('file') or f, m.group('sheet').replace("''", "'")
                    if tf not in books or sh not in books[tf].sheetnames: bad.append((f, ws.title, c.coordinate, sh))
    return bad


def _heading_static(e):
    """Статическая часть заголовка из каталога (до первой динамической части)."""
    h = e['heading']
    if isinstance(h, str): return h
    return ' '.join(p['text'] for line in h for p in line if 'text' in p)


def _check_against_catalog(books):
    """В каждом файле — только approved, порядок и вкладки — как в каталоге, заголовки — из каталога, служебный _snapshot — скрыт."""
    C = json.load(open(CAT, encoding='utf-8'))
    for fe in C['files']:
        wb = books.get(fe['file'])
        if wb is None: continue
        tabs = [s['tab'] for s in fe['sheets']]
        approved = [s['tab'] for s in fe['sheets'] if s['status'] == 'approved']
        names = [n for n in wb.sheetnames if n != '_snapshot']
        assert set(names) <= set(approved), (fe['file'], sorted(set(names) - set(approved)))
        assert names == sorted(names, key=tabs.index), (fe['file'], names)
        for s in fe['sheets']:
            if s['tab'] not in wb.sheetnames or not s['heading']: continue
            ws = wb[s['tab']]
            top = [str(ws.cell(r, 2).value or '') for r in range(1, 7)]
            hs = _heading_static(s)
            if any(t.startswith(hs) for t in top if t): continue
            assert not any(t.upper() == s['tab'].upper() for t in top), (fe['file'], s['tab'], top)   # заголовок есть, но не из каталога


def test_codes_and_builders():
    """Каждый код каталога знает оформление (sheets.CODES), и каждый лист, который строит оформление, есть в каталоге."""
    C = json.load(open(CAT, encoding='utf-8'))
    for fe in C['files']:
        b = catalog.block_of(fe['code'])
        codes = [s['code'] for s in fe['sheets']]
        assert set(codes) == set(sheets.CODES[b]), (fe['file'], set(codes) ^ set(sheets.CODES[b]))
        assert len(codes) == len(set(codes)) and [s['num'] for s in fe['sheets']] == list(range(1, len(codes) + 1))
        for s in fe['sheets']:
            assert s['status'] in ('approved', 'review', 'off') and s['tab'] and all(re.fullmatch(r'[a-z_]+', k) for k in s), s
    assert [f['num'] for f in C['files']] == ['01', '02', '03', '04', '05', '06']
    assert sheets.missing('Ошибки', ['Обзор', 'Проблемы', 'Мягкие ошибки', '_snapshot']) == []
    assert sheets.missing('Ошибки', ['Обзор', 'Новый лист']) == ['Новый лист']


def test_full_run_only_approved(tmp_path):
    """Все блоки, --check-ips и --prev: только approved, порядок, вкладки и заголовки — из каталога, ссылки живые; «Было → стало»
    и «Подозреваемые» (review) не выводятся, в журнале — строка о каждом."""
    a, b = os.path.join(tmp_path, 'a'), os.path.join(tmp_path, 'b')
    os.makedirs(a); os.makedirs(b)
    _, out, _ = synth.run(_log(), a)
    snap = glob.glob(os.path.join(out, '*.snapshot.json'))[0]
    _, out, text = synth.run(_log(), b, '--prev', snap, '--check-ips', '198.51.100.7,66.249.66.10')
    books = _books(out)
    assert len(books) == 6
    _check_against_catalog(books)
    assert not _dead_links(books), _dead_links(books)[:10]
    assert 'лист «Было → стало» не утверждён, не выводится' in text and 'лист «Подозреваемые» не утверждён, не выводится' in text
    assert not any('Было → стало' in wb.sheetnames for wb in books.values())
    assert 'Подозреваемые' not in books['NXLD_04_Bots.xlsx'].sheetnames


def test_snapshot_sheet(tmp_path):
    """Служебный «_snapshot» в 01 — не лист каталога: на месте, последним и скрыт."""
    _, out, _ = synth.run(_log(), str(tmp_path))
    wb = openpyxl.load_workbook(os.path.join(out, 'NXLD_01_Overview.xlsx'))
    assert wb.sheetnames[-1] == '_snapshot' and wb['_snapshot'].sheet_state == 'hidden'
    assert json.loads(''.join(c.value for c in wb['_snapshot']['A'][1:] if c.value))['tool'] == 'NX Log Detective'


def test_without_bots_and_seo(tmp_path):
    """Без «Ботов» и SEO: в 01 нет «IP», в 02–05 нет SEO-листов («запасных мест» нет)."""
    _, out, _ = synth.run(_log(), str(tmp_path), '--blocks', 'overview,errors,load,marketing')
    books = _books(out)
    assert 'NXLD_04_Bots.xlsx' not in books and 'NXLD_06_SEO.xlsx' not in books
    assert 'IP' not in books['NXLD_01_Overview.xlsx'].sheetnames
    for f, wb in books.items():
        assert not set(SEO_TABS) & set(wb.sheetnames), (f, wb.sheetnames)
    _check_against_catalog(books)
    assert not _dead_links(books), _dead_links(books)[:10]


def test_catalog_edit_changes_report(tmp_path, monkeypatch):
    """Правка tab и heading в каталоге меняет вкладку и заголовок в отчёте без правки кода; ссылки ведут на новую вкладку.
    С NXLD_SHOW_REVIEW=1 выводятся и листы review."""
    C = json.load(open(CAT, encoding='utf-8'))
    s = next(x for x in next(f for f in C['files'] if f['code'] == 'errors')['sheets'] if x['code'] == 'stats')
    s['tab'], s['heading'] = 'Ошибки по дням', 'ОШИБКИ ПО ДНЯМ'
    p = os.path.join(tmp_path, 'cat.json')
    json.dump(C, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    monkeypatch.setenv('NXLD_CATALOG', p)
    monkeypatch.setenv('NXLD_SHOW_REVIEW', '1')
    a, b = os.path.join(tmp_path, 'a'), os.path.join(tmp_path, 'b')
    os.makedirs(a); os.makedirs(b)
    _, out, _ = synth.run(_log(), a)
    snap = glob.glob(os.path.join(out, '*.snapshot.json'))[0]
    _, out, _ = synth.run(_log(), b, '--prev', snap)
    books = _books(out)
    wb = books['NXLD_02_Errors.xlsx']
    assert 'Ошибки по дням' in wb.sheetnames and 'Статистика' not in wb.sheetnames, wb.sheetnames
    assert wb['Ошибки по дням']['B1'].value == 'ОШИБКИ ПО ДНЯМ'
    to_new = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row
              if c.hyperlink is not None and "'Ошибки по дням'" in (c.hyperlink.location or c.hyperlink.target or '')]
    assert to_new and all('«Статистика»' not in str(c.value) for c in to_new), [(c.coordinate, c.value) for c in to_new]
    assert not _dead_links(books), _dead_links(books)[:10]
    assert 'Было → стало' in wb.sheetnames   # review — при NXLD_SHOW_REVIEW=1
