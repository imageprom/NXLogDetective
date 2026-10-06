"""NXLD: атакующие профили — «Дела» для листа «Разыскиваются» (04).

Дело — группа IP одного атакующего: оператор (IP связаны уликами), подделка одного робота или боты одного вида из одной сети.
Для каждого дела: обвинения по статьям из справочника (data/reference/charges.json — расширяемый), приметы, сигнатуры
с постоянным ID (хеш правила), состав (подсети, сети, страны, роли), сообщники, активность, пересечения со сбоями и всплесками,
ущерб и меры пресечения. ID дела — хеш от сайта и ключа группы: одинаковый в повторных проверках."""
import hashlib, json, os, re
import numpy as np
import pandas as pd
from . import common

REF = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference'))
# признаки по IP, из которых складываются обвинения типа «признак»
FEATURES = ('req', 'pages', 'probes', 'leaks', 'attacks', 'attacks500', 'odd', 'admin', 'login_post', 'maxpm', 'e5', 'bytes',
            'forms', 'accepted', 'ad_visits', 'sched', 'mask', 'noua')
ADMIN_RX = r'^/(bitrix/admin|wp-admin|administrator|manager|admin|panel|cp|backend|dashboard|crm|lk-admin)(/|$)|^/wp-login\.php'
LOGIN_RX = r'^/wp-login\.php$|^/bitrix/admin/(index\.php)?$|^/administrator/(index\.php)?$|^/manager/(index\.php)?$|^/admin/(index\.php)?$'


def nf(x):
    """Число с разрядами через неразрывный пробел."""
    return f'{int(round(float(x))):,}'.replace(',', '\u00a0')


def h6(*parts):
    return hashlib.sha1('|'.join(map(str, parts)).encode('utf-8')).hexdigest()[:6].upper()


def charges_ref():
    J = json.load(open(os.path.join(REF, 'charges.json'), encoding='utf-8'))
    L = []
    p = os.path.join(REF, 'learned', 'charges.json')
    if os.path.exists(p):
        try: L = json.load(open(p, encoding='utf-8')).get('статьи', [])
        except Exception: L = []
    return J['статьи'] + [x for x in L if x.get('id') not in {y['id'] for y in J['статьи']}]


def ip_features(c, res):
    """Признаки по каждому IP лога (индекс — код IP в R['ip']) — счётчики без строк на каждый запрос."""
    from .blocks import VULN, ATTACK
    import warnings
    R, V = c.R, c.V
    ipc = R['ip'].cat.codes.values
    n = len(R['ip'].cat.categories)
    bc = R['base'].cat.categories.to_series().astype(str)
    bcode = R['base'].cat.codes.values
    st = R['status'].values
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        vm = bc.str.contains(VULN, regex=True, case=False).values[bcode]
        ab = bc.str.contains(ATTACK, regex=True).values[bcode]
        aq = R['query'].cat.categories.to_series().astype(str).str.contains(ATTACK, regex=True).values[R['query'].cat.codes.values]
        adm = bc.str.contains(ADMIN_RX, regex=True).values[bcode]
        lg = bc.str.contains(LOGIN_RX, regex=True).values[bcode]
    lk = getattr(c, 'leaks', None)
    leak = np.isin(bc.values, list(lk['base'].astype(str)))[bcode] & (st == 200) & (R['bytes'].values > 0) if lk is not None and len(lk) else np.zeros(len(R), bool)
    login_pts = {r['Адрес точки'] for r in (res.get('intake') or []) if r['Опознано как'] == 'Вход'}
    if login_pts: lg = lg | np.isin(bc.values, list(login_pts))[bcode]
    meth = R['method'].cat.codes.values if str(R['method'].dtype) == 'category' else pd.Categorical(R['method'].astype(str)).codes
    mcat = R['method'].cat.categories.astype(str) if str(R['method'].dtype) == 'category' else pd.Categorical(R['method'].astype(str)).categories.astype(str)
    odd = ~np.isin(mcat.values, ('GET', 'POST', 'HEAD'))[meth]
    post = (mcat.values == 'POST')[meth]
    att = ab | aq
    cnt = lambda m: np.bincount(ipc[m], minlength=n) if m is not None else np.bincount(ipc, minlength=n)
    F = pd.DataFrame({'req': cnt(None), 'pages': cnt(R['is_page'].values), 'probes': cnt(vm), 'leaks': cnt(leak), 'attacks': cnt(att),
                      'attacks500': cnt(att & (st >= 500)), 'odd': cnt(odd), 'admin': cnt(adm), 'login_post': cnt(lg & post), 'e5': cnt(st >= 500),
                      'bytes': np.bincount(ipc, weights=R['bytes'].values.astype(float), minlength=n)})
    F.index = R['ip'].cat.categories.astype(str)
    T = pd.DataFrame({'ip': ipc, 'ts': R['ts'].values}).groupby('ip')['ts'].agg(['min', 'max'])
    F['t0'] = pd.Series(T['min'].values, index=F.index[T.index]); F['t1'] = pd.Series(T['max'].values, index=F.index[T.index])
    M = (res.get('security') or {}).get('массовые')
    F['maxpm'] = M.set_index('ip')['максимум'].reindex(F.index).fillna(0).astype(int).values if M is not None and len(M) else 0
    Vi = V.assign(ip=V['ip'].astype(str))
    g = Vi.groupby('ip')
    F['forms'] = g['n_goal'].sum().reindex(F.index).fillna(0).astype(int) if 'n_goal' in V else 0
    if 'goal_ok' in V: F['accepted'] = g['goal_ok'].sum().reindex(F.index).fillna(0).astype(int)
    else: F['accepted'] = 0
    F['ad_visits'] = Vi[(Vi['group'] == 'Боты') & (Vi['channel'].astype(str) == 'Реклама')].groupby('ip').size().reindex(F.index).fillna(0).astype(int)
    F['sched'] = Vi[Vi['subgroup'] == 'разведка по расписанию'].groupby('ip').size().reindex(F.index).fillna(0).astype(int)
    F['mask'] = Vi[Vi['subgroup'].astype(str).str.startswith('маскирующиеся')].groupby('ip')['n_req'].sum().reindex(F.index).fillna(0).astype(int)
    F['noua'] = Vi[Vi['subgroup'] == 'без User-Agent'].groupby('ip')['n_req'].sum().reindex(F.index).fillna(0).astype(int)
    F['days'] = g['day'].nunique().reindex(F.index).fillna(0).astype(int)
    return F


def accepted_by_ip(res):
    """Принятые заявки ботов по IP — из листа «Спам форм» и операторов (визиты не хранят признак принятой заявки)."""
    S = (res.get('sheets') or {}).get('Боты', {})
    X = S.get('Спам форм: визиты')
    if X is None or not len(X): return pd.Series(dtype=int), pd.Series(dtype=int)
    return X.groupby(X['ip'].astype(str))['n_goal'].sum(), X.groupby(X['ip'].astype(str))['n_conv'].sum()


def operators_map(res):
    O = (res.get('sheets') or {}).get('Боты', {}).get('Операторы')
    out = {}
    if O is None or not len(O): return out, O
    for _, r in O.iterrows():
        for col, role in (('адреса_спама', 'спам форм'), ('адреса_разведки', 'разведка')):
            for ip in str(r.get(col, '') or '').split(', '):
                if ip: out[ip] = (r['оператор'], role)
    return out, O


def key_of(ip, P, ops):
    if ip in ops: return 'op:' + ops[ip][0]
    p = P.loc[ip] if ip in P.index else None
    if p is None: return 'misc:?'
    g, s, f = p['группа'], str(p['подгруппа']), str(p['имя'])
    if s == 'подделки роботов': return 'fake:' + (f or 'робот')
    if s == 'разведка по расписанию': return 'sched:' + ip
    from .actors import sig_kind
    kind = {'Утилиты': 'util:' + s, 'Роботы': 'robot:' + f, 'Люди': 'human'}.get(g) or ('bot:' + (s if s == 'без User-Agent' else sig_kind(s)))
    return kind + '|' + (p['организация'] or p['сеть'] or '?')


NAMES = {'Зонды и перебор': 'Сканер', 'Маскировка': 'Маскировщик', 'Явный бот': 'Бот', 'Спам форм': 'Спамер форм', 'Прочее': 'Бот', 'без User-Agent': 'Безымянный бот'}


def nickname(key, org):
    k = key.split('|')[0]
    if k.startswith('op:'): return 'Оператор спама форм'
    if k.startswith('fake:'): return f'Фальшивый {k[5:]}'
    if k.startswith('sched:'): return 'Разведчик по расписанию'
    if k.startswith('util:'): return f'{k[5:]} из сети {org}'
    if k.startswith('robot:'): return f'Робот {k[6:]} из сети {org}'
    if k == 'human': return f'Под видом человека из сети {org}'
    return f"{NAMES.get(k[4:], 'Бот')} из сети {org}"


def subnet(ip):
    parts = str(ip).split('.')
    return '.'.join(parts[:3]) + '.0/24' if len(parts) == 4 else str(ip)


def window_share(c, ipset_codes, t0, t1):
    """Доля запросов группы IP в окне [t0, t1] и её запросы за 10 минут до окна (R отсортирован по времени)."""
    ts = c.R['ts'].values
    ipc = c.R['ip'].cat.codes.values
    a, b = np.searchsorted(ts, t0, 'left'), np.searchsorted(ts, t1, 'right')
    pa = np.searchsorted(ts, t0 - 600, 'left')
    inside = np.isin(ipc[a:b], ipset_codes)
    before = np.isin(ipc[pa:a], ipset_codes).sum()
    return (inside.sum() / max(1, b - a)), int(inside.sum()), int(before)


def build(c, res):
    R = c.R
    P = common.ip_profile(c)
    F = ip_features(c, res)
    fg, fa = accepted_by_ip(res)
    F['forms'] = fg.reindex(F.index).fillna(0).astype(int).values
    F['accepted'] = fa.reindex(F.index).fillna(0).astype(int).values
    ops, O = operators_map(res)
    staff = set(c.m.get('staff_ips', [])) | set(c.m.get('server_ips', []))
    grp = P['группа'].reindex(F.index).fillna('')
    strong = (F['leaks'] > 0) | (F['attacks'] > 0) | (F['probes'] >= 10) | (F['login_post'] >= 5) | (F['admin'] >= 5) | (F['odd'] >= 3) | (F['maxpm'] >= 30)
    cand = (grp.isin(['Боты', 'Утилиты']) | F.index.isin(list(ops)) | (strong & ~grp.isin(['Свои']))) & ~F.index.isin(list(staff))
    C = F[cand].copy()
    if not len(C): return dict(дела=[], состав=pd.DataFrame(), сигнатуры=pd.DataFrame())
    C['key'] = [key_of(ip, P, ops) for ip in C.index]
    site = (c.m.get('site_hosts') or ['site'])[0]
    REFS = charges_ref()
    OUT = (res.get('errors') or {}).get('сбои')
    B = (res.get('security') or {}).get('всплески')
    ipcats = pd.Index(R['ip'].cat.categories.astype(str))
    V = c.V
    from . import ipdb
    ipc_all = R['ip'].cat.codes.values
    order = np.argsort(ipc_all, kind='stable')   # строки R по IP — чтобы брать запросы группы без прохода по всему логу
    sorted_ip = ipc_all[order]
    starts = np.searchsorted(sorted_ip, np.arange(len(ipcats) + 1, dtype=sorted_ip.dtype) if len(ipcats) < np.iinfo(sorted_ip.dtype).max else np.arange(len(ipcats) + 1))   # границы IP в отсортированном порядке — один раз
    def rows_of(codes):
        parts = [order[starts[k]:starts[k + 1]] for k in codes]
        return np.sort(np.concatenate(parts)) if parts else np.array([], dtype=np.int64)
    # окна сбоев и всплесков: запросы каждого IP в окне и за 10 минут до него — один проход на окно, а не на дело
    ts_all = R['ts'].values
    nip = len(ipcats)
    def win_counts(t0, t1):
        a, b = np.searchsorted(ts_all, t0, 'left'), np.searchsorted(ts_all, t1, 'right')
        pa = np.searchsorted(ts_all, t0 - 600, 'left')
        return np.bincount(ipc_all[a:b], minlength=nip), max(1, b - a), np.bincount(ipc_all[pa:a], minlength=nip)
    WO = [(o, *win_counts(int(o['t0']), int(o['t1']))) for _, o in OUT.iterrows()] if OUT is not None and len(OUT) else []
    WB = [(b, *win_counts(int(b['_t0']), int(b['_t0']) + int(b['минут']) * 60 - 1)) for _, b in B.iterrows()] if B is not None and len(B) else []
    # отбор дел сразу по всем группам: обвинения по признакам, подделка, заметная доля в сбое или всплеске
    C['_code'] = ipcats.get_indexer(C.index)
    feats = [f for f in FEATURES if f in C]
    A = C.groupby('key')[feats].sum()
    if 'maxpm' in C: A['maxpm'] = C.groupby('key')['maxpm'].max()
    keep = pd.Series(False, index=A.index)
    for r_ in REFS:
        if r_.get('тип') == 'признак' and r_['признак'] in A: keep |= A[r_['признак']] >= r_['порог']
    keep |= pd.Series(A.index.str.startswith('fake:'), index=A.index)
    for _, cnt, tot, _b in WO + WB:
        keep |= (pd.Series(cnt[C['_code'].values], index=C.index).groupby(C['key']).sum() / tot).reindex(A.index).fillna(0) >= 0.05
    C = C[C['key'].isin(set(keep[keep].index))]
    cases = []
    for key, g in C.groupby('key'):
        agg = {f: (g[f].max() if f == 'maxpm' else g[f].sum()) for f in FEATURES if f in g}
        orgs = P['организация'].reindex(g.index).replace('', np.nan).fillna(P['сеть'].reindex(g.index))
        org = orgs.value_counts().index[0] if len(orgs.dropna()) else '?'
        codes = ipcats.get_indexer(g.index)
        ch = []
        ctx = dict(agg, days=int(g['days'].max()))
        fam0 = key.split(':', 1)[1].split('|')[0] if key.startswith('fake:') else ''
        # быстрый отбор: есть ли хоть одно обвинение по признакам, подделка или заметная доля в сбое/всплеске — иначе дело не заводится
        # подробности для шаблонов
        sub = R.iloc[rows_of(codes)][['base', 'status', 'bytes', 'method', 'ts', 'hour', 'query']]
        def top_paths(mask, n=3):
            s = sub.loc[mask, 'base'].astype(str).value_counts().head(n)
            return ', '.join(f"{k} ({v})" for k, v in s.items())
        from .blocks import VULN, ATTACK
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            bs = sub['base'].astype(str)
            ctx['top_probes'] = top_paths(bs.str.contains(VULN, regex=True, case=False).values)
            ctx['top_attacks'] = top_paths((bs.str.contains(ATTACK, regex=True) | sub['query'].astype(str).str.contains(ATTACK, regex=True)).values)
            ctx['top_login'] = top_paths((bs.str.contains(LOGIN_RX, regex=True) & (sub['method'].astype(str) == 'POST')).values)
        lk = getattr(c, 'leaks', None)
        lset = set(lk['base'].astype(str)) if lk is not None and len(lk) else set()
        ctx['top_leaks'] = top_paths((bs.isin(lset) & (sub['status'] == 200)).values) if lset else ''
        ctx['top_methods'] = ', '.join(f"{k} ({v})" for k, v in sub.loc[~sub['method'].astype(str).isin(['GET', 'POST', 'HEAD']), 'method'].astype(str).value_counts().head(3).items())
        fam = key.split(':', 1)[1].split('|')[0] if key.startswith('fake:') else ''
        ctx['fam'] = fam
        outages_hit, bursts_hit = [], []
        for ref in REFS:
            t = ref.get('тип')
            if t == 'признак':
                v = agg.get(ref['признак'], 0)
                if v >= ref['порог']:
                    if ref['id'] == 'spam' and agg.get('accepted', 0) > 0: continue   # принятые — своей статьёй
                    ch.append((ref, ref['шаблон'].format(**{k_: (nf(x) if isinstance(x, (int, float, np.integer, np.floating)) else x) for k_, x in ctx.items()})))
            elif t == 'подделка' and fam:
                ch.append((ref, ref['шаблон'].format(fam=fam)))
            elif t == 'сбой' and WO:
                for o, cnt, tot, bef in WO:
                    n_in, before = int(cnt[codes].sum()), int(bef[codes].sum()); share = n_in / tot
                    if share >= ref.get('доля', 0.2) or (n_in >= 50 and share >= 0.05):
                        rate = agg['req'] / max(1, (g['t1'].max() - g['t0'].min()) / 600)
                        pre = f'; за 10 минут до начала — {before} запросов (обычно ~{rate:.0f})' if before >= 3 * max(1, rate) else ''
                        strength = 'вероятно' if share >= ref.get('доля', 0.2) else 'совпадение'
                        outages_hit.append(f"{o['сбой']}: {share * 100:.0f}% запросов в окне сбоя ({n_in}){pre}")
                        ch.append((dict(ref, сила=strength), ref['шаблон'].format(сбой=o['сбой'], доля=f'{share * 100:.0f}%', до=pre)))
            elif t == 'всплеск' and WB:
                for b, cnt, tot, _bef in WB:
                    n_in = int(cnt[codes].sum()); share = n_in / tot
                    if share >= ref.get('доля', 0.2):
                        bursts_hit.append(f"{b['всплеск']}: {share * 100:.0f}% запросов ({n_in})")
                if bursts_hit:
                    ch.append((ref, ref['шаблон'].format(n_bursts=f'{len(bursts_hit)} всплеск' + ('а' if 2 <= len(bursts_hit) <= 4 else 'ов' if len(bursts_hit) > 4 else ''), bursts='; '.join(bursts_hit[:5]))))
        if not ch: continue
        ch.sort(key=lambda x: -x[0]['вес'])
        top = ch[0][0]
        sev = 'Срочно' if top['вес'] >= 85 else ('Важно' if top['вес'] >= 45 else 'К сведению')
        from . import alarms
        op_ = set(alarms.leaks_open(res))
        if (agg.get('leaks') and op_ and any(f_ in str(ctx.get('top_leaks', '')) for f_ in op_)) or any('продолжается' in str(o_) for o_ in outages_hit):
            sev = 'Тревога'   # получил файл, который отдаётся и сейчас, или причастен к сбою, который не закончился
        # состав
        nets = pd.Series([subnet(ip) for ip in g.index]).value_counts()
        req_by_net = g['req'].groupby([subnet(ip) for ip in g.index]).sum()
        roles = pd.Series([ops.get(ip, (None, P['подгруппа'].get(ip, '')))[1] for ip in g.index]).value_counts()
        countries = P['страна'].reindex(g.index).value_counts()
        # сигнатура
        if fam:
            rule = {'вид': 'подделка', 'user_agent': fam, 'сеть_не': sorted(ipdb.VERIFIED.get(fam, []))}
            tag, sig_text = 'FAKECRAWL', f"User-Agent содержит «{fam}» И сеть не из {', '.join('AS' + str(a) for a in rule['сеть_не']) or 'сетей робота'}"
            mm = (V['fam'].astype(str) == fam)
            hits = int((mm & (V['fam_verified'].astype(str) == 'нет')).sum()); spared = int((mm & (V['fam_verified'].astype(str) == 'да')).sum())
            false_ = 0; check = f'{nf(hits)} визитов; настоящий {fam} не задет ({nf(spared)} визитов)'
        else:
            asns = pd.Series(P.loc[g.index, 'организация']).value_counts().index[:3].tolist()
            subs = sorted(set(P['подгруппа'].reindex(g.index).astype(str)))
            if key.startswith('op:'):
                rule = {'вид': 'оператор', 'улики': str(O.loc[O['оператор'] == key[3:], 'улики'].iloc[0])[:200] if O is not None else '', 'входы': str(O.loc[O['оператор'] == key[3:], 'битые_входы'].iloc[0])[:200] if O is not None else ''}
                tag, sig_text = 'OPERATOR', f"заходит через битые адреса ({rule['входы'][:80]}…) и отправляет формы; приметы: {rule['улики'][:120]}"
            else:
                rule = {'вид': key.split('|')[0], 'признаки': subs[:3], 'сети': asns}
                tag = {'bot:Зонды и перебор': 'SCAN', 'bot:Маскировка': 'MASK', 'bot:Явный бот': 'BOT', 'bot:без User-Agent': 'NOUA', 'bot:Спам форм': 'SPAM'}.get(key.split('|')[0], key.split(':')[0].upper())
                from .actors import sig_label
                sig_text = f"{'; '.join(sig_label(x_).lower() for x_ in subs[:2] if x_)} — из сети {', '.join(a_ for a_ in asns if a_) or 'без названия'}"
            Vm = V['ip'].astype(str).isin(set(g.index))
            hits = int(Vm.sum())
            own_asn = set(P.loc[g.index, 'организация'])
            orgV = V['ip'].astype(str).map(P['организация'])
            false_ = int((orgV.isin(own_asn) & (V['group'] == 'Люди')).sum())
            check = f'{nf(hits)} визитов этой группы; в тех же сетях визитов людей — {nf(false_)}' + (' (сеть целиком не закрывать)' if false_ else '')
        sig_id = f"SIG-{tag}-{h6(json.dumps(rule, sort_keys=True, ensure_ascii=False))}"
        case_id = h6(site, key)
        # активность
        hours = sub['hour'].value_counts().head(3).index.tolist() if len(sub) else []
        t0, t1 = int(g['t0'].min()), int(g['t1'].max())
        ndays = int(pd.Series(sub['ts'].values // 86400).nunique()) if len(sub) else int(g['days'].max())
        act = (f"{common.dmy(t0)} — {common.dmy(t1)}, дней: {ndays}; запросов {nf(agg['req'])}, страниц {nf(agg['pages'])}; "
               f"чаще всего в {', '.join(f'{h:02d}:00' for h in hours)}" + (f"; до {nf(agg['maxpm'])} страниц в минуту" if agg.get('maxpm') else ''))
        dmg = []
        if agg.get('leaks'): dmg.append(f"получил служебные файлы: {ctx['top_leaks']}")
        if agg.get('accepted'): dmg.append(f"{int(agg['accepted'])} заявок попали к менеджерам")
        if agg.get('ad_visits'): dmg.append(f"{int(agg['ad_visits'])} визитов по оплаченной рекламе")
        dmg.append(f"трафик {nf(agg['bytes'] / 1024 ** 2)} МБ")
        if agg.get('e5'): dmg.append(f"{int(agg['e5'])} ответов 5xx")
        cases.append(dict(дело=case_id, ключ=key, кличка=nickname(key, org), вид=top['статья'], важность=sev, вес=top['вес'],
                          обвинения=[dict(статья=r_['статья'], что=t_, сила=r_['сила'], id=r_['id']) for r_, t_ in ch],
                          приметы=signs(key, P, g, sub, fam, ctx), сигнатура=dict(id=sig_id, правило=sig_text, проверка=check, ложных=false_, rule=rule),
                          состав=dict(IP=len(g), подсети=[(k_, int(v), int(req_by_net.get(k_, 0))) for k_, v in nets.head(8).items()], подсетей=len(nets),
                                      сети=orgs.value_counts().head(4).to_dict(), страны=countries.head(5).to_dict(), роли=roles.head(4).to_dict()),
                          активность=act, сбои=outages_hit, всплески=bursts_hit, ущерб='; '.join(dmg), меры=measures(ch, fam, nets, false_, key),
                          ips=list(g.index), t0=t0, t1=t1, запросов=int(agg['req'])))
    cases.sort(key=lambda x: (x['важность'] != 'Тревога', -x['вес'], -x['запросов']))
    # сообщники: общие подсети и слабые связи операторов
    net_of = {}
    for x in cases:
        for s_, _, _ in x['состав']['подсети']: net_of.setdefault(s_, set()).add(x['дело'])
    for x in cases:
        mates = {}
        for s_, _, _ in x['состав']['подсети']:
            for d in sorted(net_of.get(s_, ())):
                if d != x['дело']: mates.setdefault(d, []).append(s_)
        x['сообщники'] = [(d, f"общая подсеть {', '.join(v[:2])}") for d, v in sorted(mates.items(), key=lambda kv: (-len(kv[1]), kv[0]))][:6]   # порядок не плавает
    names = {x['дело']: x['кличка'] for x in cases}
    for x in cases: x['сообщники'] = [(d, names.get(d, ''), why) for d, why in x['сообщники']]
    # состав по IP
    rows = []
    for x in cases:
        for ip in x['ips']:
            rows.append({'дело': x['дело'], 'кличка': x['кличка'], 'ip': ip, 'подсеть': subnet(ip), 'сеть': P['организация'].get(ip, ''), 'страна': P['страна'].get(ip, ''),
                         'роль': ops.get(ip, (None, P['подгруппа'].get(ip, '')))[1], 'запросов': int(F.at[ip, 'req']), 'первый': common.dmy(F.at[ip, 't0']), 'последний': common.dmy(F.at[ip, 't1'])})
    S = pd.DataFrame([dict(id=x['сигнатура']['id'], правило=x['сигнатура']['правило'], вид=x['вид'], дело=x['дело'], кличка=x['кличка'],
                           проверка=x['сигнатура']['проверка'], ложных=x['сигнатура']['ложных'], IP=x['состав']['IP'], запросов=x['запросов']) for x in cases])
    learn_signatures(cases, site, c)
    return dict(дела=cases, состав=pd.DataFrame(rows), сигнатуры=S, меры_ip=measures_by_ip(c, res, cases, P, F))


VERDICT_ORDER = {'заблокировать': 0, 'ограничить частоту': 1, 'наблюдать': 2, 'не трогать': 3}


def measures_by_ip(c, res, cases, P, F):
    """Меры по IP: приговор каждому IP из дел и своим — готовый список для администратора.
    Заблокировать — дело серьёзное и в сети нет людей; ограничить частоту — в сети есть люди или это мобильный оператор
    (за одним IP много абонентов); наблюдать — дело «к сведению»; не трогать — свои, сервер сайта, мониторинг."""
    V = c.V
    vv = V.assign(ip=V['ip'].astype(str)).groupby('ip').agg(визитов=('n_req', 'size'), отправок=('n_goal', 'sum'))
    T = c.T.drop_duplicates('ip').set_index('ip') if 'ip' in c.T else pd.DataFrame()
    rows = []
    def row(ip, дело, кличка, приговор, основание):
        rows.append(dict(ip=ip, дело=дело, кличка=кличка, подсеть=subnet(ip), сеть=P['организация'].get(ip, ''), asn=int(P['asn'].get(ip, 0)) if 'asn' in P else 0, страна=P['страна'].get(ip, ''),
                         тип_сети=P['сеть'].get(ip, ''), визитов=int(vv['визитов'].get(ip, 0)), запросов=int(F['req'].get(ip, 0)) if ip in F.index else 0,
                         отправок=int(vv['отправок'].get(ip, 0)), приговор=приговор, основание=основание,
                         первый=common.dmy(F.at[ip, 't0']) if ip in F.index and pd.notna(F.at[ip, 't0']) else '',
                         последний=common.dmy(F.at[ip, 't1']) if ip in F.index and pd.notna(F.at[ip, 't1']) else ''))
    seen = set()
    for x in cases:
        main = x['обвинения'][0]['статья']
        people = x['сигнатура']['ложных']
        for ip in x['ips']:
            if ip in seen: continue
            seen.add(ip)
            mobile = 'мобильн' in str(P['сеть'].get(ip, ''))
            if x['важность'] == 'К сведению': v, why = 'наблюдать', f'{main}; дело к сведению'
            elif mobile: v, why = 'ограничить частоту', f'{main}; мобильный оператор — за одним IP много абонентов'
            elif people: v, why = 'ограничить частоту', f'{main}; из этой сети ходят люди ({nf(people)} визитов)'
            else: v, why = 'заблокировать', f'{main}; людей из этой сети нет'
            row(ip, x['дело'], x['кличка'], v, why)
    for ips, why in ((c.m.get('staff_ips', []), 'сотрудник'), (c.m.get('server_ips', []), 'сервер сайта'),
                     ([m_['ip'] for m_ in c.m.get('monitors', []) if isinstance(m_, dict)], 'система мониторинга')):
        for ip in ips:
            if ip not in seen: seen.add(ip); row(ip, '', '', 'не трогать', why)
    D = pd.DataFrame(rows)
    if len(D): D = D.sort_values(['приговор', 'запросов'], key=lambda s_: s_.map(VERDICT_ORDER) if s_.name == 'приговор' else -s_).reset_index(drop=True)
    return D


def signs(key, P, g, sub, fam, ctx):
    """Приметы — как узнать на глаз: список, каждая с большой буквы."""
    out = []
    ua = P['кто'].reindex(g.index).value_counts()
    if fam: out.append(f'представляется {fam}')
    if len(sub):
        out.append(f"ответы: {common.codes_text(sub['status'].values).split(', ')[0]} и другие")
        ent = sub['base'].astype(str).value_counts().head(2)
        out.append('чаще всего запрашивает: ' + ', '.join(ent.index))
    if ctx.get('mask'): out.append('браузер без загрузки картинок и стилей')
    if ctx.get('noua'): out.append('без User-Agent')
    if key.startswith('op:'): out.append('меняет IP посреди визита, заходит через битые адреса')
    out.append('кто: ' + ', '.join(ua.index[:2]))
    return [x[:1].upper() + x[1:] for x in out]


def measures(ch, fam, nets, false_, key):
    ids = {r['id'] for r, _ in ch}
    m = []
    top_nets = [k for k in nets.index[:5]]
    if fam:
        m.append(f'проверять подлинность {fam} по обратному DNS и отказывать, если не сходится')
    if top_nets and not false_ and not key.startswith('op:'):
        m.append('nginx: ' + ' '.join(f'deny {n};' for n in top_nets))
    elif false_:
        m.append('сети целиком не закрывать — там есть люди; ограничить частоту запросов (limit_req) и закрывать по поведению')
    if 'leak' in ids: m.append(r'закрыть служебные файлы: location ~ /\.(?!well-known) { deny all; }')
    if ids & {'spam', 'spam_accepted'}: m.append('на формы — скрытое поле-ловушка или капча; проверять, что форма открыта со страницы сайта')
    if 'bruteforce' in ids: m.append('fail2ban на форму входа: после 5 неудачных попыток — блокировка IP на час')
    if ids & {'mass', 'burst', 'outage'}: m.append('nginx: limit_req zone=one burst=20 nodelay — ограничение частоты')
    if 'odd_methods' in ids: m.append('nginx: принимать только GET, POST и HEAD (if ($request_method !~ ^(GET|POST|HEAD)$) { return 444; })')
    if 'ad_fraud' in ids: m.append('исключить эти сети в настройках рекламы (Директ: запрещённые IP), сообщить в поддержку о скликивании')
    return m or ['наблюдать']


def learn_signatures(cases, site, c):
    """Справочник сигнатур (learned/signatures.json): ID, правило, где и когда срабатывала. Один ID — одно правило на всех сайтах."""
    p = os.path.join(REF, 'learned', 'signatures.json')
    try: J = json.load(open(p, encoding='utf-8'))
    except Exception: J = {'сигнатуры': {}}
    d0, d1 = (c.inv.get('period') or ['', ''])[:2] if isinstance(c.inv, dict) else ('', '')
    for x in cases:
        s = x['сигнатура']
        e = J['сигнатуры'].setdefault(s['id'], dict(правило=s['правило'], rule=s['rule'], вид=x['вид'], сайты={}))
        e['сайты'][site] = dict(период=f'{str(d0)[:10]}…{str(d1)[:10]}', дело=x['дело'], визитов=x['запросов'])
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(J, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    except Exception:
        pass



def extras(c, res):
    """Для 04: журнал ботов по дням, расписание ботов (день × час по видам), боты в рекламе."""
    from .actors import sig_kind
    R, V = c.R, c.V
    out = {}
    J0 = (res.get('errors') or {}).get('журнал')
    B = V[V['group'] == 'Боты'].copy()
    B['вид'] = B['subgroup'].map(sig_kind)
    if J0 is not None and len(J0) and len(B):
        g = B.groupby('day')
        kinds = [('Маскировка', 'Маскировка'), ('Подделка робота', 'Подделки'), ('Зонды и перебор', 'Зонды'), ('Спам форм', 'Спам форм')]
        D = pd.DataFrame({'Визиты ботов|Все': g.size()})
        for k_, lab in kinds: D[f'Визиты ботов|{lab}'] = B[B['вид'] == k_].groupby('day').size()
        D['Визиты ботов|Прочие'] = B[~B['вид'].isin([k for k, _ in kinds])].groupby('day').size()
        first = B.groupby('ip')['day'].min()
        D['Новые IP|Ботов'] = first.value_counts()
        D['Заявки|Отправлено'] = g['n_goal'].sum() if 'n_goal' in B else 0
        X = (res.get('sheets') or {}).get('Боты', {}).get('Спам форм: визиты')
        if X is not None and len(X): D['Заявки|Принято'] = X.assign(d=pd.to_datetime(X['начало']).dt.strftime('%Y-%m-%d')).groupby('d')['n_conv'].sum()
        else: D['Заявки|Принято'] = 0
        D = D.fillna(0).astype(int).reset_index().rename(columns={'index': 'день', 'day': 'день'})
        meta = J0[J0['день'] != 'Итого'][['день', '_с', '_по', '_полный']]
        D = meta.merge(D, on='день', how='left').fillna(0)
        tot = {k_: int(D[k_].sum()) for k_ in D.columns if '|' in k_}
        tot['Новые IP|Ботов'] = int(B['ip'].nunique())
        out['журнал'] = pd.concat([D, pd.DataFrame([{'день': 'Итого', **tot}])], ignore_index=True)
    # расписание: запросы ботов по видам, день × час
    rg = np.asarray(c.rg)
    vk = pd.Series(V['subgroup'].map(sig_kind).values, index=V.index)
    rk = vk.reindex(R['vid'].values).values
    day, hr = R['day'].astype(str).values, R['hour'].values.astype(int)
    heat = {}
    for lab, m in (('Все боты', rg == 'Боты'), ('Подделки роботов', (rg == 'Боты') & (rk == 'Подделка робота')),
                   ('Сканеры и зонды', (rg == 'Боты') & (rk == 'Зонды и перебор')), ('Маскировка под браузер', (rg == 'Боты') & (rk == 'Маскировка'))):
        if m.any(): heat[lab] = pd.DataFrame({'d': day[m], 'h': hr[m]}).groupby(['d', 'h']).size().unstack(fill_value=0).reindex(index=sorted(set(day)), columns=range(24), fill_value=0)
    out['расписание'] = heat
    # боты в рекламе: визиты ботов с рекламных переходов
    A = B[B['channel'].astype(str) == 'Реклама']
    if len(A):
        out['реклама'] = A.groupby(['channel_sub', 'вид']).agg(визитов=('ip', 'size'), IP=('ip', 'nunique'), вход=('entry', lambda s: ', '.join(s.astype(str).value_counts().index[:2]))).reset_index().sort_values('визитов', ascending=False)
        out['реклама_люди'] = int(((V['group'] == 'Люди') & (V['channel'].astype(str) == 'Реклама')).sum())
    return out
