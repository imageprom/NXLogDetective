#!/usr/bin/env python3
"""botsig/1 — движок проверки nginx access-логов по сигнатурам ботов.

Использование:
  python3 sigscan.py --sig signatures.yaml --asn asn-ipv4.csv --out hits/ access.log [access.log.1 ...]
  (файлы .gz читаются напрямую; '-' — stdin; логи подавать в хронологическом порядке)

Выход:
  hits/hits.jsonl   — по строке на срабатывание (сигнатура, ключ, время, доказательства)
  hits/summary.csv  — свод по сигнатурам
  hits/ips.csv      — свод по IP: какие сигнатуры, рекомендованное действие
"""
import argparse, bisect, collections, csv, gzip, ipaddress, json, os, re, sys
from datetime import datetime
import yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uafam import family

LINE = re.compile(r'^(\S+) \S+ \S+ \[(\d\d)/(\w\w\w)/(\d{4}):(\d\d):(\d\d):(\d\d) [^\]]+\] "(\S+) (\S+)[^"]*" (\d{3}) (\S+) "([^"]*)" "([^"]*)"')
MON = {m: i for i, m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(), 1)}
STATIC = re.compile(r'\.(css|js|png|jpe?g|svg|webp|avif|woff2?|gif|ico|mp4|webm|ttf|eot|map|xml|json|txt|pdf)$', re.I)
FLAT = re.compile(r'/(flat|commercial|pantry|parking)/dom-[^/]+/s[^/]+/e[^/]+/n[^/]+/?$')
SITE = re.compile(r'^https?://(www\.)?example\.com')

# ---------- ASN ----------
class ASN:
    def __init__(self, path):
        self.s, self.r = [], []
        if path and os.path.exists(path):
            for row in csv.reader(open(path, encoding='utf-8')):
                try:
                    self.s.append(int(ipaddress.IPv4Address(row[0]))); self.r.append((int(ipaddress.IPv4Address(row[1])), row[2], row[3]))
                except Exception: pass
        self.cache = {}
    def get(self, ip):
        if ip in self.cache: return self.cache[ip]
        res = ('', '')
        try:
            x = int(ipaddress.IPv4Address(ip)); i = bisect.bisect_right(self.s, x) - 1
            if i >= 0 and x <= self.r[i][0]: res = (self.r[i][1], self.r[i][2])
        except Exception: pass
        self.cache[ip] = res
        return res

# ---------- предикаты ----------
class Pred:
    def __init__(self, lists):
        self.lists = lists; self.rx = {}
    def _re(self, p):
        r = self.rx.get(p)
        if r is None: r = self.rx[p] = re.compile(p)
        return r
    def _inlist(self, name, v):
        L = self.lists.get(name, [])
        if isinstance(L, dict): return v in L
        return v in L or (isinstance(v, str) and v in set(map(str, L)))
    def op(self, v, spec):
        if not isinstance(spec, dict):
            if isinstance(spec, list): return v in spec
            return v == spec
        for k, a in spec.items():
            if k == 'eq' and not v == a: return False
            if k == 'ne' and not v != a: return False
            if k == 'in' and v not in a: return False
            if k == 'not_in' and v in a: return False
            if k == 're' and not (isinstance(v, str) and self._re(a).search(v)): return False
            if k == 'not_re' and (isinstance(v, str) and self._re(a).search(v)): return False
            if k == 'in_list' and not self._inlist(a, v): return False
            if k == 'not_in_list' and self._inlist(a, v): return False
            if k == 'cidr' and not any(ipaddress.ip_address(v) in ipaddress.ip_network(c, strict=False) for c in a): return False
            if k in ('gt', 'gte', 'lt', 'lte'):
                if v is None: return False
                if k == 'gt' and not v > a: return False
                if k == 'gte' and not v >= a: return False
                if k == 'lt' and not v < a: return False
                if k == 'lte' and not v <= a: return False
            if k == 'exists' and (v is not None) != a: return False
        return True
    def __call__(self, p, r):
        if not p: return True
        for k, spec in p.items():
            if k == 'all':
                if not all(self(x, r) for x in spec): return False
            elif k == 'any':
                if not any(self(x, r) for x in spec): return False
            elif k == 'not':
                if self(spec, r): return False
            elif not self.op(r.get(k), spec): return False
        return True

OPS = {'==': lambda a, b: a == b, '!=': lambda a, b: a != b, '>': lambda a, b: a > b, '>=': lambda a, b: a >= b, '<': lambda a, b: a < b, '<=': lambda a, b: a <= b}

def burst(ts, w):
    ts = sorted(ts); best = 0; j = 0
    for i in range(len(ts)):
        while ts[i] - ts[j] > w: j += 1
        best = max(best, i - j + 1)
    return best

# ---------- запись запроса ----------
def make_record(m, asn, lists, recent404):
    ip, dd, mon, yy, hh, mi, ss, meth, path, st, size, ref, ua = m.groups()
    ts = int(datetime(int(yy), MON[mon], int(dd), int(hh), int(mi), int(ss)).timestamp())
    base = path.split('?', 1)[0]; q = path[len(base) + 1:] if '?' in path else ''
    st = int(st)
    is_form = base.startswith('/local/templates/main/forms/')
    is_static = meth == 'GET' and not is_form and bool(STATIC.search(base) or base.startswith(('/upload/', '/bitrix/cache', '/local/templates/main/', '/images/')))
    is_page = meth == 'GET' and not is_form and not is_static and not base.startswith(('/upload', '/bitrix', '/local', '/images', '/favicon')) and 'ajax=' not in q
    fam = family(ua)
    a = asn.get(ip)
    vc = lists.get('verified_crawlers', {})
    ref_internal = bool(SITE.match(ref)); ref_path = SITE.sub('', ref).split('?', 1)[0] if ref_internal else ''
    r404 = None
    if ref_internal and ref_path in recent404:
        t0, ip0 = recent404[ref_path]
        if ip0 != ip and 0 <= ts - t0: r404 = ts - t0
    y = re.search(r'yclid=(\d+)', q)
    return dict(ip=ip, ts=ts, day=f'{yy}-{MON[mon]:02d}-{dd}', hour=int(hh), method=meth, path=path, base=base, query=q, status=st,
                bytes=int(size) if size.isdigit() else 0, referer=ref, ref_internal=ref_internal, ref_path=ref_path, ua=ua,
                ua_family=fam[0] if fam else None, ua_category=fam[1] if fam else None, is_bot_ua=fam is not None,
                asn=int(a[0]) if a[0].isdigit() else None, org=a[1],
                asn_verified=(None if not fam or fam[0] not in vc else (a[0].isdigit() and int(a[0]) in vc[fam[0]])),
                is_static=is_static, is_page=is_page, is_form_get=is_form and meth == 'GET', is_form_post=is_form and meth == 'POST',
                is_flat_card=bool(FLAT.search(base)), yclid=y.group(1) if y else None,
                is_desktop=bool(re.search(r'Windows NT|Macintosh|X11', ua)) and 'Mobile' not in ua,
                is_mobile=bool(re.search(r'Mobile|Android|iPhone', ua)), ref_seen_404_other_ip=r404)

def brief(r):
    return f"{datetime.fromtimestamp(r['ts']).strftime('%d.%m %H:%M:%S')} {r['method']} {r['path'][:110]} {r['status']}" + (f" ref={r['referer'][:70]}" if r['referer'] not in ('-', '') else '')

# ---------- проверка сессии ----------
def eval_aggs(reqs, require, P):
    vals = []
    for a in require or []:
        sel = [r for r in reqs if P(a.get('match'), r)]
        if a['agg'] == 'count': v = len(sel)
        elif a['agg'] == 'distinct': v = len({r.get(a['field']) for r in sel if r.get(a['field']) is not None})
        elif a['agg'] == 'span': v = (sel[-1]['ts'] - sel[0]['ts']) if sel else 0
        elif a['agg'] == 'burst': v = burst([r['ts'] for r in sel], a.get('window', 60))
        if not OPS[a['op']](v, a['value']): return None
        vals.append(f"{a['agg']}{'('+a['field']+')' if a.get('field') else ''}={v}")
    return vals

def eval_sequence(reqs, steps, P):
    pref = [0]
    for r in reqs: pref.append(pref[-1] + (1 if r['is_page'] else 0))
    first_page = next((i for i, r in enumerate(reqs) if r['is_page']), None)
    def rec(k, prev):
        st = steps[k]
        start = 0 if prev is None else prev + 1
        for j in range(start, len(reqs)):
            r = reqs[j]
            if prev is not None:
                if st.get('within') is not None and r['ts'] - reqs[prev]['ts'] > st['within']: break
                if st.get('max_pages_between') is not None and (pref[j] - pref[prev + 1]) > st['max_pages_between']: break
            if st.get('first_page_in_session') and j != first_page: continue
            if not P(st['match'], r): continue
            if k == len(steps) - 1: return [j]
            rest = rec(k + 1, j)
            if rest: return [j] + rest
            if prev is None and st.get('first_page_in_session'): return None
        return None
    return rec(0, None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('logs', nargs='+'); ap.add_argument('--sig', required=True); ap.add_argument('--asn', default='')
    ap.add_argument('--out', default='hits'); ap.add_argument('--gap', type=int, default=1800)
    a = ap.parse_args()
    S = yaml.safe_load(open(a.sig)); lists = S.get('lists', {})
    sigs = [s for s in S['signatures'] if s.get('status', 'active') != 'disabled']
    P = Pred(lists); asn = ASN(a.asn)
    req_sigs = [s for s in sigs if s['scope'] == 'request']
    ses_sigs = [s for s in sigs if s['scope'] == 'session']
    win_sigs = [s for s in sigs if s['scope'] == 'window']
    os.makedirs(a.out, exist_ok=True)
    out = open(os.path.join(a.out, 'hits.jsonl'), 'w', encoding='utf-8')
    counts = collections.Counter(); ipsig = collections.defaultdict(lambda: collections.defaultdict(int)); ipinfo = {}
    def emit(s, key, reqs, ev, metrics):
        rec = dict(sig=s['id'], title=s['title'], category=s['category'], severity=s['severity'], confidence=s['confidence'],
                   action=s['action'], key=key, ip=reqs[0]['ip'], org=reqs[0]['org'], asn=reqs[0]['asn'], ua=reqs[0]['ua'][:200],
                   start=datetime.fromtimestamp(reqs[0]['ts']).isoformat(), end=datetime.fromtimestamp(reqs[-1]['ts']).isoformat(),
                   metrics=metrics, evidence=[brief(r) for r in ev][:12])
        out.write(json.dumps(rec, ensure_ascii=False) + '\n')
        counts[s['id']] += 1; ipsig[rec['ip']][s['id']] += 1; ipinfo[rec['ip']] = (rec['org'], rec['asn'])
    open_s = {}; recent404 = {}
    reqagg = collections.defaultdict(lambda: dict(n=0, ev=[]))
    win = {s['id']: collections.defaultdict(lambda: dict(reqs=[], vals=collections.defaultdict(set), cnt=collections.Counter())) for s in win_sigs}
    def close(ip):
        reqs = open_s.pop(ip)
        for s in ses_sigs:
            rr = [r for r in reqs if P(s.get('where'), r)] if s.get('where') else reqs
            if not rr: continue
            ev = []; metrics = []
            if s.get('sequence'):
                idx = eval_sequence(rr, s['sequence'], P)
                if not idx: continue
                ev = [rr[i] for i in idx]; metrics.append('steps=' + '→'.join(st['as'] for st in s['sequence']))
            m = eval_aggs(rr, s.get('require'), P)
            if m is None: continue
            emit(s, ip, rr, ev or rr[:6], metrics + m)
    n = bad = 0
    for path in a.logs:
        fh = sys.stdin if path == '-' else (gzip.open(path, 'rt', encoding='utf-8', errors='replace') if path.endswith('.gz') else open(path, encoding='utf-8', errors='replace'))
        for line in fh:
            m = LINE.match(line)
            if not m: bad += 1; continue
            n += 1
            r = make_record(m, asn, lists, recent404)
            if n % 200000 == 0:
                now = r['ts']
                for k in [k for k, v in open_s.items() if now - v[-1]['ts'] > a.gap + 600]: close(k)
                for k in [k for k, v in recent404.items() if now - v[0] > 7200]: del recent404[k]
            if r['method'] == 'GET' and r['status'] == 404 and not r['is_bot_ua'] and not r['is_static']:
                recent404[r['base']] = (r['ts'], r['ip'])
            for s in req_sigs:
                if P(s.get('match'), r):
                    g = reqagg[(s['id'], r['ip'], r['day'])]
                    g['n'] += 1
                    if len(g['ev']) < 6: g['ev'].append(r)
            ip = r['ip']; cur = open_s.get(ip)
            if cur and r['ts'] - cur[-1]['ts'] > a.gap: close(ip); cur = None
            if cur is None: open_s[ip] = cur = []
            cur.append(r)
            for s in win_sigs:
                if s.get('where') and not P(s['where'], r): continue
                key = (r['ip'] + '|' + r['ua']) if s.get('key') == 'ip_ua' else r['ip']
                bucket = r['day'] + (f" {r['hour']:02d}" if s.get('window') == 'hour' else '')
                w = win[s['id']][(key, bucket)]
                if len(w['reqs']) < 12: w['reqs'].append(r)
                for i, ag in enumerate(s.get('require', [])):
                    if not P(ag.get('match'), r): continue
                    if ag['agg'] == 'distinct' and r.get(ag['field']) is not None: w['vals'][i].add(r[ag['field']])
                    w['cnt'][i] += 1
                    if ag['agg'] in ('burst', 'span'): w['vals'][i].add(r['ts'])
        if fh is not sys.stdin: fh.close()
    for ip in list(open_s): close(ip)
    byid = {s['id']: s for s in req_sigs}
    for (sid, ip, day), g in reqagg.items():
        emit(byid[sid], ip, g['ev'], g['ev'], [f'requests={g["n"]}', f'day={day}'])
    for s in win_sigs:
        for (key, bucket), w in win[s['id']].items():
            ok = True; metrics = []
            for i, ag in enumerate(s.get('require', [])):
                if ag['agg'] == 'count': v = w['cnt'][i]
                elif ag['agg'] == 'distinct': v = len(w['vals'][i])
                elif ag['agg'] == 'span': v = (max(w['vals'][i]) - min(w['vals'][i])) if w['vals'][i] else 0
                else: v = burst(list(w['vals'][i]), ag.get('window', 60))
                if not OPS[ag['op']](v, ag['value']): ok = False; break
                metrics.append(f"{ag['agg']}{'('+ag['field']+')' if ag.get('field') else ''}={v}")
            if ok:
                metrics.append(f'window={bucket}'); emit(s, key, w['reqs'], w['reqs'], metrics)
    out.close()
    with open(os.path.join(a.out, 'summary.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        wr = csv.writer(f); wr.writerow(['sig', 'title', 'category', 'severity', 'hits', 'ips'])
        for s in sigs:
            wr.writerow([s['id'], s['title'], s['category'], s['severity'], counts[s['id']], sum(1 for ip in ipsig if s['id'] in ipsig[ip])])
    rank = {'info': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}; sev = {s['id']: s['severity'] for s in sigs}; act = {s['id']: s['action'] for s in sigs}
    with open(os.path.join(a.out, 'ips.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        wr = csv.writer(f); wr.writerow(['ip', 'org', 'asn', 'max_severity', 'signatures', 'actions'])
        for ip, d in sorted(ipsig.items(), key=lambda kv: -max(rank[sev[k]] for k in kv[1])):
            ms = max(d, key=lambda k: rank[sev[k]])
            wr.writerow([ip, ipinfo[ip][0], ipinfo[ip][1], sev[ms], ' '.join(f'{k}×{v}' for k, v in d.items()), ' '.join(sorted({x for k in d for x in act[k]}))])
    print(f'lines={n} unparsed={bad} hits={sum(counts.values())}', file=sys.stderr)
    for s in sigs: print(f"  {s['id']:16} {counts[s['id']]:7}  {s['title']}", file=sys.stderr)

if __name__ == '__main__':
    main()
