"""NXLD: робот веб-архива (Internet Archive, Wayback Machine): приходил ли, что получил, не нагружает ли сайт и не отказываем ли ему.

Считается по запросам роботов веб-архива (подпись archive.org_bot, special_archiver и сохранение страницы по сети и почерку) к хостам сайта.
Результат — res['web_archive'] (выжимка, снимок, сравнение с прошлой проверкой всегда) и две карточки блока «Боты»: web_archive_refused, web_archive_outage.
Подпись архива из чужой сети — «Боты · подделка робота» (общее правило подлинности), в счёт не идёт, считается отдельно (fake)."""
import numpy as np
import pandas as pd

from . import texts, thresholds

REFUSED = (403, 429, 444)


def families():
    f = texts.file('robots').get('families', {})
    return [f.get('web_archive', 'Internet Archive'), f.get('web_archive_save', '')]


def _n(x):
    return f'{int(x):,}'.replace(',', ' ')


def _pct(x):
    return f'{x:.1f}'.replace('.', ',')


def _pl(k, one, few, many):
    k = abs(int(k)) % 100
    if 11 <= k <= 19: return many
    k %= 10
    return one if k == 1 else few if 2 <= k <= 4 else many


def _t(ts):
    return str(pd.to_datetime(int(ts), unit='s'))


def rows(c):
    """Маски строк R: настоящий робот веб-архива на хостах сайта, подпись из чужой сети."""
    R = c.R
    fam = R['fam'].isin([x for x in families() if x]).values
    rg = np.asarray(c.rg)
    site = R['host_site'].values.astype(bool) if 'host_site' in R else np.ones(len(R), bool)
    return fam & (rg == 'Роботы') & site, fam & (rg == 'Боты')


def _empty():
    return dict(came=False, requests=0, ips=0, first=None, last=None, days=0, pages=0, resources=0, robots_txt=0, statuses={}, peak_per_minute=dict(requests=0, minute=None),
                save_page=dict(visits=0, requests=0), fake=dict(requests=0, ips=0), refused=dict(requests=0, share=0.0, codes={}, addresses=[], days=[], source='', countries=[]),
                outage=[], outage_coincide=dict(windows=0, archive_requests=0))


def stats(c, windows=None):
    """Числа по роботу веб-архива для выжимки и снимка; ключи латиницей. Нет архива — нули, came=False."""
    R = c.R
    real, fake = rows(c)
    d = _empty()
    if fake.any():
        d['fake'] = dict(requests=int(fake.sum()), ips=int(pd.Series(R['ip'].astype(str).values[fake]).nunique()))
    if not real.any(): return d
    ts, st = R['ts'].values, R['status'].values
    page = R['is_page'].values
    base_c = R['base'].cat.categories
    rb = np.zeros(len(R), bool)
    k = base_c.get_indexer(['/robots.txt'])[0]
    if k >= 0: rb = R['base'].cat.codes.values == k
    mn = pd.Series(ts[real] // 60).value_counts()
    d.update(came=True, requests=int(real.sum()), ips=int(pd.Series(R['ip'].astype(str).values[real]).nunique()), first=_t(ts[real].min()), last=_t(ts[real].max()),
             days=int(pd.Series(R['day'].astype(str).values[real]).nunique()), pages=int((real & page).sum()), robots_txt=int((real & rb).sum()),
             statuses={str(int(k_)): int(v) for k_, v in pd.Series(st[real]).value_counts().sort_index().items()},
             peak_per_minute=dict(requests=int(mn.iloc[0]), minute=_t(mn.index[0] * 60)))
    d['resources'] = d['requests'] - d['pages'] - d['robots_txt']
    sv = R['fam'].values[real].astype(str) == families()[1]
    d['save_page'] = dict(visits=int(pd.Series(R['vid'].values[real][sv]).nunique()), requests=int(sv.sum()))
    V = c.V
    sm = V['fam'].astype(str).values == families()[1]
    if sm.any():   # кандидат подписи Save Page Now: как выглядит сохранение страницы (подпись не подтверждена — to_verify)
        W = V[sm]
        d['save_page']['candidates'] = [dict(ua=str(u)[:300], visits=int(len(g)), ips=int(g['ip'].astype(str).nunique()), median_requests=int(g['n_req'].median()), median_seconds=int(g['dur'].median()),
                                             asn=7941, level='network_and_pattern', to_verify=True)
                                        for u, g in W.assign(ua=W['ua'].astype(str)).groupby('ua')][:5]
    ref = real & (np.isin(st, REFUSED) | (st >= 500))
    if ref.any():
        sub = pd.Series(st[ref])
        c34 = int(sub.isin(REFUSED).sum()); c5 = int((sub >= 500).sum())
        tx = texts.card('web_archive_refused')
        src = tx.get('source_both') if c34 and c5 else tx.get('source_filter') if c34 else tx.get('source_site')
        ips = pd.Series(R['ip'].values[ref]).astype(str).unique()[:50]
        cc = []
        if c34:
            from . import ipdb
            cc = [str(x) for x in ipdb.lookup(list(ips))['cc'].replace('', np.nan).dropna().value_counts().index[:3]]
        d['refused'] = dict(requests=int(ref.sum()), share=round(ref.sum() / real.sum() * 100, 1),
                            codes={str(int(k_)): int(v) for k_, v in sub.value_counts().sort_index().items()},
                            addresses=[str(x) for x in pd.Series(R['base'].values[ref].astype(str)).value_counts().index[:3]],
                            days=sorted(map(str, pd.unique(R['day'].values[ref].astype(str))))[:10], source=src or '', countries=cc)
    d['outage'] = _outage(c, real, windows)
    d['outage_coincide'] = dict(windows=len(d['outage']), archive_requests=int(sum(w['archive_requests'] for w in d['outage'])))
    return d


def _outage(c, real, windows):
    """Окна сбоев (blocks.outage_windows по всем запросам сервера), в которые робот веб-архива шёл заметной долей трафика."""
    if windows is None:
        from .blocks import outage_windows
        _, windows = outage_windows(c.R, c.R['status'].values, c.E_srv)
    R = c.R
    ts, st = R['ts'].values, R['status'].values
    hum = c.human
    out = []
    for w in windows or []:
        a, b = pd.Timestamp(w['деградация_с']).timestamp(), pd.Timestamp(w['деградация_по']).timestamp()
        inw = (ts >= a) & (ts <= b)
        n_all, n_a = int(inw.sum()), int((inw & real).sum())
        if not n_a: continue
        mins = max(1, int((b - a) // 60) + 1)
        pk = int(pd.Series(ts[inw & real] // 60).value_counts().iloc[0])
        out.append(dict(start=str(w['деградация_с']), end=str(w['деградация_по']), minutes=mins, archive_requests=n_a, all_requests=n_all, archive_share=round(n_a / max(1, n_all) * 100, 1),
                        archive_per_minute=round(n_a / mins, 1), archive_peak_per_minute=pk, all_per_minute=round(n_all / mins, 1),
                        people_5xx=int((inw & hum & (st >= 500)).sum()), people_499=int((inw & hum & (st == 499)).sum()), people_requests=int((inw & hum).sum()),
                        pages_with_5xx=int(w.get('страниц_с_5xx') or 0)))
    return out


def cards(c, F, d):
    """Карточки блока «Боты»: отказы веб-архиву (Замечание) и обход в минуты сбоя (Важно)."""
    r = d['refused']
    mn, sh = int(thresholds.value('web_archive_refused_min', 3)), float(thresholds.value('web_archive_refused_share', 5))
    if d['came'] and r['requests'] >= mn and r['share'] >= sh:
        kw = dict(n=_n(r['requests']), total=_n(d['requests']), share=_pct(r['share']), codes=', '.join(f'{k} — {v}' for k, v in r['codes'].items()), urls=', '.join(r['addresses']),
                  days=', '.join(r['days']), source=r['source'] + (texts.card('web_archive_refused').get('countries', '').format(cc=', '.join(r['countries'])) if r['countries'] else ''))
        F.add('Боты', 'Замечание', 'web_archive_refused', 'all', texts.fmt('web_archive_refused', 'title', **kw), texts.fmt('web_archive_refused', 'facts', **kw),
              texts.fmt('web_archive_refused', 'where'), texts.fmt('web_archive_refused', 'action'), r['requests'], '')
    mo, so = int(thresholds.value('web_archive_outage_min', 20)), float(thresholds.value('web_archive_outage_share', 10))
    hit = [w for w in d['outage'] if w['archive_requests'] >= mo and w['archive_share'] >= so and (w['people_5xx'] or w['people_499'] or w['pages_with_5xx'])]
    if hit:
        parts = []
        for w in hit[:3]:
            parts.append(texts.fmt('web_archive_outage', 'window', start=w['start'][:16], end=w['end'][11:16], archive=_n(w['archive_requests']), archive_pm=_pct(w['archive_per_minute']),
                                   peak=_n(w['archive_peak_per_minute']), all_pm=_pct(w['all_per_minute']), p5=_n(w['people_5xx']), p499=_n(w['people_499'])))
        kw = dict(n=_n(sum(w['archive_requests'] for w in hit)), windows='; '.join(parts), k=len(hit))
        F.add('Боты', 'Важно', 'web_archive_outage', 'all', texts.fmt('web_archive_outage', 'title', **kw), texts.fmt('web_archive_outage', 'facts', **kw),
              texts.fmt('web_archive_outage', 'where'), texts.fmt('web_archive_outage', 'action'), sum(w['archive_requests'] for w in hit), '')


def compare(now, prev):
    """Было → стало к прошлой проверке: числа, которые есть в обоих снимках. Нет прошлой записи — None."""
    if not prev: return None
    keys = ('requests', 'ips', 'pages', 'resources', 'robots_txt', 'days')
    out = {k: dict(was=prev.get(k), became=now.get(k)) for k in keys if k in prev}
    out['peak_per_minute'] = dict(was=(prev.get('peak_per_minute') or {}).get('requests'), became=now['peak_per_minute']['requests'])
    out['refused_requests'] = dict(was=(prev.get('refused') or {}).get('requests'), became=now['refused']['requests'])
    out['outage_windows'] = dict(was=(prev.get('outage_coincide') or {}).get('windows'), became=now['outage_coincide']['windows'])
    return out


def build(c, F, prev=None, windows=None):
    """res['web_archive']: всегда (нули, если архив не приходил); карточки — в F."""
    d = stats(c, windows)
    cards(c, F, d)
    d['compare'] = compare(d, prev)
    return d
