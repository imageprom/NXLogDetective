"""NXLD: реестр точек приёма данных — один на все отчёты.

Каждый адрес, на который отправляют данные: POST — любой, GET — фильтры, поиск, пагинация, API и скрипты с параметрами.
Для каждого: метод, опознание (заявка, вход, фильтр, служебный скрипт, загрузка файлов, API, сканер…), улики, кто отправлял
(свои и посторонние), ответы, первый и последний раз, персональные данные в адресе.
Листы только выбирают из реестра: 01 «Точки приёма данных» — что сайт принимает, 03 «POST» и «GET» — всё, вместе со сканерами."""
import re
import numpy as np
import pandas as pd


SITE_KINDS = ('Заявка', 'Заявка?', 'Вход', 'Обмен с 1С', 'API', 'Вебхук', 'Фильтр каталога', 'Поиск по сайту', 'Форма (GET)', 'Пагинация', 'Тип отображения', 'Сортировка', 'Служебный скрипт', 'Подгрузка на странице', 'Админка', 'Загрузка файлов')


def _codes(s):
    import re
    return {int(k): int(v) for k, v in re.findall(r'(\d{3}):\s*(\d+)', str(s))}


def classify_post(r, login_roots, engine, ev=None, prof=None):
    """Что это за адрес и почему — человеческим языком."""
    import re
    a, out = str(r['адрес']), str(r.get('вывод', ''))
    cd = _codes(r.get('коды'))
    tot = max(1, sum(cd.values()))
    ok = sum(v for k, v in cd.items() if 200 <= k < 400 and k not in (301,)) / tot
    if out.startswith('цель'):
        e = (ev or {}).get(a)
        if e and e['редиректов']:
            how = ', '.join(f"{k} — {v}" for k, v in sorted(e['как'].items(), key=lambda x: -x[1]))
            if e['подтверждено'] == e['редиректов']:
                return 'Заявка', f"после отправки — переадресация (302), затем {how}: подтверждено {e['подтверждено']} из {e['редиректов']}"
            if e['подтверждено']:
                return 'Заявка', f"после отправки — переадресация (302), затем {how}: подтверждено {e['подтверждено']} из {e['редиректов']}; остальные не приняты"
            return 'Заявка', f"переадресация (302) есть, но подтверждения успеха нет ни в одном из {e['редиректов']} случаев — заявки не приняты"
        return 'Заявка', ('переадресация после отправки (3xx)' if '3xx' in out else 'успех по коду ответа не виден (всегда 200) — не подтверждено')
    if any(a == root or a.startswith(root) and a.rstrip('/') == root.rstrip('/') for root in login_roots) or (a in login_roots):
        return 'Вход', 'форма входа: неудачный вход возвращает ту же страницу, удачный — другую'
    if re.search(r'/bitrix/admin/|/wp-admin/|/administrator/', a):
        return 'Админка', 'запросы из админки движка (работа сотрудников)'
    if re.search(r'/wp-|wordpress|xmlrpc|^/wp/', a) and engine != 'WordPress':
        return 'Сканер', 'адрес WordPress, а сайт на другом движке'
    bad = cd.get(404, 0) + cd.get(405, 0) + cd.get(301, 0) + cd.get(302, 0)
    if cd and cd.get(404, 0) + cd.get(405, 0) >= 0.8 * tot:
        return 'Сканер', 'такой страницы нет на сайте (404)'
    if cd and bad >= 0.8 * tot:
        return 'Сканер', 'страницы нет (404) или перенаправление (301) — форму не принимает'
    if cd and cd.get(403, 0) >= 0.5 * tot:
        return 'Сканер', 'защита отказала (403)'
    if 'upload' in a:
        return 'Загрузка файлов', 'загрузка файлов на сервер'
    if any(a.startswith(root) for root in login_roots):
        return 'Служебный скрипт', 'скрипт внутри закрытого раздела'
    if re.search(r'ajax|/tools/|/services/|autosave|\.php$', a) and a not in ('/index.php',) and ok >= 0.5:
        return 'Служебный скрипт', 'скрипт сайта: подгружает данные, не заявка'
    p = (prof or {}).get(a, {})
    if p.get('свои', 0) >= 0.8:
        return 'Подгрузка на странице', f"POST шлют браузеры посетителей, которые уже на сайте ({int(p['свои'] * 100)}%) — страница подгружает данные (список, форму)"
    if p:
        tail = f", например параметр «{p['параметр']}»" if p.get('параметр') else ''
        return 'Сканер', f"POST на обычную страницу без перехода с сайта ({int((1 - p.get('свои', 0)) * 100)}% запросов){tail} — боты и сканеры"
    if ok >= 0.5:
        return 'Подгрузка на странице', 'обычная страница отвечает на POST'
    return 'Сканер', 'обычная страница, форму не принимает — отправляют боты и сканеры'


def post_rows(res):
    m = res.get('site_map') or {}
    F = m.get('forms') or []
    if isinstance(F, str):
        try: F = eval(F)
        except Exception: F = []
    OS = res.get('sheets', {}).get('Нагрузка и безопасность', {}).get('Открытые служебные разделы', pd.DataFrame())
    roots = set(OS.loc[OS['форма_входа'] == 'да', 'раздел'].astype(str)) if len(OS) and 'форма_входа' in OS else set()
    engine = ((m.get('engines') or [{}])[0] or {}).get('движок', '')
    rows = []
    for f in F:
        if not isinstance(f, dict): continue
        kind, why = classify_post(f, roots, engine, res.get('form_evidence'), (res.get('anatomy') or {}).get('post_pages'))
        rows.append({'Адрес точки': f['адрес'], 'Метод': 'POST', 'Опознано как': kind, 'Запросов': int(f.get('отправок') or 0), 'Уникальных IP': int(f.get('IP') or 0), 'Улики': why,
                     'Коды ответа': str(f.get('коды', '')), '_t0': pd.to_datetime(f.get('первый')), '_t1': pd.to_datetime(f.get('последний'))})
    return rows


SCRIPT_RX = r'\.php\d?$|/ajax|/api/|/services/|/tools/|/rest/|\.ashx$|\.aspx$|\.cgi$|\.pl$'


def get_scripts(c):
    """GET с параметрами на скрипты (не страницы): кто и сколько обращался, что ответил сервер. Скрипт сайта — если полный ответ
    получали люди или свои (реестр адресов); иначе — сканер."""
    R = c.R
    bc = R['base'].cat.categories.to_series().astype(str)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        sc = bc.str.contains(SCRIPT_RX, regex=True, case=False).values
    m = sc[R['base'].cat.codes.values] & (R['method'].values == 'GET') & (R['query'].astype(str).values != '')
    if not m.any(): return []
    from .common import real_addresses
    real = real_addresses(c)
    X = pd.DataFrame({'b': R['base'].cat.codes.values[m], 'ip': R['ip'].cat.codes.values[m], 'st': R['status'].values[m], 'ts': R['ts'].values[m],
                      'k': pd.Series(R['query'].astype(str).values[m]).str.extract(r'^([^=&]+)')[0].values})
    out = []
    for b, g in X.groupby('b'):
        if len(g) < 3: continue
        ok = bool(real[b])
        ks = g['k'].value_counts().index[:3]
        out.append(dict(адрес=bc.iloc[b], метод='GET', что='Служебный скрипт' if ok else 'Сканер',
                        почему=('скрипт сайта: отвечает людям и своим' if ok else 'скрипта нет на сайте или он отвечает только сканерам') + ('; параметры: ' + ', '.join(ks) if len(ks) else ''),
                        отправок=len(g), IP=g['ip'].nunique(), коды=', '.join(f'{a}:{n}' for a, n in g['st'].value_counts().head(4).items()),
                        первый=pd.to_datetime(g['ts'].min(), unit='s'), последний=pd.to_datetime(g['ts'].max(), unit='s'), источник='скрипт'))
    return out


def build(c, res):
    """Реестр: POST (формы и всё, что приняло POST), GET (фильтры, поиск, API из «Анатомии», скрипты с параметрами).
    Колонки — те же, что раньше собирал отчёт, плюс «свои», «посторонние» и «пд»."""
    rows = [dict(r, источник='POST') for r in post_rows(res)]
    for g in (res.get('anatomy') or {}).get('api', []) + (res.get('anatomy') or {}).get('get_приём', []):
        rows.append({'Адрес точки': g['адрес'], 'Метод': 'GET', 'Опознано как': g['что'], 'Запросов': g['отправок'], 'Уникальных IP': g['IP'], 'Улики': g['почему'],
                     'Коды ответа': g['коды'], '_t0': pd.to_datetime(g['первый']), '_t1': pd.to_datetime(g['последний']), 'источник': 'GET'})
    known = {r['Адрес точки'] for r in rows}
    for g in get_scripts(c):
        if g['адрес'] in known: continue
        rows.append({'Адрес точки': g['адрес'], 'Метод': 'GET', 'Опознано как': g['что'], 'Запросов': g['отправок'], 'Уникальных IP': g['IP'], 'Улики': g['почему'],
                     'Коды ответа': g['коды'], '_t0': g['первый'], '_t1': g['последний'], 'источник': 'скрипт'})
    # свои и посторонние, персональные данные — по точным адресам (у сводных строк «Анатомии» вида «/projects/* — …» их нет)
    R = c.R
    bc = R['base'].cat.categories.astype(str)
    idx = {a: i for i, a in enumerate(bc)}
    staff = np.asarray(c.rg == 'Свои')
    meth = R['method'].astype(str).values
    want = {(idx[r['Адрес точки']], r['Метод']) for r in rows if r['Адрес точки'] in idx}
    codes = R['base'].cat.codes.values
    sel = np.isin(codes, [b for b, _ in want])
    X = pd.DataFrame({'b': codes[sel], 'm': meth[sel], 's': staff[sel]})
    if len(X):
        X = X[X['m'].isin(['GET', 'POST'])]
        if len(X):
            X = X[[ (b, m) in want or (b, 'GET/POST') in want for b, m in zip(X['b'], X['m'])]]
    cnt = X.groupby(['b', 'm'])['s'].agg(['sum', 'size']) if len(X) else pd.DataFrame(columns=['sum', 'size'])
    from .recon import has_pd
    G = getattr(c, 'G', None)
    pd_n = G[G['query'].astype(str).map(has_pd)].groupby(G['base'].astype(str)).size() if G is not None and len(G) else pd.Series(dtype=int)
    for r in rows:
        b = idx.get(r['Адрес точки'])
        if b is None or r['Метод'] not in ('GET', 'POST') or (b, r['Метод']) not in cnt.index:
            r['свои'], r['посторонние'] = None, None
        else:
            s_, n_ = cnt.loc[(b, r['Метод'])]
            r['свои'], r['посторонние'] = int(s_), int(n_ - s_)
        r['пд'] = int(pd_n.get(r['Адрес точки'], 0)) if r['Метод'] == 'GET' else 0
    return rows


def findings(res, items):
    """Карточки по реестру: загрузка файлов посторонними."""
    rows = res.get('intake') or []
    up = [r for r in rows if r['Опознано как'] == 'Загрузка файлов' and (r.get('посторонние') or 0) > 0 and '200' in str(r.get('Коды ответа', ''))]
    items[:] = [x for x in items if x['key'] != 'Нагрузка и безопасность:upload_outsiders:site']
    if up:
        items.append(dict(key='Нагрузка и безопасность:upload_outsiders:site', блок='Нагрузка и безопасность', важность='Срочно',
                          что_происходит='Посторонние загружают файлы на сервер',
                          факты='; '.join(f"{r['Адрес точки']} — {r['посторонние']} запросов не от сотрудников, ответы: {r['Коды ответа']}" for r in up[:5]),
                          где_править='сервер / права на загрузку', что_сделать='Проверить, кто и что загрузил; закрыть загрузку для тех, кто не вошёл на сайт',
                          главная_цифра=int(sum(r['посторонние'] for r in up)), лист='POST', также_в='', статус=''))
