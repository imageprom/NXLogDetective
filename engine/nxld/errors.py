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
STATES = ('работает', 'переадресация', 'отказ', 'нет на сервере', 'ошибка сервера')   # состояние адреса за день
TYPE_LABEL = {'страница': 'страница', 'файл': 'файл', 'конструкт': 'битый адрес'}
AD_MARK = r'(?:^|&)(?:yclid|gclid|fbclid|utm_source|utm_medium|utm_campaign|_openstat)='
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


def _state(st):
    """Код ответа → индекс состояния в STATES (499 — не состояние адреса: посетитель ушёл сам)."""
    return np.select([st < 300, st < 400, (st == 404) | (st == 410), st < 500], [0, 1, 3, 2], 4)


def _fmt_day(d): return pd.Timestamp(d).strftime('%d.%m')


def history(c, codes):
    """Статус адреса как история по дням: «работает → ошибка сервера с 24.09 → нет на сервере с 26.09», «нет на сервере весь период».
    Состояние дня — преобладающий ответ людям, своим и поисковикам; если их не было — всем. 499 не считается."""
    R = c.R
    cc = R['base'].cat.codes.values
    m = np.isin(cc, np.asarray(list(codes))) & (R['status'].values != 499)
    if not m.any(): return {}
    w = who_of(c)[m]
    X = pd.DataFrame({'b': cc[m], 'd': R['day'].astype(str).values[m], 's': _state(R['status'].values[m]), 'own': np.isin(w, (0, 1, 4))})
    has_own = X.groupby('b')['own'].transform('any')
    X = X[X['own'] | ~has_own]
    days_all = sorted(R['day'].astype(str).unique())
    d0, d1 = days_all[0], days_all[-1]
    N = X.groupby(['b', 'd', 's']).size().reset_index(name='n').sort_values(['b', 'd', 'n'], ascending=[True, True, False])
    top = N.drop_duplicates(['b', 'd'])
    out = {}
    for b, g in top.groupby('b', sort=False):
        runs = []
        for d, st_ in zip(g['d'], g['s']):
            if runs and runs[-1][0] == st_: runs[-1][2] = d
            else: runs.append([st_, d, d])
        names = [STATES[r[0]] for r in runs]
        if len(runs) == 1:
            txt = f'{names[0]} весь период' if runs[0][1] <= days_all[min(1, len(days_all) - 1)] else f'{names[0]} с {_fmt_day(runs[0][1])}'
        else:
            parts = []
            for i, (st_, a, z) in enumerate(runs):
                nm = STATES[st_]
                if i == 0:
                    parts.append(nm if st_ == 0 else (f'{nm} с первого дня' if a <= days_all[min(1, len(days_all) - 1)] else f'{nm} с {_fmt_day(a)}'))
                elif i == len(runs) - 1:
                    parts.append(('снова работает' if st_ == 0 else nm) + f' с {_fmt_day(a)}')
                else:
                    parts.append(f"{nm} {_fmt_day(a)}" if a == z else f"{nm} {_fmt_day(a)}–{_fmt_day(z)}")
            txt = ' → '.join(parts)
        out[int(b)] = dict(статус=txt, итог=STATES[runs[-1][0]], менялся=len(runs) > 1, работал=any(r[0] == 0 for r in runs))
    return out


def sources(c, m):
    """Откуда пришли запросы с ошибкой — сводкой по видам: страницы сайта (по шаблонам), реклама, поиск, сайты, напрямую.
    Возвращает длинную таблицу b, код, вид, деталь, n — её сворачивает by_family."""
    from .visits import SEARCH
    R = c.R
    st = R['status'].values[m]
    o = origin_of(R)[m]
    host = R['ref_host'].astype(str).str.split(',').str[0].str.strip().values[m]
    qc = R['query'].cat.categories.to_series()
    ad = qc.str.contains(AD_MARK, regex=True).values[R['query'].cat.codes.values[m]]
    se = pd.Series(host).str.contains(SEARCH, regex=True).values
    kind = np.select([ad, o == 0, (o == 2) & se, o == 2], ['реклама', 'страницы сайта', 'поиск', 'сайты'], 'напрямую')
    # страницы сайта — по шаблону страницы-источника (тот же шаблон, что у «Типов страниц»)
    tpl_of = pd.Series(R['tpl'].astype(str).values, index=R['base'].astype(str).values)
    tpl_of = tpl_of[~tpl_of.index.duplicated()]
    rp = R['ref_path'].astype(str).values[m]
    det = np.where(kind == 'страницы сайта', pd.Series(rp).map(tpl_of).fillna(pd.Series(rp)).values, np.where(np.isin(kind, ['поиск', 'сайты']), host, ''))
    X = pd.DataFrame({'b': R['base'].cat.codes.values[m], 'код': st, 'вид': kind, 'деталь': det})
    return X.groupby(['b', 'код', 'вид', 'деталь']).size().reset_index(name='n')


SRC_ORDER = ('страницы сайта', 'реклама', 'поиск', 'сайты', 'напрямую')


def sources_text(S_b):
    """«страницы сайта: 120 (/projects/*/flat/, /action/*) · реклама: 40 · поиск: 12 (yandex.ru) · напрямую: 5»."""
    parts = []
    for k in SRC_ORDER:
        g = S_b[S_b['вид'] == k]
        if not len(g): continue
        n = int(g['n'].sum())
        det = g[g['деталь'] != ''].groupby('деталь')['n'].sum().sort_values(ascending=False)
        tail = f" ({', '.join(det.index[:2])}{' и др.' if len(det) > 2 else ''})" if len(det) else ''
        parts.append(f'{k}: {n}{tail}')
    return ' · '.join(parts)


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


def by_family(T, family, Sr=None):
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
    for col in ('адрес', 'форма', 'группа', 'существование', 'зонд', 'раздел', 'статус', 'итог', 'тип'):
        if col in X: D[col] = g[col].first()
    D['источник'] = g['источник'].agg(lambda s: next((x for x in s if x), ''))
    if Sr is not None and len(Sr):
        Sx = Sr[f(Sr['код'].values) & Sr['b'].isin(D.index)]
        txt = {b: sources_text(gb) for b, gb in Sx.groupby('b')}
        D['источники'] = [txt.get(b, '') for b in D.index]
    D['первый'] = g['первый'].min(); D['последний'] = g['последний'].max()
    D['чужое'] = (D['зонд'] != '') | (D['форма'] == 'конструкт') & (D[['Люди', 'Свои']].sum(axis=1) == 0)
    return D.sort_values(['Люди', 'запросов'], ascending=False).reset_index(drop=True)


def site_errors(T):
    """Ошибки сайта по общему критерию: 4xx/5xx (кроме 499) людям, своим и поисковикам, на адреса сайта (не зонды, не конструкты посторонних)."""
    if T is None or not len(T): return pd.DataFrame()
    m = (T['код'] != 499) & (T['зонд'] == '') & (T['форма'] != 'конструкт') & ((T['Люди'] + T['Свои'] + T['Поисковики']) > 0)   # конструкты со страниц сайта — отдельным блоком «Битые адреса из скриптов»
    return T[m]


def broken(T, Sr=None):
    """«Нерабочие адреса»: все адреса сайта, на которых люди, свои или поисковики получали ошибку, — с историей статуса.
    И трупы (не работали весь период), и тяжёлые (ошибка сервера с первого дня), и те, что починились."""
    E = site_errors(T)
    if not len(E): return pd.DataFrame()
    g = E.groupby('b')
    D = g[['Люди', 'Поисковики', 'Свои', 'запросов']].sum()
    D['коды'] = g.apply(lambda d: ', '.join(f"{k}: {n}" for k, n in d.groupby('код')['запросов'].sum().items()))
    for col in ('адрес', 'тип', 'группа', 'раздел', 'статус', 'итог', 'менялся'): D[col] = g[col].first()
    D['первый'] = g['первый'].min(); D['последний'] = g['последний'].max()
    if Sr is not None and len(Sr):
        Sx = Sr[Sr['b'].isin(D.index) & (Sr['код'] != 499)]
        tx = {b: sources_text(gb) for b, gb in Sx.groupby('b')}
        D['источники'] = [tx.get(b, '') for b in D.index]
    D['починился'] = D['итог'] == 'работает'
    return D.sort_values(['починился', 'Люди', 'запросов'], ascending=[True, False, False]).reset_index(drop=True)


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


def summary(c, T, Sr=None):
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
                                 источник=('источник', 'first'), статус=('статус', 'first'))
        top = top.sort_values('Люди', ascending=False).head(10)
        if Sr is not None and len(Sr):
            Sx = Sr[Sr['b'].isin(top.index) & (Sr['код'] != 499)]
            tx = {b: sources_text(g) for b, g in Sx.groupby('b')}
            top['источник'] = [tx.get(b, '') for b in top.index]
        out['страницы'] = top.reset_index(drop=True)
        Fi = E[E['форма'] == 'файл']
        if len(Fi):
            fg = Fi.groupby('группа').agg(файлов=('b', 'nunique'), Люди=('Люди', 'sum'), запросов=('запросов', 'sum'),
                                          примеры=('адрес', lambda s: list(pd.unique(s))[:2]))
            out['файлы'] = fg.sort_values('Люди', ascending=False).reset_index()
    return out


def build(c):
    T = codes_table(c)
    H = history(c, set(T['b'])) if len(T) else {}
    if len(T):
        T['статус'] = T['b'].map(lambda b: H.get(int(b), {}).get('статус', ''))
        T['итог'] = T['b'].map(lambda b: H.get(int(b), {}).get('итог', ''))
        T['менялся'] = T['b'].map(lambda b: H.get(int(b), {}).get('менялся', False))
        T['тип'] = T['форма'].map(TYPE_LABEL).fillna(T['форма'])
    Sr = sources(c, c.R['status'].values >= 400) if len(T) else pd.DataFrame()
    return dict(коды=T, источники=Sr, журнал=journal(c), сводка=summary(c, T, Sr), нерабочие=broken(T, Sr))
