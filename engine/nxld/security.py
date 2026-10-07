"""NXLD: данные файла 03 «Нагрузка и безопасность» — срезы для листов и обзора.

Карточки проблем по-прежнему заводит blocks.load_security; здесь — таблицы в человеческом виде на общих расчётах
(common: кто это по IP, эпизоды, история по дням, настоящий или ложный адрес)."""
import re
import numpy as np
import pandas as pd
from . import common
from .common import ip_profile, codes_text, split_codes_arr, dmy, episode_id, who_text

GROUPS_HEAT = ('Все', 'Люди', 'Роботы', 'Боты')
GB = 1024 ** 3


def _sv(R, col, idx):
    """Строковые значения колонки R только для выбранных строк — без перевода в строки всех миллионов запросов."""
    x = R[col]
    if str(x.dtype) == 'category':
        return x.cat.categories.astype(str).values[x.cat.codes.values[idx]]
    return x.values[idx].astype(str)


def _cat(R, col):
    return R[col].cat.categories.astype(str), R[col].cat.codes.values


# ---------- нагрузка по часам ----------
def heat(c):
    """Запросов за час: день × час по группам; и где нагрузка программ пересекается с людьми и растёт 499."""
    R = c.R
    day = R['day'].astype(str).values
    hr = R['hour'].values.astype(int)
    rg = np.asarray(c.rg)
    out = {}
    for g in GROUPS_HEAT:
        m = np.ones(len(R), bool) if g == 'Все' else (rg == g)
        P = pd.DataFrame({'d': day[m], 'h': hr[m]}).groupby(['d', 'h']).size().unstack(fill_value=0).reindex(columns=range(24), fill_value=0)
        out[g] = P
    # пересечение: часы, где у людей много запросов и у программ (роботы + боты) тоже; доля 499 у людей в эти часы
    st = R['status'].values
    hum = c.human
    X = pd.DataFrame({'d': day, 'h': hr, 'p': hum, 'b': np.isin(rg, ('Роботы', 'Боты')), 'w': hum & (st == 499)})
    H = X.groupby(['d', 'h']).agg(люди=('p', 'sum'), программы=('b', 'sum'), обрывы=('w', 'sum')).reset_index()
    H['доля_499'] = H['обрывы'] / H['люди'].clip(lower=1)
    base_499 = float(H['обрывы'].sum() / max(1, H['люди'].sum()))
    q_p, q_b = H['люди'].quantile(0.75), H['программы'].quantile(0.75)
    both = H[(H['люди'] >= q_p) & (H['программы'] >= q_b)].sort_values('программы', ascending=False)
    out['_пересечение'] = both.head(10)
    out['_499_обычно'] = base_499
    out['_499_в_пересечении'] = float(both['обрывы'].sum() / max(1, both['люди'].sum())) if len(both) else None
    return out


# ---------- всплески нагрузки и натиск ----------
def bursts(c, OUT=None, k=3.0, add=500, gap=10, min_excess=2000):
    """Всплески: подряд идущие минуты, когда запросов в k раз больше обычного для этого часа (и больше обычного на add).
    Для каждого: сколько, кто, что били, чем ответил сервер, сработала ли защита, последствия, картина."""
    R = c.R
    ts = R['ts'].values
    idx, full, norm = common.minute_norm(ts)
    hot = full >= np.maximum(k * norm, norm + add)
    E = common.episodes(idx[hot], gap)
    if not E: return pd.DataFrame()
    P = ip_profile(c)
    m_all = ts // 60
    ipc, ipcode = _cat(R, 'ip')
    bc, bcode = _cat(R, 'base')
    st = R['status'].values
    rg = np.asarray(c.rg)
    ch_all = c.V['channel'].astype(str).reindex(R['vid'].values).values
    rows = []
    for a, b, ii in E:
        n_ = full[(idx >= a) & (idx <= b)]
        nm_ = norm[(idx >= a) & (idx <= b)]
        excess = float(n_.sum() - nm_.sum())
        if excess < min_excess: continue
        lo, hi = np.searchsorted(m_all, a, 'left'), np.searchsorted(m_all, b, 'right')   # R отсортирован по времени
        sl = slice(lo, hi)
        ips = pd.Series(ipcode[sl]).value_counts()
        top_ip = ipc[ips.index[0]]; top_share = ips.iloc[0] / max(1, hi - lo)
        grp = pd.Series(rg[sl]).value_counts()
        nets = R['asn'].values[sl]
        st_ = st[sl]
        prot = int(np.isin(st_, (403, 429, 444)).sum())
        hum = c.human[sl]
        h499 = float(((st_ == 499) & hum).sum() / max(1, hum.sum()))
        fam = pd.Series(_sv(R, 'fam', sl)); fam = fam[fam != '']
        if top_share >= 0.6: pic = f"массовые запросы с одного IP: {top_ip} ({P['кто'].get(top_ip, '')})"
        elif grp.get('Роботы', 0) / len(st_) >= 0.6: pic = f"обход робота: {fam.value_counts().index[0] if len(fam) else 'робот'}"
        elif grp.get('Люди', 0) / len(st_) >= 0.6:
            chs = pd.Series(ch_all[sl][c.human[sl]]).value_counts(normalize=True)
            pic = f"наплыв людей: {chs.index[0].lower()} {chs.iloc[0] * 100:.0f}%" if len(chs) else 'наплыв людей'
        elif len(ips) >= 50 and top_share < 0.2: pic = 'распределённая нагрузка: много IP понемногу — похоже на DDoS'
        else: pic = 'смешанная: ' + who_text(grp, 2)
        cons = []
        if OUT is not None and len(OUT):
            hit = OUT[(OUT['t0'] <= b * 60 + 59) & (OUT['t1'] >= a * 60)]
            if len(hit): cons.append('сбой ' + ', '.join(hit['сбой']))
        if hum.sum() >= 20 and h499 >= 0.05: cons.append(f'люди не дождались: {h499 * 100:.0f}% запросов')
        rows.append({'всплеск': episode_id(a * 60), 'начало': dmy(a * 60), 'конец': dmy(b * 60 + 59), 'минут': b - a + 1, 'запросов': int(hi - lo),
                     'пик_в_минуту': int(n_.max()), 'в_норме': int(round(float(nm_.mean()))), 'IP': int(len(ips)), 'сетей': int(pd.Series(nets).nunique()),
                     'главный_IP': f"{top_ip} — {top_share * 100:.0f}%", 'кто_главный': P['кто'].get(top_ip, ''),
                     'что_били': ', '.join(f"{bc[k_]} ({v:,})".replace(',', ' ') for k_, v in pd.Series(bcode[sl]).value_counts().head(3).items()),
                     'ответы': split_codes_arr(st_)[0], 'ошибки': split_codes_arr(st_)[1], 'отказы': prot, 'последствия': '; '.join(cons) or 'не видно',
                     'картина': pic, 'кто': who_text(grp), '_excess': excess, '_t0': a * 60})
    return pd.DataFrame(rows)


def mass_requests(c, per_min=30):
    """Массовые запросы (флуд): IP, которые хотя бы минуту запрашивали не меньше per_min страниц.
    Файлы и подгрузки не считаются: браузер человека за минуту легко подгружает сотни ресурсов, а страниц человек столько не откроет.
    Строка — IP за весь период."""
    R = c.R
    nf = R['is_page'].values
    m = R['ts'].values[nf] // 60
    ipc, ipcode_all = _cat(R, 'ip')
    X = pd.DataFrame({'m': m, 'ip': ipcode_all[nf]}).groupby(['ip', 'm']).size()
    ipcode = ipcode_all
    hot = X[X >= per_min]
    if not len(hot): return pd.DataFrame()
    P = ip_profile(c)
    g = hot.groupby(level=0)
    D = pd.DataFrame({'максимум': g.max(), 'минут': g.size(), 'первая': g.apply(lambda s: s.index.get_level_values(1).min()),
                      'последняя': g.apply(lambda s: s.index.get_level_values(1).max())})
    D['ip'] = ipc[D.index]
    st = R['status'].values
    sel = np.isin(ipcode, D.index.values)
    S_ = pd.DataFrame({'ip': ipcode[sel], 'st': st[sel]})
    tot = S_.groupby('ip').size()
    D['запросов'] = tot.reindex(D.index).values
    sp = S_.groupby('ip')['st'].agg(split_codes_arr).reindex(D.index)
    D['ответы'] = sp.str[0].values; D['ошибки'] = sp.str[1].values
    D['отказы'] = S_.assign(p=np.isin(S_['st'], (403, 429, 444))).groupby('ip')['p'].sum().reindex(D.index).astype(int).values
    D['кто'] = D['ip'].map(P['кто']).fillna('')
    D['сеть'] = D['ip'].map(P['организация']).fillna('')
    D['страна'] = D['ip'].map(P['страна']).fillna('')
    D['первая'] = D['первая'].map(lambda v: dmy(v * 60)); D['последняя'] = D['последняя'].map(lambda v: dmy(v * 60))
    return D.sort_values('максимум', ascending=False).reset_index(drop=True)


# ---------- источники нагрузки ----------
def sources(c):
    """Категория (группа) · Тип (подгруппа) · Подозреваемый (кто именно) — запросы, страницы, трафик, максимум за минуту.
    Считается по кодам категорий, без строк на каждый запрос: в логе миллионы строк."""
    R = c.R
    gc, sc = np.asarray(c.rg.codes), np.asarray(c.rsub.codes)
    gn, sn = list(c.rg.categories), list(c.rsub.categories)
    fc = R['fam'].cat.codes.values
    fn = R['fam'].cat.categories.astype(str)
    ipc = R['ip'].cat.codes.values
    gi = {g: i for i, g in enumerate(gn)}
    kind = np.full(len(R), 2, dtype=np.int8)   # 0 — имя робота, 1 — IP сотрудника, 2 — подгруппа, 3 — без подозреваемого
    code = sc.astype(np.int64).copy()
    if 'Роботы' in gi:
        m = gc == gi['Роботы']; kind[m] = 0; code[m] = fc[m]
    if 'Свои' in gi:
        m = gc == gi['Свои']; kind[m] = 1; code[m] = ipc[m]
    if 'Боты' in gi:
        m = gc == gi['Боты']; named = m & (fn.values[fc] != '') if len(fn) else m & False
        kind[m] = 3; kind[named] = 0; code[m] = -1; code[named] = fc[named]
    if 'Люди' in gi:
        m = gc == gi['Люди']; kind[m] = 3; code[m] = -1
    D = pd.DataFrame({'g': gc, 's': sc, 'k': kind, 'c': code, 'b': R['bytes'].values, 'p': ~R['is_static'].values, 'm': R['ts'].values // 60})
    key = ['g', 's', 'k', 'c']
    g = D.groupby(key).agg(запросов=('b', 'size'), страниц=('p', 'sum'), байт=('b', 'sum'))
    g['максимум'] = D.groupby(key + ['m']).size().groupby(level=[0, 1, 2, 3]).max()
    del D
    g = g.reset_index()
    ipn = R['ip'].cat.categories.astype(str)
    g['категория'] = [gn[i] for i in g['g']]
    g['тип'] = ['посетители' if gn[gg] == 'Люди' else (sn[ss] if ss >= 0 else '') for gg, ss in zip(g['g'], g['s'])]
    g['подозреваемый'] = [fn[cc] if kk == 0 else (ipn[cc] if kk == 1 else (sn[cc] if kk == 2 and cc >= 0 else '—')) for kk, cc in zip(g['k'], g['c'])]
    g['трафик_%'] = g['байт'] / max(1, R['bytes'].values.sum()) * 100
    return g.drop(columns=key).sort_values('запросов', ascending=False).reset_index(drop=True)


def sources_channels(c):
    """Нагрузка от людей по каналам: откуда пришли — запросы, страницы, трафик, максимум страниц за минуту."""
    R, V = c.R, c.V
    h = c.human
    ch = V['channel'].astype(str).reindex(R['vid'].values[h]).values
    X = pd.DataFrame({'ch': ch, 'b': R['bytes'].values[h], 'p': R['is_page'].values[h], 'm': R['ts'].values[h] // 60})
    g = X.groupby('ch').agg(запросов=('b', 'size'), страниц=('p', 'sum'), байт=('b', 'sum'))
    g['макс'] = X[X['p']].groupby(['ch', 'm']).size().groupby(level=0).max().reindex(g.index).fillna(0).astype(int)
    g['трафик_%'] = g['байт'] / max(1, R['bytes'].values.sum()) * 100
    return g.sort_values('запросов', ascending=False).reset_index().rename(columns={'ch': 'канал'})


# ---------- файлы ----------
def file_types(c):
    from .classify import ext_of, load_extensions
    R = c.R
    st = R['status'].values
    ext = R['ext'].astype(str).values
    st_ = R['is_static'].values
    X = pd.DataFrame({'e': ext[st_], 'b': R['bytes'].values[st_], 's304': st[st_] == 304, 'g': np.asarray(c.rg).astype(object)[st_]})
    g = X.groupby('e').agg(запросов=('b', 'size'), байт=('b', 'sum'), кэш=('s304', 'mean'), средний=('b', 'mean'))
    g['кто'] = X.groupby('e')['g'].agg(lambda s: who_text(s.value_counts(), 2))
    e2g = load_extensions()['ext2grp']
    g['группа'] = [e2g.get(str(e).lower(), '') for e in g.index]
    g['трафик_%'] = g['байт'] / max(1, R['bytes'].values.sum()) * 100
    return g.sort_values('байт', ascending=False).reset_index().rename(columns={'e': 'расширение'})


def heavy_files(c, top=200):
    R = c.R
    st = R['status'].values
    m = R['is_static'].values & (st == 200)
    bc, bcode = _cat(R, 'base')
    X = pd.DataFrame({'b': bcode[m], 'by': R['bytes'].values[m], 'ri': R['ref_internal'].values[m].astype(bool), 'g': np.asarray(c.rg).astype(object)[m], 'd': _sv(R, 'day', m)})
    g = X.groupby('b').agg(запросов=('by', 'size'), байт=('by', 'sum'), средний=('by', 'mean'), с_сайта=('ri', 'sum'), первый=('d', 'min'), последний=('d', 'max'))
    g = g.sort_values('байт', ascending=False).head(top)
    sub = X[X['b'].isin(g.index)]
    g['кто'] = sub.groupby('b')['g'].agg(lambda s: who_text(s.value_counts(), 2)).reindex(g.index).values
    g['файл'] = bc[g.index]
    A = getattr(c, 'addr', None)
    g['вид'] = A['группа'].values[g.index] if A is not None else ''
    return g.reset_index(drop=True)


# ---------- паразитные адреса ----------
KIND_OF_GROUP = {'Реклама и аналитика': 'рекламные метки', 'Метки сервисов': 'рекламные метки', 'Поисковики и Яндекс': 'рекламные метки', 'Сброс кэша': 'сброс кэша'}
MEASURES = {'рекламные метки': 'Clean-param в robots.txt для меток; rel=canonical на адрес без меток',
            'фильтры': 'rel=canonical на страницу без фильтра; noindex для сочетаний фильтров; закрыть сочетания в robots.txt',
            'сортировки': 'Clean-param для сортировки; rel=canonical на адрес без сортировки',
            'страницы': 'rel=canonical на первую страницу или ограничить глубину обхода',
            'сброс кэша': 'Clean-param для параметра сброса кэша', 'прочие параметры': 'проверить, меняет ли параметр содержимое; если нет — Clean-param и canonical'}


def _param_group(res):
    exact, wild = {}, []
    for p in res.get('params') or []:
        for k_ in p.get('ключи') or [p['ключ']]: exact[str(k_).rstrip('.')] = p['группа']
        if str(p['ключ']).endswith('*'): wild.append((p['ключ'][:-1], p['группа']))
    def f(k_):
        if k_ in exact: return exact[k_]
        for pre, g in wild:
            if k_.startswith(pre): return g
        return ''
    return f


def _kind(key, group):
    if group in KIND_OF_GROUP: return KIND_OF_GROUP[group]
    if re.search(r'(?i)sort|order', key): return 'сортировки'
    if re.search(r'(?i)^pagen|^page$|^p$|paged', key): return 'страницы'
    if group == 'Поиск и навигация' or re.search(r'(?i)filter', key): return 'фильтры'
    return 'прочие параметры'


def parasites(c, res, min_variants=300):
    """Паразитные адреса: базовый адрес страницы, у которого из-за параметров тысячи вариантов; кто по ним ходит и какие параметры виноваты."""
    R = c.R
    pg = R['is_page'].values & c.search_ok   # только поисковые роботы: человек по ссылке с меткой — норма, обход вариантов роботом — нет
    qc, qcode = _cat(R, 'query')
    tc, tcode = _cat(R, 'tpl')
    X = pd.DataFrame({'t': tcode[pg], 'q': qcode[pg], 'g': _sv(R, 'fam', pg), 'v': R['vid'].values[pg]})
    var = X.groupby('t')['q'].nunique()
    var = var[var >= min_variants].sort_values(ascending=False)
    if not len(var): return pd.DataFrame()
    pgroup = _param_group(res)
    rows = []
    for t, n in var.head(50).items():
        sub = X[X['t'] == t]
        uq = pd.unique(sub['q'])
        cnt = {}
        for q in qc[uq]:
            for kv in str(q).split('&'):
                k_ = kv.split('=', 1)[0]
                if k_: cnt.setdefault(k_, set()).add(kv)
        top = sorted(((k_, len(v)) for k_, v in cnt.items()), key=lambda x: -x[1])[:3]
        kinds = [_kind(k_, pgroup(k_)) for k_, _ in top]
        kind = kinds[0] if kinds else 'прочие параметры'
        grp = sub['g'].value_counts()
        nb = lambda k_, v: f"{k_} ({v:,})".replace(',', '\u00a0')
        rows.append({'адрес': tc[t], 'вариантов': int(n), 'запросов': int(len(sub)), 'фигуранты': '\n'.join(nb(k_, v) for k_, v in grp.head(3).items()),
                     'виновники': '\n'.join(nb(k_, v) for k_, v in top), 'вид': kind, 'меры': MEASURES[kind]})
    return pd.DataFrame(rows)


# ---------- внешнее встраивание ----------
def embedding(c, res, S):
    H = S.get('Хотлинк')
    if H is None or not len(H): return pd.DataFrame()
    R = c.R
    known = (res.get('edits_embedding') or {})
    rows = []
    hosts = set(H['ref_host'].astype(str))
    m = R['ref_host'].astype(str).isin(hosts).values & R['is_static'].values & ~R['ref_internal'].values
    bc, bcode = _cat(R, 'base')
    X = pd.DataFrame({'h': _sv(R, 'ref_host', m), 'b': bcode[m], 'd': _sv(R, 'day', m)})
    for _, r in H.iterrows():
        h = str(r['ref_host'])
        sub = X[X['h'] == h]
        files = '\n'.join(f"{bc[k_]} ({v})" for k_, v in sub['b'].value_counts().head(3).items())
        if h in known: why = known[h]
        elif h in set(c.m.get('server_ips', [])): why = 'лежит на нашем сервере (IP сервера сайта)'
        elif re.fullmatch(r'[\d.]+', h): why = 'IP без домена'
        elif re.search(r'dev|test|stage|staging|demo|local', h): why = 'похоже на тестовую копию — сверить IP с нашим сервером'
        else: why = 'чужой сайт'
        rows.append({'сайт': h, 'запросов': int(r['запросов']), 'байт': int(r['байт']), 'файлы': files, 'вывод': why,
                     'первый': sub['d'].min() if len(sub) else '', 'последний': sub['d'].max() if len(sub) else ''})
    return pd.DataFrame(rows)


# ---------- админка ----------
def admin(c, S):
    A = S.get('Админка')
    if A is None or not len(A): return pd.DataFrame()
    R = c.R
    P = ip_profile(c)
    m = R['is_admin'].values
    X = pd.DataFrame({'ip': _sv(R, 'ip', m), 'ts': R['ts'].values[m]}).groupby('ip')['ts'].agg(['min', 'max'])
    D = A.copy()
    D['ip'] = D['ip'].astype(str)
    D['первый'] = D['ip'].map(X['min']).map(lambda v: dmy(v) if pd.notna(v) else '')
    D['последний'] = D['ip'].map(X['max']).map(lambda v: dmy(v) if pd.notna(v) else '')
    D['живой'] = D['сотрудник'] | D['ip'].map(P['живой']).fillna(False).astype(bool)
    D['кто'] = np.where(D['сотрудник'], 'Сотрудник', np.where(D['живой'], 'Неизвестный', D['ip'].map(P['кто']).fillna('')))   # посторонний человек — «Неизвестный»
    D['чужой'] = ~D['сотрудник']
    D = D.sort_values(['живой', 'запросов'], ascending=[False, False]).reset_index(drop=True)
    return D


# ---------- служебные разделы ----------
def sections(S):
    """Служебные разделы одной таблицей: настоящие (отвечают 200) и ложные (сканеры угадывали) вместе."""
    X = S.get('Открытые служебные разделы')
    if X is None or not len(X): return pd.DataFrame()
    X = X.copy()
    X['настоящий'] = X['ответов_200'] > 0   # настоящий раздел отвечает 200; ложный — только 404 и переадресации
    return X.sort_values(['настоящий', 'запросов' if 'запросов' in X else 'IP'], ascending=False).reset_index(drop=True)


# ---------- сканеры ----------
SCAN_EXTRA = [('Служебные файлы движка', r'/\.ht(access|passwd)|/bitrix/\.settings|dbconn\.php|/php_interface/|/wp-config|/configuration\.php|/local/php_interface/'),
              ('Закрытые разделы сайта', r'^/(manager|admin|administrator|panel|cp|backend|dashboard|crm|lk-admin)/')]
def scanners(c, S):
    """Цели сканеров: сколько попыток, сколько сервер выполнил (200) и что именно отдал. Обычные страницы сайта,
    которые сканеры просто перебирали, — отдельно: это не улика."""
    from .blocks import VULN, TARGETS
    R = c.R
    bc, bcode = _cat(R, 'base')
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        vm_c = pd.Series(bc).str.contains(VULN, regex=True, case=False).values
    vm = vm_c[bcode]
    if not vm.any(): return pd.DataFrame(), pd.DataFrame()
    st = R['status'].values[vm]
    bb = bcode[vm]
    by = R['bytes'].values[vm]
    tgt = np.full(len(bc), 'Прочее', dtype=object)
    names = pd.Series(bc)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        for name, rx in reversed(TARGETS):
            tgt[names.str.contains(rx, regex=True, case=False).values] = name
        tgt[(tgt == 'Прочее') & names.str.contains(SCAN_EXTRA[0][1], regex=True, case=False).values] = SCAN_EXTRA[0][0]
        tgt[names.str.contains(SCAN_EXTRA[1][1], regex=True, case=False).values & (tgt == 'Прочее')] = SCAN_EXTRA[1][0]
    real = common.real_addresses(c)
    X = pd.DataFrame({'t': tgt[bb], 'b': bb, 'st': st, 'ip': R['ip'].cat.codes.values[vm], 'own': real[bb], 'by': by,
                      'd': _sv(R, 'day', vm)})
    lk = getattr(c, 'leaks', None)   # находка — то, что проверка утечек признала настоящим содержимым (blocks: размер не как у заглушки)
    leak_codes = set(np.where(np.isin(bc, list(lk['base'].astype(str))))[0]) if lk is not None and len(lk) else set()
    X['leak'] = X['b'].isin(leak_codes)
    rows = []
    for t, g in X.groupby('t'):
        ok = g[(g['st'] == 200) & (g['by'] > 0)]
        found = ok[ok['leak']]
        what = '\n'.join(f"{bc[k_]} ({v:,})".replace(',', ' ') for k_, v in found['b'].value_counts().head(4).items())
        rows.append({'цель': t, 'запросов': len(g), 'IP': g['ip'].nunique(), 'IP_с_200': ok['ip'].nunique(), 'отдано_200': len(ok), 'страницы_сайта': int(ok['own'].sum()),
                     'заглушки': int(len(ok) - ok['own'].sum() - len(found)), 'находки': len(found), 'что_отдано': what,
                     'ответы': split_codes_arr(g['st'])[0], 'ошибки': split_codes_arr(g['st'])[1]})
    T = pd.DataFrame(rows).sort_values('запросов', ascending=False).reset_index(drop=True)
    P = ip_profile(c)
    ipc = R['ip'].cat.categories.astype(str)
    I = X.groupby('ip').agg(запросов=('b', 'size'), дней=('d', 'nunique'), первый=('d', 'min'), последний=('d', 'max'),
                            целей=('t', lambda s: ', '.join(s.value_counts().index[:3])), отдано=('st', lambda s: int((s == 200).sum())))
    I['находок'] = X[(X['st'] == 200) & X['leak'] & (X['by'] > 0)].groupby('ip').size().reindex(I.index).fillna(0).astype(int)
    I.index = ipc[I.index]
    I['кто'] = I.index.map(P['кто']); I['сеть'] = I.index.map(P['организация']); I['страна'] = I.index.map(P['страна'])
    return T, I.sort_values('запросов', ascending=False).reset_index().rename(columns={'index': 'ip'})


# ---------- методы и протоколы ----------
METHOD_NOTES = [
    (r'^GET$', 'обычные запросы'), (r'^POST$', 'отправка данных'), (r'^HEAD$', 'проверка доступности без содержимого'),
    (r'^OPTIONS$', 'разведка: какие методы и CORS принимает сервер'), (r'^CONNECT$', 'ищут открытый прокси'),
    (r'^(PUT|PATCH|DELETE)$', 'REST API: изменение и удаление данных'), (r'^(PROPFIND|PROPPATCH|MKCOL|COPY|MOVE|LOCK|UNLOCK|SEARCH)$', 'WebDAV: доступ к файлам сервера'),
    (r'^TRACE$', 'отладочный метод: отражение запроса'), (r'^PRI$', 'HTTP/2 по старому протоколу: сканер или ошибка клиента'),
    (r'^-$', 'пустой запрос: соединение открыли и закрыли, ничего не отправив, — проверка открытого порта'), (r'^\\x16\\x03', 'TLS (https) на обычный порт: сканер портов'),
    (r'^\\x03\\x00\\x00', 'RDP: ищут удалённый рабочий стол Windows'), (r'^SSTP', 'SSTP: ищут VPN'), (r'^t3', 'T3: ищут сервер WebLogic'),
    (r'(?i)wget|curl|%20', 'попытка внедрить команду'), (r'^REQMOD|^RESPMOD', 'ICAP: ищут прокси-фильтр')]


def method_note(m):
    for rx, t in METHOD_NOTES:
        if re.search(rx, m): return t
    return 'случайный метод: сканер проверяет, как ответит сервер'


def method_kind(m):
    if re.match(r'^\\x16\\x03', m): return 'TLS на HTTP-порт'
    if re.match(r'^\\x', m) or not re.fullmatch(r'[A-Z-]{1,12}', m): return 'Мусор и чужие протоколы'
    return m


def methods(c):
    """Сводка по методам: что это, сколько, кто, куда, что ответил сервер. Сырые строки необычных методов — отдельно."""
    R = c.R
    if str(R['method'].dtype) == 'category':
        mc, mcode = _cat(R, 'method')
    else:
        cat_ = pd.Categorical(R['method'].astype(str)); mc, mcode = cat_.categories.astype(str), cat_.codes
    st = R['status'].values
    kinds = np.array([method_kind(m) for m in mc], dtype=object)
    Kc = pd.Categorical(kinds)
    Kcode = Kc.codes[mcode]
    rows = []
    for ki, k in enumerate(Kc.categories):
        m = Kcode == ki
        if not m.any(): continue
        ips = R['ip'].cat.codes.values[m]
        bcats = R['base'].cat.categories.astype(str)
        bb = pd.Series(R['base'].cat.codes.values[m]).value_counts().index[:3]
        ts = R['ts'].values[m]
        orig = sorted(set(mc[np.unique(mcode[m])]))
        rows.append({'метод': k, 'что': method_note(orig[0]) if len(orig) == 1 or k == 'TLS на HTTP-порт' else 'случайные методы и обрывки чужих протоколов: сканеры проверяют, как ответит сервер',
                     'запросов': int(m.sum()), 'IP': int(pd.Series(ips).nunique()), 'куда': ', '.join(bcats[bb]),
                     'ответы': split_codes_arr(st[m])[0], 'ошибки': split_codes_arr(st[m])[1], 'принято': int(((st[m] >= 200) & (st[m] < 300)).sum()),
                     'первый': dmy(ts.min()), 'последний': dmy(ts.max())})
    T = pd.DataFrame(rows).sort_values('запросов', ascending=False).reset_index(drop=True)
    odd = ~np.isin(mc.values[mcode], ('GET', 'POST', 'HEAD'))
    Raw = pd.DataFrame({'время': [dmy(x) for x in R['ts'].values[odd]], 'ip': _sv(R, 'ip', odd), 'метод': mc.values[mcode[odd]],
                        'адрес': _sv(R, 'base', odd), 'код': st[odd], 'user_agent': _sv(R, 'ua', odd)})
    P = ip_profile(c)
    Raw['кто'] = Raw['ip'].map(P['кто']).fillna('')
    Raw['опознание'] = Raw['метод'].map(method_note)
    return T, Raw


# ---------- атаки в параметрах ----------
ATTACK_KINDS = [('Обход каталогов', r'\.\./|%2e%2e%2f|/etc/passwd'), ('SQL-инъекция', r"(?i)union(\s|%20|\+)+select|'(\s|%20|\+)*or(\s|%20|\+)*'?1'?=|sleep\(|benchmark\("),
                ('XSS', r'(?i)<script|%3Cscript|javascript:'), ('Log4Shell', r'(?i)\$\{jndi:'),
                ('Выполнение команд', r'(?i)cmd=|exec\(|base64_decode|wget(\s|%20)http|curl(\s|%20)http')]


def attacks(c):
    from .blocks import ATTACK
    R = c.R
    qc, qcode = _cat(R, 'query')
    bc, bcode = _cat(R, 'base')
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        qa = pd.Series(qc).str.contains(ATTACK, regex=True).values
        ba = pd.Series(bc).str.contains(ATTACK, regex=True).values
    am = qa[qcode] | ba[bcode]
    if not am.any(): return pd.DataFrame()
    st = R['status'].values
    by = R['bytes'].values
    full = pd.Series(qc[qcode[am]]).values + '|' + pd.Series(bc[bcode[am]]).values
    kind = np.full(am.sum(), 'Прочее', dtype=object)
    for nm, rx in reversed(ATTACK_KINDS):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            kind[pd.Series(full).str.contains(rx, regex=True).values] = nm
    X = pd.DataFrame({'b': bcode[am], 'k': kind, 'st': st[am], 'by': by[am], 'ip': _sv(R, 'ip', am), 'q': qc[qcode[am]], 'ts': R['ts'].values[am]})
    # обычные размеры страницы: все ответы 200 этого адреса без атаки. Атака проигнорирована, если её ответ по размеру (±2%)
    # совпадает хоть с одним обычным ответом: сайт показал свою обычную страницу.
    norm_m = ~am & (st == 200)
    NB = pd.DataFrame({'b': bcode[norm_m], 'by': by[norm_m]})
    NB = NB[NB['b'].isin(set(X['b']))]
    NS = {b: np.sort(g['by'].values) for b, g in NB.groupby('b')}
    def matches(b, size_):
        arr = NS.get(b)
        if arr is None or not len(arr): return False
        i = np.searchsorted(arr, size_)
        near = [arr[j] for j in (i - 1, i) if 0 <= j < len(arr)]
        return any(abs(v - size_) <= max(200, 0.02 * size_) for v in near)
    rows = []
    P = ip_profile(c)
    for (b, k), g in X.groupby(['b', 'k']):
        ips = g['ip'].value_counts()
        ok = g[g['st'] == 200]
        arr = NS.get(b)
        odd = [int(v) for v in ok['by'] if not matches(b, v)]
        st_ok, st_bad = split_codes_arr(g['st'])
        rows.append({'адрес': bc[b], 'вид': k, 'запросов': len(g), 'IP': len(ips), 'главный_IP': f"{ips.index[0]} ({ips.iloc[0]})", 'кто': P['кто'].get(ips.index[0], ''),
                     'ответы': st_ok, 'ошибки': st_bad, 'отдано_200': len(ok), 'размер_200': int(ok['by'].median()) if len(ok) else None,
                     'обычный_размер': (f"{int(arr.min()):,}–{int(arr.max()):,}".replace(',', '\u00a0') if arr is not None and len(arr) else '—'),
                     'необычных': len(odd), 'пример': str(g['q'].iloc[0])[:200], 'первый': dmy(g['ts'].min()), 'последний': dmy(g['ts'].max())})
    D = pd.DataFrame(rows)
    D['подозрительно'] = D['необычных'] > 0
    return D.sort_values('запросов', ascending=False).reset_index(drop=True)


# ---------- серверный фильтр: кому защита сервера отказывает ----------
BLOCK_CODES = (403, 429, 444, 503)
AD_CHECKERS = ('YaDirectFetcher', 'AdsBot-Google')   # роботы проверки объявлений (модерация посадочных)
FILTER_GROUPS = ('Поисковые роботы', 'Роботы проверки объявлений', 'Люди')
FILTER_WHAT = {'Поисковые роботы': 'страницы перестают обходиться и выпадают из поиска',
               'Роботы проверки объявлений': 'объявления с такими посадочными могут не пройти модерацию',
               'Люди': 'посетители не видят сайт'}
GEO_NOTE = 'Похоже на гео-фильтр по стране; под него попадают подлинные поисковые роботы'
FILTER_TODO = 'Исключить из фильтра подлинных поисковых роботов и роботов Яндекса по их официальным сетям'


def waves(days):
    """Дни отказов, слитые в диапазоны: «1–2.09, 18–24.09» (через месяц — «30.09–2.10»)."""
    ds = sorted(pd.to_datetime(sorted(set(map(str, days)))))
    if not ds: return ''
    runs, a, b = [], ds[0], ds[0]
    for d_ in ds[1:]:
        if (d_ - b).days == 1: b = d_
        else: runs.append((a, b)); a = b = d_
    runs.append((a, b))
    fmt = lambda x: f'{x.day}.{x.month:02d}'
    return ', '.join(fmt(a) if a == b else (f'{a.day}–{fmt(b)}' if (a.year, a.month) == (b.year, b.month) else f'{fmt(a)}–{fmt(b)}') for a, b in runs)


def server_filter(c):
    """Отказы защиты сервера (403/429/444/503) подлинным поисковым роботам, роботам проверки объявлений и людям.
    Зонды сканеров и уязвимые адреса не считаются. Строка — (группа, кто, код, тип сети, страна).
    Возвращает словарь: таблица, группы (итоги для Обзора), кто (итоги по роботам и людям для карточек), вывод, что_сделать, гео."""
    from .blocks import VULN
    R = c.R
    st = R['status'].values
    codes = R['base'].cat.codes.values
    bcat = R['base'].cat.categories.to_series()
    vuln_b = bcat.str.contains(VULN, regex=True, case=False).values[codes]
    probe = bcat.str.contains(r'\.log$|/logs?/|^/(upload|uploads|images|files|bitrix|local)/$', regex=True, case=False).values[codes]   # логи и листинги папок ищут сканеры
    # «люди» — только визиты, которые смотрели сайт (есть страница с ответом 200); сканер служебных файлов — не человек
    browsing = np.isin(R['vid'].values, np.unique(R['vid'].values[c.human & R['is_page'].values & (st == 200)]))
    fam = R['fam'].astype(str).values
    ad = np.isin(fam, AD_CHECKERS) & (R['fam_verified'].astype(str).values == 'да')
    grp = np.select([c.search_ok, ad, c.human & browsing], list(FILTER_GROUPS), '')
    who = np.where(grp == 'Люди', 'люди', fam)
    inside = grp != ''
    blk = inside & np.isin(st, BLOCK_CODES) & ~vuln_b & ~probe
    empty = dict(таблица=pd.DataFrame(), группы=pd.DataFrame(), кто=pd.DataFrame(), вывод='', что_сделать=FILTER_TODO, гео=False)
    if not blk.any(): return empty
    total = pd.Series(who[inside]).value_counts()
    X = pd.DataFrame({'группа': grp[blk], 'кто': who[blk], 'код': st[blk].astype(int), 'сеть': R['nettype'].astype(str).values[blk],
                      'страна': R['cc'].astype(str).values[blk], 'день': R['day'].astype(str).values[blk], 'адрес': R['base'].astype(str).values[blk]})
    g = X.groupby(['группа', 'кто', 'код', 'сеть', 'страна'], sort=False)
    D = g.agg(ответов=('день', 'size'), дней=('день', 'nunique'), пример=('адрес', 'first')).reset_index()
    D['волны'] = [waves(v) for v in g['день'].agg(lambda s: tuple(s.unique())).values]
    D['доля_%'] = (D['ответов'] / D['кто'].map(total).values * 100).round(1)
    D['_g'] = D['группа'].map({k: i for i, k in enumerate(FILTER_GROUPS)})
    D = D.sort_values(['_g', 'ответов'], ascending=[True, False]).drop(columns='_g').reset_index(drop=True)
    D = D[['группа', 'кто', 'код', 'сеть', 'страна', 'ответов', 'доля_%', 'дней', 'волны', 'пример']]
    W = X.groupby('кто').agg(группа=('группа', 'first'), отказов=('день', 'size'), дней=('день', 'nunique')).reset_index()
    W['запросов'] = W['кто'].map(total).astype(int).values
    W['доля_%'] = (W['отказов'] / W['запросов'] * 100).round(1)
    W['волны'] = W['кто'].map(X.groupby('кто')['день'].agg(waves))
    W['страны'] = W['кто'].map(X.groupby('кто')['страна'].agg(lambda s: ', '.join(f'{k or "?"} — {v}' for k, v in s.value_counts().head(5).items())))
    W['коды'] = W['кто'].map(X.groupby('кто')['код'].agg(lambda s: ', '.join(f'{k}: {v}' for k, v in s.value_counts().items())))
    W = W.sort_values('отказов', ascending=False).reset_index(drop=True)
    G = pd.DataFrame([dict(группа=k, отказов=int((X['группа'] == k).sum()), дней=int(X.loc[X['группа'] == k, 'день'].nunique()),
                           кто=', '.join(W.loc[W['группа'] == k, 'кто']) if k != 'Люди' else '', что=FILTER_WHAT[k]) for k in FILTER_GROUPS])
    # гео-фильтр: все отказы — зарубежным адресам, а российские (они в логе есть) не получили ни одного
    ru_all = int((inside & (R['cc'].astype(str).values == 'RU')).sum())
    geo = bool(ru_all and X['страна'].ne('RU').all() and X['страна'].ne('').all())
    robots = bool((X['группа'] != 'Люди').any())
    note = (GEO_NOTE if robots else GEO_NOTE.split(';')[0]) if geo else ''
    return dict(таблица=D, группы=G, кто=W, вывод=note, что_сделать=FILTER_TODO, гео=geo)


# ---------- токены ----------
def tokens(c):
    R = c.R
    qc, qcode = _cat(R, 'query')
    from .recon import SECRET_RX as rx   # список секретов — общий с маскировкой (+ USER_CHECKWORD); значения на лист не выводятся
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        t = pd.Series(qc).str.contains(rx, regex=True).values
    m = t[qcode]
    if not m.any(): return pd.DataFrame()
    rg = np.asarray(c.rg).astype(object)[m]
    X = pd.DataFrame({'b': _sv(R, 'base', m), 'p': pd.Series(qc[qcode[m]]).str.extract(rx)[0].str.lower().values,
                      'g': rg, 'se': c.search_ok[m], 'ts': R['ts'].values[m]})
    D = X.groupby(['b', 'p']).agg(запросов=('g', 'size'), свои=('g', lambda s: int((s == 'Свои').sum())), посторонние=('g', lambda s: int((~s.isin(['Свои'])).sum())),
                                  поисковики=('se', 'sum'), t0=('ts', 'min'), t1=('ts', 'max')).reset_index()
    D['первый'] = D['t0'].map(dmy); D['последний'] = D['t1'].map(dmy)
    return D.drop(columns=['t0', 't1']).sort_values('запросов', ascending=False).reset_index(drop=True)


# ---------- конструкты для безопасности ----------
INJECT = r"\$\{|\{\{|'\s*\+|\+\s*'|<script|%3C|\.\./|%27|union|select"


def constructs_sec(c):
    from .blocks import constructs
    kg = constructs(c)
    if not len(kg): return pd.DataFrame()
    k = kg.copy()
    inj = k['адрес'].astype(str).str.contains(INJECT, regex=True, case=False)
    got = k['коды'].astype(str).str.contains(r'(?:^|,\s*)200:')
    outs = k['вывод'].astype(str).str.startswith('посторонние')
    k = k[outs | got | (inj & (k['люди'] < k['запросов']))].copy()
    if not len(k): return k
    k['вид'] = np.where(k['адрес'].astype(str).str.contains(r'\.\./|%2e%2e', case=False, regex=True), 'обход каталогов',
                np.where(k['адрес'].astype(str).str.contains(r'<script|%3Cscript', case=False, regex=True), 'XSS',
                np.where(k['адрес'].astype(str).str.contains(r'\$\{|\{\{', regex=True), 'подстановка шаблона', 'склейка строк или мусор')))
    k['опасно'] = got
    return k.sort_values(['опасно', 'запросов'], ascending=False).reset_index(drop=True)


# ---------- утечки: история и текущий ответ посторонним ----------
def leaks(c, S, checks=None):
    L = S.get('Утечки служебных файлов')
    if L is None or not len(L): return pd.DataFrame()
    R = c.R
    staff = set(c.m.get('staff_ips', []))
    bc, bcode = _cat(R, 'base')
    days_all = sorted(R['day'].astype(str).unique())
    rows = []
    checks = checks or {}
    for _, r in L.iterrows():
        f = str(r['файл'])
        pc = np.where(bc == f)[0]
        m = np.isin(bcode, pc) & ~R['ip'].astype(str).isin(staff).values
        st = R['status'].values[m]; by = R['bytes'].values[m]; d = _sv(R, 'day', m)
        served = (st == 200) & (by > 0)
        D = pd.DataFrame({'d': d, 's': served}).groupby('d')['s'].any()
        hist = common.day_runs(D.index, D.values, days_all, {True: 'отдаётся', False: 'закрыт'})
        if len(D) and D.index.max() < days_all[-1]:   # после последнего запроса лог молчит: что с файлом сейчас — по логу не видно
            hist += f"; после {pd.Timestamp(D.index.max()).strftime('%d.%m')} запросов не было"
        if len(D) and D.iloc[-1]: hist = hist.replace('отдаётся с', 'отдавался с', 1) if 'запросов не было' in hist else hist
        last = int(st[-1]) if len(st) else None
        ch = checks.get(f) or {}
        open_now = bool(len(st)) and bool(served[-1]) and str(d[-1]) >= common_recent(days_all)   # последний ответ посторонним — содержимое, и это последние дни лога
        rows.append({'файл': f, 'открыт_сейчас': open_now, 'отдан_раз': int(r['ответов_200']), 'IP': int(r['IP']), 'размер': int(round(r['размер_у_чужих'] if pd.notna(r.get('размер_у_чужих')) else r['размер'])),
                     'история': hist, 'последний_ответ': last, 'первый': r['первый'], 'последний': r['последний'],
                     'проверка': ch.get('итог', 'не проверено'), 'проверено': ch.get('когда', ''), 'внутри': ch.get('внутри', ''), 'тревога': bool(ch.get('тревога'))})
    return pd.DataFrame(rows)


def journal(c, res):
    """По дням: запросы по группам, трафик, пик в минуту, сканеры и их находки. Шапка в два уровня, как в журналах 01 и 02."""
    from .blocks import VULN
    R = c.R
    J0 = (res.get('errors') or {}).get('журнал')
    if J0 is None or not len(J0): return None
    day = R['day'].astype(str).values
    rg = np.asarray(c.rg).astype(object)
    bc, bcode = _cat(R, 'base')
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        vm = pd.Series(bc).str.contains(VULN, regex=True, case=False).values[bcode]
    lk = getattr(c, 'leaks', None)
    leak = np.isin(bc, list(lk['base'].astype(str)))[bcode] if lk is not None and len(lk) else np.zeros(len(R), bool)
    st = R['status'].values
    find = vm & (st == 200) & (R['bytes'].values > 0) & leak
    other = ~np.isin(rg, ('Люди', 'Роботы', 'Боты'))
    X = pd.DataFrame({'d': day, 'b': R['bytes'].values, 'h': c.human, 'r': rg == 'Роботы', 'bt': rg == 'Боты', 'o': other, 'v': vm, 'f': find, 'm': R['ts'].values // 60})
    g = X.groupby('d')
    D = pd.DataFrame({'Запросов|Все': g.size(), 'Запросов|Люди': g['h'].sum(), 'Запросов|Роботы': g['r'].sum(), 'Запросов|Боты': g['bt'].sum(), 'Запросов|Прочие': g['o'].sum(),
                      'Трафик|ГБ': (g['b'].sum() / GB).round().astype(int),
                      'Пик|В минуту': X.groupby(['d', 'm']).size().groupby(level=0).max(),
                      'Сканеры|Запросов': g['v'].sum(), 'Сканеры|Находок': g['f'].sum()}).reset_index().rename(columns={'d': 'день'})
    meta = J0[J0['день'] != 'Итого'][['день', '_с', '_по', '_полный']]
    D = meta.merge(D, on='день', how='left').fillna(0)
    tot = {k_: (int(D[k_].sum()) if k_ != 'Пик|В минуту' else int(D[k_].max())) for k_ in D.columns if '|' in k_}
    D = pd.concat([D, pd.DataFrame([{'день': 'Итого', **tot}])], ignore_index=True)
    return D


def common_recent(days_all):
    """С какого дня «сейчас»: последние 2 дня лога или 10% периода — как у адресов в 02 (errors.recent_day)."""
    return days_all[max(0, len(days_all) - max(2, int(round(len(days_all) * 0.1))))] if days_all else ''


def build(c, res, S):
    """Все срезы 03 одним словарём (res['security'])."""
    out = {}
    OUT = (res.get('errors') or {}).get('сбои')
    steps = [('часы', lambda: heat(c)), ('всплески', lambda: bursts(c, OUT)), ('массовые', lambda: mass_requests(c)), ('источники', lambda: sources(c)), ('каналы', lambda: sources_channels(c)),
             ('типы_файлов', lambda: file_types(c)), ('тяжёлые', lambda: heavy_files(c)), ('паразиты', lambda: parasites(c, res)),
             ('встраивание', lambda: embedding(c, res, S)), ('админка', lambda: admin(c, S)), ('разделы', lambda: sections(S)),
             ('сканеры', lambda: scanners(c, S)), ('методы', lambda: methods(c)), ('атаки', lambda: attacks(c)), ('токены', lambda: tokens(c)),
             ('конструкты', lambda: constructs_sec(c)), ('фильтр', lambda: getattr(c, 'server_filter', None)), ('журнал', lambda: journal(c, res)), ('утечки', lambda: leaks(c, S, res.get('leak_checks')))]
    for k, f in steps:
        try: out[k] = f()
        except Exception:
            import traceback; traceback.print_exc(); out[k] = None
    return out


def findings(res, items):
    """Карточки по срезам 03: паразитные адреса вместо «ловушек»; всплески, похожие на DDoS."""
    X = res.get('security') or {}
    items[:] = [x for x in items if x['key'] not in ('Нагрузка и безопасность:parasites:site', 'Нагрузка и безопасность:ddos_like:site')]   # повторный вызов ничего не дублирует
    P = X.get('паразиты')
    if P is not None and len(P):
        items[:] = [x for x in items if ':trap:' not in x['key']]
        sev = 'Важно' if (P['вариантов'] >= 1000).any() else 'К сведению'
        top = P.head(5)
        items.append(dict(key='Нагрузка и безопасность:parasites:site', блок='Нагрузка и безопасность', важность=sev,
                          что_происходит=f'Паразитные адреса: поисковые роботы обходят тысячи вариантов {len(P)} страниц из-за меток и фильтров',
                          факты='; '.join(f"{r['адрес']} — {r['вариантов']} вариантов; виновники: {r['виновники']}; обходят: {r['фигуранты']}".replace('\n', ', ') for _, r in top.iterrows()),
                          где_править='robots.txt, rel=canonical, шаблоны ссылок', что_сделать='; '.join(sorted(set(top['меры']))),
                          главная_цифра=int(P['вариантов'].sum()), лист='Паразитные адреса', также_в='', статус=''))
    items[:] = [x for x in items if x['key'] not in ('Нагрузка и безопасность:attack_odd_200:params', 'Нагрузка и безопасность:odd_method_accepted:site')]
    At = X.get('атаки')
    if At is not None and len(At) and At['подозрительно'].any():
        a_ = At[At['подозрительно']]
        items.append(dict(key='Нагрузка и безопасность:attack_odd_200:params', блок='Нагрузка и безопасность', важность='Срочно',
                          что_происходит=f'Атака получила необычный ответ сервера ({len(a_)} адресов)',
                          факты='; '.join(f"{r['адрес']} — {r['вид'].lower()}, {r['необычных']} раз; ответ {r['размер_200']} байт, обычно {r['обычный_размер']} байт" for _, r in a_.head(5).iterrows()),
                          где_править='код сайта', что_сделать='Открыть адреса из примеров и проверить, что сервер вернул: обычную страницу или содержимое файла',
                          главная_цифра=int(a_['необычных'].sum()), лист='Атаки в параметрах', также_в='', статус=''))
    M = X.get('методы')
    if M is not None and M[0] is not None and len(M[0]):
        m_ = M[0][~M[0]['метод'].isin(['GET', 'POST', 'HEAD']) & (M[0]['принято'] > 0)]
        if len(m_):
            items.append(dict(key='Нагрузка и безопасность:odd_method_accepted:site', блок='Нагрузка и безопасность', важность='Срочно',
                              что_происходит='Сервер принимает необычные методы запросов',
                              факты='; '.join(f"{r['метод']} — принято {r['принято']} раз; куда: {r['куда']}" for _, r in m_.iterrows()),
                              где_править='nginx', что_сделать='Принимать только GET, POST и HEAD; остальное — отказ (444)',
                              главная_цифра=int(m_['принято'].sum()), лист='Методы и протоколы', также_в='', статус=''))
    B = X.get('всплески')
    if B is not None and len(B):
        dd = B[B['картина'].str.startswith('распределённая')]
        if len(dd):
            items.append(dict(key='Нагрузка и безопасность:ddos_like:site', блок='Нагрузка и безопасность', важность='Важно',
                              что_происходит=f'Всплески нагрузки с многих IP сразу — похоже на DDoS ({len(dd)})',
                              факты='; '.join(f"{r['всплеск']}: {r['минут']} мин, {r['запросов']} запросов с {r['IP']} IP, последствия: {r['последствия']}" for _, r in dd.head(5).iterrows()),
                              где_править='хостинг / защита от DDoS', что_сделать='Проверить, сработала ли защита; включить ограничение частоты и фильтрацию на уровне хостинга',
                              главная_цифра=int(dd['запросов'].sum()), лист='Всплески нагрузки', также_в='', статус=''))
