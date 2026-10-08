"""NXLD: визиты, очистка искажений, каналы, группы трафика."""
import re
import numpy as np, pandas as pd

GAP = 1800
SEARCH = r'(^|\.)(yandex\.[a-z.]+|ya\.ru|google\.[a-z.]+|bing\.com|go\.mail\.ru|duckduckgo\.com|search\.yahoo\.com|rambler\.ru|nova\.rambler\.ru)$'
AI_REF = r'(^|\.)(chatgpt\.com|chat\.openai\.com|perplexity\.ai|copilot\.microsoft\.com|gemini\.google\.com|chat\.deepseek\.com|giga\.chat|claude\.ai|alice\.yandex\.ru|chat\.mistral\.ai|you\.com|grok\.com)$'
SOCIAL = r'(^|\.)(vk\.com|vk\.ru|ok\.ru|t\.me|telegram\.org|web\.telegram\.org|facebook\.com|instagram\.com|l\.instagram\.com|dzen\.ru|youtube\.com|whatsapp\.com|max\.ru|web\.max\.ru|pinterest\.com|tiktok\.com|x\.com|twitter\.com|away\.vk\.com|m\.vk\.com)$'
MAPS = r'(^|\.)(2gis\.[a-z]+|maps\.google\.[a-z.]+|yandex\.ru/maps)$'
AGGR = r'(^|\.)(cian\.ru|avito\.ru|domclick\.ru|realty\.ya\.ru|realty\.yandex\.ru|market\.yandex\.ru|novostroy-m\.ru|novostroev\.ru|nedvex\.ru|yell\.ru|zoon\.ru|flamp\.ru|otzovik\.com)$'


def build(R, embedded_tpl_codes=None, tpl=None):
    """Нумерует визиты (IP + UA, пауза 30 мин) и помечает искажения. Меняет R на месте."""
    ipc = R['ip'].cat.codes.values.astype(np.int64)
    uac = R['ua'].cat.codes.values.astype(np.int64)
    ts = R['ts'].values
    order = np.lexsort((ts, uac, ipc))
    i_, u_, t_ = ipc[order], uac[order], ts[order]
    new = np.ones(len(order), dtype=bool)
    new[1:] = (i_[1:] != i_[:-1]) | (u_[1:] != u_[:-1]) | (t_[1:] - t_[:-1] > GAP)
    vid_sorted = np.cumsum(new) - 1
    vid = np.empty(len(order), dtype=np.int64)
    vid[order] = vid_sorted
    R['vid'] = vid
    R['_ord'] = np.empty(len(order), dtype=np.int64)
    R.loc[order, '_ord'] = np.arange(len(order))
    meth = R['method'].values
    st = R['status'].values
    getlike = np.isin(meth, ['GET', 'HEAD'])
    page_raw = getlike & ~R['is_static'].values
    if embedded_tpl_codes is not None:
        emb = np.isin(R['base'].cat.codes.values, embedded_tpl_codes)
    else:
        emb = np.zeros(len(R), dtype=bool)
    R['is_embedded'] = page_raw & emb
    page = page_raw & ~emb
    # повторы адреса в пределах 5 с внутри визита (двойная загрузка в браузерах приложений, перезагрузка)
    key = R['base'].cat.codes.values.astype(np.int64) * 1_000_003 + R['query'].cat.codes.values.astype(np.int64)
    k_s, p_s, t_s, v_s = key[order], page[order], t_, vid_sorted
    dup_s = np.zeros(len(order), dtype=bool)
    # предыдущая страница в том же визите
    idx = np.where(p_s)[0]
    if len(idx) > 1:
        same_v = v_s[idx[1:]] == v_s[idx[:-1]]
        same_k = k_s[idx[1:]] == k_s[idx[:-1]]
        close = t_s[idx[1:]] - t_s[idx[:-1]] <= 5
        dup_s[idx[1:][same_v & same_k & close]] = True
    dup = np.empty(len(order), dtype=bool); dup[order] = dup_s
    # редирект и его цель: 3xx-страница, за которой в течение 3 с следует страница — считаем один просмотр
    red_s = np.zeros(len(order), dtype=bool)
    if len(idx) > 1:
        st_s = st[order]
        r = np.isin(st_s[idx[:-1]], [301, 302, 303, 307, 308]) & (v_s[idx[1:]] == v_s[idx[:-1]]) & (t_s[idx[1:]] - t_s[idx[:-1]] <= 3)
        red_s[idx[:-1][r]] = True
    red = np.empty(len(order), dtype=bool); red[order] = red_s
    R['is_dup'] = page & dup
    R['is_redirect_hop'] = page & red
    R['is_page'] = page & ~dup & ~red
    return R


def detect_embedded(R, tpl, min_share=0.85, min_hits=200):
    """Шаблоны, которые браузер грузит сам сразу после страницы (модальные формы, блоки) — часть страницы, не просмотр."""
    order = R['_ord'].values
    inv = np.argsort(order)
    ts = R['ts'].values[inv]; vid = R['vid'].values[inv]
    br = R['ua_browser'].values[inv]
    getlike = np.isin(R['method'].values[inv], ['GET'])
    nonstatic = ~R['is_static'].values[inv]
    refint = R['ref_internal'].values[inv]
    cand = getlike & nonstatic & br
    prev_t = np.r_[-10**12, ts[:-1]]; prev_v = np.r_[-1, vid[:-1]]
    soon = (vid == prev_v) & (ts - prev_t <= 3) & refint
    codes = R['base'].cat.codes.values[inv]
    T = pd.DataFrame({'tpl': tpl[codes][cand], 'soon': soon[cand]})
    g = T.groupby('tpl')['soon'].agg(['mean', 'size'])
    emb_tpl = g[(g['mean'] >= min_share) & (g['size'] >= min_hits)]
    emb_codes = np.where(np.isin(tpl, emb_tpl.index.values))[0]
    return emb_codes, emb_tpl.reset_index().rename(columns={'tpl': 'шаблон', 'mean': 'доля_сразу_после_страницы', 'size': 'запросов'})


def channel_of(ref_host, ref_internal, query, ref_full):
    q = query.lower()
    if 'yclid=' in q or re.search(r'utm_source=(yandex|yd|ya|direct)', q): return 'Реклама', 'Яндекс Директ'
    if 'gclid=' in q or 'gbraid=' in q or 'wbraid=' in q or 'utm_source=google' in q and 'cpc' in q: return 'Реклама', 'Google Ads'
    if 'rb_clickid=' in q or 'vkclid=' in q or re.search(r'utm_source=(vk|mytarget|vkads)', q): return 'Реклама', 'VK Реклама'
    if re.search(r'utm_source=(tg|telegram)', q) and 'cpc' in q: return 'Реклама', 'Telegram Ads'
    if 'utm_source=chatgpt.com' in q: return 'ИИ-ассистенты', 'ChatGPT'
    if re.search(r'utm_medium=(e-?mail|newsletter|rassylka)', q): return 'Рассылки', ''
    if re.search(r'utm_medium=(cpc|cpm|cpa|paid|ppc)', q): return 'Реклама', 'прочие системы'
    h = ref_host or ''
    if ref_internal: return 'Внутренний переход', ''
    if re.search(AI_REF, h): return 'ИИ-ассистенты', h
    if re.search(MAPS, h) or ('yandex.' in h and '/maps' in ref_full) or ('google.' in h and '/maps' in ref_full): return 'Карты', h
    if re.search(SEARCH, h): return 'Поиск', 'Яндекс' if ('yandex' in h or h == 'ya.ru') else ('Google' if 'google' in h else h)
    if re.search(SOCIAL, h): return 'Соцсети и мессенджеры', h
    if re.search(AGGR, h): return 'Площадки и агрегаторы', h
    if 'utm_' in q: return 'Метки: прочие', re.search(r'utm_source=([^&]*)', q).group(1) if 'utm_source=' in q else ''
    if not h: return 'Прямые заходы', ''
    return 'Ссылки с сайтов', h


def aggregate(R, staff_ips=(), monitor_keys=()):
    """Таблица визитов V."""
    g = R.groupby('vid', sort=True)
    first = R.drop_duplicates('vid').set_index('vid').sort_index()
    pg = R[R['is_page'].values]
    fp = pg.drop_duplicates('vid').set_index('vid')
    V = pd.DataFrame({
        'ip': first['ip'].astype(str), 'ua': first['ua'].astype(str), 'fam': first['fam'].astype(str), 'fam_cat': first['fam_cat'].astype(str),
        'fam_verified': first['fam_verified'].astype(str), 'asn': first['asn'], 'nettype': first['nettype'].astype(str), 'cc': first['cc'].astype(str),
        'ua_browser': first['ua_browser'], 'ua_old': first['ua_old'], 'ua_mobile': first['ua_mobile'], 'ua_webview': first['ua_webview'],
        'start': g['ts'].min(), 'end': g['ts'].max(), 'n_req': g.size(),
        'n_pages': g['is_page'].sum(), 'n_pages_raw': (g['is_page'].sum() + g['is_dup'].sum() + g['is_redirect_hop'].sum()),
        'n_dup': g['is_dup'].sum(), 'n_redirect': g['is_redirect_hop'].sum(), 'n_embedded': g['is_embedded'].sum(),
        'n_static': g['is_static'].sum(),
        'bytes': g['bytes'].sum(),
    })
    V['n_post'] = R.assign(_p=(R['method'].values == 'POST')).groupby('vid')['_p'].sum()
    V['n_head'] = R.assign(_h=(R['method'].values == 'HEAD')).groupby('vid')['_h'].sum()
    V['n_err4'] = R.assign(_e=(R['status'].values >= 400) & (R['status'].values < 500)).groupby('vid')['_e'].sum()
    V['n_err5'] = R.assign(_e=(R['status'].values >= 500)).groupby('vid')['_e'].sum()
    V['dur'] = V['end'] - V['start']
    V['entry'] = fp['base'].astype(str).reindex(V.index).fillna(first['base'].astype(str))
    V['entry_query'] = fp['query'].astype(str).reindex(V.index).fillna(first['query'].astype(str))
    V['entry_status'] = fp['status'].reindex(V.index).fillna(first['status']).astype(int)
    V['entry_ref'] = fp['ref'].astype(str).reindex(V.index).fillna(first['ref'].astype(str))
    V['entry_ref_host'] = fp['ref_host'].astype(str).reindex(V.index).fillna(first['ref_host'].astype(str))
    V['entry_ref_internal'] = fp['ref_internal'].reindex(V.index).fillna(first['ref_internal']).astype(bool)
    ch = [channel_of(h, ri, q, rf) for h, ri, q, rf in zip(V['entry_ref_host'], V['entry_ref_internal'], V['entry_query'], V['entry_ref'])]
    V['channel'] = [c[0] for c in ch]
    V['channel_sub'] = [c[1] for c in ch]
    V['day'] = pd.to_datetime(V['start'], unit='s').dt.strftime('%Y-%m-%d')
    V['hour'] = (V['start'] // 3600) % 24
    V['weekday'] = pd.to_datetime(V['start'], unit='s').dt.dayofweek
    # группы
    staff = V['ip'].isin(set(staff_ips))
    mon = pd.Series([(i, u) in set(monitor_keys) for i, u in zip(V['ip'], V['ua'])], index=V.index)
    declared = V['fam'] != ''
    honest_cat = ~V['fam_cat'].isin(['Скрипты/библиотеки', 'Прочие боты'])
    fake = V['fam_verified'] == 'нет'
    explicit = (~declared) & (~V['ua_browser'] | (V['n_head'] == V['n_req']))
    noload = V['ua_browser'] & (V['n_static'] == 0) & (V['n_pages'] >= 1) & (V['n_embedded'] == 0)
    grp = np.select(
        [staff | mon, declared & fake, declared & honest_cat, declared & ~honest_cat, explicit, noload],
        ['Свои', 'Боты', 'Роботы', 'Роботы', 'Боты', 'Боты'], default='Люди')
    sub = np.select(
        [staff, mon, declared & fake, declared & honest_cat, declared & ~honest_cat, explicit, noload],
        ['сотрудники', 'мониторинги', 'подделки роботов', 'известные', 'неизвестные', 'явные (не браузер)', 'маскирующиеся: без загрузки ресурсов'],
        default='')
    V['group'] = grp
    V['subgroup'] = sub
    return regroup(V, R)


_MON = None


def monitors_ref():
    """Справочник систем мониторинга + найденное Детективом (learned/monitors.json)."""
    global _MON
    if _MON is None:
        import json, os, re as re_
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference'))
        def rd(p):
            try: return json.load(open(p, encoding='utf-8'))
            except Exception: return {}
        M = rd(os.path.join(base, 'monitors.json'))
        L = rd(os.path.join(base, 'learned', 'monitors.json'))
        items = (M.get('сервисы') or []) + (L.get('сервисы') or [])
        _MON = dict(rx=[(x['сервис'], re_.compile(x['шаблон'], re_.I)) for x in items if x.get('шаблон')],
                    max_addr=int((M.get('поведение') or {}).get('адресов_не_больше', 3)))
    return _MON


def monitor_name(ua):
    """Название системы мониторинга по User-Agent из справочника; None — не знаем."""
    for nm, rx in monitors_ref()['rx']:
        if rx.search(str(ua)): return nm
    return None


def learn_monitors(items, site=''):
    """Запись Детектива: [{сервис, шаблон, ссылка}] → learned/monitors.json (без ссылки не принимается)."""
    import json, os
    from .reference import anon
    p = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference', 'learned', 'monitors.json'))
    try: L = json.load(open(p, encoding='utf-8'))
    except Exception: L = {'сервисы': []}
    have = {x['сервис'].lower() for x in L['сервисы']}
    ok = []
    for it in items or []:
        nm, rx, url = str(it.get('сервис', '')).strip(), str(it.get('шаблон', '')).strip(), str(it.get('ссылка', ''))
        if not nm or not rx or not url.startswith('http') or nm.lower() in have: continue
        L['сервисы'].append(dict(сервис=nm, шаблон=rx, ссылка=url, источник='поиск', сайт=anon(site))); ok.append(nm); have.add(nm.lower())
    if ok:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(L, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        global _MON
        _MON = None
    return ok


_RANGES = None


def robot_ranges():
    """Официальные сети роботов из data/reference/robot_ranges.json: {семейство: [сети]} (обновление — tools/update_robot_ranges.py)."""
    global _RANGES
    if _RANGES is None:
        import json, os, ipaddress
        p = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference', 'robot_ranges.json')
        try:
            d = json.load(open(p, encoding='utf-8')).get('семейства', {})
            _RANGES = {f: [ipaddress.ip_network(n, strict=False) for n in nets] for f, nets in d.items() if nets}
        except Exception:
            _RANGES = {}
    return _RANGES


def reverify(R, V):
    """Подлинность объявленных роботов — заново по справочнику сетей (ipdb.VERIFIED), если он изменился после подготовки логов.
    Визит робота, который пришёл не из своей сети, — подделка: группа «Боты», подгруппа «подделки роботов»."""
    from . import ipdb
    fam = R['fam'].astype(str).values
    ver = R['fam_verified'].astype(str).values.copy()
    for f, allowed in ipdb.VERIFIED.items():
        m = fam == f
        if m.any(): ver[m] = np.where(np.isin(R['asn'].values[m], list(allowed)), 'да', 'нет')
    RG = robot_ranges()   # официальные списки сетей (Google, Bing, OpenAI, Perplexity, DuckDuckGo): точнее, чем ASN
    if RG:
        import ipaddress
        ipc, ipcode = R['ip'].cat.categories.astype(str).values, R['ip'].cat.codes.values
        for f, nets in RG.items():
            m = fam == f
            if not m.any(): continue
            codes = np.unique(ipcode[m])
            ok = np.zeros(len(ipc), bool)
            for k in codes:
                try:
                    a_ = ipaddress.ip_address(ipc[k]); ok[k] = any(a_ in n_ for n_ in nets)
                except ValueError: pass
            ver[m] = np.where(ok[ipcode[m]], 'да', 'нет')
    R['fam_verified'] = pd.Categorical(ver)
    first = pd.Series(ver).groupby(R['vid'].values).first()
    V = V.copy()
    V['fam_verified'] = first.reindex(V.index).fillna('').values
    fake = (V['fam_verified'] == 'нет') & (V['fam'] != '') & V['group'].isin(['Роботы', 'Люди'])
    V.loc[fake, 'group'] = 'Боты'; V.loc[fake, 'subgroup'] = 'подделки роботов'
    return R, V


SELF_CHECK = r'^/bitrix/admin/site_checker\.php$|^/bitrix/site_check_exec\.php$|^/bitrix/tools/check_|^/wp-cron\.php$'


def own_server(V, R):
    """IP сервера сайта: он сам себя проверяет — «Проверка системы» Битрикса (site_checker) или wp-cron, без User-Agent.
    Его обращения — «Свои», подгруппа «сервер сайта». Возвращает (V, список IP)."""
    cats = R['base'].cat.categories.to_series().astype(str)
    hit = cats.str.contains(SELF_CHECK, regex=True).values[R['base'].cat.codes.values]
    noua = R['ua'].astype(str).isin(['', '-']).values
    ips = sorted(set(R.loc[hit & noua, 'ip'].astype(str)))
    if ips:
        V = V.copy()
        m = V['ip'].astype(str).isin(ips) & (V['group'] != 'Свои')
        V.loc[m, 'group'] = 'Свои'; V.loc[m, 'subgroup'] = 'сервер сайта'
    return V, ips


def regroup(V, R=None):
    """Группы без смешения. «Свои» — только люди-сотрудники.
    Системы мониторинга — по имени (справочник) или ритму, и только если поведение мониторинговое: мало адресов. Имя есть,
    а поведение другое — бот под именем мониторинга. Ритм без имени — «неопознанный мониторинг»: вопрос аналитику.
    Утилиты (curl, wget, Python, PHP, Go, headless) — своя группа: решают улики. Без User-Agent — боты: честные программы и браузеры
    себя называют. Повторный вызов ничего не меняет."""
    V = V.copy()
    key = V['ip'].astype(str) + '|' + V['ua'].astype(str)
    if R is not None:   # разных адресов у обращающегося за период
        rk = key.reindex(R['vid'].values).values
        n_addr = pd.Series(R['base'].cat.codes.values).groupby(rk).nunique()
    else:
        n_addr = V.groupby(key)['entry'].nunique()
    addr = key.map(n_addr).fillna(1).values
    MX = monitors_ref()['max_addr']
    named = pd.Series([monitor_name(u) for u in V['ua'].astype(str)], index=V.index)
    by_name = ((V['fam'] != '') & (V['fam_cat'] == 'Мониторинг')) | named.notna()
    by_name &= V['group'].isin(['Роботы', 'Люди', 'Боты', 'Системы мониторинга']) & (V['subgroup'] != 'сотрудники')
    rhythm = V['subgroup'].isin(['мониторинги', 'неопознанный мониторинг'])
    ok_beh = addr <= MX
    from .actors import product_name
    if R is not None and rhythm.any():   # ритм без имени, но с зондами — это не мониторинг, а разведка по расписанию
        import warnings
        cats = R['base'].cat.categories.to_series().astype(str)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            pr = cats.str.contains(probe_rx(('однозначный', 'неоднозначный')), regex=True, case=False).values[R['base'].cat.codes.values]
        probing = set(pd.unique(rk[pr]))
        spy = rhythm & key.isin(probing)
        V.loc[spy, 'group'] = 'Боты'; V.loc[spy, 'subgroup'] = 'разведка по расписанию'
        rhythm &= ~spy
    mon = (by_name & ok_beh) | rhythm
    V.loc[mon, 'group'] = 'Системы мониторинга'
    V.loc[mon & by_name, 'subgroup'] = [named[i] or product_name(V.at[i, 'ua']) for i in V.index[mon & by_name]]
    V.loc[mon & ~by_name, 'subgroup'] = 'неопознанный мониторинг'
    fake = by_name & ~ok_beh & ~rhythm
    V.loc[fake, 'group'] = 'Боты'
    V.loc[fake, 'subgroup'] = 'выдаёт себя за мониторинг'
    noua = (V['fam'] == 'Без User-Agent') & V['group'].isin(['Роботы', 'Утилиты'])
    V.loc[noua, 'group'] = 'Боты'
    V.loc[noua, 'subgroup'] = 'без User-Agent'
    ut = (V['fam'] != '') & (V['fam_cat'] == 'Скрипты/библиотеки') & V['group'].isin(['Роботы', 'Утилиты']) & ~noua
    V.loc[ut, 'group'] = 'Утилиты'
    V.loc[ut, 'subgroup'] = [UTIL_LABEL.get(f, f) if f != 'Скрипты: прочие' else product_name(u) for f, u in zip(V.loc[ut, 'fam'].astype(str), V.loc[ut, 'ua'].astype(str))]
    return V


UTIL_LABEL = {'Скрипты: прочие': 'Прочие программы'}


def load_probes():
    """Зонды и сигнатуры сканеров — data/reference/probes.json."""
    import json, os
    p = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference', 'probes.json'))
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return {'зонды': [], 'сигнатуры': []}


def probe_rx(strength=('однозначный',), engines=()):
    """Одно регулярное выражение для зондов нужной силы; условие «сайт не на WordPress» учитывается."""
    wp = any('wordpress' in str(e).lower() for e in engines)
    parts = [z['шаблон'] for z in load_probes().get('зонды', []) if z.get('сила') in strength and not (wp and 'WordPress' in z.get('условие', ''))]
    return '|'.join(f'(?:{x})' for x in parts) or r'^$'


def mark_scanners(V, R, engines=()):
    """Сканеры под браузер — по сигнатурам из probes.json, без порогов (один однозначный зонд — уже факт):
    однозначный зонд; перебор неоднозначных зондов; перебор вариантов одного файла; веер 404 по разным страницам."""
    V = V.copy()
    sig = {x['id']: x for x in load_probes().get('сигнатуры', [])}
    cats = R['base'].cat.categories.to_series().astype(str)
    codes = R['base'].cat.codes.values
    vid, st = R['vid'].values, R['status'].values
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)   # группы в шаблонах справочника — не для извлечения
        from urllib.parse import unquote
        dec = cats.map(unquote)   # /.%65%6e%76 и /%D0%BA%D0%BE%D0%BD%D1%82%D0%B0%D0%BA%D1%82%D1%8B — тоже зонды
        def hit_(strength):
            rx_ = probe_rx(strength, engines)
            return (cats.str.contains(rx_, regex=True, case=False) | dec.str.contains(rx_, regex=True, case=False)).values[codes]
        strong, weak = hit_(('однозначный',)), hit_(('неоднозначный',))
    why = pd.Series('', index=V.index, dtype=object)
    why[V.index.isin(pd.unique(vid[strong]))] = sig.get('probe_hit', {}).get('название', 'Однозначный зонд')
    # общий критерий: в сигнатурах перебора считаются только адреса, которые обращающийся выбрал сам. Ресурсы и ссылки,
    # которые браузер взял со страниц сайта (реферер — страница сайта), — ошибки сайта, а не перебор. Реферер «сам на себя» — подделка.
    chosen = ~R['ref_internal'].values.astype(bool) | (R['ref_path'].astype(str).values == cats.values[codes])
    miss = weak & chosen & (st >= 400) & (st < 500)   # неоднозначный зонд, которого на сайте нет
    W = pd.DataFrame({'vid': vid[miss], 'b': codes[miss], 'ok': np.zeros(int(miss.sum()), bool)})
    if len(W):
        g = W.groupby('vid').agg(n=('b', 'nunique'), ok=('ok', 'any'))
        hit = g[(g['n'] >= sig.get('probe_series', {}).get('минимум_адресов', 3)) & ~g['ok']].index
        why[V.index.isin(hit) & (why == '')] = sig.get('probe_series', {}).get('название', 'Перебор зондов')
        W['ip'] = V['ip'].reindex(W['vid']).values; W['ua'] = V['ua'].reindex(W['vid']).values
        gi = W.groupby(['ip', 'ua']).agg(n=('b', 'nunique'), ok=('ok', 'any'))
        bad_ = gi[(gi['n'] >= sig.get('probe_series', {}).get('минимум_адресов', 3)) & ~gi['ok']].index
        if len(bad_):
            key = pd.MultiIndex.from_arrays([V['ip'], V['ua']])
            why[key.isin(bad_) & (why == '').values] = sig.get('probe_series', {}).get('название', 'Перебор зондов')
    e4 = (st >= 400) & (st < 500) & chosen
    E = pd.DataFrame({'vid': vid[e4], 'b': cats.values[codes[e4]]})
    if len(E):   # варианты одного имени: .env / .env.local / .env.bak; backup.zip / backup.tar.gz
        E['stem'] = E['b'].str.extract(r'/(\.?[^/.]+)[^/]*$')[0]
        E = E[E['stem'].notna() & (E['b'].str.count(r'\.') >= 1)]
        g = E.groupby(['vid', 'stem'])['b'].nunique()
        hit = g[g >= sig.get('variants', {}).get('минимум_вариантов', 3)].index.get_level_values(0).unique()
        why[V.index.isin(hit) & (why == '')] = sig.get('variants', {}).get('название', 'Перебор вариантов одного файла')
    pg = R['is_page'].values & chosen
    Pg = pd.DataFrame({'vid': vid[pg], 'b': codes[pg], 'e': (st[pg] >= 400) & (st[pg] < 500), 'ok': (st[pg] >= 200) & (st[pg] < 300)})
    if len(Pg):
        g = Pg.groupby('vid').agg(n=('b', 'nunique'), ok=('ok', 'any'), e=('e', 'all'))
        hit = g[(g['n'] >= sig.get('fan_404', {}).get('минимум_адресов', 5)) & g['e'] & ~g['ok']].index
        why[V.index.isin(hit) & (why == '')] = sig.get('fan_404', {}).get('название', 'Веер 404')
        # то же по IP и браузеру за весь период: перебор разбит на короткие визиты
        Pg['ip'] = V['ip'].reindex(Pg['vid']).values; Pg['ua'] = V['ua'].reindex(Pg['vid']).values
        gi = Pg.groupby(['ip', 'ua']).agg(n=('b', 'nunique'), ok=('ok', 'any'), e=('e', 'all'))
        bad_ = gi[(gi['n'] >= sig.get('fan_404_ip', {}).get('минимум_адресов', 5)) & gi['e'] & ~gi['ok']].index
        if len(bad_):
            key = pd.MultiIndex.from_arrays([V['ip'], V['ua']])
            why[key.isin(bad_) & (why == '').values] = sig.get('fan_404_ip', {}).get('название', 'Веер 404 с одного адреса')
    m = (why != '') & (V['group'] == 'Люди')
    kind = actor_kind(V, R, m, strong | weak)
    # визит с N и больше запросов к однозначным зондам — сканер, сколько бы «статики» он ни грузил (N — data/thresholds.json)
    from .thresholds import value
    ns = pd.Series(np.bincount(vid[strong], minlength=int(vid.max()) + 1 if len(vid) else 0)).reindex(V.index).fillna(0)
    many = m & (ns >= value('зондов_в_визите_сканер_от', 10))
    kind[many] = _actors()['выводы']['сканер']
    V.loc[m, 'group'] = 'Боты'
    V.loc[m, 'subgroup'] = kind[m] + ': ' + why[m].str.lower()
    return V


def _actors():
    import json, os
    return json.load(open(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference', 'actors.json')), encoding='utf-8'))


def rendered_static(R):
    """Сколько файлов в каждом визите подгрузила страница этого же визита: реферер — страница сайта, открытая в визите.
    Только такая «статика» — признак, что браузер отрисовал страницу; файлы без реферера или со ссылкой на чужую страницу — нет."""
    vid = R['vid'].values
    cats = R['base'].cat.categories
    codes = R['base'].cat.codes.values.astype(np.int64)
    L = len(cats) + 1
    opened = ~R['is_static'].values & np.isin(R['method'].values, ['GET', 'HEAD'])   # страницы визита (с повторами и переадресациями)
    pages = np.unique(vid[opened].astype(np.int64) * L + codes[opened])
    st = R['is_static'].values & R['ref_internal'].values.astype(bool)
    rp = R['ref_path'].astype(str).values[st]
    rc = pd.Index(cats).get_indexer(rp).astype(np.int64)
    ok = (rc >= 0) & np.isin(vid[st].astype(np.int64) * L + rc, pages)
    return pd.Series(vid[st][ok]).value_counts()


def mark_unrendered(V, R):
    """«Люди» со страницами, но без единого файла, подгруженного страницей визита, — не браузер, который отрисовал страницу
    (сканер со «статикой» чужого движка). Так же, как визит без загрузки ресурсов вообще."""
    V = V.copy()
    m = (V['group'] == 'Люди') & (V['n_pages'] >= 1) & (V['n_static'] > 0) & (V['n_embedded'] == 0)
    if not m.any(): return V
    m &= rendered_static(R).reindex(V.index).fillna(0).values == 0
    V.loc[m, 'group'] = 'Боты'
    V.loc[m, 'subgroup'] = 'маскирующиеся: без загрузки ресурсов'
    return V


def actor_kind(V, R, m, probe):
    """Кто стоит за подозрительными визитами (IP + браузер за весь период): автомат или живой человек.
    Улики с весами — data/reference/actors.json. Подозрение уже доказано сигнатурами; здесь решается только «кто»."""
    import json, os
    A = json.load(open(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference', 'actors.json')), encoding='utf-8'))
    H, out = A['человечность'], A['выводы']
    kind = pd.Series(out['сканер'], index=V.index, dtype=object)
    if not m.any(): return kind
    key = V['ip'].astype(str) + '|' + V['ua'].astype(str)
    sus = set(key[m])
    Vs = V[key.isin(sus)].assign(k=key[key.isin(sus)])
    days_ = Vs[m.reindex(Vs.index).values].groupby('k')['day'].nunique()   # регулярность — по дням с подозрительными визитами
    g = Vs.groupby('k').agg(res=('n_static', lambda s: (s > 0).mean()), req=('n_req', 'sum'), dur=('dur', 'sum'),
                            net=('nettype', 'first'), br=('ua_browser', 'first'), days=('day', 'nunique'))
    rk = key.reindex(R['vid'].values).values
    insus = pd.Series(rk).isin(sus).values
    st = R['status'].values
    pages_ok = pd.Series(rk[insus & R['is_page'].values & (st >= 200) & (st < 300) & ~probe]).value_counts()
    probes_n = pd.Series(rk[insus & probe]).value_counts()
    # темп зондов: человек набирает адреса руками — секунды между попытками; автомат сыплет их подряд
    P_ = pd.DataFrame({'k': rk[insus & probe], 't': R['ts'].values[insus & probe]}).sort_values(['k', 't'])
    gap = P_.groupby('k')['t'].diff().groupby(P_['k']).median()
    fast_ = gap.reindex(g.index) < A.get('зонды_человека_не_чаще_сек', 3)
    # общий список: те же зонды просят и другие подозрительные адреса — это словарь программы (и распределённый скан), а не догадки человека
    P_['b'] = R['base'].cat.codes.values[insus & probe]
    P_['ip'] = P_['k'].str.split('|').str[0]
    others = P_.groupby('b')['ip'].nunique()
    share_ = (P_.assign(o=P_['b'].map(others)).drop_duplicates(['k', 'b']).groupby('k')['o']
              .apply(lambda o: (o > A.get('общий_список_адресов_от', 3)).mean()))
    common_ = share_.reindex(g.index).fillna(0) >= 0.5
    # ресурсы, которые браузер взял со страниц сайта (картинки, стили по рефереру-странице), — признак настоящей отрисовки;
    # архивы и прочие «файлы» без реферера в счёт не идут
    rend = pd.Series(rk[insus & R['is_static'].values & R['ref_internal'].values.astype(bool)]).value_counts()
    # смена браузера на каждом запросе с одного IP — ротация User-Agent, так делают программы
    nua = pd.Series(V.loc[m, 'ua'].astype(str).values, index=V.loc[m, 'ip'].astype(str).values).groupby(level=0).nunique()
    rot_ = g.index.str.split('|').str[0].map(nua).fillna(1).values > A.get('браузеров_с_IP_не_больше', 3)
    score = (H['грузит_ресурсы']['вес'] * (rend.reindex(g.index).fillna(0) >= 3)
             + H['живой_темп']['вес'] * (g['req'] / g['dur'].clip(lower=1) < H['живой_темп']['порог_запросов_в_секунду'])
             + H['домашняя_сеть']['вес'] * ~g['net'].isin(['хостинг/облако', 'VPN/прокси-релей'])
             + H['браузер']['вес'] * g['br'].astype(bool)
             + H['ходит_по_сайту']['вес'] * (pages_ok.reindex(g.index).fillna(0) > 0))
    human = (score >= A['человек_если_баллов_от']) & ~g['net'].isin(A.get('автомат_если_сеть', [])) & ~fast_.fillna(False) & ~common_ & ~rot_ & (probes_n.reindex(g.index).fillna(0) <= A['человек_не_больше_зондов'])
    regular = days_.reindex(g.index).fillna(0) >= A['регулярно_если_дней_от']
    lab = pd.Series(out['сканер'], index=g.index, dtype=object)
    lab[human & ~regular] = out['человек_разово']
    lab[human & regular] = out['человек_регулярно']
    kind[m] = key[m].map(lab).fillna(out['сканер'])
    return kind


def impossible_ua(ua, year=None):
    """Невозможная версия в User-Agent — признак генератора: Windows 95/98/NT 4, iPhone OS старше порога, Gecko/дата сборки из будущего."""
    from .thresholds import value
    ua = str(ua)
    if re.search(r'Windows 95|Windows 98|Win 9x|Windows NT 4\.0', ua): return True
    m = re.search(r'(?:iPhone|CPU) OS (\d+)_', ua)
    if m and int(m.group(1)) < value('ua_ios_не_старше', 7): return True
    m = re.search(r'Gecko/(20\d{2})(\d{2})(\d{2})\b', ua)   # Firefox пишет Gecko/20100101; дата сборки после года лога — выдумана
    if m and year and int(m.group(1)) > year: return True
    return False


def mark_files_only(V, R):
    """Визит без единой страницы, только файлы (без POST и подгружаемых блоков), — не «Люди»: скрапер картинок, превью.
    Исключения: продолжение визита человека (файлы подгружены страницей сайта, и тот же IP с тем же браузером смотрел страницы
    в соседнем визите — пауза больше 30 минут разрезала визит) и человек из поиска по картинкам (реферер — поисковик):
    оба остаются «Людьми». Хотлинк (файлы подгружает чужой сайт: реферер — чужой домен) — группа «Чужой сайт», не боты:
    это посетители другого сайта, их IP не попадают в дела, «Меры по IP» и STIX."""
    V = V.copy()
    m = (V['group'] == 'Люди') & (V['n_pages_raw'] == 0) & (V['n_post'] == 0) & (V['n_embedded'] == 0) & (V['n_static'] > 0)
    if not m.any(): return V
    vid = R['vid'].values
    ext_ref = ~R['ref_internal'].values.astype(bool) & ~R['ref'].astype(str).isin(['-', '']).values
    rh = R['ref_host'].astype(str)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)   # группы в шаблоне поисковиков — не для извлечения
        search_ref = ext_ref & rh.str.contains(SEARCH, regex=True).values   # Яндекс/Google Картинки и другие поисковики
    own_ref = pd.Series(R['ref_internal'].values.astype(bool)).groupby(vid).all()
    any_ext = pd.Series(ext_ref & ~search_ref).groupby(vid).any()
    any_search = pd.Series(search_ref).groupby(vid).any()
    only4 = pd.Series((R['status'].values >= 400) & (R['status'].values < 500)).groupby(vid).all()
    key = V['ip'].astype(str) + '|' + V['ua'].astype(str)
    browsing = set(key[(V['group'] == 'Люди') & (V['n_pages'] > 0)])
    cont = m & own_ref.reindex(V.index).fillna(False).values & key.isin(browsing)
    m &= ~cont
    img = m & any_search.reindex(V.index).fillna(False).values   # человек из поиска по картинкам — «Люди»
    V.loc[img, 'subgroup'] = 'из поиска по картинкам'
    m &= ~img
    hot = m & any_ext.reindex(V.index).fillna(False).values   # хотлинк — посетители чужого сайта, не боты
    V.loc[hot, 'group'] = 'Чужой сайт'
    V.loc[hot, 'subgroup'] = 'хотлинк'
    m &= ~hot
    year = int(pd.to_datetime(V['end'].max(), unit='s').year)
    imp = pd.Series([impossible_ua(u, year) for u in V['ua']], index=V.index)
    sub = np.select([imp.values,
                     V['nettype'].isin(['хостинг/облако', 'VPN/прокси-релей']).values, only4.reindex(V.index).fillna(False).values,
                     (V['entry_ref'].isin(['-', ''])).values],
                    ['генератор User-Agent', 'скрапер с хостинга', 'только ошибки 4xx', 'прямой заход'], 'прочие')
    V.loc[m, 'group'] = 'Боты'
    V.loc[m, 'subgroup'] = 'файлы без страниц: ' + pd.Series(sub, index=V.index)[m]
    return V


def audience(V):
    """Страна основной аудитории — самая частая среди визитов людей — и доля людей из неё; предупреждение, если доля ниже порога."""
    from .thresholds import value
    H = V[V['group'] == 'Люди']
    if not len(H): return None
    cc = H['cc'].astype(str).replace('', '?').value_counts()
    share = round(float(cc.iloc[0]) / len(H) * 100, 1)
    lim = value('люди_из_основной_страны_%', 50)
    return dict(страна=cc.index[0], доля=share, порог=lim, предупреждение=share < lim)


def mark_form_spam(V, R):
    """Поведенческие признаки спама форм (универсальные). Переводит такие визиты в группу «Боты»."""
    V = V.copy()
    g = V['n_goal'] > 0
    direct = V['entry_ref'].isin(['-', ''])
    ext_nosearch = ~V['entry_ref_internal'] & ~direct & ~V['entry_ref_host'].str.contains(SEARCH, regex=True)
    cls = pd.Series('', index=V.index, dtype=object)
    cls[g & (V['entry_status'] == 404) & (direct | ext_nosearch) & (V['n_pages'] <= 6)] = 'спам форм: битый адрес → главная → форма'
    nopage = g & (V['n_pages'] == 0) & (cls == '')
    # исключение: тот же человек сменил IP (мобильная сеть, прокси браузера) — страницу из реферера за ≤30 мин до отправки
    # открыл другой IP с тем же самым UA и это обычный визит человека; путь «/» не в счёт — слишком частый
    same_user = pd.Series(False, index=V.index)
    for vid in V.index[nopage & V['entry_ref_internal']]:
        path = re.sub(r'^https?://[^/]+', '', V.at[vid, 'entry_ref']).split('?')[0]
        if path in ('', '/'): continue
        t, ua, ip = V.at[vid, 'start'], V.at[vid, 'ua'], V.at[vid, 'ip']
        o = V[(V['ua'] == ua) & (V['ip'] != ip) & (V['group'] == 'Люди') & (V['start'] <= t) & (V['end'] >= t - 1800) & (V['n_pages'] > 0)]
        if len(o) and path in set(R.loc[R['vid'].isin(o.index) & (R['base'] == path), 'base'].astype(str)):
            same_user[vid] = True
    cls[nopage & (V['n_static'] == 0) & ~same_user] = 'спам форм: отправка без просмотра страниц'
    # страница открыта другим IP: этот IP грузил только картинки/скрипты и отправил форму, а саму страницу не открывал (хостинг/VPN)
    cls[nopage & (V['n_static'] > 0) & V['entry_ref_internal'] & ~same_user & V['nettype'].isin(['хостинг/облако', 'VPN/прокси-релей']) & (cls == '')] = 'спам форм: страницу открыл другой IP'
    fast = g & (V['n_goal'] >= 2) & (V['n_pages'] >= 5) & (V['n_pages'] / V['dur'].clip(lower=1) > 0.4)
    cls[fast & (cls == '')] = 'спам форм: быстрый обход и пачка отправок'
    # смена IP посреди визита: вход со страницы сайта, которую за <= 2 ч до этого открыл ДРУГОЙ IP и получил 404
    e404 = V[(V['entry_status'] == 404)][['ip', 'start', 'entry']]
    if len(e404):
        last404 = e404.sort_values('start').groupby('entry').agg(list)
        cand = V[g & V['entry_ref_internal'] & (cls == '')]
        for vid, r in cand.iterrows():
            path = re.sub(r'^https?://[^/]+', '', r['entry_ref']).split('?')[0]
            if path in last404.index:
                ips, ts_ = last404.loc[path, 'ip'], last404.loc[path, 'start']
                if any(i != r['ip'] and 0 <= r['start'] - t <= 7200 for i, t in zip(ips, ts_)):
                    cls[vid] = 'спам форм: смена IP посреди визита'
    # тот же IP уже пойман (±7 дней) — его быстрые заявки с прямого захода тоже спам
    caught = V.loc[cls != '', ['ip', 'start']]
    quick = g & direct & (V['n_pages'] <= 2) & (V['dur'] < 120) & (cls == '')
    for vid in V.index[quick]:
        t = caught.loc[caught['ip'] == V.at[vid, 'ip'], 'start']
        if len(t) and (abs(t - V.at[vid, 'start']) <= 7 * 86400).any():
            cls[vid] = 'спам форм: быстрая заявка с IP, уже пойманного за неделю'
    m = (cls != '') & (V['group'].isin(['Люди', 'Боты']))
    V.loc[m, 'group'] = 'Боты'
    V.loc[m, 'subgroup'] = cls[m]
    return V



SUCCESS_MARK = r'(?:^|&)(success|formresult|result|sent|ok|status)=(?!$|0|false|error)|thank|spasibo|blagodar'


def confirm_form_success(R, V, window=10):
    """Успех заявки = переадресация 302/303 И подтверждение следующим запросом того же IP (≤ window с):
    адрес с меткой успеха (success=, formresult=addok, «спасибо») или возврат на страницу, с которой отправляли.
    Неподтверждённые переадресации не считаются заявками. Возвращает (R, V, улики по формам)."""
    import re
    import pandas as pd
    if 'goal' not in R or 'goal_success' not in R: return R, V, {}
    g = R['goal'].astype(str).values
    post = (g != '') & (g != 'nan') & (R['method'].values == 'POST')
    idx = np.flatnonzero(post)
    if not len(idx): return R, V, {}
    ipc = R['ip'].cat.codes.values.astype(np.int64)
    ts = R['ts'].values.astype(np.int64)
    ips = np.unique(ipc[idx])
    near = np.flatnonzero(np.isin(ipc, ips) & ~R['is_static'].values)
    near = near[np.argsort(ipc[near] * 10 ** 11 + ts[near], kind='stable')]
    key = ipc[near].astype(np.int64) * 10 ** 11 + ts[near]
    qcat = R['query'].cat.categories.to_series().str.contains(SUCCESS_MARK, regex=True, case=False).values
    bcat = R['base'].cat.categories.to_series().str.contains(SUCCESS_MARK, regex=True, case=False).values
    ok_mark = qcat[R['query'].cat.codes.values] | bcat[R['base'].cat.codes.values]
    st = R['status'].values
    ref = R['ref_path'].astype(str).values if 'ref_path' in R else np.array([''] * len(R))
    base = R['base'].astype(str).values
    conf = {}
    ev = {}
    for i in idx:
        k0 = ipc[i] * 10 ** 11 + ts[i]
        lo, hi = np.searchsorted(key, k0), np.searchsorted(key, k0 + window, side='right')
        how = ''
        for j in near[lo:hi]:
            if j == i or (R['method'].values[j] == 'POST'): continue
            if ok_mark[j]: how = 'страница с меткой успеха'; break
            if ref[i] and base[j] == ref[i]: how = 'возврат на страницу формы'; break
        conf[i] = how
        e = ev.setdefault(g[i], dict(отправок=0, редиректов=0, подтверждено=0, как={}))
        e['отправок'] += 1
        if st[i] in (302, 303):
            e['редиректов'] += 1
            if how:
                e['подтверждено'] += 1; e['как'][how] = e['как'].get(how, 0) + 1
    chk = np.array([''] * len(R), dtype=object)
    for i, h in conf.items(): chk[i] = h
    R = R.assign(goal_check=chk)   # чем подтверждён успех отправки (пусто — не подтверждён)
    gs = R['goal_success'].values.copy()
    demote = np.array([i for i in idx if st[i] in (302, 303) and gs[i] and not conf[i]], dtype=np.int64)
    if len(demote):
        gs[demote] = False
        R = R.assign(goal_success=gs)
        if 'vid' in R and 'n_conv' in V:
            dv = pd.Series(R['vid'].values[demote]).value_counts()
            V = V.copy(); V.loc[dv.index, 'n_conv'] = (V.loc[dv.index, 'n_conv'] - dv.values).clip(lower=0)
    return R, V, ev
