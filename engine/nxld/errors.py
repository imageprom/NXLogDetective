"""NXLD: ошибки — срез реестра адресов (classify) по кодам ответа и реестра обращающихся (кто получил).

Одна компактная таблица «адрес × код» (только 4xx, 5xx и 499) с разбивкой по группам и по тому, откуда пришёл запрос.
Из неё строятся вкладки по кодам (404, 5xx, 403 и прочие 4xx, 499), сводка «Обзор» файла ошибок и журнал по дням.

Ошибка сайта (для сводки и карточек) — общий критерий: 4xx/5xx людям, своим или поисковикам на адрес, который сайт
должен обслуживать: не зонд и не конструкт посторонних. 499 — не ошибка, а «не дождались»: показывается отдельно.
Вкладки по кодам показывают всё, вместе со сканерами: зонды и конструкты посторонних там серыми строками."""
import numpy as np
import pandas as pd

WHO = ('Люди', 'Поисковики', 'Роботы', 'Боты', 'Свои')
ORIGIN = ('Со страниц сайта', 'Напрямую', 'С других сайтов')
FAMILIES = [('404', lambda k: k == 404), ('5xx', lambda k: k >= 500),
            ('403 и прочие 4xx', lambda k: (k >= 400) & (k < 500) & (k != 404) & (k != 499)), ('499', lambda k: k == 499)]


def who_of(c):
    """Кто получил ответ: люди, поисковики (подлинные), прочие роботы, боты, свои — индексы в WHO."""
    rg = np.asarray(c.rg)
    return np.select([c.human, c.search_ok, rg == 'Роботы', rg == 'Свои'], [0, 1, 2, 4], 3).astype(np.int8)


def origin_of(R):
    """Откуда запрос: со страниц сайта (реферер — сайт), напрямую (без реферера), с других сайтов."""
    internal = R['ref_internal'].values.astype(bool)
    host = R['ref_host'].astype(str).values
    return np.select([internal, (host == '') | (host == '-') | (host == 'nan')], [0, 1], 2).astype(np.int8)


def codes_table(c):
    """«Адрес × код» для всех ответов 4xx, 5xx и 499: запросы по группам и по источнику, IP, первый и последний день, пример источника."""
    R = c.R
    st = R['status'].values
    m = st >= 400
    if not m.any(): return pd.DataFrame()
    w, o = who_of(c)[m], origin_of(R)[m]
    X = pd.DataFrame({'b': R['base'].cat.codes.values[m], 'код': st[m], 'w': w, 'o': o, 'ip': R['ip'].cat.codes.values[m], 'ts': R['ts'].values[m]})
    key = ['b', 'код']
    g = X.groupby(key)
    T = g.agg(запросов=('w', 'size'), IP=('ip', 'nunique'), t0=('ts', 'min'), t1=('ts', 'max'))
    for i, nm in enumerate(WHO): T[nm] = (X['w'] == i).groupby([X['b'], X['код']]).sum()
    for i, nm in enumerate(ORIGIN): T[nm] = (X['o'] == i).groupby([X['b'], X['код']]).sum()
    # пример источника: страница сайта или чужой сайт, с которого пришли
    rp = R['ref_path'].astype(str).values[m]; rh = R['ref_host'].astype(str).values[m]
    src = np.where(o == 0, rp, np.where(o == 2, rh, ''))
    S_ = pd.DataFrame({'b': X['b'], 'код': X['код'], 's': src})
    S_ = S_[S_['s'] != '']
    if len(S_): T['источник'] = S_.groupby(key)['s'].agg(lambda s: s.value_counts().index[0])
    else: T['источник'] = ''
    T = T.reset_index()
    T['источник'] = T['источник'].fillna('')
    T['первый'] = pd.to_datetime(T['t0'], unit='s').dt.strftime('%Y-%m-%d')
    T['последний'] = pd.to_datetime(T['t1'], unit='s').dt.strftime('%Y-%m-%d')
    A = c.addr
    for col in ('адрес', 'форма', 'группа', 'существование', 'зонд', 'раздел'):
        T[col] = A[col].values[T['b'].values]
    return T.drop(columns=['t0', 't1'])


def by_family(T, family):
    """Вкладка по коду: строки по адресу, коды семейства — списком; сортировка: люди, затем все запросы."""
    if T is None or not len(T): return pd.DataFrame()
    f = dict(FAMILIES)[family]
    X = T[f(T['код'].values)]
    if not len(X): return pd.DataFrame()
    num = ['запросов', 'IP', *WHO, *ORIGIN]
    g = X.groupby('b')
    D = g[num].sum()
    D['IP'] = g['IP'].max()   # по разным кодам IP не складываются; оценка снизу
    D['коды'] = g.apply(lambda d: ', '.join(f"{k}: {n}" for k, n in zip(d['код'], d['запросов'])))
    for col in ('адрес', 'форма', 'группа', 'существование', 'зонд', 'раздел'): D[col] = g[col].first()
    D['источник'] = g['источник'].agg(lambda s: next((x for x in s if x), ''))
    D['первый'] = g['первый'].min(); D['последний'] = g['последний'].max()
    D['чужое'] = (D['зонд'] != '') | (D['форма'] == 'конструкт') & (D[['Люди', 'Свои']].sum(axis=1) == 0)
    return D.sort_values(['Люди', 'запросов'], ascending=False).reset_index(drop=True)


def site_errors(T):
    """Ошибки сайта по общему критерию: 4xx/5xx (кроме 499) людям, своим и поисковикам, на адреса сайта (не зонды, не конструкты посторонних)."""
    if T is None or not len(T): return pd.DataFrame()
    m = (T['код'] != 499) & (T['зонд'] == '') & (T['форма'] != 'конструкт') & ((T['Люди'] + T['Свои'] + T['Поисковики']) > 0)   # конструкты со страниц сайта — отдельным блоком «Битые адреса из скриптов»
    return T[m]


def journal(c):
    """Журнал ошибок по дням: 5xx и 4xx — по группам, 499 — у людей и поисковиков; плюс какая часть суток попала в лог."""
    from .blocks import day_span
    R = c.R
    st = R['status'].values
    w = who_of(c)
    day = R['day'].astype(str).values
    D = pd.DataFrame({'день': sorted(pd.unique(day))}).set_index('день')
    for lab, mk in (('5xx', st >= 500), ('4xx', (st >= 400) & (st < 500) & (st != 499))):
        for i, nm in enumerate(WHO):
            D[f'{lab}|{nm}'] = pd.Series(day[mk & (w == i)]).value_counts()
    for i, nm in ((0, 'Люди'), (1, 'Поисковики')):
        D[f'499 — не дождались|{nm}'] = pd.Series(day[(st == 499) & (w == i)]).value_counts()
    D = D.fillna(0).astype(int).join(day_span(R)).reset_index()
    tot = {'день': 'Итого', '_полный': True, '_с': '', '_по': ''}
    tot.update({k: int(D[k].sum()) for k in D.columns if '|' in k})
    return pd.concat([D, pd.DataFrame([tot])], ignore_index=True)


def summary(c, T):
    """Сводка для «Обзора» файла ошибок — из таблицы кодов и реестров, без своих условий."""
    st = c.R['status'].values
    w = who_of(c)
    rows = []
    for i, nm in enumerate(WHO):
        m = w == i
        n = int(m.sum())
        rows.append(dict(кто=nm, запросов=n, ок=int((m & (st < 400)).sum()), e4=int((m & (st >= 400) & (st < 500) & (st != 499)).sum()),
                         e5=int((m & (st >= 500)).sum()), n499=int((m & (st == 499)).sum())))
    E = site_errors(T)
    out = dict(коды=pd.DataFrame(rows))
    if len(E):
        Ep = E[E['форма'] == 'страница']   # разделы — уровень страниц; файлы — своим блоком
        pe = Ep.groupby('раздел')[['Люди', 'Поисковики', 'Свои', 'запросов']].sum()
        pe['адресов'] = Ep.groupby('раздел')['b'].nunique()
        out['разделы'] = pe.sort_values('Люди', ascending=False).reset_index()
        P = E[E['форма'] != 'файл']
        top = P.groupby('b').agg(адрес=('адрес', 'first'), Люди=('Люди', 'sum'), Поисковики=('Поисковики', 'sum'), коды=('код', lambda s: ', '.join(map(str, sorted(set(s))))),
                                 источник=('источник', 'first'), существование=('существование', 'first'))
        out['страницы'] = top.sort_values('Люди', ascending=False).head(10).reset_index(drop=True)
        Fi = E[E['форма'] == 'файл']
        if len(Fi):
            fg = Fi.groupby('группа').agg(файлов=('b', 'nunique'), Люди=('Люди', 'sum'), запросов=('запросов', 'sum'),
                                          примеры=('адрес', lambda s: list(pd.unique(s))[:2]))
            out['файлы'] = fg.sort_values('Люди', ascending=False).reset_index()
    return out


def build(c):
    T = codes_table(c)
    return dict(коды=T, журнал=journal(c), сводка=summary(c, T))
