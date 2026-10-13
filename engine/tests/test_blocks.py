"""Блоки листов в каталоге структуры (задача #11): заголовки, подзаголовки, примечания, ссылки и легенда блоков — из каталога.
Правка каталога меняет отчёт без правки кода; блок review не выводится; ссылка на лист, которого нет, не выводится."""
import json
import os
import re

import pytest
import synth
import test_catalog as TC

CAT = TC.CAT
STATUSES = {'approved', 'review'}


def _sheet(C, file, code):
    return next(s for s in next(f for f in C['files'] if f['code'] == file)['sheets'] if s['code'] == code)


def _block(C, file, sheet, code):
    return next(b for b in _sheet(C, file, sheet)['blocks'] if b['code'] == code)


def _cells(ws):
    return [c for row in ws.iter_rows() for c in row if c.value is not None]


def _texts(ws):
    return [str(c.value) for c in _cells(ws)]


@pytest.fixture(scope='module')
def edited(tmp_path_factory):
    """Один прогон с правленым каталогом: правки разных блоков — в разных местах отчёта."""
    tmp = str(tmp_path_factory.mktemp('blocks'))
    C = json.load(open(CAT, encoding='utf-8'))
    resp = _block(C, 'errors', 'index', 'responses')
    resp['heading'] = [[{'text': 'Ответы сервера — правка'}]]
    resp['subheading'] = []   # пустой подзаголовок не выводится
    _block(C, 'errors', 'index', 'victims')['status'] = 'review'   # блок review без NXLD_SHOW_REVIEW не выводится
    resp['links'] += [{'text': 'Тестовая ссылка на лист review', 'sheet': 'compare'},   # «Было → стало» — review: листа в отчёте нет
                      {'text': 'Тестовая ссылка на лист есть', 'sheet': 'broken_internal'}]
    e404 = _block(C, 'errors', 'e404', 'main')
    e404['notes'][0][0]['text'] = 'Правка примечания.'
    e404['links'][0]['text'] = 'Сводка — правка'
    e404['legend'] = False
    sf = _block(C, 'load_security', 'server_filter', 'main')
    sf['notes'][0], sf['notes'][1] = sf['notes'][1], sf['notes'][0]   # порядок абзацев
    todo = next(ln for ln in sf['notes'] if any(p.get('auto') == 'todo' for p in ln))
    todo.reverse()   # порядок частей строки
    p = os.path.join(tmp, 'cat.json')
    json.dump(C, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    old = {k: os.environ.get(k) for k in ('NXLD_CATALOG', 'NXLD_SHOW_REVIEW')}
    os.environ['NXLD_CATALOG'] = p
    os.environ.pop('NXLD_SHOW_REVIEW', None)
    try:
        d = os.path.join(tmp, 'run'); os.makedirs(d)
        _, out, _ = synth.run(TC._log(), d)
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    return TC._books(out), json.load(open(CAT, encoding='utf-8'))


def test_heading_and_empty_subheading(edited):
    books, C = edited
    ws = books['NXLD_02_Errors.xlsx']['Обзор']
    head = [c for c in _cells(ws) if c.value == 'ОТВЕТЫ СЕРВЕРА — ПРАВКА']
    assert head, [t for t in _texts(ws) if t.isupper()]
    assert 'ОТВЕТЫ СЕРВЕРА' not in _texts(ws)
    old_sub = ' '.join(p['text'] for ln in _block(C, 'errors', 'index', 'responses')['subheading'] for p in ln if 'text' in p)
    assert old_sub and old_sub not in _texts(ws)
    r = head[0].row
    assert ws.cell(r + 1, 2).value == 'Кто', ws.cell(r + 1, 2).value   # сразу под заголовком — шапка таблицы, строки подзаголовка нет


def test_review_block_hidden(edited):
    books, _ = edited
    ws = books['NXLD_02_Errors.xlsx']['Обзор']
    assert 'ПОСТРАДАВШИЕ СТРАНИЦЫ' not in _texts(ws)
    assert not [t for t in _texts(ws) if 'Пострадавшие страницы' in t and '→' in t]   # и ссылки блока нет
    assert 'Пострадавшие страницы' in books['NXLD_02_Errors.xlsx'].sheetnames   # сам лист — на месте


def test_link_to_absent_sheet(edited):
    books, _ = edited
    found = [t for wb in books.values() for ws in wb.worksheets for t in _texts(ws) if 'Тестовая ссылка' in t]
    assert found == ['Тестовая ссылка на лист есть: лист «Битые внутренние» →'], found   # ссылка на лист, который есть, выводится; на отсутствующий — нет
    assert not TC._dead_links(books), TC._dead_links(books)[:10]


def test_notes_links_legend_of_table(edited):
    books, _ = edited
    ws = books['NXLD_02_Errors.xlsx']['404']
    t = _texts(ws)
    assert 'Правка примечания.' in t, [x for x in t if 'статус' in x]
    assert not [x for x in t if x.startswith('Текущий статус — что адрес отвечает')]
    assert 'Сводка — правка: лист «Обзор» →' in t, [x for x in t if '→' in x]
    assert 'Критично — см. «Почему важно»' not in t   # легенда выключена в каталоге


def test_notes_order(edited):
    books, C = edited
    ws = books['NXLD_03_Load_Security.xlsx']['Серверный фильтр']
    notes = _block(C, 'load_security', 'server_filter', 'main')['notes']
    first, second = (' '.join(p['text'] for p in notes[i]) for i in (0, 1))
    rows = {str(c.value): c.row for c in _cells(ws)}
    assert rows[second] < rows[first]   # абзацы — в порядке каталога
    todo = [x for x in rows if x.endswith('Что сделать:')]
    assert todo and not [x for x in rows if x.startswith('Что сделать:')], [x for x in rows if 'сделать' in x]


def test_blocks_schema():
    """У каждого листа — список блоков; коды блоков уникальны, ключи латиницей, статус известен, ссылки — на коды листов каталога."""
    C = json.load(open(CAT, encoding='utf-8'))
    codes = {f['code']: {s['code'] for s in f['sheets']} for f in C['files']}
    n = 0
    for f in C['files']:
        for s in f['sheets']:
            bl = s.get('blocks')
            assert isinstance(bl, list), (f['code'], s['code'])
            assert len({b['code'] for b in bl}) == len(bl), (f['code'], s['code'])
            for b in bl:
                n += 1
                assert set(b) == {'code', 'status', 'heading', 'subheading', 'notes', 'links', 'legend'}, (f['code'], s['code'], b['code'])
                assert re.fullmatch(r'[a-z0-9_]+', b['code']) and b['status'] in STATUSES
                for k in ('heading', 'subheading', 'notes'):
                    for ln in b[k]:
                        assert ln and all(set(p) in ({'text'}, {'auto'}) for p in ln), (s['code'], b['code'], k)
                for lk in b['links']:
                    assert ('text' in lk) != ('auto' in lk), lk
                    assert lk['sheet'] in codes[lk.get('file', f['code'])], (f['code'], s['code'], b['code'], lk)
    assert n > 100
