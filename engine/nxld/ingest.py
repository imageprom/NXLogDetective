"""NXLD: приём логов.

Находит файлы (папки, .gz, .zip, обычные), определяет тип (access / error),
формат и сайт, разбирает access-логи в компактные таблицы (pickle по кускам),
error-логи — в отдельную таблицу. Работает кусками и продолжает с места обрыва.
"""
import gzip, hashlib, io, json, os, re, zipfile, time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import pandas as pd

CHUNK = 1_000_000
MON = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}

# combined (nginx / apache) + необязательный хвост ("$host" $request_time и т.п.)
ACCESS_RX = re.compile(r'^(\S+) \S+ (\S+) \[(\d\d)/(\w\w\w)/(\d{4}):(\d\d):(\d\d):(\d\d) ([+-]\d{4})\] "(.*?)" (\d{3}) (\d+|-) "(.*?)" "(.*?)"(.*)$')
COMMON_RX = re.compile(r'^(\S+) \S+ (\S+) \[(\d\d)/(\w\w\w)/(\d{4}):(\d\d):(\d\d):(\d\d) ([+-]\d{4})\] "(.*?)" (\d{3}) (\d+|-)\s*$')
NGX_ERR_RX = re.compile(r'^(\d{4})/(\d\d)/(\d\d) (\d\d):(\d\d):(\d\d) \[(\w+)\] \d+#\d+: (?:\*\d+ )?(.*)$')
APA_ERR_RX = re.compile(r'^\[(\w{3}) (\w{3}) (\d\d) (\d\d):(\d\d):(\d\d)(?:\.\d+)? (\d{4})\] \[([\w:]+)\] (.*)$')


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


def parse_access(path, member, outdir, src_id, start_chunk):
    """Разбирает один access-источник в куски req_*.pkl. Время — местное время лога (как в строке)."""
    cols = {k: [] for k in ('ts', 'ip', 'user', 'method', 'base', 'query', 'proto', 'status', 'bytes', 'ref', 'ua', 'tail')}
    chunks, nbad, nlines = [], 0, 0
    minute_counts = Counter()
    tz = Counter()
    ci = start_chunk

    def flush():
        nonlocal ci, cols
        if not cols['ts']: return
        df = pd.DataFrame(cols)
        df['src'] = src_id
        for c in ('ip', 'user', 'method', 'base', 'query', 'proto', 'ref', 'ua', 'tail', 'src'):
            df[c] = df[c].astype('category')
        df['status'] = df['status'].astype('int16')
        df['bytes'] = df['bytes'].astype('int64')
        df['ts'] = df['ts'].astype('int64')
        fn = os.path.join(outdir, f'req_{ci:05d}.pkl')
        df.to_pickle(fn)
        chunks.append(os.path.basename(fn))
        ci += 1
        cols = {k: [] for k in cols}

    with _open_member(path, member) as f:
        for line in f:
            nlines += 1
            m = ACCESS_RX.match(line.rstrip('\n'))
            if not m:
                m2 = COMMON_RX.match(line.rstrip('\n'))
                if not m2:
                    nbad += 1
                    continue
                g = list(m2.groups()) + ['', '', '']
            else:
                g = m.groups()
            ip, user, d, mon, y, hh, mm, ss, z, req, st, by, ref, ua, tail = g
            try:
                t = _ts(d, mon, y, hh, mm, ss)
            except Exception:
                nbad += 1
                continue
            tz[z] += 1
            minute_counts[t // 60] += 1
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
            cols['ts'].append(t); cols['ip'].append(ip); cols['user'].append(user)
            cols['method'].append(meth[:12]); cols['base'].append(base[:500]); cols['query'].append(q[:1000])
            cols['proto'].append(proto[:12]); cols['status'].append(int(st)); cols['bytes'].append(0 if by == '-' else int(by))
            cols['ref'].append(ref[:500]); cols['ua'].append(ua[:400]); cols['tail'].append(tail.strip()[:200])
            if len(cols['ts']) >= CHUNK:
                flush()
    flush()
    return dict(chunks=chunks, lines=nlines, bad=nbad, tz=tz.most_common(1)[0][0] if tz else '',
                minutes=minute_counts, next_chunk=ci)


# ---------- разбор error ----------
ERR_FIELDS = re.compile(r', (client|server|request|upstream|host|referrer): "?([^",]*)"?')


def parse_error(path, member, kind):
    rows = []
    with _open_member(path, member) as f:
        for line in f:
            line = line.rstrip('\n')
            if kind == 'nginx':
                m = NGX_ERR_RX.match(line)
                if not m: continue
                y, mo, d, hh, mm, ss, lvl, msg = m.groups()
                t = int(datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss), tzinfo=timezone.utc).timestamp())
            else:
                m = APA_ERR_RX.match(line)
                if not m: continue
                _, mon, d, hh, mm, ss, y, lvl, msg = m.groups()
                t = int(datetime(int(y), MON.get(mon, 1), int(d), int(hh), int(mm), int(ss), tzinfo=timezone.utc).timestamp())
            fields = dict(ERR_FIELDS.findall(msg))
            core = msg.split(', client:')[0]
            rows.append(dict(ts=t, level=lvl, msg=core[:600], client=fields.get('client', ''), server=fields.get('server', ''),
                             request=fields.get('request', '')[:400], upstream=fields.get('upstream', '')[:200],
                             host=fields.get('host', ''), referrer=fields.get('referrer', '')[:300]))
    return rows


# ---------- главный вход ----------
def ingest(paths, workdir, log=print):
    os.makedirs(workdir, exist_ok=True)
    state_fn = os.path.join(workdir, 'ingest_state.json')
    state = json.load(open(state_fn)) if os.path.exists(state_fn) else {'sources': {}, 'next_chunk': 0}
    srcs = discover(paths)
    err_rows = []
    for sid, path, member in srcs:
        if sid in state['sources'] and state['sources'][sid].get('done'):
            continue
        kind, fmt = sniff(path, member)
        rec = dict(path=path, member=member, kind=kind, format=fmt, site_by_name=site_from_name(sid))
        t0 = time.time()
        if kind == 'access':
            r = parse_access(path, member, workdir, sid, state['next_chunk'])
            state['next_chunk'] = r.pop('next_chunk')
            mins = r.pop('minutes')
            pd.Series(mins).to_pickle(os.path.join(workdir, f"min_{hashlib.md5(sid.encode()).hexdigest()[:10]}.pkl"))
            rec.update(r, first=min(mins) * 60 if mins else None, last=max(mins) * 60 + 59 if mins else None)
        elif kind == 'error':
            rows = parse_error(path, member, fmt)
            for x in rows: x['src'] = sid
            err_rows += rows
            rec.update(lines=len(rows), first=min((x['ts'] for x in rows), default=None), last=max((x['ts'] for x in rows), default=None))
        else:
            rec.update(lines=0)
        rec['done'] = True
        rec['seconds'] = round(time.time() - t0, 1)
        state['sources'][sid] = rec
        json.dump(state, open(state_fn, 'w'), ensure_ascii=False, indent=1, default=str)
        log(f"  {sid}: {kind}/{fmt}, строк {rec.get('lines')}, {rec['seconds']} с")
    if err_rows:
        old = os.path.join(workdir, 'errors.pkl')
        df = pd.DataFrame(err_rows)
        if os.path.exists(old):
            df = pd.concat([pd.read_pickle(old), df], ignore_index=True)
        for c in ('level', 'msg', 'client', 'server', 'request', 'upstream', 'host', 'referrer', 'src'):
            if c in df.columns: df[c] = df[c].astype('category')
        df.to_pickle(old)
    return state


def overlaps(workdir, state):
    """Пересечения access-источников по минутам: совпадающие минуты (одинаковое число строк) считаются дублями."""
    acc = [(sid, r) for sid, r in state['sources'].items() if r['kind'] == 'access' and r.get('first')]
    acc.sort(key=lambda x: x[1]['first'])
    mins = {sid: pd.read_pickle(os.path.join(workdir, f"min_{hashlib.md5(sid.encode()).hexdigest()[:10]}.pkl")) for sid, _ in acc}
    seen = Counter()
    drop = {}  # sid -> set of minutes to drop
    report = []
    for sid, r in acc:
        m = mins[sid]
        dup = [k for k, v in m.items() if seen.get(k) == v]
        part = [k for k, v in m.items() if k in seen and seen.get(k) != v]
        if dup:
            drop[sid] = set(dup)
        if dup or part:
            report.append(dict(source=sid, minutes_duplicate=len(dup), minutes_partial=len(part), lines_duplicate=int(sum(m[k] for k in dup))))
        for k, v in m.items():
            if k not in seen: seen[k] = v
    return drop, report
