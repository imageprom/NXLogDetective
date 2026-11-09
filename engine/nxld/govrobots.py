"""NXLD: ведомственные роботы (проверяющие системы Роскомнадзора — сети ГРЧЦ; сканер СайберОК): кто, что смотрели, что получили, отказы.

Типы и операторы проставляет visits.mark_gov_robots / finish_gov_robots (V.gov_op, V.gov_kind). Здесь — таблица для блока «Ведомственные роботы» листа «Роботы» (04),
числа для выжимки и снимка (всегда, даже без визитов) и две карточки «Общего анализа»: gov_robots_visit («К сведению»), gov_robots_refused («Важно»)."""
import re

import numpy as np
import pandas as pd

from . import gov, texts, thresholds
from .common import codes_text
from .webarchive import _n

REFUSED = (403, 429, 444)
ROBOT_KINDS = ('scanner_security', 'scanner_browser')


def _dmy(x, hm=False):
    """Дата для текста карточки: 01.09.2026 (с hm — 01.09.2026 11:12)."""
    t = pd.Timestamp(x)
    return t.strftime('%d.%m.%Y %H:%M' if hm else '%d.%m.%Y')


def _empty():
    return dict(came=False, visits=0, ips=0, first=None, last=None, robots=dict(visits=0, ips=0), visitors=dict(visits=0, ips=0, ad_clicks=0), by_operator={}, by_kind={},
                statuses={}, refused=dict(requests=0, ips=0, codes={}, addresses=[], first=None, last=None), error_log=dict(lines=0, ips=0, by_kind={}), compare=None)


def _ip_host_vids(c):
    """Номера визитов, которые обращались к хосту «IP вместо имени» (по IP сервера)."""
    from .hosts import normalize
    R = c.R
    if 'vhost' not in R: return set()
    ipnames = {normalize(r['хост']) for r in (c.m.get('hosts') or []) if r.get('причина') == 'IP вместо имени'}
    if not ipnames: return set()
    cats = [normalize(x) for x in R['vhost'].cat.categories]
    hit = np.array([x in ipnames for x in cats], bool)
    codes = R['vhost'].cat.codes.values
    rows = np.where(codes >= 0, hit[np.where(codes >= 0, codes, 0)], False)
    return set(R['vid'].values[rows].tolist())


def _origin(channel, ip_host):
    o = gov.tx().get('origins', {})
    if ip_host: return o.get('ip_host', '')
    return {'Реклама': o.get('ads', ''), 'Поиск': o.get('search', ''), 'Прямые заходы': o.get('direct', '')}.get(str(channel), str(channel))


def _kind_of(msg):
    return 'tls_probe' if re.search(r'SSL_do_handshake|bad key share|SSL: error', str(msg)) else 'other'


def _errorlog(c, ips):
    """Строки error-лога с клиентов из сетей справочника: по IP — «проба TLS: 66 за 8 дней»."""
    E = getattr(c, 'E_srv', None)
    if E is None or not len(E) or 'client' not in E or not ips: return {}, dict(lines=0, ips=0, by_kind={})
    m = E['client'].astype(str).isin(ips)
    if not m.any(): return {}, dict(lines=0, ips=0, by_kind={})
    X = E.loc[m, ['client', 'msg', 'ts']].copy()
    X['kind'] = X['msg'].map(_kind_of)
    X['day'] = pd.to_datetime(X['ts'], unit='s').dt.strftime('%Y-%m-%d')
    t = gov.tx()
    kinds, dw = t.get('errorlog', {}), t.get('days_word', ['день', 'дня', 'дней'])
    per_ip = {}
    for ip, g in X.groupby(X['client'].astype(str)):
        lines = []
        for k, gk in g.groupby('kind'):
            nd = gk['day'].nunique()
            word = dw[0] if nd % 10 == 1 and nd % 100 != 11 else dw[1] if 2 <= nd % 10 <= 4 and not 12 <= nd % 100 <= 14 else dw[2]
            lines.append(t.get('errorlog_line', '{kind}: {n} за {days} {days_word}').format(kind=kinds.get(k, k), n=_n(len(gk)), days=nd, days_word=word))
        per_ip[ip] = '\n'.join(lines)
    return per_ip, dict(lines=int(len(X)), ips=int(X['client'].nunique()), by_kind={kinds.get(k, k): int(v) for k, v in X['kind'].value_counts().items()})


def table_and_stats(c):
    """(таблица блока для листа «Роботы», числа для выжимки). Нет визитов — (пустая таблица, нули)."""
    V, R = c.V, c.R
    d = _empty()
    if 'gov_kind' not in V: return pd.DataFrame(), d
    vm = (V['gov_kind'].astype(str) != '').values
    if not vm.any(): return pd.DataFrame(), d
    t = gov.tx()
    ops, kinds = t.get('operators', {}), t.get('kinds', {})
    G = V[vm]
    gk = G['gov_kind'].astype(str)
    rob = gk.isin(ROBOT_KINDS)
    vis = gk == 'visitor'
    d.update(came=True, visits=int(len(G)), ips=int(G['ip'].astype(str).nunique()),
             robots=dict(visits=int(rob.sum()), ips=int(G.loc[rob, 'ip'].astype(str).nunique())),
             visitors=dict(visits=int(vis.sum()), ips=int(G.loc[vis, 'ip'].astype(str).nunique()), ad_clicks=int((vis & (G['channel'].astype(str) == 'Реклама')).sum())),
             by_operator={ops.get(o, o): int(n) for o, n in G['gov_op'].astype(str).value_counts().items()},
             by_kind={kinds.get(k, k): int(n) for k, n in gk.value_counts().items()})
    pos = V.index.get_indexer(R['vid'].values)
    rows = np.where(pos >= 0, vm[np.where(pos >= 0, pos, 0)], False)
    X = pd.DataFrame({'ip': R['ip'].astype(str).values[rows], 'kind': V['gov_kind'].astype(str).values[pos[rows]], 'op': V['gov_op'].astype(str).values[pos[rows]],
                      'asn': V['asn'].values[pos[rows]], 'vid': R['vid'].values[rows], 'ts': R['ts'].values[rows], 'st': R['status'].values[rows],
                      'base': R['base'].astype(str).values[rows], 'site': (R['host_site'].values[rows] if 'host_site' in R else np.ones(int(rows.sum()), bool))})
    d['first'], d['last'] = str(pd.to_datetime(int(X['ts'].min()), unit='s')), str(pd.to_datetime(int(X['ts'].max()), unit='s'))
    d['statuses'] = {str(int(k)): int(v) for k, v in X['st'].value_counts().sort_index().items()}
    ipv = _ip_host_vids(c)
    ch = V['channel'].astype(str).reindex(X['vid'].unique()) if len(X) else pd.Series(dtype=str)
    X['origin'] = [_origin(ch.get(v, ''), v in ipv) for v in X['vid'].values]
    X['kindname'] = X['kind'].map(lambda k: kinds.get(k, k))
    per_ip, d['error_log'] = _errorlog(c, sorted(X['ip'].unique()))
    out = []
    for (ip, kind), g in X.groupby(['ip', 'kind'], sort=False):
        pages = g['base'].value_counts()
        viewed = ', '.join(pages.index[:5]) + (' ' + t.get('more', 'и др.') if len(pages) > 5 else '')
        asn = int(g['asn'].iloc[0] or 0)
        net = t.get('nettype', 'госсеть') + (f", {ops.get(g['op'].iloc[0], g['op'].iloc[0])}" + (f' (AS{asn})' if asn else ''))
        out.append(dict(first=str(pd.to_datetime(int(g['ts'].min()), unit='s')), last=str(pd.to_datetime(int(g['ts'].max()), unit='s')), ip=ip, network=net, kind=kinds.get(kind, kind),
                        kind_code=kind, origin=g['origin'].value_counts().index[0], viewed=viewed, got=codes_text(g['st'].values), requests=int(len(g)), errorlog=per_ip.get(ip, '')))
    T = pd.DataFrame(out).sort_values('first').reset_index(drop=True)
    # отказы роботам на хостах сайта (хост «IP вместо имени» и подобранные имена — не сайт)
    R_ = X[X['kind'].isin(ROBOT_KINDS) & X['site'].astype(bool) & (X['st'].isin(REFUSED) | (X['st'] >= 500))]
    if len(R_):
        d['refused'] = dict(requests=int(len(R_)), ips=int(R_['ip'].nunique()), codes={str(int(k)): int(v) for k, v in R_['st'].value_counts().sort_index().items()},
                            addresses=[str(x) for x in R_['base'].value_counts().index[:3]], first=str(pd.to_datetime(int(R_['ts'].min()), unit='s')),
                            last=str(pd.to_datetime(int(R_['ts'].max()), unit='s')), operators=sorted({ops.get(o, o) for o in R_['op']}))
    d['_robot_pages'] = [str(x) for x in X[X['kind'].isin(ROBOT_KINDS)]['base'].value_counts().index[:5]]
    return T, d


def compare(now, prev):
    if not prev: return None
    return {k: dict(was=(prev.get(k) if not isinstance(prev.get(k), dict) else None), became=now.get(k)) for k in ('visits', 'ips')} | dict(
        robot_visits=dict(was=(prev.get('robots') or {}).get('visits'), became=now['robots']['visits']),
        visitor_visits=dict(was=(prev.get('visitors') or {}).get('visits'), became=now['visitors']['visits']),
        refused_requests=dict(was=(prev.get('refused') or {}).get('requests'), became=now['refused']['requests']))


def cards(F, d):
    t = gov.tx()
    ops = t.get('operators', {})
    if d['robots']['visits']:
        who = ', '.join(o for o in ops.values() if o in d['by_operator']) or ', '.join(d['by_operator'])
        kw = dict(visits=_n(d['robots']['visits']), ips=_n(d['robots']['ips']), who=who, first=_dmy(d['first']), last=_dmy(d['last']), viewed=', '.join(d['_robot_pages']) or '—',
                  visitors=_n(d['visitors']['visits']), ads=_n(d['visitors']['ad_clicks']))
        kw['visits'] = f"{kw['visits']} {_pl(d['robots']['visits'], 'визит', 'визита', 'визитов')}"
        kw['ips'] = f"{kw['ips']} {_pl(d['robots']['ips'], 'IP', 'IP', 'IP')}"
        F.add('Общий анализ', 'К сведению', 'gov_robots_visit', 'all', texts.fmt('gov_robots_visit', 'title', **kw), texts.fmt('gov_robots_visit', 'facts', **kw),
              texts.fmt('gov_robots_visit', 'where'), texts.fmt('gov_robots_visit', 'action'), d['robots']['visits'], '')
    r = d['refused']
    if r['requests'] >= int(thresholds.value('gov_refused_min', 1)):
        kw = dict(n=_n(r['requests']), codes=', '.join(f'{k} — {v}' for k, v in r['codes'].items()), urls=', '.join(r['addresses']), first=_dmy(r['first'], True), last=_dmy(r['last'], True),
                  who=', '.join(r.get('operators') or []))
        F.add('Общий анализ', 'Важно', 'gov_robots_refused', 'all', texts.fmt('gov_robots_refused', 'title', **kw), texts.fmt('gov_robots_refused', 'facts', **kw),
              texts.fmt('gov_robots_refused', 'where'), texts.fmt('gov_robots_refused', 'action'), r['requests'], '')


def _pl(k, one, few, many):
    k = abs(int(k)) % 100
    if 11 <= k <= 19: return many
    k %= 10
    return one if k == 1 else few if 2 <= k <= 4 else many


def build(c, F, prev=None):
    """(res['gov_robots'] — всегда, нули без визитов; таблица блока). Карточки — в F."""
    T, d = table_and_stats(c)
    cards(F, d)
    d.pop('_robot_pages', None)
    d['compare'] = compare(d, prev)
    return d, T
