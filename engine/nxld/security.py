"""NXLD: данные файла 03 «Нагрузка и безопасность» — срезы для листов и обзора.

Карточки проблем по-прежнему заводит blocks.load_security; здесь — таблицы в человеческом виде на общих расчётах
(common: кто это по IP, эпизоды, история по дням, настоящий или выдуманный адрес)."""
import re
import numpy as np
import pandas as pd
from . import common
from .common import ip_profile, codes_text, dmy, episode_id, who_text

GROUPS_HEAT = ('Все', 'Люди', 'Роботы', 'Боты')
GB = 1024 ** 3


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
def bursts(c, OUT=None, k=3.0, add=500, gap=10, min_excess=3000):
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
        fam = pd.Series(R['fam'].astype(str).values[sl]); fam = fam[fam != '']
        if top_share >= 0.6: pic = f"натиск с одного IP: {top_ip} ({P['кто'].get(top_ip, '')})"
        elif grp.get('Роботы', 0) / len(st_) >= 0.6: pic = f"обход робота: {fam.value_counts().index[0] if len(fam) else 'робот'}"
        elif grp.get('Люди', 0) / len(st_) >= 0.6: pic = 'наплыв людей'
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
                     'ответы': codes_text(st_), 'защита': f'{prot:,}'.replace(',', ' ') if prot else 'нет', 'последствия': '; '.join(cons) or 'не видно',
                     'картина': pic, 'кто': who_text(grp), '_excess': excess, '_t0': a * 60})
    return pd.DataFrame(rows)


def onslaught(c, per_min=120):
    """Натиск (флуд): IP, которые хотя бы минуту слали не меньше per_min запросов. Строка — IP за весь период."""
    R = c.R
    m = R['ts'].values // 60
    ipc, ipcode = _cat(R, 'ip')
    X = pd.DataFrame({'m': m, 'ip': ipcode}).groupby(['ip', 'm']).size()
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
    D['ответы'] = S_.groupby('ip')['st'].agg(codes_text).reindex(D.index).values
    D['защита'] = S_.assign(p=np.isin(S_['st'], (403, 429, 444))).groupby('ip')['p'].sum().reindex(D.index).astype(int).values
    D['кто'] = D['ip'].map(P['кто']).fillna('')
    D['сеть'] = D['ip'].map(P['организация']).fillna('')
    D['страна'] = D['ip'].map(P['страна']).fillna('')
    D['первая'] = D['первая'].map(lambda v: dmy(v * 60)); D['последняя'] = D['последняя'].map(lambda v: dmy(v * 60))
    return D.sort_values('максимум', ascending=False).reset_index(drop=True)


# ---------- источники нагрузки ----------
def sources(c):
    """Категория (группа) · Тип (подгруппа) · Подозреваемый (кто именно) — запросы, страницы, трафик, максимум за минуту."""
    R, V = c.R, c.V
    rg, rs = np.asarray(c.rg).astype(object), np.asarray(c.rsub).astype(object)
    fam = R['fam'].astype(str).values
    ch = V['channel'].astype(str).reindex(R['vid'].values).values if 'channel' in V else np.full(len(R), '')
    ip = R['ip'].astype(str).values
    who = np.where(np.isin(rg, ('Роботы',)), fam,
          np.where(rg == 'Люди', ch,
          np.where(rg == 'Свои', ip,
          np.where(rg == 'Боты', np.where(fam != '', fam, '—'), rs))))
    key = pd.Series(rg + '\x00' + rs + '\x00' + who.astype(object))
    kc = pd.Categorical(key)
    by = R['bytes'].values
    page = ~R['is_static'].values
    m = R['ts'].values // 60
    D = pd.DataFrame({'k': kc.codes, 'b': by, 'p': page})
    g = D.groupby('k').agg(запросов=('b', 'size'), страниц=('p', 'sum'), байт=('b', 'sum'))
    mx = pd.DataFrame({'k': kc.codes, 'm': m}).groupby(['k', 'm']).size().groupby(level=0).max()
    g['максимум'] = mx.reindex(g.index).values
    parts = pd.Series(kc.categories[g.index]).str.split('\x00', expand=True)
    g['категория'], g['тип'], g['подозреваемый'] = parts[0].values, parts[1].values, parts[2].values
    g['трафик_%'] = g['байт'] / max(1, by.sum()) * 100
    return g.sort_values('запросов', ascending=False).reset_index(drop=True)


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
    X = pd.DataFrame({'b': bcode[m], 'by': R['bytes'].values[m], 'ri': R['ref_internal'].values[m].astype(bool), 'g': np.asarray(c.rg).astype(object)[m], 'd': R['day'].astype(str).values[m]})
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


def parasites(c, res, min_variants=500):
    """Паразитные адреса: базовый адрес страницы, у которого из-за параметров тысячи вариантов; кто по ним ходит и какие параметры виноваты."""
    R = c.R
    pg = R['is_page'].values
    qc, qcode = _cat(R, 'query')
    tc, tcode = _cat(R, 'tpl')
    X = pd.DataFrame({'t': tcode[pg], 'q': qcode[pg], 'g': np.asarray(c.rg).astype(object)[pg], 'v': R['vid'].values[pg]})
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
        grp = sub.groupby('g')['v'].nunique()
        prog = grp.drop(labels=[x for x in ('Люди', 'Свои') if x in grp.index]).sum()
        rows.append({'адрес': tc[t], 'вариантов': int(n), 'запросов': int(len(sub)), 'фигуранты': who_text(grp, 3) + ' визитов',
                     'виновники': ', '.join(f"{k_} ({v:,})".replace(',', ' ') for k_, v in top), 'вид': kind, 'меры': MEASURES[kind],
                     'программы_доля': float(prog / max(1, grp.sum()))})
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
    X = pd.DataFrame({'h': R['ref_host'].astype(str).values[m], 'b': bcode[m], 'd': R['day'].astype(str).values[m]})
    for _, r in H.iterrows():
        h = str(r['ref_host'])
        sub = X[X['h'] == h]
        files = ', '.join(f"{bc[k_]} ({v})" for k_, v in sub['b'].value_counts().head(3).items())
        if h in known: why = known[h]
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
    X = pd.DataFrame({'ip': R['ip'].astype(str).values[m], 'ts': R['ts'].values[m]}).groupby('ip')['ts'].agg(['min', 'max'])
    D = A.copy()
    D['ip'] = D['ip'].astype(str)
    D['первый'] = D['ip'].map(X['min']).map(lambda v: dmy(v) if pd.notna(v) else '')
    D['последний'] = D['ip'].map(X['max']).map(lambda v: dmy(v) if pd.notna(v) else '')
    D['кто'] = np.where(D['сотрудник'], 'Свои — сотрудник', D['ip'].map(P['кто']).fillna(''))
    D['живой'] = D['сотрудник'] | D['ip'].map(P['живой']).fillna(False).astype(bool)
    D['чужой'] = ~D['сотрудник']
    D = D.sort_values(['живой', 'запросов'], ascending=[False, False]).reset_index(drop=True)
    return D


# ---------- служебные разделы ----------
def sections(S):
    X = S.get('Открытые служебные разделы')
    if X is None or not len(X): return pd.DataFrame(), pd.DataFrame()
    real = X['ответов_200'] > 0   # настоящий раздел отвечает 200; выдуманный — только 404 и переадресации
    return X[real].reset_index(drop=True), X[~real].reset_index(drop=True)


# ---------- сканеры ----------
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
    real = common.real_addresses(c)
    X = pd.DataFrame({'t': tgt[bb], 'b': bb, 'st': st, 'ip': R['ip'].cat.codes.values[vm], 'own': real[bb], 'by': by,
                      'd': R['day'].astype(str).values[vm]})
    rows = []
    for t, g in X.groupby('t'):
        ok = g[(g['st'] == 200) & (g['by'] > 0)]
        found = ok[~ok['own']]
        what = ', '.join(f"{bc[k_]} ({v:,})".replace(',', ' ') for k_, v in found['b'].value_counts().head(4).items())
        rows.append({'цель': t, 'запросов': len(g), 'IP': g['ip'].nunique(), 'отдано_200': len(ok), 'страницы_сайта': int(ok['own'].sum()),
                     'находки': len(found), 'что_отдано': what, 'ответы': codes_text(g['st'])})
    T = pd.DataFrame(rows).sort_values('запросов', ascending=False).reset_index(drop=True)
    P = ip_profile(c)
    ipc = R['ip'].cat.categories.astype(str)
    I = X.groupby('ip').agg(запросов=('b', 'size'), дней=('d', 'nunique'), первый=('d', 'min'), последний=('d', 'max'),
                            целей=('t', lambda s: ', '.join(s.value_counts().index[:3])), отдано=('st', lambda s: int((s == 200).sum())))
    I['находок'] = X[(X['st'] == 200) & ~X['own'] & (X['by'] > 0)].groupby('ip').size().reindex(I.index).fillna(0).astype(int)
    I.index = ipc[I.index]
    I['кто'] = I.index.map(P['кто']); I['сеть'] = I.index.map(P['организация']); I['страна'] = I.index.map(P['страна'])
    return T, I.sort_values('запросов', ascending=False).reset_index().rename(columns={'index': 'ip'})


# ---------- методы и протоколы ----------
METHOD_NOTES = [
    (r'^GET$', 'обычные запросы'), (r'^POST$', 'отправка данных'), (r'^HEAD$', 'проверка доступности без содержимого'),
    (r'^OPTIONS$', 'разведка: какие методы и CORS принимает сервер'), (r'^CONNECT$', 'ищут открытый прокси'),
    (r'^(PUT|PATCH|DELETE)$', 'REST API: изменение и удаление данных'), (r'^(PROPFIND|PROPPATCH|MKCOL|COPY|MOVE|LOCK|UNLOCK|SEARCH)$', 'WebDAV: доступ к файлам сервера'),
    (r'^TRACE$', 'отладочный метод: отражение запроса'), (r'^PRI$', 'HTTP/2 по старому протоколу: сканер или ошибка клиента'),
    (r'^-$', 'пустой запрос: проверка открытого порта'), (r'^\\x16\\x03', 'TLS (https) на обычный порт: сканер портов'),
    (r'^\\x03\\x00\\x00', 'RDP: ищут удалённый рабочий стол Windows'), (r'^SSTP', 'SSTP: ищут VPN'), (r'^t3', 'T3: ищут сервер WebLogic'),
    (r'(?i)wget|curl|%20', 'попытка внедрить команду'), (r'^REQMOD|^RESPMOD', 'ICAP: ищут прокси-фильтр')]


def method_note(m):
    for rx, t in METHOD_NOTES:
        if re.search(rx, m): return t
    return 'неизвестный метод или мусор: сканер другого протокола'


def method_kind(m):
    if re.match(r'^\\x16\\x03', m): return 'TLS на HTTP-порт'
    if re.match(r'^\\x', m) or not re.fullmatch(r'[A-Z-]{1,12}', m): return 'Мусор и чужие протоколы'
    return m


def methods(c):
    """Сводка по методам: что это, сколько, кто, куда, что ответил сервер. Сырые строки необычных методов — отдельно."""
    R = c.R
    mc, mcode = _cat(R, 'method') if str(R['method'].dtype) == 'category' else (None, None)
    meth = R['method'].astype(str).values
    st = R['status'].values
    U = pd.Series(meth).value_counts()
    rows = []
    kinds = {m: method_kind(m) for m in U.index}
    K = pd.Series(meth).map(kinds).values
    for k in pd.unique(K):
        m = K == k
        ips = R['ip'].values[m]
        bb = R['base'].astype(str).values[m]
        ts = R['ts'].values[m]
        orig = sorted(set(meth[m]))
        rows.append({'метод': k, 'что': method_note(orig[0]) if len(orig) == 1 else (method_note(orig[0]) if k == 'TLS на HTTP-порт' else 'разное: ' + ', '.join(orig[:6])),
                     'запросов': int(m.sum()), 'IP': int(pd.Series(ips).nunique()), 'куда': ', '.join(pd.Series(bb).value_counts().index[:3]),
                     'ответы': codes_text(st[m]) if m.sum() < 5e6 else '', 'принято': int(((st[m] >= 200) & (st[m] < 300)).sum()),
                     'первый': dmy(ts.min()), 'последний': dmy(ts.max())})
    T = pd.DataFrame(rows).sort_values('запросов', ascending=False).reset_index(drop=True)
    odd = ~np.isin(meth, ('GET', 'POST', 'HEAD'))
    Raw = pd.DataFrame({'время': [dmy(x) for x in R['ts'].values[odd]], 'ip': R['ip'].astype(str).values[odd], 'метод': meth[odd],
                        'адрес': R['base'].astype(str).values[odd], 'код': st[odd], 'user_agent': R['ua'].astype(str).values[odd]})
    P = ip_profile(c)
    Raw['кто'] = Raw['ip'].map(P['кто']).fillna('')
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
    X = pd.DataFrame({'b': bcode[am], 'k': kind, 'st': st[am], 'by': by[am], 'ip': R['ip'].astype(str).values[am], 'q': qc[qcode[am]], 'ts': R['ts'].values[am]})
    # обычный размер страницы: медиана ответов 200 этого адреса без атаки
    norm_m = ~am & (st == 200)
    NS = pd.Series(by[norm_m]).groupby(bcode[norm_m]).median()
    rows = []
    P = ip_profile(c)
    for (b, k), g in X.groupby(['b', 'k']):
        ips = g['ip'].value_counts()
        ok = g[g['st'] == 200]
        ns = NS.get(b)
        rows.append({'адрес': bc[b], 'вид': k, 'запросов': len(g), 'IP': len(ips), 'главный_IP': f"{ips.index[0]} ({ips.iloc[0]})", 'кто': P['кто'].get(ips.index[0], ''),
                     'ответы': codes_text(g['st']), 'отдано_200': len(ok), 'размер_200': int(ok['by'].median()) if len(ok) else None,
                     'обычный_размер': int(ns) if ns is not None and not pd.isna(ns) else None, 'пример': str(g['q'].iloc[0])[:200],
                     'первый': dmy(g['ts'].min()), 'последний': dmy(g['ts'].max())})
    D = pd.DataFrame(rows)
    D['подозрительно'] = (D['отдано_200'] > 0) & ((D['обычный_размер'].isna()) | ((D['размер_200'] - D['обычный_размер']).abs() > (0.1 * D['обычный_размер']).clip(lower=300)))
    return D.sort_values('запросов', ascending=False).reset_index(drop=True)


# ---------- токены ----------
def tokens(c):
    R = c.R
    qc, qcode = _cat(R, 'query')
    rx = r'(?i)(?:^|&)(sessid|phpsessid|token|access_token|api_key|apikey|key|password|passwd)='
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        t = pd.Series(qc).str.contains(rx, regex=True).values
    m = t[qcode]
    if not m.any(): return pd.DataFrame()
    rg = np.asarray(c.rg).astype(object)[m]
    X = pd.DataFrame({'b': R['base'].astype(str).values[m], 'p': pd.Series(qc[qcode[m]]).str.extract(rx)[0].str.lower().values,
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
        st = R['status'].values[m]; by = R['bytes'].values[m]; d = R['day'].astype(str).values[m]
        served = (st == 200) & (by > 0)
        D = pd.DataFrame({'d': d, 's': served}).groupby('d')['s'].any()
        hist = common.day_runs(D.index, D.values, days_all, {True: 'отдаётся', False: 'закрыт'})
        last = int(st[-1]) if len(st) else None
        ch = checks.get(f) or {}
        rows.append({'файл': f, 'отдан_раз': int(r['ответов_200']), 'IP': int(r['IP']), 'размер': int(round(r['размер_у_чужих'] if pd.notna(r.get('размер_у_чужих')) else r['размер'])),
                     'история': hist, 'последний_ответ': last, 'первый': r['первый'], 'последний': r['последний'],
                     'проверка': ch.get('итог', 'не проверено'), 'проверено': ch.get('когда', ''), 'внутри': ch.get('внутри', ''), 'тревога': bool(ch.get('тревога'))})
    return pd.DataFrame(rows)


def build(c, res, S):
    """Все срезы 03 одним словарём (res['security'])."""
    out = {}
    OUT = (res.get('errors') or {}).get('сбои')
    steps = [('часы', lambda: heat(c)), ('всплески', lambda: bursts(c, OUT)), ('натиск', lambda: onslaught(c)), ('источники', lambda: sources(c)),
             ('типы_файлов', lambda: file_types(c)), ('тяжёлые', lambda: heavy_files(c)), ('паразиты', lambda: parasites(c, res)),
             ('встраивание', lambda: embedding(c, res, S)), ('админка', lambda: admin(c, S)), ('разделы', lambda: sections(S)),
             ('сканеры', lambda: scanners(c, S)), ('методы', lambda: methods(c)), ('атаки', lambda: attacks(c)), ('токены', lambda: tokens(c)),
             ('конструкты', lambda: constructs_sec(c)), ('утечки', lambda: leaks(c, S, res.get('leak_checks')))]
    for k, f in steps:
        try: out[k] = f()
        except Exception:
            import traceback; traceback.print_exc(); out[k] = None
    return out


def findings(res, items):
    """Карточки по срезам 03: паразитные адреса вместо «ловушек»; всплески, похожие на DDoS."""
    X = res.get('security') or {}
    P = X.get('паразиты')
    if P is not None and len(P):
        items[:] = [x for x in items if ':trap:' not in x['key']]
        hot = P[P['программы_доля'] >= 0.5]
        sev = 'Важно' if len(hot) else 'К сведению'
        top = (hot if len(hot) else P).head(5)
        items.append(dict(key='Нагрузка и безопасность:parasites:site', блок='Нагрузка и безопасность', важность=sev,
                          что_происходит=f'Паразитные адреса: у {len(P)} страниц тысячи вариантов адреса из-за параметров — ловушка для роботов',
                          факты='; '.join(f"{r['адрес']} — {r['вариантов']:,} вариантов, виновники: {r['виновники']}; ходят: {r['фигуранты']}".replace(',', ' ') for _, r in top.iterrows()),
                          где_править='robots.txt, rel=canonical, шаблоны ссылок', что_сделать='; '.join(sorted(set(top['меры']))),
                          главная_цифра=int(P['вариантов'].sum()), лист='Паразитные адреса', также_в='', статус=''))
    B = X.get('всплески')
    if B is not None and len(B):
        dd = B[B['картина'].str.startswith('распределённая')]
        if len(dd):
            items.append(dict(key='Нагрузка и безопасность:ddos_like:site', блок='Нагрузка и безопасность', важность='Важно',
                              что_происходит=f'Всплески нагрузки с многих IP сразу — похоже на DDoS ({len(dd)})',
                              факты='; '.join(f"{r['всплеск']}: {r['минут']} мин, {r['запросов']} запросов с {r['IP']} IP, последствия: {r['последствия']}" for _, r in dd.head(5).iterrows()),
                              где_править='хостинг / защита от DDoS', что_сделать='Проверить, сработала ли защита; включить ограничение частоты и фильтрацию на уровне хостинга',
                              главная_цифра=int(dd['запросов'].sum()), лист='Всплески нагрузки', также_в='', статус=''))
