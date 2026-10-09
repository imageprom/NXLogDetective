"""NXLD: блок «SEO» (файл 06) — как поисковики видят сайт.

Обход поисковиками (по роботам и разделам), файлы для роботов (robots.txt, sitemap, llms.txt), страницы без обхода
и обратное, переадресации у роботов, подлинность поисковиков, журнал по дням. Сюда же переезжают карточки
о паразитных адресах, поисковых ошибках, служебных файлах для роботов и видимости страниц входа — ключи
карточек не меняются (отметки «это норма» и сравнение с прошлой проверкой сохраняются)."""
import re
import numpy as np, pandas as pd
from .common import codes_text

BLOCK = 'SEO'
ROBOT_FILES = re.compile(r'^/(robots\.txt|sitemap[^/]*\.xml(\.gz)?|sitemap[^/]*/.*\.xml|llms(-full)?\.txt|ads\.txt|security\.txt|\.well-known/.*)$', re.I)
MOVE_KINDS = {'parasites', 'trap', 'search_errors', 'login_indexed', 'ai_index'}   # карточки, которые переезжают в 06 (ключ прежний)
ROBOT_SERVICE = re.compile(r'sitemap|robots\.txt|llms', re.I)
ENGINE = {'YandexBot': 'Яндекс', 'YandexRenderResourcesBot': 'Яндекс', 'YandexImages': 'Яндекс', 'Googlebot': 'Google', 'Googlebot-Image': 'Google', 'Bingbot': 'Bing'}


def _cats(R, col):
    return R[col].cat.categories.astype(str).values, R[col].cat.codes.values


def masks(c):
    R = c.R
    fc, fcode = _cats(R, 'fam_cat')
    search = np.isin(fcode, np.where(fc == 'Поисковик')[0])
    ver = (R['fam_verified'] == 'да').values
    return search & ver, search & ~ver


def section_of(paths):
    """Раздел — первый сегмент пути: /projects/x/ → /projects/."""
    return pd.Series(paths).astype(str).str.extract(r'^(/[^/?]*/?)')[0].fillna('/').str.replace(r'^(/[^/]+)$', r'\1', regex=True).values


def crawl(c, ok):
    """Обход по роботам: сколько запросов, страниц, адресов с параметрами, ответов по классам кодов, трафик, последний день."""
    R = c.R
    fam, fcode = _cats(R, 'fam')
    st = R['status'].values; pg = R['is_page'].values
    qc, qcode = _cats(R, 'query')
    empty_q = np.where((qc == '') | (qc == 'nan'))[0]
    hasq = ~np.isin(qcode, empty_q)
    X = pd.DataFrame({'f': fcode[ok], 'st': st[ok], 'pg': pg[ok], 'q': hasq[ok], 'b': R['base'].cat.codes.values[ok], 'by': R['bytes'].values[ok], 'd': R['day'].cat.codes.values[ok]})
    days = R['day'].cat.categories.astype(str).values
    rows = []
    for f, g in X.groupby('f'):
        P = g[g['pg']]
        n = len(g)
        rows.append({'робот': fam[f], 'поисковик': ENGINE.get(fam[f], fam[f]), 'запросов': n, 'страниц': len(P), 'адресов_страниц': int(P['b'].nunique()),
                     'с_параметрами_%': round(P['q'].mean() * 100, 1) if len(P) else 0,
                     'ответ_2xx_%': round(((g['st'] >= 200) & (g['st'] < 300)).mean() * 100, 1), 'переадресаций_%': round(((g['st'] >= 300) & (g['st'] < 400)).mean() * 100, 1),
                     'ошибок_4xx_%': round(((g['st'] >= 400) & (g['st'] < 500)).mean() * 100, 1), 'ошибок_5xx_%': round((g['st'] >= 500).mean() * 100, 1),
                     'МБ': round(g['by'].sum() / 2 ** 20, 1), 'последний': days[g['d'].max()],
                     'впустую_%': round(((g['st'] >= 300) | (g['pg'] & g['q'])).mean() * 100, 1),   # переадресации, ошибки и страницы с параметрами
                     'мимо_%': round((g['st'] >= 300).mean() * 100, 1)})   # только переадресации и ошибки (параметры — карточка о паразитных адресах)
    return pd.DataFrame(rows).sort_values('запросов', ascending=False).reset_index(drop=True) if rows else pd.DataFrame()


def by_section(c, ok):
    """Разделы сайта глазами поисковиков: запросы Яндекса, Google и прочих, ошибки, доля с параметрами."""
    R = c.R
    bc, bcode = _cats(R, 'base')
    sec = section_of(bc)
    fam, fcode = _cats(R, 'fam')
    eng = np.array([ENGINE.get(f, 'прочие') for f in fam])
    m = ok & R['is_page'].values
    X = pd.DataFrame({'s': sec[bcode[m]], 'e': eng[fcode[m]], 'st': R['status'].values[m]})
    if not len(X): return pd.DataFrame()
    t = X.groupby(['s', 'e']).size().unstack(fill_value=0)
    out = pd.DataFrame({'раздел': t.index, 'запросов': t.sum(axis=1).values})
    for e in ('Яндекс', 'Google', 'Bing', 'прочие'):
        out[e] = t[e].values if e in t else 0
    g = X.groupby('s')['st']
    out['ошибок_%'] = (g.apply(lambda s: (s >= 400).mean() * 100).round(1)).reindex(t.index).values
    out['переадресаций_%'] = (g.apply(lambda s: ((s >= 300) & (s < 400)).mean() * 100).round(1)).reindex(t.index).values
    return out.sort_values('запросов', ascending=False).reset_index(drop=True)


def redirect_followed(R, m):
    """Переадресация 3xx по строкам m, после которой тот же клиент (IP + браузер) в пределах robots_redirect_followup_sec секунд
    и robots_redirect_followup_steps следующих своих запросов взял тот же путь с ответом 200: http → https или www ↔ без www того же
    адреса — норма (схемы и хоста в access-логе нет, различаем по следующему запросу). Булев массив по строкам R."""
    from .thresholds import value
    st = R['status'].values
    out = np.zeros(len(R), bool)
    r3 = m & (st >= 300) & (st < 400)
    if not r3.any(): return out
    W, N = value('robots_redirect_followup_sec', 60), int(value('robots_redirect_followup_steps', 3))
    ipc = R['ip'].cat.codes.values.astype(np.int64); uac = R['ua'].cat.codes.values.astype(np.int64)
    cl = ipc * (int(uac.max()) + 1) + uac
    sel = np.isin(cl, np.unique(cl[r3]))   # все запросы клиентов, у которых есть такая переадресация
    idx = np.where(sel)[0]
    idx = idx[np.lexsort((R['ts'].values[idx], cl[idx]))]
    c_, t_, b_, s_ = cl[idx], R['ts'].values[idx], R['base'].cat.codes.values[idx], st[idx]
    for k in np.where(r3[idx])[0]:
        for j in range(k + 1, min(k + 1 + N, len(idx))):
            if c_[j] != c_[k] or t_[j] - t_[k] > W: break
            if b_[j] == b_[k]:
                out[idx[k]] = s_[j] == 200   # тот же путь: 200 — норма; снова 3xx — цепочка или петля
                break
    return out


def robot_files(c, ok):
    """Файлы для роботов: кто просит, что отвечает сервер, сколько раз через переадресацию."""
    R = c.R
    bc, bcode = _cats(R, 'base')
    hit = np.array([bool(ROBOT_FILES.match(b)) for b in bc])
    m = hit[bcode]
    if not m.any(): return pd.DataFrame()
    X = pd.DataFrame({'b': bc[bcode[m]], 'st': R['status'].values[m], 'ok': ok[m], 'ts': R['ts'].values[m], 'norm': redirect_followed(R, m)[m]})
    rows = []
    for b, g in X.groupby('b'):
        g = g.sort_values('ts')
        se = g[g['ok']]
        r3 = (g['st'] >= 300) & (g['st'] < 400)
        bad3 = r3 & ~g['norm']   # переадресация не на тот же путь с ответом 200 (другой путь, чужой хост, цепочка, петля, ошибка)
        rows.append({'файл': b, 'запросов': len(g), 'от_поисковиков': len(se), 'коды': codes_text(g['st']), 'последний_код': int(g['st'].iloc[-1]),
                     'через_переадресацию': int(r3.sum()), 'переадресаций_с_проблемой': int(bad3.sum()), 'ошибок': int((g['st'] >= 400).sum()),
                     'вывод': ('не отвечает' if (g['st'] >= 400).mean() >= 0.5 else ('отвечает через переадресацию' if bad3.mean() >= 0.5 else 'отвечает'))})
    t = pd.DataFrame(rows)
    t = t[(t['от_поисковиков'] > 0) | (t['запросов'] >= 20)]   # перебор имён сканерами (sitemap-pt-post-1.xml …) — не файлы для роботов
    return t.sort_values('запросов', ascending=False).reset_index(drop=True)


NOT_PAGE = re.compile(r'^/(bitrix|local|upload|manager|admin|cgi-bin)/|/index\.php$|\.(php|html?)$|/filter/', re.I)


def uncrawled(c, ok, min_people=3):
    """Страницы людей, которые поисковики не открывали за период; и обратное — что поисковики обходят, а люди не открывают."""
    R = c.R
    bc, bcode = _cats(R, 'base')
    pg = R['is_page'].values; st = R['status'].values
    hp = c.human & pg & (st == 200) & ~R['is_redirect_hop'].values
    ppl = pd.Series(R['vid'].values[hp]).groupby(bcode[hp]).nunique()
    rb = pd.Series(1, index=bcode[ok & pg]).groupby(level=0).size()
    last = pd.Series(R['ts'].values[ok & pg]).groupby(bcode[ok & pg]).max()
    from .common import real_addresses
    real = real_addresses(c)
    keep = np.array([bool(real[i]) and not NOT_PAGE.search(bc[i]) for i in ppl.index]) if len(ppl) else np.array([], bool)
    P = ppl[keep][ppl[keep] >= min_people] if len(ppl) else ppl   # настоящие страницы сайта: без служебных путей, фильтров и скриптов
    miss = P[~P.index.isin(rb.index)].sort_values(ascending=False)
    A = pd.DataFrame({'страница': bc[miss.index], 'визитов_людей': miss.values.astype(int)})
    rs = pd.Series(st[ok & pg]).groupby(bcode[ok & pg]).agg(lambda s: codes_text(s))
    only = rb[~rb.index.isin(ppl.index)].sort_values(ascending=False).head(500)
    B = pd.DataFrame({'страница': bc[only.index], 'запросов_роботов': only.values.astype(int), 'коды': rs.reindex(only.index).values,
                      'последний_обход': pd.to_datetime(last.reindex(only.index).values, unit='s').strftime('%d.%m.%Y')})
    return A, B, int(len(P))


def redirects(c, ok):
    """Переадресации, которые получают поисковики: адрес, сколько раз, кто."""
    R = c.R
    st = R['status'].values
    m = ok & (st >= 300) & (st < 400)
    if not m.any(): return pd.DataFrame()
    bc, bcode = _cats(R, 'base'); fam, fcode = _cats(R, 'fam')
    X = pd.DataFrame({'b': bcode[m], 'f': fam[fcode[m]], 'st': st[m]})
    g = X.groupby('b')
    t = pd.DataFrame({'адрес': bc[g.size().index], 'переадресаций': g.size().values, 'коды': g['st'].agg(codes_text).values,
                      'роботы': g['f'].agg(lambda s: ', '.join(f'{k} ({v})' for k, v in s.value_counts().head(3).items())).values})
    return t.sort_values('переадресаций', ascending=False).reset_index(drop=True)


def authenticity(c):
    """Подлинность поисковиков: сколько IP называли себя поисковиком и сколько из них подлинные."""
    V = c.V
    S = V[V['fam_cat'].astype(str) == 'Поисковик']
    if not len(S): return pd.DataFrame()
    fv = S['fam_verified'].astype(str)
    S = S.assign(_ok=(fv == 'да'), _fake=(fv == 'нет'))   # пусто — у робота нет опубликованных сетей: подлинность не проверить, это не подделка
    f_ = S['fam'].astype(str)
    g = S.groupby(f_)
    t = pd.DataFrame({'IP': g['ip'].nunique(), 'подлинных_IP': S[S['_ok']].groupby(f_[S['_ok']])['ip'].nunique(),
                      'поддельных_IP': S[S['_fake']].groupby(f_[S['_fake']])['ip'].nunique(),
                      'запросов': g['n_req'].sum(), 'запросов_подделок': S[S['_fake']].groupby(f_[S['_fake']])['n_req'].sum()}).fillna(0).astype(int)
    t['подделок_%'] = (t['запросов_подделок'] / t['запросов'].clip(lower=1) * 100).round(1)
    checked = S.groupby(f_)['fam_verified'].agg(lambda s_: (s_.astype(str) != '').any())
    t['проверяется'] = checked.reindex(t.index).fillna(False).values
    return t.sort_values('запросов', ascending=False).reset_index().rename(columns={'fam': 'робот', 'index': 'робот'})


def journal(c, ok, J0):
    if J0 is None or not len(J0): return None
    R = c.R
    fam, fcode = _cats(R, 'fam')
    eng = np.array([ENGINE.get(f, 'Прочие') for f in fam])[fcode[ok]]
    d = R['day'].cat.categories.astype(str).values[R['day'].cat.codes.values[ok]]
    st = R['status'].values[ok]
    X = pd.DataFrame({'d': d, 'e': eng, 'st': st})
    g = X.groupby('d')
    D = pd.DataFrame({'Запросы поисковиков|Яндекс': X[X['e'] == 'Яндекс'].groupby('d').size(), 'Запросы поисковиков|Google': X[X['e'] == 'Google'].groupby('d').size(),
                      'Запросы поисковиков|Прочие': X[~X['e'].isin(['Яндекс', 'Google'])].groupby('d').size(),
                      'Ответы роботам|Переадресаций': X[(X['st'] >= 300) & (X['st'] < 400)].groupby('d').size(),
                      'Ответы роботам|Ошибок 4xx': X[(X['st'] >= 400) & (X['st'] < 500)].groupby('d').size(), 'Ответы роботам|Ошибок 5xx': X[X['st'] >= 500].groupby('d').size()})
    V = c.V
    H = V[(V['group'] == 'Люди') & (V['channel'].astype(str) == 'Поиск')]
    D['Люди из поиска|Визитов'] = H.groupby('day').size()
    D['Люди из поиска|Заявок'] = H.groupby('day')['n_conv'].sum()
    D = D.fillna(0).astype(int).reset_index().rename(columns={'index': 'день', 'd': 'день'})
    meta = J0[J0['день'] != 'Итого'][['день', '_с', '_по', '_полный']]
    D = meta.merge(D, on='день', how='left').fillna(0)
    tot = {k_: int(D[k_].sum()) for k_ in D.columns if '|' in k_}
    return pd.concat([D, pd.DataFrame([{'день': 'Итого', **tot}])], ignore_index=True)


def build(c, res):
    ok, fake = masks(c)
    out = {'обход': crawl(c, ok), 'разделы': by_section(c, ok), 'файлы': robot_files(c, ok), 'переадресации': redirects(c, ok),
           'подлинность': authenticity(c), 'журнал': journal(c, ok, (res.get('errors') or {}).get('журнал'))}
    A, B, n_ppl = uncrawled(c, ok)
    out['без_обхода'], out['без_людей'], out['страниц_людей'] = A, B, n_ppl
    return out


def findings(res, items):
    """Карточки SEO: переезд прежних (ключ тот же) и новые — карта сайта, robots.txt, обход впустую, страницы без обхода."""
    for x in items:
        k = str(x.get('key', '')).split(':')
        kind = k[1] if len(k) > 1 else ''
        if kind in MOVE_KINDS or (kind == 'no_service' and ROBOT_SERVICE.search(':'.join(k[2:]))):
            x['блок'] = BLOCK
            if not x.get('тема'): x['тема'] = 'Поиск'
    D = res.get('seo') or {}
    def add(sev, kind, sub, title, facts, where, todo, n, sheet):
        key = f'{BLOCK}:{kind}:{sub}'
        items[:] = [x for x in items if not (x['key'] == key and x.get('статус_вид') == 'исправлена')]   # заглушка «исправлена» из сравнения — карточка снова есть
        if any(x['key'] == key for x in items): return
        items.append(dict(key=key, блок=BLOCK, важность=sev, что_происходит=title, заголовок=title, факты=facts, факт=facts, где_править=where, что_сделать=todo,
                          главная_цифра=n, лист=sheet, также_в='', статус='', доказательство='', тема='Поиск'))
    Fl = D.get('файлы')
    have = {x['key'] for x in items}
    if Fl is not None and len(Fl):
        for _, r in Fl.iterrows():
            f = str(r['файл'])
            if f.lower().startswith('/sitemap') and r['вывод'] == 'не отвечает' and int(r['от_поисковиков']) >= 5 and f'Ошибки:no_service:{f}' not in have:
                add('Важно', 'sitemap_down', f, f'Карта сайта {f} не отвечает', f"{int(r['запросов'])} запросов, ответы: {r['коды']}; от поисковиков — {int(r['от_поисковиков'])}",
                    'сайт / генерация карты сайта', 'Восстановить карту сайта или убрать её адрес из robots.txt', int(r['запросов']), 'Файлы для роботов')
            # http → https и www ↔ без www того же пути с ответом 200 — штатная настройка (#9); карточка — только при проблемной переадресации
            if f.lower() == '/robots.txt' and int(r.get('переадресаций_с_проблемой', r['через_переадресацию'])) >= 100:
                add('К сведению', 'robots_redirect', f, 'Файл robots.txt отдаётся через переадресацию',
                    f"{int(r['переадресаций_с_проблемой'])} из {int(r['запросов'])} запросов получили переадресацию не на тот же адрес с ответом 200 (другой путь, другой хост, цепочка или ошибка); ответы: {r['коды']}",
                    'nginx / настройки зеркал', 'Отдавать robots.txt на всех зеркалах сразу, без переадресации, или проверить, что зеркала склеены', int(r['переадресаций_с_проблемой']), 'Файлы для роботов')
    C = D.get('обход')
    if C is not None and len(C):
        W_ = C[(C['запросов'] >= 1000) & (C['мимо_%'] >= 20)]
        if len(W_):
            p_ = lambda v: str(v).replace('.', ',')
            add('Важно', 'crawl_waste', 'site', 'Поисковики тратят обход на переадресации и ошибки',
                '; '.join(f"{r['робот']} — {p_(r['мимо_%'])}% из {int(r['запросов'])} запросов (переадресаций {p_(r['переадресаций_%'])}%, ошибок 4xx {p_(r['ошибок_4xx_%'])}%)" for _, r in W_.iterrows()),
                'ссылки на сайте, карта сайта, настройки переадресаций', 'Исправить внутренние ссылки на конечные адреса, убрать из карты сайта переадресации и несуществующие страницы',
                int(W_['запросов'].sum()), 'Обход поисковиками')
    A = D.get('без_обхода')
    if A is not None and len(A) >= 20:
        add('Важно' if len(A) >= 50 else 'К сведению', 'uncrawled', 'pages', f'{len(A)} страниц, которые открывают люди, поисковики не обходили',
            f"Из {D.get('страниц_людей', 0)} страниц с 3 и больше визитами людей; крупнейшие: {', '.join(A['страница'].head(3))}",
            'карта сайта, внутренние ссылки', 'Добавить страницы в карту сайта и в навигацию; проверить, не закрыты ли они в robots.txt', len(A), 'Страницы без обхода')
