"""NXLD: расчёт выбранных блоков по подготовленным таблицам. Результат — results.pkl (листы, сводки, проблемы)."""
import json, os, pickle, re, warnings
import numpy as np, pandas as pd
from . import coverage, profile, anatomy, visits, blocks, brief, recon, findings_meta, findings_text
from .findings import Findings, calibrate

warnings.filterwarnings('ignore')
STATUS_THRESHOLD = 0.30   # порог «стала хуже / исправлена частично» при повторной проверке
BLOCKS = ['Общий анализ', 'Ошибки', 'Нагрузка и безопасность', 'Боты', 'Маркетинг']


def cleaning_stats(R, V):
    H = V[V['group'] == 'Люди']
    return {
        'Просмотров у людей до очистки': int(H['n_pages_raw'].sum()), 'Просмотров у людей после очистки': int(H['n_pages'].sum()),
        'Склеено двойных загрузок (повтор адреса ≤ 5 с)': int(H['n_dup'].sum()), 'Склеено редиректов с их целью': int(H['n_redirect'].sum()),
        'Подгрузок форм и блоков (не считаются просмотрами)': int(H['n_embedded'].sum()),
        'Визитов людей во встроенных браузерах приложений': int(H['ua_webview'].sum()),
    }


def important_ips(c, S_bots):
    V, T = c.V, c.T.set_index('ip')
    rows = []
    def add(ips, cat, action):
        for ip in ips:
            vv = V[V['ip'] == ip]
            t = T.loc[ip] if ip in T.index else None
            rows.append(dict(ip=ip, категория=cat, сеть=t['org'] if t is not None else '', ASN=int(t['asn']) if t is not None else 0,
                             страна=t['cc'] if t is not None else '', тип_сети=t['nettype'] if t is not None else '',
                             визитов=len(vv), запросов=int(vv['n_req'].sum()), отправок=int(vv['n_goal'].sum()), принято=int(vv['n_conv'].sum()),
                             первый=blocks.dt(vv['start'].min()) if len(vv) else None, последний=blocks.dt(vv['end'].max()) if len(vv) else None,
                             действие=action if t is None or t['nettype'] in ('хостинг/облако',) else ('проверить/метка' if action.startswith('бан') else action)))
    spam = V[V['subgroup'].str.startswith('спам форм')]['ip'].unique()
    add(spam, 'спам форм', 'бан')
    if 'Подделки' in S_bots: add(S_bots['Подделки']['ip'].astype(str).unique(), 'поддельный робот', 'бан')
    if 'Операторы' in S_bots and len(S_bots['Операторы']):
        rc = set(x for x in ','.join(S_bots['Операторы'].get('адреса_разведки', pd.Series(dtype=str)).fillna('')).replace(' ', '').split(',') if x) - set(spam)
        add(sorted(rc), 'разведка оператора', 'наблюдение')
    add(c.m.get('staff_ips', []), 'свои: сотрудники', 'не трогать')
    add([m_['ip'] for m_ in c.m.get('monitors', [])], 'свои: мониторинг', 'не трогать')
    D = pd.DataFrame(rows, columns=['ip', 'категория', 'сеть', 'ASN', 'страна', 'тип_сети', 'визитов', 'запросов', 'отправок', 'принято', 'первый', 'последний', 'действие']).drop_duplicates('ip')
    return D


def run(workdir, selected=None, check_ips=(), marks=None, prev=None, log=print):
    selected = selected or BLOCKS
    selected = ['Общий анализ', 'Ошибки'] + [b for b in selected if b not in ('Общий анализ', 'Ошибки')]
    log('Загрузка подготовленных таблиц')
    R = pd.read_pickle(os.path.join(workdir, 'R.pkl'))
    V = pd.read_pickle(os.path.join(workdir, 'V.pkl'))
    T = pd.read_pickle(os.path.join(workdir, 'T.pkl'))
    G = pd.read_pickle(os.path.join(workdir, 'G.pkl'))
    E = pd.read_pickle(os.path.join(workdir, 'errors.pkl')) if os.path.exists(os.path.join(workdir, 'errors.pkl')) else pd.DataFrame()
    m = json.load(open(os.path.join(workdir, 'site_map.json')))
    inv = json.load(open(os.path.join(workdir, 'inventory.json')))
    V = visits.mark_scanners(V, R, [e.get('движок') for e in (m.get('engines') or []) if isinstance(e, dict)])   # сканеры под браузер — не люди
    V = visits.mark_form_spam(V, R)
    R, V, form_ev = visits.confirm_form_success(R, V)
    c = blocks.Ctx(R, V, E, T, m, inv, G)
    F = Findings()
    res = {'sheets': {}, 'summary': {}, 'selected': selected, 'site_map': m, 'inventory': inv, 'cleaning': cleaning_stats(R, V), 'form_evidence': form_ev,
           'hosting': recon.detect_hosting(E), 'check_ips': list(check_ips or []),
           'mobile_share': round(float(V.loc[V['group'] == 'Люди', 'ua_mobile'].mean()) * 100, 1) if (V['group'] == 'Люди').any() else None}
    fn = {'Общий анализ': lambda: blocks.overview(c, F), 'Ошибки': lambda: blocks.errors(c, F),
          'Нагрузка и безопасность': lambda: blocks.load_security(c, F), 'Боты': lambda: blocks.bots(c, F, check_ips),
          'Маркетинг': lambda: blocks.marketing(c, F)}
    for b in BLOCKS:
        if b in selected or b == 'Боты':   # боты считаем всегда: нужны для листа IP и спама форм
            log(f'Блок: {b}')
            S, s = fn[b]()
            res['sheets'][b] = S
            res['summary'][b] = s
    res['ips'] = important_ips(c, res['sheets'].get('Боты', {}))
    # GET-отправки — в «Нагрузку и безопасность» (03), рядом с карточкой о персональных данных
    go = res['sheets'].get('Общий анализ', {}).pop('GET-отправки', None)
    if go is not None and 'Нагрузка и безопасность' in res['sheets']:
        res['sheets']['Нагрузка и безопасность']['GET-отправки'] = go
    sp = V[V['subgroup'].str.startswith('спам форм')].sort_values('start')
    res['spam_examples'] = [dict(класс=k, ip=g['ip'].iloc[-1], время=str(blocks.dt(g['start'].iloc[-1]))[:16], вход=g['entry'].iloc[-1], визитов=len(g)) for k, g in sp.groupby('subgroup')]
    if 'Боты' not in selected:
        res['sheets'].pop('Боты'); res['summary'].pop('Боты')
        F.items = [x for x in F.items if x['блок'] != 'Боты']
    # важность по вреду, однотипное — одной проблемой
    F.items = calibrate(F.items, int((V['group'] == 'Люди').sum()), int(R['ts'].max()))
    # отметки «это норма» из прошлого снимка или от человека
    marks = dict((prev or {}).get('marks', {}), **(marks or {}))
    for x in F.items:
        if x['key'] in marks:
            x['статус'] = 'отмечено как норма'
            x['отметка'] = marks[x['key']]
    if prev:
        old = {x['key']: x for x in prev.get('findings', [])}
        thr = STATUS_THRESHOLD
        for x in F.items:
            if x['статус']: continue
            if x['key'] not in old:
                x['статус'], x['статус_вид'] = 'новая', 'новая'; continue
            o, n = old[x['key']].get('главная_цифра'), x['главная_цифра']
            x['было'], x['стало'] = o, n
            if isinstance(o, (int, float)) and isinstance(n, (int, float)) and o:
                ch = (n - o) / abs(o)
                vid = 'стала хуже' if ch >= thr else ('исправлена частично' if ch <= -thr else 'сохраняется')
                x['статус'] = f"{vid}: {o:g} → {n:g}" + (f" ({ch:+.0%})" if vid == 'исправлена частично' else '')
            else:
                vid = 'сохраняется'; x['статус'] = vid
            x['статус_вид'] = vid
        cur = {x['key'] for x in F.items}
        for k, o in old.items():
            if k not in cur and o.get('блок') in selected:
                F.items.append(dict(key=k, блок=o['блок'], важность='К сведению', что_происходит=o['что_происходит'], факты='В новом периоде не обнаружено. Проверить: исправлено или просто нет запросов к этому адресу.',
                                    где_править='', что_сделать='Убедиться, что исправлено', главная_цифра=None, лист='', также_в='', статус='исправлена', статус_вид='исправлена', было=o.get('главная_цифра')))
        rows = []
        for b, sm in res['summary'].items():
            for k, v in sm.items():
                ov = prev.get('summary', {}).get(b, {}).get(k)
                rows.append(dict(блок=b, показатель=k, было=ov, стало=v))
        res['compare'] = pd.DataFrame(rows)
        res['prev_period'] = prev.get('period')
    try:
        res['site_profile'] = profile.detect(c, res.get('site_map') or {})
    except Exception as e:
        res['site_profile'] = {'назначение': 'не определено', 'ошибка': str(e)}
    findings_meta.proofs(c, F.items, res['sheets'])
    flood_circumstance(F.items, res['sheets'])
    findings_text.humanize(F.items, res['sheets'], res['summary'])
    res['findings'] = F.items
    res['coverage'], res['loose_signals'] = coverage.check(res, F.items)
    res['query_params'] = getattr(c, 'query_params', None)
    from .thresholds import Sizes
    T_ = Sizes(визиты=int((V['group'] == 'Люди').sum()), запросы=len(R), ip=int(R['ip'].nunique()))   # пороги — доли от размера лога
    try:
        res['files'] = recon.files_inventory(R, T=T_).to_dict('records')
    except Exception as e:
        log(f'files_inventory: {e}'); res['files'] = None
    if res['files']:
        for x in res['findings']:
            if x['key'].split(':')[1] in ('missing_static', 'no_service', 'service_err', 'hotlink', 'ai_index', 'heavy_images'):
                x['ещё_листы'] = ['Файлы']
    try:
        res['anatomy'] = anatomy.build(c, res)
        sp_, np_ = res.get('site_profile') or {}, res['anatomy'].get('всего_страниц')
        if np_ and sp_.get('страниц'):   # одно число страниц везде: после склейки фильтров и без мусорных адресов
            sp_['страниц'] = np_; sp_['размер'] = 'маленький' if np_ <= 50 else 'средний' if np_ <= 5000 else 'большой'
    except Exception as e:
        import traceback; traceback.print_exc()
        res['anatomy'] = {'ошибка': str(e)}
    try:   # параметры — после «Анатомии»: нужны её системные папки и закрытые зоны; справочник — по найденному движку
        from .anatomy import PARAM_GROUPS, param_groups
        from . import reference
        A_ = res.get('anatomy') or {}
        site_ = (m.get('site_hosts') or ['site'])[0]
        ref = reference.load(m, R['base'].cat.categories.astype(str), site_)
        # системное — ядро, админка, API и закрытые зоны; шаблоны и доработки сайта (/local/ и т. п.) — это код самого сайта, не движок
        # системное — только папки движка по справочнику (ядро, админка, API); закрытые разделы сайта — отдельно: их сделал программист
        sysp = [p_ for p_ in ref.folders(('система', 'админка', 'api', 'служебное', 'обмен')) if p_.startswith('/')]
        if not sysp: sysp = [x['папка'] for x in A_.get('папки') or [] if not re.search(r'загруж|шаблон', str(x.get('что', '')))]
        zones_ = [x['адрес'] for x in A_.get('зоны') or [] if str(x.get('адрес', '')).startswith('/') and not any(x['адрес'].startswith(p_) for p_ in sysp)]
        FC = res['sheets'].get('Общий анализ', {}).get('Фасеты')
        navk = set(FC.groupby('ключ')['запросов'].sum().loc[lambda x: x >= T_('ключ_фасета')].index.astype(str)) if FC is not None and len(FC) else set()   # мусор из битых адресов — не фасет
        allref = reference.Reference([n_ for n_ in reference.all_engine_names()], (), site_)
        ref.other = allref
        ref.foreign_paths = reference.foreign_paths(allref, ref)
        Pr = recon.query_params_inventory(R, c.human, PARAM_GROUPS, navk, sysp, ref, staff=np.asarray(c.rg == 'Свои'), zone_prefixes=zones_, T=T_)
        res['params'] = Pr.to_dict('records')
        # незнакомые: нет в справочнике (или запись из поиска устарела) и заметное число запросов — Детектив ищет их в сети
        unk = Pr[(Pr['источник'] == 'дедукция') & ~Pr['группа'].isin(['Атаки и зонды', 'Логика сайта']) & (Pr['запросов'] >= T_('незнакомый_ключ'))]   # логику сайта в сети не найти
        stale = [r_ for r_ in res['params'] if r_['источник'].startswith('поиск') and ref.stale(ref.match(r_['ключ']))]
        res['unknown_params'] = [dict(ключ=r_['ключ'], ключи=r_['ключи'][:8], сейчас=r_['группа'], по=r_['источник'] or 'нет', запросов=r_['запросов'],
                                      людей=r_['людей'], значения=r_['значения'], где=r_['где'], роботы=r_['роботы'], вместе_с=r_['вместе_с'])
                                 for r_ in unk.head(40).to_dict('records')] + [dict(ключ=r_['ключ'], сейчас=r_['группа'], по='поиск, устарело', запросов=r_['запросов']) for r_ in stale[:10]]
        # подсказка Детективу: ключ описан у другого движка (на сайте его нет — часто это зонды под чужой движок)
        for u in res['unknown_params']:
            h_ = allref.match(u['ключ'])
            if h_ and h_.get('файл', '').startswith('engines/'): u['есть_у_другого_движка'] = f"{h_['название_файла']}: {h_['группа']} — {h_.get('что', '')}"
        res['reference_files'] = [f['файл'] for f in ref.files]
        adm_ = [p_ for p_ in ref.folders(('админка',)) if p_.startswith('/')]
        res['embedded'] = recon.embedded_inventory(R, c.human, m.get('embedded_templates'), adm_, zones_, T=T_).to_dict('records')
        ref.save()
        if 'параметры' in A_: A_['параметры'] = param_groups(m, res)
    except Exception as e:
        import traceback; traceback.print_exc(); res['params'] = None
    pickle.dump(res, open(os.path.join(workdir, 'results.pkl'), 'wb'))
    brief.save(brief.build(res, c, prev), workdir)
    log(f'Проблем найдено: {len(F.items)}')
    return res


def flood_circumstance(items, sheets):
    """Подделка, которая ещё и флудит, — обстоятельство к карточке подделок (не отдельная проблема)."""
    fl = sheets.get('Нагрузка и безопасность', {}).get('Флуд', pd.DataFrame())
    fk = sheets.get('Боты', {}).get('Подделки', pd.DataFrame())
    if not len(fl) or not len(fk): return
    top = fl[fl['запросов_в_минуту'] >= 1000].groupby('ip')['запросов_в_минуту'].max()
    hit = top[top.index.astype(str).isin(fk['ip'].astype(str))].sort_values(ascending=False)
    for x in items:
        if x['key'].split(':')[1] == 'fake_crawlers' and len(hit):
            add = f"подделка ещё и нагружает сервер: {hit.index[0]} — до {int(hit.iloc[0])} запросов в минуту" + (f" (и ещё {len(hit) - 1})" if len(hit) > 1 else '')
            x['почему'] = '; '.join(v for v in (x.get('почему'), add) if v)
