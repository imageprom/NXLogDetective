"""Слой событий 0.3: логи складываются в базу проверки (DuckDB), куски одного лога склеиваются по строкам.

Склейка «максимум, а не сумма»: строка, повторённая в одном файле, — столько же событий; та же строка из
пересекающегося куска другого файла новых событий не даёт. Данные вымышленные."""
import gzip, os, shutil, sys, tempfile
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import openpyxl
import synth
from nxld import db, ingest

UA = synth.UA_CHROME


def acc(ip, t, url, code=200):
    return f'{ip} - - [{t:%d/%b/%Y:%H:%M:%S} +0300] "GET {url} HTTP/1.1" {code} 1234 "-" "{UA}"'


def err(t, client, url):
    return f'{t:%Y/%m/%d %H:%M:%S} [error] 100#100: *7 open() "/var/www{url}" failed (2: No such file or directory), client: {client}, server: example.com, request: "GET {url}?x=1 HTTP/1.1", host: "example.com", referrer: "https://example.com/"'


def write(d, name, lines, bom=False, crlf=False):
    p = os.path.join(d, name)
    with open(p, 'w', newline='') as f:
        f.write(('﻿' if bom else '') + ('\r\n' if crlf else '\n').join(lines) + ('\r\n' if crlf else '\n'))
    return p


def lines_(n0, n1):
    """По строке в 20 секунд: в минуте три разных строки."""
    return [acc('198.51.100.%d' % (k % 5 + 1), synth.T0 + timedelta(seconds=20 * k), f'/page{k}/') for k in range(n0, n1)]


def count(work, table='access_events'):
    con = db.connect(work, read_only=True)
    try: return con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
    finally: con.close()


def test_overlapping_chunks_are_glued_by_line():
    """Два куска одного лога перекрываются на полторы минуты: каждая строка — одно событие.
    Раньше минута на стыке, попавшая в куски не целиком, оставалась из обоих — строки считались дважды."""
    with tempfile.TemporaryDirectory() as d:
        a = write(d, 'access.log.1', lines_(0, 100))
        b = write(d, 'access.log', lines_(95, 200))   # 95–99 уже есть в первом куске; минута 96–98 в первом куске не целиком
        st = ingest.ingest([a, b], os.path.join(d, 'w'), log=lambda *_: None)
        assert count(os.path.join(d, 'w')) == 200
        assert st['sources']['access.log']['repeats'] == 5
        R = ingest.requests_frame(db.connect(os.path.join(d, 'w'), read_only=True))
        assert len(R) == 200 and R['ts'].is_monotonic_increasing and R['base'].nunique() == 200


def test_repeat_inside_one_file_is_kept():
    """Бот дважды за секунду запросил один адрес: строки одинаковые, но это два запроса. В пересекающемся куске те же две строки — новых событий нет."""
    with tempfile.TemporaryDirectory() as d:
        twice = [acc('203.0.113.9', synth.T0, '/same/')] * 2
        a = write(d, 'a.log', twice + lines_(1, 10))
        b = write(d, 'b.log', twice + lines_(1, 20))
        ingest.ingest([a, b], os.path.join(d, 'w'), log=lambda *_: None)
        con = db.connect(os.path.join(d, 'w'), read_only=True)
        assert con.execute("SELECT count(*) FROM access_events e JOIN dim_path p USING (path_id) WHERE p.path = '/same/'").fetchone()[0] == 2
        assert con.execute('SELECT count(*) FROM access_events').fetchone()[0] == 2 + 19
        assert con.execute('SELECT count(*) FROM (SELECT line_hash, occ FROM access_events GROUP BY ALL HAVING count(*) > 1)').fetchone()[0] == 0


def test_same_file_under_another_name_is_not_parsed_again():
    with tempfile.TemporaryDirectory() as d:
        a = write(d, 'access.log', lines_(0, 50))
        b = os.path.join(d, 'access_copy.log'); shutil.copy(a, b)
        seen = []
        st = ingest.ingest([a, b], os.path.join(d, 'w'), log=seen.append)
        assert count(os.path.join(d, 'w')) == 50
        assert 'копия уже загруженного файла' in seen[1]
        assert st['sources']['access_copy.log']['lines'] == 50   # в списке файлов копия остаётся — со своим числом строк


def test_bom_crlf_and_gzip_do_not_break_gluing():
    """Тот же кусок в другой упаковке (BOM в начале, переводы строк Windows, gzip) — те же строки."""
    with tempfile.TemporaryDirectory() as d:
        a = write(d, 'a.log', lines_(0, 30))
        b = write(d, 'b.log', lines_(0, 40), bom=True, crlf=True)
        c = os.path.join(d, 'c.log.gz')
        with gzip.open(c, 'wt') as f: f.write('\n'.join(lines_(20, 60)) + '\n')
        ingest.ingest([a, b, c], os.path.join(d, 'w'), log=lambda *_: None)
        assert count(os.path.join(d, 'w')) == 60


def test_error_log_chunks_are_glued_and_share_ip_dictionary():
    with tempfile.TemporaryDirectory() as d:
        el = [err(synth.T0 + timedelta(seconds=30 * k), '198.51.100.1', f'/img/{k}.png') for k in range(40)]
        a = write(d, 'access.log', lines_(0, 20))
        e1 = write(d, 'error.log.1', el[:25]); e2 = write(d, 'error.log', el[20:])
        ingest.ingest([a, e1, e2], os.path.join(d, 'w'), log=lambda *_: None)
        con = db.connect(os.path.join(d, 'w'), read_only=True)
        assert con.execute('SELECT count(*) FROM error_events').fetchone()[0] == 40
        # IP клиента из error-лога — тот же номер словаря, что у запросов access-лога
        assert con.execute("""SELECT count(DISTINCT e.ip_id) FROM error_events e JOIN access_events a USING (ip_id) JOIN dim_ip i USING (ip_id) WHERE i.ip = '198.51.100.1'""").fetchone()[0] == 1
        row = con.execute("SELECT e.method, p.path, q.query FROM error_events e JOIN dim_path p USING (path_id) JOIN dim_query q USING (query_id) ORDER BY e.eid LIMIT 1").fetchone()
        assert row == ('GET', '/img/0.png', 'x=1')
        E = ingest.errors_frame(con)
        assert len(E) == 40 and E['client'].astype(str).eq('198.51.100.1').all() and E['request'].astype(str).iloc[0] == 'GET /img/0.png?x=1 HTTP/1.1'


def test_new_chunk_is_added_without_reading_old_ones():
    """Дозагрузка: при втором запуске читается только новый файл."""
    with tempfile.TemporaryDirectory() as d:
        a = write(d, 'access.log.1', lines_(0, 100))
        ingest.ingest([a], os.path.join(d, 'w'), log=lambda *_: None)
        b = write(d, 'access.log', lines_(90, 150))
        seen = []
        ingest.ingest([a, b], os.path.join(d, 'w'), log=seen.append)
        assert len(seen) == 1 and seen[0].lstrip().startswith('access.log:') and 'уже было в других файлах 10' in seen[0]
        assert count(os.path.join(d, 'w')) == 150


def test_logs_sheet_shows_two_periods_and_no_overlap_line():
    """01 «Логи», блок «Итого»: периоды access- и error-логов отдельными строками; строки «Повторы на стыках» нет."""
    with tempfile.TemporaryDirectory() as d:
        L = synth.Log(); L.people(days=3, per_day=10)
        e = write(d, 'error.log', [err(synth.T0 + timedelta(hours=5 + k), synth.RU[0], f'/upload/{k}.jpg') for k in range(30)])
        _, out, _ = synth.run(L, d, '--logs', os.path.join(d, 'access.log'), e)
        ws = openpyxl.load_workbook(os.path.join(out, 'NXLD_01_Overview.xlsx'))['Логи']
        labels = {str(c.value): str(ws.cell(c.row, c.column + 1).value) for r in ws.iter_rows() for c in r if c.value}
        assert 'Период access-логов' in labels and 'Период error-логов' in labels
        assert labels['Период error-логов'].startswith('1 сентября 2026 05:00 — 2 сентября 2026')
        assert 'Повторы на стыках' not in labels and 'Период' not in labels
