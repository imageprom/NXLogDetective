"""NXLD: данные файла 05 «Маркетинг» сверх листов блока (blocks.marketing).

Одна метрика визитов на все срезы (metrics), журнал по дням, конверсии по времени (день недели × час),
качество каналов и заявок, рекламные срезы с ботами и кликами впустую, вердикт площадкам.
Оформление (report_marketing) только рисует; те же цифры берут выжимка для Redmine и снимок."""
import numpy as np, pandas as pd

AD_DIMS = (('кампания', 'Кампании'), ('фраза', 'Фразы'), ('source', 'Площадки'), ('aid', 'Объявления'), ('region', 'Регионы'), ('device', 'Устройства (метка)'))


_REG = None


def regions():
    """Справочник регионов Яндекса (data/reference/regions_yandex.json): код → название, родитель, уровень."""
    global _REG
    if _REG is None:
        import json, os
        p = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference', 'regions_yandex.json')
        try: _REG = json.load(open(p, encoding='utf-8')).get('регионы', {})
        except Exception: _REG = {}
    return _REG


def region_of(code):
    """Код региона из рекламной метки → (название, область). Неизвестный код — (None, None): на листе остаётся кодом."""
    R = regions()
    x = R.get(str(code).strip())
    if not x: return None, None
    area, cur, seen = None, x, set()
    while cur is not None and id(cur) not in seen:   # область — ближайший предок второго уровня (субъект РФ, область страны)
        seen.add(id(cur))
        if cur.get('уровень') == 2: area = cur['название']; break
        cur = R.get(str(cur.get('родитель'))) if cur.get('родитель') else None
    return x['название'], (area if area != x['название'] else None)


PHRASE = {'---autotargeting': 'автотаргетинг', '': '(фраза не передана)'}


def phrase_label(v):
    """Фраза из метки utm_term: «---autotargeting» — автотаргетинг Директа, пустая — фраза не передана."""
    v = '' if v is None or str(v) == 'nan' else str(v).strip()
    if v.lower().startswith('---autotargeting'): return 'автотаргетинг'   # бывает с хвостом «|20559»
    if v.startswith('{') and v.endswith('}'): return '(макрос не подставлен)'   # {keyword} — шаблон отслеживания не сработал
    return PHRASE.get(v.lower(), v)


def label_ads(S, B):
    """Подписи рекламных срезов — в движке: фразы по-человечески, регионы — названием и областью по справочнику."""
    for T in (S.get('Реклама: Фразы'), (B or {}).get('Фразы')):
        if T is not None and len(T) and 'фраза' in T: T['фраза'] = T['фраза'].map(phrase_label)
    P = S.get('Реклама: Фразы')   # разные метки с одной подписью («---autotargeting» и «---autotargeting|20559») — одной строкой
    if P is not None and len(P) and P['фраза'].duplicated().any():
        w = P['визитов'].clip(lower=0)
        agg = P.assign(**{f'_{c}': P[c] * w for c in ('страниц_на_визит', 'мгновенный_уход_%', 'смотрели_каталог_%') if c in P}).groupby('фраза', as_index=False).sum(numeric_only=True)
        for c in ('страниц_на_визит', 'мгновенный_уход_%', 'смотрели_каталог_%'):
            if f'_{c}' in agg: agg[c] = (agg[f'_{c}'] / agg['визитов'].clip(lower=1)).round(2 if c == 'страниц_на_визит' else 1)
        agg['конверсия_%'] = (agg['принято'] / agg['визитов'].clip(lower=1) * 100).round(3)
        S['Реклама: Фразы'] = agg[[c for c in P.columns if c in agg]].sort_values('визитов', ascending=False)
    Bp = (B or {}).get('Фразы')
    if Bp is not None and len(Bp) and Bp['фраза'].duplicated().any():
        g = Bp.groupby('фраза', as_index=False).sum(numeric_only=True)
        g['доля_ботов_%'] = (g['ботов'] / g['визитов_всех'].clip(lower=1) * 100).round(1)
        B['Фразы'] = g
    for T in (S.get('Реклама: Регионы'), (B or {}).get('Регионы')):
        if T is not None and len(T) and 'region' in T:
            rr = [region_of(c) for c in T['region']]
            T['регион'] = [a or '' for a, _ in rr]; T['область'] = [b or '' for _, b in rr]



def ad_tops(S, B):
    """Сводки для Обзора 05: фразы по кликам (10), фразы с заявками (5), регионы по кликам (5) — клики всех, люди, впустую, заявки."""
    out = {}
    for name, col, key in (('Фразы', 'фраза', 'фразы'), ('Регионы', 'region', 'регионы')):
        Bt, P = (B or {}).get(name), S.get(f'Реклама: {name}')
        if Bt is None or P is None or not len(Bt): continue
        M = Bt.merge(P[[col, 'визитов', 'принято']], on=col, how='left').fillna({'визитов': 0, 'принято': 0})
        M['конверсия_%'] = (M['принято'] / M['визитов'].clip(lower=1) * 100).round(2)
        M = M.sort_values('визитов_всех', ascending=False)
        if key == 'фразы':
            out['фразы_топ'] = M.head(10).reset_index(drop=True)
            out['фразы_с_заявками'] = M[M['принято'] > 0].sort_values(['принято', 'визитов_всех'], ascending=False).head(5).reset_index(drop=True)
        else:
            out['регионы_топ'] = M.head(5).reset_index(drop=True)
    return out


def metrics(df):
    """Метрика визитов людей — одна на все срезы 05 (каналы, реклама, аудитория, страницы входа)."""
    return pd.Series({'визитов': len(df), 'IP': df['ip'].nunique(), 'страниц_на_визит': round(df['n_pages'].mean(), 2) if len(df) else 0,
                      'мгновенный_уход_%': round(((df['n_pages'] <= 1) & (df['dur'] < 10)).mean() * 100, 1) if len(df) else 0,
                      'смотрели_каталог_%': round((df['n_catalog'] > 0).mean() * 100, 1) if len(df) else 0,
                      'отправок': int(df['n_goal'].sum()), 'принято': int(df['n_conv'].sum()), 'конверсия_%': round(df['n_conv'].sum() / max(1, len(df)) * 100, 3)})


def _wasted(df):
    """Клик впустую: бот по рекламной ссылке или человек, попавший на посадочную с ошибкой (кроме 499 — это скорость, не битая страница)."""
    return (df['group'] == 'Боты') | ((df['group'] == 'Люди') & (df['entry_status'] >= 400) & (df['entry_status'] != 499))


def ad_visits(V):
    """Все визиты по рекламным ссылкам (люди, боты, роботы проверки объявлений) с разобранными метками."""
    from .blocks import parse_ad
    A = V[V['channel'].astype(str) == 'Реклама'].copy()
    if not len(A): return A
    pa = pd.DataFrame([parse_ad(q) for q in A['entry_query']], index=A.index)
    return A.join(pa[[c for c in pa.columns if c not in A.columns]])


def ad_bots(A):
    """По каждому срезу рекламы: визиты всех, ботов, доля ботов, ошибки посадочной у людей, клики впустую."""
    out = {}
    if not len(A): return out
    A = A.assign(_бот=(A['group'] == 'Боты').astype(int), _робот=(A['group'] == 'Роботы').astype(int),
                 _ошибка=((A['group'] == 'Люди') & (A['entry_status'] >= 400) & (A['entry_status'] != 499)).astype(int), _впустую=_wasted(A).astype(int),
                 _бот_принято=np.where(A['group'] == 'Боты', A['n_conv'], 0))
    for col, name in AD_DIMS:
        if col not in A: continue
        g = A.groupby(col).agg(визитов_всех=('ip', 'size'), ботов=('_бот', 'sum'), роботов=('_робот', 'sum'), ошибок_посадочной=('_ошибка', 'sum'),
                               впустую=('_впустую', 'sum'), заявок_ботов=('_бот_принято', 'sum'))
        g['доля_ботов_%'] = (g['ботов'] / g['визитов_всех'].clip(lower=1) * 100).round(1)
        out[name] = g.reset_index()
    return out


def verdict(r):
    """Вердикт площадке: что делать с ней в рекламном кабинете."""
    v, p, b = int(r.get('визитов', 0) or 0), int(r.get('принято', 0) or 0), float(r.get('доля_ботов_%', 0) or 0)
    if str(r.get('source', '')).lower() == 'none': return 'поиск — не площадка'
    if b >= 50 and v + int(r.get('ботов', 0) or 0) >= 20: return 'отключить: в основном боты'
    if v >= 30 and p == 0: return 'отключить: трафик без заявок'
    if p > 0: return 'работает'
    return 'мало данных'


def heat_week(df, val=None):
    """День недели × час: сумма за период (val — колонка-вес, иначе число визитов)."""
    if not len(df): return None
    w = df[val] if val else pd.Series(1, index=df.index)
    return w.groupby([df['weekday'].astype(int), df['hour'].astype(int)]).sum().unstack(fill_value=0).reindex(index=range(7), columns=range(24), fill_value=0)


def journal(V, J0):
    """Журнал маркетинга по дням: визиты людей по каналам, рекламные клики (люди и боты), заявки."""
    if J0 is None or not len(J0): return None
    Hm = V[V['group'] == 'Люди']; ch = Hm['channel'].astype(str)
    g = Hm.groupby('day')
    D = pd.DataFrame({'Визиты людей|Все': g.size(), 'Визиты людей|Реклама': Hm[ch == 'Реклама'].groupby('day').size(),
                      'Визиты людей|Поиск': Hm[ch == 'Поиск'].groupby('day').size(), 'Визиты людей|Прочие': Hm[~ch.isin(['Реклама', 'Поиск'])].groupby('day').size()})
    A = V[V['channel'].astype(str) == 'Реклама']
    D['Рекламные клики|Ботов'] = A[A['group'] == 'Боты'].groupby('day').size()
    D['Рекламные клики|Впустую'] = A[_wasted(A)].groupby('day').size()
    D['Заявки|Отправлено'] = g['n_goal'].sum()
    D['Заявки|Принято'] = g['n_conv'].sum()
    D['Заявки|Из рекламы'] = Hm[ch == 'Реклама'].groupby('day')['n_conv'].sum()
    D['Заявки|От ботов'] = V[V['group'] == 'Боты'].groupby('day')['n_conv'].sum()
    D = D.fillna(0).astype(int).reset_index().rename(columns={'index': 'день', 'day': 'день'})
    meta = J0[J0['день'] != 'Итого'][['день', '_с', '_по', '_полный']]
    D = meta.merge(D, on='день', how='left').fillna(0)
    tot = {k_: int(D[k_].sum()) for k_ in D.columns if '|' in k_}
    return pd.concat([D, pd.DataFrame([{'день': 'Итого', **tot}])], ignore_index=True)


def quality(V):
    """Качество каналов и заявок: люди и боты, принятые заявки людей и ботов, доля фальшивых заявок."""
    X = V[V['channel'].notna() & V['group'].isin(['Люди', 'Боты'])]
    if not len(X): return None
    ch = X['channel'].astype(str)
    q = pd.DataFrame({'людей': X[X['group'] == 'Люди'].groupby(ch).size(), 'ботов': X[X['group'] == 'Боты'].groupby(ch).size(),
                      'заявок_людей': X[X['group'] == 'Люди'].groupby(ch)['n_conv'].sum(), 'заявок_ботов': X[X['group'] == 'Боты'].groupby(ch)['n_conv'].sum()}).fillna(0).astype(int)
    q['доля_ботов_%'] = (q['ботов'] / (q['людей'] + q['ботов']).clip(lower=1) * 100).round(1)
    q['фальшивых_заявок_%'] = (q['заявок_ботов'] / (q['заявок_людей'] + q['заявок_ботов']).clip(lower=1) * 100).round(1)
    q['конверсия_людей_%'] = (q['заявок_людей'] / q['людей'].clip(lower=1) * 100).round(3)
    return q.sort_values('людей', ascending=False).reset_index().rename(columns={'channel': 'канал', 'index': 'канал'})


def build(c, res):
    V = c.V
    H = V[V['group'] == 'Люди']
    out = {'журнал': journal(V, (res.get('errors') or {}).get('журнал')), 'качество': quality(V)}
    A = ad_visits(V)
    AH = A[A['group'] == 'Люди'] if len(A) else A
    out['время'] = [('Визиты людей', 'Все визиты людей за период', heat_week(H)),
                    ('Визиты из рекламы', 'Люди, пришедшие по рекламным ссылкам', heat_week(AH) if len(AH) else None),
                    ('Принятые заявки', 'Заявки людей, принятые сайтом', heat_week(H, 'n_conv'))]
    out['реклама_боты'] = ad_bots(A)
    label_ads((res.get('sheets') or {}).get('Маркетинг', {}), out['реклама_боты'])   # подписи фраз и регионов — общий уровень, не оформление
    out.update(ad_tops((res.get('sheets') or {}).get('Маркетинг', {}), out['реклама_боты']))
    if len(A):
        g = A.groupby('channel_sub')
        out['реклама_итог'] = {'кликов': int(len(A)), 'людей': int((A['group'] == 'Люди').sum()), 'ботов': int((A['group'] == 'Боты').sum()),
                               'роботов': int((A['group'] == 'Роботы').sum()), 'впустую': int(_wasted(A).sum()),
                               'заявок_людей': int(AH['n_conv'].sum()), 'заявок_ботов': int(A.loc[A['group'] == 'Боты', 'n_conv'].sum())}
        out['реклама_по_системам'] = g.agg(кликов=('ip', 'size')).join(A[A['group'] == 'Люди'].groupby('channel_sub').apply(metrics)).fillna(0).reset_index()
    return out
