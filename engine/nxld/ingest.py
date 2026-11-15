"""NXLD: приём логов.

Находит файлы (папки, .gz, .zip, обычные), определяет тип (access / error),
формат и сайт, разбирает access- и error-логи и складывает события в базу проверки (DuckDB):
куски одного лога склеиваются по контрольной сумме строки, словари (IP, адрес, браузер…) общие.
"""
import gzip, hashlib, io, json, os, re, zipfile, time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import numpy as np, pandas as pd

CHUNK = 1_000_000
MON = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}

# combined (nginx / apache); необязательные BOM в начале файла и $host после $remote_user (мультисайты); необязательный хвост ("$host" $request_time и т.п.)
ACCESS_RX = re.compile(r'^\ufeff?(\S+) \S+ (\S+)(?: ([A-Za-z0-9.:-]+))? \[(\d\d)/(\w\w\w)/(\d{4}):(\d\d):(\d\d):(\d\d) ([+-]\d{4})\] "(.*?)" (\d{3}) (\d+|-) "(.*?)" "(.*?)"(.*)$')
COMMON_RX = re.compile(r'^\ufeff?(\S+) \S+ (\S+)(?: ([A-Za-z0-9.:-]+))? \[(\d\d)/(\w\w\w)/(\d{4}):(\d\d):(\d\d):(\d\d) ([+-]\d{4})\] "(.*?)" (\d{3}) (\d+|-)\s*$')
NGX_ERR_RX = re.compile(r'^\ufeff?(\d{4})/(\d\d)/(\d\d) (\d\d):(\d\d):(\d\d) \[(\w+)\] \d+#\d+: (?:\*\d+ )?(.*)$')
APA_ERR_RX = re.compile(r'^\ufeff?\[(\w{3}) (\w{3}) (\d\d) (\d\d):(\d\d):(\d\d)(?:\.\d+)? (\d{4})\] \[([\w:]+)\] (.*)$')


# ---------- источники ----------
def _open_member(path, member=None):
    if member is not None:
        z = zipfile.ZipFile(path)
        raw = z.open(member)
        if member.endswith('.gz'):
            raw = gzip.GzipFile(fileobj=raw)
        return io.TextIOWrapper(raw, encoding='utf-8', errors='replace')
    if path.endswith('.gz'):
        return io.TextIOWrapper(gzip.open(path), encoding='utf-8', errors='replace')
    return open(path, encoding='utf-8', errors='replace')


def discover(paths):
    """Список источников: (id, путь, член_архива или None)."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    if f.startswith('nxld.duckdb'): continue   # база проверки — не лог
                    out += discover([os.path.join(root, f)])
            continue
        if p.endswith('.zip'):
            with zipfile.ZipFile(p) as z:
                for m in z.namelist():
                    if not m.endswith('/') and not os.path.basename(m).startswith('.'):
                        out.append((f'{os.path.basename(p)}:{m}', p, m))
        else:
            out.append((os.path.basename(p), p, None))
    return out


def sniff(path, member, n=50):
    """Тип и формат по первым строкам."""
    kinds = Counter()
    with _open_member(path, member) as f:
        for i, line in enumerate(f):
            if i >= n: break
            line = line.rstrip('\n')
            if not line: continue
            if ACCESS_RX.match(line): kinds['access:combined'] += 1
            elif COMMON_RX.match(line): kinds['access:common'] += 1
            elif NGX_ERR_RX.match(line): kinds['error:nginx'] += 1
            elif APA_ERR_RX.match(line): kinds['error:apache'] += 1
            else: kinds['unknown'] += 1
    if not kinds: return 'empty', None
    k = kinds.most_common(1)[0][0]
    return (k.split(':')[0], k.split(':')[1]) if ':' in k else ('unknown', None)


SITE_FROM_NAME = re.compile(r'((?:[a-z0-9-]+\.)+[a-z]{2,})(?=[._-](?:access|error|ssl))', re.I)


def site_from_name(name):
    m = SITE_FROM_NAME.search(os.path.basename(name.split(':')[-1]))
    return m.group(1).lower() if m else None


# ---------- разбор access ----------
_minute_cache = {}


def _ts(d, mon, y, hh, mm, ss):
    key = (d, mon, y, hh, mm)
    b = _minute_cache.get(key)
    if b is None:
        b = int(datetime(int(y), MON[mon], int(d), int(hh), int(mm), tzinfo=timezone.utc).timestamp())
        _minute_cache[key] = b
    return b + int(ss)


def line_hash(line):
    """Контрольная сумма строки до разбора (без BOM и перевода строки): по ней склеиваются куски одного лога."""
    return int.from_bytes(hashlib.blake2b(line.encode('utf-8', 'replace'), digest_size=8).digest(), 'little')


ACCESS_COLS = ('n', 'line_hash', 'ts', 'ip', 'vhost', 'method', 'base', 'query', 'proto', 'status', 'bytes', 'ref', 'ua')


def parse_access(path, member, sink):
    """Разбирает один access-источник кусками: sink(таблица) на каждый кусок. Время — местное время лога (как в строке)."""
    cols = {k: [] for k in ACCESS_COLS}
    nbad, nlines = 0, 0
    tz = Counter()

    def flush():
        nonlocal cols
        if not cols['ts']: return
        df = pd.DataFrame(cols)
        df['line_hash'] = df['line_hash'].astype('uint64')
        sink(df)
        cols = {k: [] for k in cols}

    with _open_member(path, member) as f:
        for line in f:
            nlines += 1
            line = line.rstrip('\r\n').lstrip('\ufeff')
            m = ACCESS_RX.match(line)
            if not m:
                m2 = COMMON_RX.match(line)
                if not m2:
                    nbad += 1
                    continue
                g = list(m2.groups()) + ['', '', '']
            else:
                g = m.groups()
            ip, user, vh, d, mon, y, hh, mm, ss, z, req, st, by, ref, ua, tail = g
            try:
                t = _ts(d, mon, y, hh, mm, ss)
            except Exception:
                nbad += 1
                continue
            tz[z] += 1
            parts = req.split(' ')
            if len(parts) == 3:
                meth, url, proto = parts
            elif len(parts) == 2:
                meth, url, proto = parts[0], parts[1], ''
            else:
                meth, url, proto = '-', req[:300], ''
            if '?' in url:
                base, q = url.split('?', 1)
            else:
                base, q = url, ''
            cols['n'].append(nlines); cols['line_hash'].append(line_hash(line))
            cols['ts'].append(t); cols['ip'].append(ip); cols['vhost'].append((vh or '').lower())
            cols['method'].append(meth[:12]); cols['base'].append(base[:500]); cols['query'].append(q[:1000])
            cols['proto'].append(proto[:12]); cols['status'].append(int(st)); cols['bytes'].append(0 if by == '-' else int(by))
            cols['ref'].append(ref[:500]); cols['ua'].append(ua[:400])
            if len(cols['ts']) >= CHUNK:
                flush()
    flush()
    return dict(lines=nlines, bad=nbad, tz=tz.most_common(1)[0][0] if tz else '')


# ---------- разбор error ----------
ERR_FIELDS = re.compile(r', (client|server|request|upstream|host|referrer): "?([^",]*)"?')


ERR_COLS = ('n', 'line_hash', 'ts', 'level', 'msg', 'client', 'server', 'request', 'upstream', 'host', 'referrer')


def parse_error(path, member, kind):
    """Строки error-лога: (таблица, прочитано строк, не разобрано)."""
    cols = {k: [] for k in ERR_COLS}
    nlines = nbad = 0
    with _open_member(path, member) as f:
        for line in f:
            nlines += 1
            line = line.rstrip('\r\n').lstrip('\ufeff')
            if kind == 'nginx':
                m = NGX_ERR_RX.match(line)
                if not m: nbad += 1; continue
                y, mo, d, hh, mm, ss, lvl, msg = m.groups()
                t = int(datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss), tzinfo=timezone.utc).timestamp())
            else:
                m = APA_ERR_RX.match(line)
                if not m: nbad += 1; continue
                _, mon, d, hh, mm, ss, y, lvl, msg = m.groups()
                t = int(datetime(int(y), MON.get(mon, 1), int(d), int(hh), int(mm), int(ss), tzinfo=timezone.utc).timestamp())
            fields = dict(ERR_FIELDS.findall(msg))
            core = msg.split(', client:')[0]
            for k, v in (('n', nlines), ('line_hash', line_hash(line)), ('ts', t), ('level', lvl), ('msg', core[:600]), ('client', fields.get('client', '')),
                         ('server', fields.get('server', '')), ('request', fields.get('request', '')[:400]), ('upstream', fields.get('upstream', '')[:200]),
                         ('host', fields.get('host', '')), ('referrer', fields.get('referrer', '')[:300])):
                cols[k].append(v)
    df = pd.DataFrame(cols)
    df['line_hash'] = df['line_hash'].astype('uint64')
    return df, nlines, nbad


# ---------- загрузка в базу проверки ----------
DIMS = {'ip': ('dim_ip', 'ip_id', 'ip'), 'host': ('dim_host', 'host_id', 'host'), 'path': ('dim_path', 'path_id', 'path'),
        'query': ('dim_query', 'query_id', 'query'), 'ref': ('dim_ref', 'ref_id', 'ref'), 'ua': ('dim_ua', 'ua_id', 'ua')}
EVENT_TABLES = ['sources', 'access_events', 'error_events'] + [d[0] for d in DIMS.values()]


def file_hash(path, member):
    """Отпечаток содержимого: тот же файл под другим именем второй раз не разбирается."""
    if member is not None:
        zi = zipfile.ZipFile(path).getinfo(member)
        return f'zip:{zi.CRC:08x}:{zi.file_size}'
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def _dim_add(con, dim, sql):
    """Новые значения словаря из запроса sql (колонки v — значение, fn — порядок первого появления)."""
    tbl, idc, valc = DIMS[dim]
    con.execute(f"""INSERT INTO {tbl} ({idc}, {valc})
        SELECT (SELECT coalesce(max({idc}), 0) FROM {tbl}) + row_number() OVER (ORDER BY fn, v), v
        FROM (SELECT v, min(fn) fn FROM ({sql}) GROUP BY v) x WHERE v IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {tbl} d WHERE d.{valc} = x.v)""")


def _new_rows(con, stg, events):
    """Строки куска, которых ещё нет в событиях. Склейка «максимум, а не сумма»: строка, повторённая в одном файле k раз, —
    k событий (occ = 1…k); те же строки из пересекающегося куска другого файла новых событий не дают."""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE new_rows AS
        SELECT s.* FROM (SELECT *, row_number() OVER (PARTITION BY line_hash ORDER BY n)::UINTEGER occ FROM {stg}) s
        ANTI JOIN {events} e ON e.line_hash = s.line_hash AND e.occ = s.occ""")
    return con.execute('SELECT count(*) FROM new_rows').fetchone()[0]


def _load_access(con, sid, path, member):
    con.execute("CREATE OR REPLACE TEMP TABLE stg (n INTEGER, line_hash UBIGINT, ts BIGINT, ip VARCHAR, vhost VARCHAR, method VARCHAR, base VARCHAR, query VARCHAR, "
                "proto VARCHAR, status SMALLINT, bytes BIGINT, ref VARCHAR, ua VARCHAR)")

    def sink(chunk_df):
        con.register('chunk_df', chunk_df)
        con.execute(f"INSERT INTO stg SELECT {', '.join(ACCESS_COLS)} FROM chunk_df")
        con.unregister('chunk_df')
    r = parse_access(path, member, sink)
    t0, t1 = con.execute('SELECT min(ts), max(ts) FROM stg').fetchone()
    new = _new_rows(con, 'stg', 'access_events')
    for dim, col in (('ip', 'ip'), ('host', 'vhost'), ('path', 'base'), ('query', 'query'), ('ref', 'ref'), ('ua', 'ua')):
        _dim_add(con, dim, f'SELECT {col} v, n fn FROM new_rows')
    con.execute(f"""INSERT INTO access_events (eid, source_id, n, line_hash, occ, ts, ip_id, host_id, method, path_id, query_id, proto, status, bytes, ref_id, ua_id)
        SELECT ({sid}::BIGINT << 32) | s.n, {sid}, s.n, s.line_hash, s.occ, s.ts, i.ip_id, h.host_id, s.method, p.path_id, q.query_id, s.proto, s.status, s.bytes, f.ref_id, u.ua_id
        FROM new_rows s JOIN dim_ip i ON i.ip = s.ip JOIN dim_host h ON h.host = s.vhost JOIN dim_path p ON p.path = s.base
        JOIN dim_query q ON q.query = s.query JOIN dim_ref f ON f.ref = s.ref JOIN dim_ua u ON u.ua = s.ua""")
    return dict(r, ts_first=t0, ts_last=t1, new_rows=new)


def _load_error(con, sid, path, member, fmt):
    err_df, nlines, nbad = parse_error(path, member, fmt)
    if not len(err_df): return dict(lines=nlines, bad=nbad, tz='', ts_first=None, ts_last=None, new_rows=0)
    con.register('err_df', err_df)
    con.execute(r"""CREATE OR REPLACE TEMP TABLE stg AS
        SELECT * EXCLUDE (url), CASE WHEN url IS NULL THEN NULL ELSE left(split_part(url, '?', 1), 500) END base,
               CASE WHEN url IS NULL THEN NULL WHEN contains(url, '?') THEN left(substr(url, strpos(url, '?') + 1), 1000) ELSE '' END query
        FROM (SELECT * REPLACE (n::INTEGER AS n, ts::BIGINT AS ts), left(nullif(regexp_extract(request, '^(\S+) (\S+)', 1), ''), 12) AS method,
                     nullif(regexp_extract(request, '^(\S+) (\S+)', 2), '') AS url FROM err_df)""")
    con.unregister('err_df')
    t0, t1 = con.execute('SELECT min(ts), max(ts) FROM stg').fetchone()
    new = _new_rows(con, 'stg', 'error_events')
    for dim, col in (('ip', 'client'), ('host', 'host'), ('path', 'base'), ('query', 'query'), ('ref', 'referrer')):
        _dim_add(con, dim, f"SELECT nullif({col}, '') v, n fn FROM new_rows" if col in ('client', 'host', 'referrer') else f'SELECT {col} v, n fn FROM new_rows')
    con.execute(f"""INSERT INTO error_events (eid, source_id, n, line_hash, occ, ts, level, msg, ip_id, host_id, request, method, path_id, query_id, upstream, server, ref_id)
        SELECT ({sid}::BIGINT << 32) | s.n, {sid}, s.n, s.line_hash, s.occ, s.ts, s.level, s.msg, i.ip_id, h.host_id, s.request, s.method, p.path_id, q.query_id, s.upstream, s.server, f.ref_id
        FROM new_rows s LEFT JOIN dim_ip i ON i.ip = nullif(s.client, '') LEFT JOIN dim_host h ON h.host = nullif(s.host, '') LEFT JOIN dim_path p ON p.path = s.base
        LEFT JOIN dim_query q ON q.query = s.query LEFT JOIN dim_ref f ON f.ref = nullif(s.referrer, '')""")
    return dict(lines=nlines, bad=nbad, tz='', ts_first=t0, ts_last=t1, new_rows=new)


def ingest(paths, workdir, log=print, con=None):
    """Приём логов в базу проверки. Уже загруженный источник (по имени) не читается; тот же файл под другим именем
    (по отпечатку содержимого) записывается как копия без разбора. Каждый источник — одна транзакция: обрыв не оставляет половины файла."""
    from . import db
    own = con is None
    if own: con = db.connect(workdir)
    db.ensure(con, EVENT_TABLES)
    have = {r[0]: r for r in con.execute('SELECT name, source_id, file_hash FROM sources').fetchall()}
    by_hash = {r[2]: r[1] for r in have.values() if r[2]}
    next_id = max([r[1] for r in have.values()] + [0]) + 1
    added = 0
    for name, path, member in discover(paths):
        if name in have: continue
        t0 = time.time()
        kind, fmt = sniff(path, member)
        fh = file_hash(path, member)
        rec = dict(lines=0, bad=0, tz='', ts_first=None, ts_last=None, new_rows=0)
        copy_of = by_hash.get(fh) if kind in ('access', 'error') else None
        con.execute('BEGIN')
        try:
            if copy_of is not None:
                o = con.execute('SELECT lines, bad, tz, ts_first, ts_last FROM sources WHERE source_id = ?', [copy_of]).fetchone()
                rec.update(lines=o[0], bad=o[1], tz=o[2], ts_first=o[3], ts_last=o[4])
            elif kind == 'access':
                rec = _load_access(con, next_id, path, member)
            elif kind == 'error':
                rec = _load_error(con, next_id, path, member, fmt)
            secs = round(time.time() - t0, 1)
            con.execute('INSERT INTO sources (source_id, name, path, member, file_hash, copy_of, site_by_name, kind, format, tz, ts_first, ts_last, lines, bad, new_rows, loaded_at, seconds) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now()::TIMESTAMP, ?)',
                        [next_id, name, path, member, fh, copy_of, site_from_name(name), kind, fmt, rec['tz'], rec['ts_first'], rec['ts_last'], rec['lines'], rec['bad'], rec['new_rows'], secs])
            con.execute('COMMIT')
        except BaseException:
            con.execute('ROLLBACK')
            raise
        if copy_of is None: by_hash.setdefault(fh, next_id)
        ok = rec['lines'] - rec['bad']
        rep = ok - rec['new_rows']
        log(f"  {name}: {kind}/{fmt}, строк {rec['lines']}" + (' — копия уже загруженного файла, не разбирается' if copy_of is not None else
                                                              f", уже было в других файлах {rep}" if rep and kind in ('access', 'error') else '') + f", {secs} с")
        added += rec['new_rows']
        next_id += 1
    if added and con.execute("SELECT count(*) FROM sources WHERE kind = 'access' AND new_rows > 0").fetchone()[0] > 1:
        con.execute('CREATE OR REPLACE TABLE access_events AS SELECT * FROM access_events ORDER BY ts, eid')   # события лежат по времени: запрос «эта минута» читает только свои блоки
    if added:
        for t in ('access_events', 'error_events'): db.mark_built(con, t)
    con.execute('DROP TABLE IF EXISTS stg'); con.execute('DROP TABLE IF EXISTS new_rows')
    state = state_of(con)
    if own: con.close()
    return state


def state_of(con):
    """Сведения об источниках в прежнем виде (для этапов, которые ещё читают их словарём)."""
    q = con.execute('SELECT name, path, member, kind, format, site_by_name, lines, bad, tz, ts_first, ts_last, new_rows, seconds, copy_of FROM sources ORDER BY source_id').fetchall()
    out = {}
    for name, path, member, kind, fmt, site, lines, bad, tz, t0, t1, new, secs, copy_of in q:
        r = dict(path=path, member=member, kind=kind, format=fmt, site_by_name=site, done=True, seconds=secs)
        if kind == 'access':   # период файла — с точностью до минуты, как раньше
            r.update(lines=lines, bad=bad, tz=tz, first=t0 // 60 * 60 if t0 is not None else None, last=t1 // 60 * 60 + 59 if t1 is not None else None, repeats=lines - bad - new if copy_of is None else 0)
        elif kind == 'error':
            r.update(lines=lines - bad, first=t0, last=t1)
        else:
            r.update(lines=0)
        out[name] = r
    return {'sources': out}


def _categorical(ids, dim_ids, dim_vals):
    """Колонка-справочник из номеров словаря: категории — только встреченные значения, по алфавиту."""
    cat = pd.Series(dim_vals).astype('category')
    m = np.full(int(dim_ids.max()) + 1 if len(dim_ids) else 1, -1, dtype='int32')
    m[dim_ids] = cat.cat.codes.values
    return pd.Categorical.from_codes(m[ids], categories=cat.cat.categories)


def requests_frame(con):
    """Таблица запросов в прежнем виде (R до признаков): по времени, затем по порядку источников и строк."""
    ev = con.execute('SELECT ts, ip_id, host_id, method, path_id, query_id, proto, status, bytes, ref_id, ua_id, source_id FROM access_events ORDER BY ts, eid').fetchnumpy()
    R = pd.DataFrame({'ts': ev['ts'].astype('int64')})
    for col, dim, idc in (('ip', 'ip', 'ip_id'), ('vhost', 'host', 'host_id')):
        tbl, i_, v_ = DIMS[dim]
        d = con.execute(f'SELECT {i_}, {v_} FROM {tbl} WHERE {i_} IN (SELECT DISTINCT {idc} FROM access_events)').fetchnumpy()
        R[col] = _categorical(ev[idc], d[i_], d[v_])
    R['method'] = pd.Series(ev['method']).astype('category')
    for col, dim, idc in (('base', 'path', 'path_id'), ('query', 'query', 'query_id')):
        tbl, i_, v_ = DIMS[dim]
        d = con.execute(f'SELECT {i_}, {v_} FROM {tbl} WHERE {i_} IN (SELECT DISTINCT {idc} FROM access_events)').fetchnumpy()
        R[col] = _categorical(ev[idc], d[i_], d[v_])
    R['proto'] = pd.Series(ev['proto']).astype('category')
    R['status'] = ev['status'].astype('int16')
    R['bytes'] = ev['bytes'].astype('int64')
    for col, dim, idc in (('ref', 'ref', 'ref_id'), ('ua', 'ua', 'ua_id')):
        tbl, i_, v_ = DIMS[dim]
        d = con.execute(f'SELECT {i_}, {v_} FROM {tbl} WHERE {i_} IN (SELECT DISTINCT {idc} FROM access_events)').fetchnumpy()
        R[col] = _categorical(ev[idc], d[i_], d[v_])
    s = con.execute('SELECT source_id, name FROM sources').fetchnumpy()
    R['src'] = _categorical(ev['source_id'], s['source_id'][np.isin(s['source_id'], ev['source_id'])], s['name'][np.isin(s['source_id'], ev['source_id'])])
    return R


def errors_frame(con):
    """Error-лог в прежнем виде (E): по порядку источников и строк."""
    E = con.execute("""SELECT e.ts, e.level, e.msg, coalesce(i.ip, '') client, e.server, e.request, e.upstream, coalesce(h.host, '') host, coalesce(f.ref, '') referrer, s.name src
        FROM error_events e LEFT JOIN dim_ip i USING (ip_id) LEFT JOIN dim_host h USING (host_id) LEFT JOIN dim_ref f USING (ref_id) JOIN sources s USING (source_id)
        ORDER BY e.eid""").fetchdf()
    if not len(E): return pd.DataFrame()
    E['ts'] = E['ts'].astype('int64')
    for c in ('level', 'msg', 'client', 'server', 'request', 'upstream', 'host', 'referrer', 'src'):
        E[c] = E[c].astype('category')
    return E
