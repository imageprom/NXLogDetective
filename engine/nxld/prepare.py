"""NXLD: этап подготовки — логи разбираются один раз и складываются в базу проверки (nxld.duckdb), дальше всё считается по ней.
База — единственное хранилище запросов, визитов и error-лога (таблицы для расчётов — nxld/frames.py). Рядом — распечатки site_map.json и inventory.json."""
import json, os, re, time
from collections import Counter
import numpy as np, pandas as pd
from . import ingest, load, recon, visits, ipdb

VERSION = '0.3.0-beta1'


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


def run(paths, workdir, log=print, map_override=None):
    t0 = time.time()
    log('1/5 Приём файлов')
    from . import db
    con = db.connect(workdir)
    state = ingest.ingest(paths, workdir, log=log, con=con)
    src_ = state.get('sources', {}).values()
    if not any(r.get('kind') == 'access' and (r.get('lines') or 0) > 0 for r in src_):   # формат не распознан — дальше считать нечего
        bad_ = [os.path.basename(str(r.get('member') or r.get('path'))) for r in src_ if r.get('kind') not in ('access', 'error')]
        raise SystemExit('Ни одной строки access-лога не распознано' + (f" (не распознаны: {', '.join(bad_[:10])})" if bad_ else '') +
                         '. Пришлите 3–5 первых строк лога и log_format из конфигурации nginx: формат нужно добавить в engine/nxld/ingest.py (ACCESS_RX).')
    log('2/5 Сборка таблицы запросов')
    R, dup_report = load.load_requests(con)
    E = ingest.errors_frame(con)
    db.set_meta(con, 'engine_version', VERSION)
    from . import dims
    db.ensure(con, ['query_params', 'path_site'])
    from . import hosts as hosts_
    hosts = site_hosts_from(state, R)
    if map_override and map_override.get('site_hosts'): hosts = list(map_override['site_hosts']) + hosts   # поправка добавляет домены сайта (первый — основной)
    not_site = [hosts_.normalize(h) for h in (map_override or {}).get('not_site_hosts') or []]   # поправка убирает домены: это не сайт
    hosts = [h for h in hosts_.names_only(hosts) if h not in not_site]   # только имена: IP сервера — не домен сайта
    vh_names = [n for n in dict.fromkeys(hosts_.normalize(v) for v in (R['vhost'].cat.categories if 'vhost' in R else [])) if n]   # хосты, к которым обращаются в этом логе (включая IP сервера)
    R = load.add_features(R, con, hosts + [h for h in vh_names if h not in hosts])   # реферер с любого из них — переход внутри сервера, не «внешний сайт»
    site_mask, host_table, copy_mask = hosts_.classify(R, hosts, not_site)   # тип хоста — один раз, по запросам к нему; дальше его берут блоки
    dims.store_hosts(con, host_table, hosts_.normalize)   # область хоста: сайт / тот же сервер / копии вне отчёта
    off_ = hosts_.summary(host_table)
    if copy_mask.any() and not copy_mask.all():   # копии на других доменах — вне всех блоков отчёта, включая 03 и 04: из данных убираем (счёт — в сводке хостов)
        R = R[~copy_mask].reset_index(drop=True)
        site_mask = site_mask[~copy_mask]
        for c_ in R.columns:
            if str(R[c_].dtype) == 'category': R[c_] = R[c_].cat.remove_unused_categories()
        off_['копии_запросов'] = int(copy_mask.sum())
    R['host_site'] = site_mask
    if off_['хостов']:
        log(f"   хостов вне сайта: {off_['хостов']}, запросов к ним {off_['запросов']:,} ({off_['запросов'] / max(1, len(R)):.1%}): " + ', '.join(f"{r['хост']} ({r['запросов']:,})" for r in off_['хосты'][:8])
            + (f"; копии на других доменах — {off_['копии_запросов']:,} запросов, вне всех блоков отчёта" if off_.get('копии_запросов') else ''))
    T = load.ip_table(R, con)
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
    if map_override and map_override.get('form_success_rules'):   # поправки карты — до расчёта целей (R.goal, goal_success, n_goal, n_conv), а не только в site_map.json
        rules = {k: v for k, v in dict(map_override['form_success_rules']).items() if str(v).startswith('цель')}
    # сотрудники: успешные запросы к админке движка
    admin_rx = '|'.join(recon.ADMIN_PATHS[e] for e in engines['движок'] if e in recon.ADMIN_PATHS) or recon.GENERIC_ADMIN
    bases = R['base'].cat.categories.to_series()
    is_admin = bases.str.contains(admin_rx, regex=True).values[R['base'].cat.codes.values]
    R['is_admin'] = is_admin
    A = R.loc[is_admin & R['ua_browser'].values, ['ip', 'base', 'method', 'status', 'bytes']]
    staff_ips = recon.admin_staff(A, admin_rx)   # вход или работа в админке; ответ размера формы входа — не сотрудник
    if map_override: staff_ips += map_override.get('staff_ips', [])
    if map_override and map_override.get('staff_ips_remove'):   # ошибочно найденные «сотрудники» (например, зонд формы входа)
        rm_ = set(map_override['staff_ips_remove'])
        staff_ips = [i for i in staff_ips if i not in rm_]
    staff_ips = list(dict.fromkeys(staff_ips))
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
                    get_pd_requests=int(len(G)), hosts=host_table, off_site=off_)
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
    from . import orders as orders_, reference
    eng_spec = reference.engine_orders([e.get('движок') for e in engines.to_dict('records')])
    spec = reference.site_orders(eng_spec, map_override)   # заказы магазина — по справочнику найденных движков (#22) и поправкам карты (своя корзина)
    is_goal = post & fkey.isin(list(rules.keys())).values & ~orders_.not_goals(R, spec) & R['host_site'].values   # к хостам вне сайта цели не считаются (#23); шаги оформления, проверка подписки, кабинет и админка — не цели
    succ = np.zeros(len(R), dtype=bool)
    for k, rule in rules.items():
        m = is_goal & (fkey.values == k)
        if '3xx' in rule: succ |= m & np.isin(R['status'].values, [302, 303])
        else: succ |= m & (R['status'].values == 200)
    goal = np.where(is_goal, fkey.values, '').astype(object)
    is_order = np.zeros(len(R), dtype=bool)
    pos, ids = orders_.first_orders(R, spec, R['host_site'].values)   # заказ — один раз: в визите, где номер встретился впервые (V.n_conv — число таких номеров)
    if len(pos):
        goal[pos] = R['tpl'].astype(str).values[pos]; is_goal[pos] = True; succ[pos] = True; is_order[pos] = True
    site_map['orders'] = dict(движки=spec['движки'], заказов=len(pos), to_verify=spec['to_verify'])
    if len(pos): log(f"   заказов по номеру: {len(pos):,} ({', '.join(spec['движки'])})")
    R['goal'] = pd.Categorical(goal)
    R['goal_success'] = succ
    R['is_order'] = is_order
    R['order_step'] = orders_.steps(R, spec)   # шаги оформления: ошибка на них — возможная потеря заказа (карточка «Заявки», #24)
    from . import shop
    sh = shop.detect(R, V, spec, eng_spec, map_override or {}, site_map['catalog_templates'])   # магазин опознаётся сам: корзина, оформление, действия с товаром (поправки карты важнее)
    site_map['orders'].update(cart=shop.with_text(sh['pages']['cart']), checkout=shop.with_text(sh['pages']['checkout']), success=shop.with_text(sh['pages']['success']))
    site_map['site_actions_found'] = shop.with_text(sh['found'])
    site_map['shop'] = dict(spec_add=sh['spec_add'], rules=sh['rules'], cart_separable=sh['cart_separable'], step=sh['step'])
    if sh['step'] == 'action':
        from . import texts
        site_map['shop']['note'] = texts.file('shop').get('cart_not_separable', '')
    if sh['found']: log('   действия на сайте: ' + ', '.join(f"{f['kind']} {f['path']} ({f['how']}, визитов {f['visits']})" for f in sh['found'][:6]))
    V['n_goal'] = pd.Series(is_goal, index=R.index).groupby(R['vid']).sum()
    V['n_conv'] = pd.Series(succ, index=R.index).groupby(R['vid']).sum()
    dims.store_path_site(con, R['base'].cat.categories, tpl, bases.str.contains(admin_rx, regex=True).values, site_map['catalog_templates'])
    from . import store
    store.all_of(workdir, R, V, site_map, map_override, con=con, prepared=True)   # признаки событий, визиты и карта сайта — в базу проверки
    con.close()
    log('5/5 Сохранение')
    F, gaps = inventory(state, R, E, dup_report)
    inv = dict(version=VERSION, files=F.astype(str).to_dict('records'), duplicates=dup_report, hour_gaps=[str(g) for g in gaps],
               requests=int(len(R)), ips=int(R['ip'].nunique()), period=[str(pd.to_datetime(R.ts.min(), unit='s')), str(pd.to_datetime(R.ts.max(), unit='s'))],
               tz=Counter(r.get('tz') for r in state['sources'].values() if r.get('tz')).most_common(1)[0][0] if any(r.get('tz') for r in state['sources'].values()) else '',
               period_errors=[str(pd.to_datetime(E['ts'].min(), unit='s')), str(pd.to_datetime(E['ts'].max(), unit='s'))] if len(E) else None,
               errors_lines=int(len(E)), seconds=round(time.time() - t0))
    json.dump(site_map, open(os.path.join(workdir, 'site_map.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    json.dump(inv, open(os.path.join(workdir, 'inventory.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    log(f'Готово за {time.time()-t0:.0f} с: визитов {len(V):,}')
    return R, V, site_map, inv
