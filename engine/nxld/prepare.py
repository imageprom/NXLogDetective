"""NXLD: этап подготовки — один полный разбор, затем всё считается по компактным таблицам.
Сохраняет в рабочую папку: R.pkl (запросы), V.pkl (визиты), E.pkl (error-лог), site_map.json, inventory.json."""
import json, os, re, time
from collections import Counter
import numpy as np, pandas as pd
from . import ingest, load, recon, visits, ipdb

VERSION = '0.2.0-alpha'


def site_hosts_from(state, R):
    names = Counter(r.get('site_by_name') for r in state['sources'].values() if r.get('site_by_name'))
    hosts = [h for h, _ in names.most_common()]
    if not hosts:
        rh = R['ref'].astype(str).str.extract(r'^https?://(?:www\.)?([^/:?#]+)')[0].value_counts()
        hosts = [rh.index[0]] if len(rh) else []
    return hosts


def inventory(state, R, E, dup_report):
    rows = []
    for sid, r in state['sources'].items():
        rows.append(dict(файл=sid, тип=r['kind'], формат=r.get('format') or '', сайт_по_имени=r.get('site_by_name') or '',
                         строк=r.get('lines', 0), нераспознано=r.get('bad', 0),
                         с=pd.to_datetime(r['first'], unit='s') if r.get('first') else None,
                         по=pd.to_datetime(r['last'], unit='s') if r.get('last') else None))
    F = pd.DataFrame(rows).sort_values(['тип', 'с'])
    # пропуски по времени: часы без единой строки внутри периода
    hours = pd.Series(1, index=pd.to_datetime(R['ts'] // 3600 * 3600, unit='s')).groupby(level=0).size()
    full = pd.date_range(hours.index.min(), hours.index.max(), freq='h')
    gaps = [h for h in full if h not in hours.index]
    return F, gaps


def compact_save(R, V, T, G, workdir):
    """Компактное хранение: без лишних столбцов, узкие типы, справочники вместо строк; куски разбора удаляются."""
    import glob
    R = R.drop(columns=[c for c in ('user', 'tail', '_ord') if c in R.columns])
    for c, t in (('ts', 'uint32'), ('bytes', 'uint32'), ('asn', 'uint32'), ('vid', 'int32')):
        if c in R.columns and R[c].max() < np.iinfo(t).max: R[c] = R[c].astype(t)
    for c in R.columns:
        if str(R[c].dtype) == 'category': R[c] = R[c].cat.remove_unused_categories()
    R.to_pickle(os.path.join(workdir, 'R.pkl'))
    V = V.copy()
    for c in V.columns:
        if V[c].dtype == object and V[c].nunique() < 0.5 * len(V): V[c] = V[c].astype('category')
    V.to_pickle(os.path.join(workdir, 'V.pkl'))
    T.to_pickle(os.path.join(workdir, 'T.pkl'))
    G = G.copy()
    for c in G.columns:
        if str(G[c].dtype) == 'category': G[c] = G[c].astype(str)
    G.to_pickle(os.path.join(workdir, 'G.pkl'))
    for fn in glob.glob(os.path.join(workdir, 'req_*.pkl')):
        os.remove(fn)
    st = os.path.join(workdir, 'ingest_state.json')
    j = json.load(open(st))
    for r in j['sources'].values():
        if r.get('kind') == 'access': r['done'] = False   # куски удалены: повторный prepare перечитает логи
    j['next_chunk'] = 0
    json.dump(j, open(st, 'w'), ensure_ascii=False, indent=1, default=str)


def run(paths, workdir, log=print, map_override=None):
    t0 = time.time()
    log('1/5 Приём файлов')
    state = ingest.ingest(paths, workdir, log=log)
    log('2/5 Сборка таблицы запросов')
    R, dup_report = load.load_requests(workdir, state)
    E = pd.read_pickle(os.path.join(workdir, 'errors.pkl')) if os.path.exists(os.path.join(workdir, 'errors.pkl')) else pd.DataFrame()
    hosts = site_hosts_from(state, R)
    if map_override and map_override.get('site_hosts'): hosts = map_override['site_hosts']
    R = load.add_features(R, hosts)
    T = load.ip_table(R)
    R = load.attach_ip(R, T)
    log(f'   запросов {len(R):,}, IP {len(T):,}, {time.time()-t0:.0f} с')
    log('3/5 Разведка')
    engines, engines_all = recon.detect_engine(R)
    server = recon.detect_server(R, E)
    pagelike = np.isin(R['method'].values, ['GET']) & ~R['is_static'].values & R['ua_browser'].values & (R['status'].values == 200)
    tpl = recon.build_templates(R, pagelike)
    log('4/5 Визиты и очистка')
    R = visits.build(R)
    emb_codes, emb_tbl = visits.detect_embedded(R, tpl)
    R = visits.build(R, emb_codes)
    R['tpl'] = pd.Categorical(tpl[R['base'].cat.codes.values])
    forms, rules = recon.detect_forms(R, tpl)
    # сотрудники: успешные запросы к админке движка
    admin_rx = '|'.join(recon.ADMIN_PATHS[e] for e in engines['движок'] if e in recon.ADMIN_PATHS) or recon.GENERIC_ADMIN
    bases = R['base'].cat.categories.to_series()
    is_admin = bases.str.contains(admin_rx, regex=True).values[R['base'].cat.codes.values]
    R['is_admin'] = is_admin
    A = R.loc[is_admin & R['ua_browser'].values]
    ok_admin = A[(A['status'] == 200) & ~A['base'].astype(str).str.contains(r'login|auth', case=False)]
    staff = ok_admin.groupby('ip', observed=True).size()
    staff_ips = staff[staff >= 5].index.astype(str).tolist()
    if map_override: staff_ips += map_override.get('staff_ips', [])
    # мониторинги: один адрес с одного IP строго по расписанию
    cand = R.groupby(['ip', 'ua', 'base'], observed=True).size()
    cand = cand[cand >= 300].reset_index()
    monitors = []
    for _, c in cand.iterrows():
        t = R.loc[(R['ip'] == c['ip']) & (R['ua'] == c['ua']) & (R['base'] == c['base']), 'ts'].values
        d = np.diff(t)
        if len(d) > 50 and np.median(d) > 20 and np.std(d) / (np.mean(d) + 1e-9) < 0.5:
            monitors.append(dict(ip=str(c['ip']), ua=str(c['ua']), адрес=str(c['base']), запросов=int(c[0]), интервал_с=int(np.median(d))))
    mon_keys = [(m['ip'], m['ua']) for m in monitors]
    V = visits.aggregate(R, staff_ips, mon_keys)
    # входы людей: метки
    entry_mask = R['is_page'].values & np.isin(R['vid'].values, V.index[(V['group'] == 'Люди').values]) & ~R['ref_internal'].values
    ad_known, ad_other = recon.detect_ad_params(R, entry_mask)
    services = recon.detect_service_files(R)
    G = recon.detect_get_pd(R)
    # элементы каталога: шаблоны, оканчивающиеся на *, с >= 30 разными адресами у людей
    hp = R.loc[R['is_page'].values & np.isin(R['vid'].values, V.index[(V['group'] == 'Люди').values]), ['tpl', 'base']]
    tp = hp.groupby('tpl', observed=True)['base'].nunique().sort_values(ascending=False)
    catalog = [t for t, n in tp.items() if n >= 30 and re.search(r'/[\w-]{0,8}\*/?$', t)]
    sections = hp['base'].astype(str).str.extract(r'^(/[^/]*/?)')[0].value_counts().head(30)
    # предзагружаемые формы: GET-адрес формы почти в каждом визите людей
    hv = V[(V['group'] == 'Люди') & (V['n_pages'] >= 1)].index
    preloaded = emb_tbl['шаблон'].tolist()
    site_map = dict(version=VERSION, site_hosts=hosts, server=server,
                    engines=engines.to_dict('records'), engines_all=engines_all.to_dict('records'),
                    admin_regex=admin_rx, staff_ips=staff_ips, monitors=monitors,
                    embedded_templates=emb_tbl.to_dict('records'), forms=forms.to_dict('records') if len(forms) else [],
                    form_success_rules=rules, ad_params=ad_known, other_entry_params=ad_other,
                    catalog_templates=catalog, top_sections=sections.to_dict(),
                    service_files=services.head(40).to_dict('records') if len(services) else [],
                    get_pd_requests=int(len(G)))
    if map_override:
        for k, v in map_override.items():
            if k not in ('staff_ips', 'site_hosts'): site_map[k] = v
    R['is_catalog'] = R['tpl'].isin(site_map['catalog_templates']).values & R['is_page'].values
    V['n_catalog'] = R.groupby('vid')['is_catalog'].sum()
    # конверсии: POST на цель с признаком успеха
    post = (R['method'].values == 'POST') & R['ref_internal'].values
    qc = R['query'].cat.categories.to_series().str.extract(r'(?:^|&)(?:form|form_id|WEB_FORM_ID|formid|form_name)=([^&]+)', flags=re.I)[0].fillna('').values
    fq = qc[R['query'].cat.codes.values]
    fkey = pd.Series(R['tpl'].astype(str).values + np.where(fq != '', '?form=' + fq, ''), index=R.index)
    is_goal = post & fkey.isin(list(rules.keys())).values
    succ = np.zeros(len(R), dtype=bool)
    for k, rule in rules.items():
        m = is_goal & (fkey.values == k)
        if '3xx' in rule: succ |= m & np.isin(R['status'].values, [302, 303])
        else: succ |= m & (R['status'].values == 200)
    R['goal'] = pd.Categorical(np.where(is_goal, fkey.values, ''))
    R['goal_success'] = succ
    V['n_goal'] = pd.Series(is_goal, index=R.index).groupby(R['vid']).sum()
    V['n_conv'] = pd.Series(succ, index=R.index).groupby(R['vid']).sum()
    log('5/5 Сохранение')
    F, gaps = inventory(state, R, E, dup_report)
    inv = dict(version=VERSION, files=F.astype(str).to_dict('records'), duplicates=dup_report, hour_gaps=[str(g) for g in gaps],
               requests=int(len(R)), ips=int(R['ip'].nunique()), period=[str(pd.to_datetime(R.ts.min(), unit='s')), str(pd.to_datetime(R.ts.max(), unit='s'))],
               tz=Counter(r.get('tz') for r in state['sources'].values() if r.get('tz')).most_common(1)[0][0] if any(r.get('tz') for r in state['sources'].values()) else '',
               errors_lines=int(len(E)), seconds=round(time.time() - t0))
    compact_save(R, V, T, G, workdir)
    json.dump(site_map, open(os.path.join(workdir, 'site_map.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    json.dump(inv, open(os.path.join(workdir, 'inventory.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    log(f'Готово за {time.time()-t0:.0f} с: визитов {len(V):,}')
    return R, V, site_map, inv
