"""NXLD: ошибки — срез реестра адресов (classify) по кодам ответа и реестра обращающихся (кто получил).

Одна компактная таблица «адрес × код» (только 4xx, 5xx и 499) с разбивкой по группам и по тому, откуда пришёл запрос.
Из неё строятся вкладки по кодам (404, 5xx, 403 и прочие 4xx, 499), сводка «Обзор» файла ошибок и журнал по дням.

Ошибка сайта (для сводки и карточек) — общий критерий: 4xx/5xx людям, своим или поисковикам на адрес, который сайт
должен обслуживать: не зонд и не конструкт посторонних. 499 — не ошибка, а «не дождались»: показывается отдельно.
Вкладки по кодам показывают всё, вместе со сканерами: зонды и конструкты посторонних там серыми строками."""
import numpy as np
import pandas as pd

WHO = ('Люди', 'Поисковики', 'Роботы', 'Мониторинг', 'Утилиты', 'Боты', 'Свои')
ORIGIN = ('Со страниц сайта', 'Напрямую', 'С других сайтов')
STATES = ('работает', 'переадресация', 'отказ', 'нет на сервере', 'ошибка сервера', 'ошибка сервера в сбое')   # состояние адреса за день
TYPE_LABEL = {'страница': 'страница', 'файл': 'файл', 'конструкт': 'битый адрес'}
AD_MARK = r'(?:^|&)(?:yclid|gclid|fbclid|utm_source|utm_medium|utm_campaign|_openstat)='
FAMILIES = [('404', lambda k: k == 404), ('5xx', lambda k: k >= 500),
            ('403 и прочие 4xx', lambda k: (k >= 400) & (k < 500) & (k != 404) & (k != 499)), ('499', lambda k: k == 499)]


def who_of(c):
    """Кто получил ответ: люди, поисковики (подлинные), прочие роботы, боты, свои — индексы в WHO."""
    rg = np.asarray(c.rg)
    return np.select([c.human, c.search_ok, rg == 'Роботы', rg == 'Системы мониторинга', rg == 'Утилиты', rg == 'Свои'], [0, 1, 2, 3, 4, 6], 5).astype(np.int8)


def origin_of(R):
    """Откуда запрос: со страниц сайта (реферер — сайт), напрямую (без реферера), с других сайтов."""
    internal = R['ref_internal'].values.astype(bool)
    host = R['ref_host'].astype(str).values
    return np.select([internal, (host == '') | (host == '-') | (host == 'nan')], [0, 1], 2).astype(np.int8)


def _state(st):
    """Код ответа → индекс состояния в STATES (499 — не состояние адреса: посетитель ушёл сам)."""
    return np.select([(st < 300) | (st == 304), st < 400, (st == 404) | (st == 410), st < 500], [0, 1, 3, 2], 4)   # 304 — «не изменился»: работает, отдано из кэша


def _fmt_day(d): return pd.Timestamp(d).strftime('%d.%m')


def recent_day(R):
    """С какого дня ошибка считается актуальной: последние 2 дня лога или последние 10% периода, что больше."""
    days_all = sorted(R['day'].astype(str).unique())
    return days_all[max(0, len(days_all) - max(2, int(round(len(days_all) * 0.1))))]


def outages(c, X):
    """Сбои с кодом по времени начала («27.09 22:22» — не меняется, сколько логов ни добавь) и числом запросов за время сбоя."""
    if X is None or not len(X): return pd.DataFrame()
    ts = c.R['ts'].values
    D = X.copy()
    t0 = pd.to_datetime(D['деградация_с'].fillna(D['начало'])) if 'деградация_с' in D else pd.to_datetime(D['начало'])
    t1 = pd.to_datetime(D['деградация_по'].fillna(D['конец'])) if 'деградация_по' in D else pd.to_datetime(D['конец'])
    D['сбой'] = pd.to_datetime(D['начало']).dt.strftime('%d.%m %H:%M')
    D['t0'] = t0.values.astype('datetime64[s]').astype('int64'); D['t1'] = t1.values.astype('datetime64[s]').astype('int64') + 59   # секунды эпохи, как R['ts']
    D['запросов'] = [int(((ts >= a) & (ts <= b)).sum()) for a, b in zip(D['t0'], D['t1'])]
    D['день'] = pd.to_datetime(D['начало']).dt.strftime('%Y-%m-%d')
    return D


def redirect_ends(c, codes):
    """Чем кончается переадресация: следующий запрос того же посетителя через несколько секунд — до 5 шагов.
    Возвращает {b: (код, куда, итоговый_код, шагов)} — самый частый исход для адреса."""
    R = c.R
    st = R['status'].values
    cc = R['base'].cat.codes.values
    RED_ = (st >= 300) & (st < 400) & (st != 304)
    red = np.where(np.isin(cc, np.asarray(list(codes))) & RED_)[0]
    if not len(red): return {}
    vid, ts = R['vid'].values, R['ts'].values
    cats_s = np.asarray(R['base'].cat.categories.astype(str))
    order = np.lexsort((ts, vid))
    pos = np.empty(len(order), dtype=np.int64); pos[order] = np.arange(len(order))
    cur = red.copy(); hops = np.zeros(len(red), int); alive = np.ones(len(red), bool)
    first_dst = np.full(len(red), -1)
    for step in range(5):
        p_ = pos[cur] + 1
        okp = alive & (p_ < len(order))
        nx = np.where(okp, order[np.minimum(p_, len(order) - 1)], -1)
        okn = okp & (nx >= 0)
        okn[okn] = (vid[nx[okn]] == vid[cur[okn]]) & (ts[nx[okn]] - ts[cur[okn]] <= 3)
        # следующий запрос — это переход по переадресации, только если адрес родственный: тот же раздел, со слэшем или без, главная;
        # иначе это просто следующий запрос (у сканеров — следующий зонд)
        if okn.any():
            i_ = np.where(okn)[0]
            src = cats_s[cc[cur[i_]]]; dst = cats_s[cc[nx[i_]]]
            sec = lambda a: a.str.extract(r'^(/[^/]*)')[0]
            rel = (sec(pd.Series(src)).values == sec(pd.Series(dst)).values) | (dst == '/') | (pd.Series(src).str.rstrip('/').values == pd.Series(dst).str.rstrip('/').values)
            okn[i_[~rel]] = False
        alive &= okn
        if step == 0: first_dst = np.where(okn, nx, -1)
        cur = np.where(okn, nx, cur); hops += okn
        if not (RED_[cur] & alive).any(): break
        alive &= RED_[cur]
    D = pd.DataFrame({'b': cc[red], 'код': st[red], 'куда': np.where(first_dst >= 0, cc[np.maximum(first_dst, 0)], -1),
                      'итог': np.where(hops > 0, st[cur], -1), 'шагов': hops})
    cats = R['base'].cat.categories.astype(str)
    out = {}
    for b_, g in D.groupby('b'):
        top = g.groupby(['код', 'куда', 'итог']).size().sort_values(ascending=False).reset_index().iloc[0]
        out[int(b_)] = (int(top['код']), cats[int(top['куда'])] if top['куда'] >= 0 else '', int(top['итог']), int(g['шагов'].max()))
    return out


def _redirect_text(info):
    code, dst, fin, hops = info
    if fin < 0 or not dst: return f'переадресация {code}, куда — по логу не видно'
    end = 'работает' if fin < 300 or fin == 304 else ('нет на сервере' if fin in (404, 410) else ('ошибка сервера' if fin >= 500 else ('цепочка переадресаций' if fin < 400 else f'отказ {fin}')))
    return f'переадресация {code} → {dst} ({end})' + (f', шагов: {hops}' if hops >= 3 else '')


def history(c, codes, OUT=None):
    """Статус адреса по дням и «сейчас». Состояние дня — преобладающий ответ людям, своим и поисковикам (если их не было — всем);
    переадресация оценивается по концу цепочки: привела на живую страницу — работает. 499 не считается.
    Актуально — адрес не работает сейчас и запрашивался в последние дни лога (2 дня или 10% периода, что больше)."""
    R = c.R
    cc = R['base'].cat.codes.values
    m = np.isin(cc, np.asarray(list(codes))) & (R['status'].values != 499)
    if not m.any(): return {}
    RD = redirect_ends(c, codes)
    w = who_of(c)[m]
    st_m = R['status'].values[m]
    s_ = _state(st_m)
    bm = cc[m]
    # переадресация с известным концом — состояние конца цепочки
    fin = np.array([RD.get(int(b_), (0, '', -1, 0))[2] for b_ in bm]) if RD else np.full(len(bm), -1)
    rr = (s_ == 1) & (fin >= 0)
    s_[rr] = _state(np.maximum(fin[rr], 200))
    s_[rr & (fin >= 300) & (fin < 400)] = 1
    # 5xx во время сбоя — не поломка страницы, а сбой сервера: состояние «ошибка сервера в сбое …»
    oid = np.array([''] * len(s_), dtype=object)
    if OUT is not None and len(OUT):
        tm = R['ts'].values[m]
        for _, o in OUT.iterrows():
            inn = (s_ == 4) & (tm >= o['t0']) & (tm <= o['t1'])
            s_[inn] = 5; oid[inn] = o['сбой']
    X = pd.DataFrame({'b': bm, 'd': R['day'].astype(str).values[m], 's': s_, 'own': np.isin(w, (0, 1, 6)), 'o': oid})
    OID = X[X['o'] != ''].groupby(['b', 'd'])['o'].agg(lambda v: v.value_counts().index[0]).to_dict()
    has_own = X.groupby('b')['own'].transform('any')
    X = X[X['own'] | ~has_own]
    days_all = sorted(R['day'].astype(str).unique())
    span = max(2, int(round(len(days_all) * 0.1)))
    recent_from = days_all[max(0, len(days_all) - span)]
    N = X.groupby(['b', 'd', 's']).size().reset_index(name='n').sort_values(['b', 'd', 'n'], ascending=[True, True, False])
    top = N.drop_duplicates(['b', 'd'])
    out = {}
    for b, g in top.groupby('b', sort=False):
        runs = []
        for d, st_ in zip(g['d'], g['s']):
            if runs and runs[-1][0] == st_: runs[-1][2] = d
            else: runs.append([st_, d, d])
        def nm_of(st_, a, z):   # «ошибка сервера в сбое 27.09 22:22» — по коду сбоя
            return f"ошибка сервера в сбое {OID.get((b, a), '')}".strip() if st_ == 5 else STATES[st_]
        names = [nm_of(*r) for r in runs]
        if len(runs) == 1:
            txt = names[0] if runs[0][0] == 5 else (f'{names[0]} весь период' if runs[0][1] <= days_all[min(1, len(days_all) - 1)] else f'{names[0]} с {_fmt_day(runs[0][1])}')
        else:
            parts = []
            for i, (st_, a, z) in enumerate(runs):
                nm = nm_of(st_, a, z)
                if i == 0:
                    parts.append(nm if st_ in (0, 5) else (f'{nm} с первого дня' if a <= days_all[min(1, len(days_all) - 1)] else f'{nm} с {_fmt_day(a)}'))
                elif i == len(runs) - 1:
                    parts.append(('снова работает' if st_ == 0 else nm) + f' с {_fmt_day(a)}')
                else:
                    parts.append(nm if st_ == 5 else (f"{nm} {_fmt_day(a)}" if a == z else f"{nm} {_fmt_day(a)}–{_fmt_day(z)}"))
            txt = ' → '.join(parts)
        last = runs[-1]
        recent = last[2] >= recent_from
        ill = any(r[0] in (2, 3, 4, 5) for r in runs)
        now = nm_of(*last)
        if int(b) in RD and last[0] in (0, 1): now = _redirect_text(RD[int(b)])
        elif last[0] == 0 and ill: now = 'работает'
        if not recent: now += f' (последний запрос {_fmt_day(last[2])})'
        out[int(b)] = dict(статус=txt, сейчас=now, итог=STATES[last[0]], менялся=len(runs) > 1, работал=any(r[0] == 0 for r in runs),
                           болел=ill, актуально=bool(recent and last[0] in (2, 3, 4, 5)))
    return out


def criticality(T, Sr, human_visits):
    """Почему ошибка важна: реклама ведёт, ссылка с сайта, 5xx у людей, поисковики получают 5xx, массово (доля от визитов людей).
    Возвращает {b: «реклама · ссылка с сайта»}; пусто — не критично."""
    if T is None or not len(T): return {}
    E = T[T['код'] != 499]
    mass = max(10, 0.001 * human_visits)   # порог «много людей» — 0,1% визитов людей
    why = {}
    g = E.groupby('b')
    p5 = E[E['код'] >= 500].groupby('b')[['Люди', 'Поисковики']].sum()
    people = g['Люди'].sum()
    kinds = Sr[Sr['код'] != 499].groupby(['b', 'вид'])['n'].sum().unstack(fill_value=0) if Sr is not None and len(Sr) else pd.DataFrame()
    for b in people.index:
        r = []
        if len(kinds) and b in kinds.index and kinds.loc[b].get('реклама', 0) > 0: r.append('реклама ведёт сюда')
        if len(kinds) and b in kinds.index and kinds.loc[b].get('страницы сайта', 0) > 0: r.append('ссылка с сайта')
        if b in p5.index and p5.at[b, 'Люди'] > 0: r.append('5xx у людей')
        if b in p5.index and p5.at[b, 'Поисковики'] > 0: r.append('поисковики получают 5xx')
        if people[b] >= mass: r.append('массово')
        if r: why[int(b)] = ' · '.join(r)
    return why


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
    self_ = R['ref_path'].astype(str).values[m] == R['base'].astype(str).values[m]   # обновил ту же страницу — не источник
    kind = np.select([ad, (o == 0) & ~self_, (o == 2) & se, o == 2], ['реклама', 'страницы сайта', 'поиск', 'сайты'], 'напрямую')
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
    for col in ('адрес', 'форма', 'группа', 'существование', 'зонд', 'раздел', 'статус', 'итог', 'тип', 'сейчас', 'актуально', 'болел', 'почему', 'критично'):
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


ERRLOG_MEANING = {
    'Бэкенд: таймаут': ('PHP не успел ответить, сервер отдал посетителю 504', False),
    'Бэкенд: не отвечает': ('PHP-FPM упал или перегружен, сервер отдал 502', False),
    'База данных': ('сайт не смог обратиться к базе данных', False),
    'PHP Fatal': ('скрипт сайта упал с фатальной ошибкой — страница не отдалась', False),
    'PHP Warning': ('предупреждение в коде сайта: страница отдалась, но код с ошибкой', False),
    'PHP Notice/Deprecated': ('замечания к коду: устаревшие функции, неаккуратный код', False),
    'Слишком большой запрос (413)': ('отправили файл или форму больше разрешённого размера', False),
    'Ограничение частоты': ('сервер притормозил слишком частые запросы — работает защита', True),
    'Запрещено правилом': ('сервер закрыл доступ по своим правилам — работает защита', True),
    'Файл не найден': ('запрошенного файла нет на диске', False),
    'Права доступа': ('серверу не хватает прав прочитать файл', False),
    'Нет места на диске': ('на сервере закончилось место', False),
    'Мало соединений': ('серверу не хватило соединений под нагрузку', False),
    'SSL': ('ошибка защищённого соединения', False),
    'Буферизация ответа (норма)': ('большой ответ записан во временный файл — норма', True),
    'Прочее': ('прочие сообщения', False)}


def broken_links(c, internal=True):
    """Битые ссылки по шаблонам: внутренние — «где стоит ссылка → куда ведёт» (страница сайта → несуществующая страница);
    внешние — «откуда пришли → куда»: реклама, поиск, другие сайты. Зонды не в счёт, только страницы."""
    R, A = c.R, c.addr
    st = R['status'].values
    cc = R['base'].cat.codes.values
    page = (A['форма'].values == 'страница')[cc] & (A['зонд'].values == '')[cc]
    bad = page & (((st >= 400) & (st < 500) & (st != 499)) | (st >= 500))
    o = origin_of(R)
    qc = R['query'].cat.categories.to_series()
    ad = qc.str.contains(AD_MARK, regex=True).values[R['query'].cat.codes.values]
    rp = R['ref_path'].astype(str).values
    m = bad & (o == 0) & (rp != R['base'].astype(str).values) if internal else bad & ((o == 2) | ad)
    if not m.any(): return pd.DataFrame()
    w = who_of(c)[m]
    tpl = R['tpl'].astype(str).values
    if internal:
        tpl_of = pd.Series(tpl, index=R['base'].astype(str).values)
        tpl_of = tpl_of[~tpl_of.index.duplicated()]
        src = pd.Series(rp[m]).map(tpl_of).fillna(pd.Series(rp[m])).values
        X = pd.DataFrame({'откуда': src, 'страница': rp[m]})
    else:
        from .visits import SEARCH
        host = R['ref_host'].astype(str).str.split(',').str[0].str.strip().values[m]
        kind = np.where(ad[m], 'реклама', np.where(pd.Series(host).str.contains(SEARCH, regex=True).values, 'поиск', 'сайты'))
        X = pd.DataFrame({'вид': kind, 'откуда': np.where(np.isin(host, ['', '-', 'nan']), 'без реферера', host), 'страница': host})
    X['куда'] = tpl[m]; X['адрес'] = R['base'].astype(str).values[m]; X['vid'] = R['vid'].values[m]
    X['люди'] = w == 0; X['поисковики'] = w == 1; X['ip'] = R['ip'].astype(str).values[m]; X['код'] = st[m]; X['day'] = R['day'].astype(str).values[m]
    keys = ['откуда', 'куда'] if internal else ['вид', 'откуда', 'куда']
    g = X.groupby(keys)
    D = g.agg(переходов=('vid', 'size'), визитов=('vid', 'nunique'), людей=('люди', 'sum'), поисковиков=('поисковики', 'sum'),
              страниц=('страница', 'nunique'), адресов=('адрес', 'nunique'), коды=('код', lambda s: ', '.join(f"{k}: {v}" for k, v in s.value_counts().items())),
              первый=('day', 'min'), последний=('day', 'max'))
    D['актуально'] = D['последний'] >= recent_day(R)
    return D.sort_values(['людей', 'переходов'], ascending=False).reset_index()


def broken(T, Sr=None):
    """«Нерабочие адреса»: все адреса сайта, на которых люди, свои или поисковики получали ошибку, — с историей статуса.
    И трупы (не работали весь период), и тяжёлые (ошибка сервера с первого дня), и те, что починились."""
    E = site_errors(T)
    if not len(E) or 'форма' not in E: return pd.DataFrame()   # ошибок нет — нет данных (у пустого реестра нет и колонок)
    E = E[E['форма'] == 'страница']   # «Пострадавшие страницы»: только страницы, файлы — своим листом
    if not len(E): return pd.DataFrame()
    g = E.groupby('b')
    D = g[['Люди', 'Поисковики', 'Свои', 'запросов']].sum()
    D['коды'] = g.apply(lambda d: ', '.join(f"{k}: {n}" for k, n in d.groupby('код')['запросов'].sum().items()))
    for col in ('адрес', 'тип', 'группа', 'раздел', 'статус', 'итог', 'менялся', 'сейчас', 'актуально', 'болел', 'почему', 'критично'): D[col] = g[col].first()
    D['первый'] = g['первый'].min(); D['последний'] = g['последний'].max()
    if Sr is not None and len(Sr):
        Sx = Sr[Sr['b'].isin(D.index) & (Sr['код'] != 499)]
        tx = {b: sources_text(gb) for b, gb in Sx.groupby('b')}
        D['источники'] = [tx.get(b, '') for b in D.index]
    D['починился'] = ~D['актуально']
    return D.sort_values(['критично', 'актуально', 'Люди', 'запросов'], ascending=[False, False, False, False]).reset_index(drop=True)


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
                                 источник=('источник', 'first'), статус=('статус', 'first'), сейчас=('сейчас', 'first'), почему=('почему', 'first'),
                                 критично=('критично', 'first'), актуально=('актуально', 'first'), запросов=('запросов', 'sum'))
        top = top[top['критично']].sort_values('запросов', ascending=False).head(10) if top['критично'].any() else top.sort_values('запросов', ascending=False).head(10)
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


TIMEOUT_RX = r'timed out|upstream prematurely closed|no live upstreams|Connection reset by peer|Resource temporarily unavailable'


def slowness(c):
    """Признаки торможения по часам: доля обрывов 499 у людей, ошибки шлюза 502 и 504, таймауты в error-логе;
    если в логе есть время ответа ($request_time) — медиана по часам. Таблицы «день × час»."""
    R = c.R
    day, hr, st = R['day'].astype(str).values, R['hour'].values.astype(int), R['status'].values
    hum = c.human
    X = pd.DataFrame({'d': day[hum], 'h': hr[hum], 'w': st[hum] == 499})
    g = X.groupby(['d', 'h'])
    n, w = g.size(), g['w'].sum()
    share = (w / n.clip(lower=1) * 100).where(n >= 50)   # мало запросов — доля ничего не значит
    out = {'499': share.unstack().reindex(columns=range(24)).round(1),
           '_499_n': n.unstack().reindex(columns=range(24)).fillna(0)}
    gw = np.isin(st, (502, 504))
    out['шлюз'] = pd.DataFrame({'d': day[gw], 'h': hr[gw]}).groupby(['d', 'h']).size().unstack(fill_value=0).reindex(index=sorted(set(day)), columns=range(24), fill_value=0)
    E = c.E
    if E is not None and len(E) and 'msg' in E:
        m = E['msg'].astype(str).str.contains(TIMEOUT_RX, regex=True, case=False).values
        t = pd.to_datetime(E['ts'].values[m].astype('int64'), unit='s')
        out['таймауты'] = pd.DataFrame({'d': t.strftime('%Y-%m-%d'), 'h': t.hour}).groupby(['d', 'h']).size().unstack(fill_value=0).reindex(index=sorted(set(day)), columns=range(24), fill_value=0)
    if 'rt' in R:
        Y = pd.DataFrame({'d': day[hum], 'h': hr[hum], 'rt': R['rt'].values[hum]})
        out['время'] = Y.groupby(['d', 'h'])['rt'].median().unstack().reindex(columns=range(24)).round(2)
    S_ = share.dropna().sort_values(ascending=False)
    out['_худшие'] = [(d, h, float(v)) for (d, h), v in S_.head(3).items()]
    out['_обычно'] = float(w.sum() / max(1, n.sum()) * 100)
    return out


def build(c, outage_rows=None):
    T = codes_table(c)
    OUT = outages(c, outage_rows)
    H = history(c, set(T['b']), OUT) if len(T) else {}
    if len(T):
        for k_ in ('сейчас', 'актуально', 'болел'):
            T[k_] = T['b'].map(lambda b: H.get(int(b), {}).get(k_, '' if k_ == 'сейчас' else False))
        T['статус'] = T['b'].map(lambda b: H.get(int(b), {}).get('статус', ''))
        T['итог'] = T['b'].map(lambda b: H.get(int(b), {}).get('итог', ''))
        T['менялся'] = T['b'].map(lambda b: H.get(int(b), {}).get('менялся', False))
        T['тип'] = T['форма'].map(TYPE_LABEL).fillna(T['форма'])
    Sr = sources(c, c.R['status'].values >= 400) if len(T) else pd.DataFrame()
    if len(T):
        WHY = criticality(T, Sr, int((c.V['group'] == 'Люди').sum()))
        T['почему'] = T['b'].map(lambda b: WHY.get(int(b), ''))
        T['критично'] = T['актуально'] & (T['почему'] != '') & (T['зонд'] == '')
    return dict(с_дня=recent_day(c.R), сбои=OUT, торможение=slowness(c), коды=T, источники=Sr, журнал=journal(c), сводка=summary(c, T, Sr), нерабочие=broken(T, Sr),
                битые_внутренние=broken_links(c, True), битые_внешние=broken_links(c, False))
