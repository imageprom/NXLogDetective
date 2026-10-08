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


UTIL_LABEL = {'Скрипты: прочие': 'Прочие утилиты'}


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
             + H['домашняя_сеть']['вес'] * ~(g['net'].astype(str).str.startswith('дата-центр') | (g['net'] == 'VPN/прокси-релей'))
             + H['браузер']['вес'] * g['br'].astype(bool)
             + H['ходит_по_сайту']['вес'] * (pages_ok.reindex(g.index).fillna(0) > 0))
    human = (score >= A['человек_если_баллов_от']) & ~g['net'].astype(str).str.startswith(tuple(A.get('автомат_если_сеть', [])) or ('\x00',)) & ~fast_.fillna(False) & ~common_ & ~rot_ & (probes_n.reindex(g.index).fillna(0) <= A['человек_не_больше_зондов'])
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


DC_NETS = ('дата-центр', 'Яндекс')   # дата-центры (по началу подписи: «дата-центр (компания)»): серверы, а не люди
HOME_NETS = ('мобильный оператор', 'RU провайдер доступа', 'зарубежный провайдер доступа')   # домашние и мобильные сети


_FG = None


def file_groups():
    """Справочник групп файлов (data/reference/file_groups.json) и составные шаблоны: служебные файлы, чувствительные адреса
    (вместе с «backup_paths» движков), перенос сайта."""
    global _FG
    if _FG is None:
        import json, os
        from .reference import engine_backup_paths
        ref = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference'))
        G = json.load(open(os.path.join(ref, 'file_groups.json'), encoding='utf-8'))
        ext = json.load(open(os.path.join(ref, 'extensions.json'), encoding='utf-8'))
        wk = next((g['шаблон'] for g in ext.get('по_адресу', []) if g.get('группа') == 'Служебные (.well-known)'), None)
        G['service_rx'] = G['service_files'] + (f'|{wk}' if wk else '')
        G['sensitive_rx'] = '|'.join(f'(?:{x})' for x in G['sensitive'] + engine_backup_paths())
        G['transfer_rx'] = '|'.join(f'(?:{x})' for x in G['transfer'])
        _FG = G
    return _FG


def _cat_mask(R, rx):
    """Шаблон по категориям адресов R['base'] → булев массив по категориям."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        return R['base'].cat.categories.to_series().astype(str).str.contains(rx, regex=True, case=False).values


def _page_form(R, page_form=None):
    """Адрес — страница по реестру (classify.form_of) — булев массив по категориям R['base']."""
    if page_form is not None: return np.asarray(page_form, bool)
    from .classify import form_of
    return np.array([form_of(p_)[0] == 'страница' for p_ in R['base'].cat.categories.astype(str)], bool)


def mark_backups(V, R, staff_ips=(), admin_rx=None):
    """Чувствительные адреса (file_groups.json «sensitive» и «backup_paths» движков: бэкапы, дампы, архивы сайта в корне,
    restore.php, .env) с ответом 200 — раньше всех правил «только файлы». 403/404 на них — зонд, как и раньше (здесь не трогаются).
    - перед скачиванием с того же IP или тем же браузером — успешный вход в админку, затем перенос (restore.php, архив частями
      .tar.gz.1…) — «Свои · скачал бэкап»: обвинений нет (profiles снимает их);
    - перед скачиванием искал бэкапы по разным адресам (403/404, порог backup_search_min_paths) или бэкап скачан многими IP
      (порог backup_many_ips) — дело: «Боты · скачал бэкап»; доступность бэкапа — находка «Сервер отдал служебные файлы»;
    - иначе (разовое скачивание без связи с админкой и без поиска) — «Подозрительные лица · скачал бэкап».
    Возвращает (V, список фактов для res['backups'])."""
    from .thresholds import value
    V = V.copy()
    G = file_groups()
    sens_c = _cat_mask(R, G['sensitive_rx'])
    codes = R['base'].cat.codes.values
    st = R['status'].values
    sens = sens_c[codes]
    got = sens & (st == 200) & (R['bytes'].values > 0)
    if not got.any(): return V, []
    V['evidence_people'] = V.get('evidence_people', pd.Series('', index=V.index)).fillna('')
    V['evidence_bot'] = V.get('evidence_bot', pd.Series('', index=V.index)).fillna('')
    cats = R['base'].cat.categories.astype(str)
    ips, uas, ts, vid = R['ip'].astype(str).values, R['ua'].astype(str).values, R['ts'].values, R['vid'].values
    # успешный вход в админку: IP сотрудников (recon.admin_staff) — их ответы 200 в админке; браузер — тот же User-Agent
    staff = set(staff_ips)
    adm = np.zeros(len(R), bool)
    if admin_rx and staff:
        adm = _cat_mask(R, admin_rx)[codes] & np.isin(ips, list(staff)) & (st == 200)
    A = pd.DataFrame({'ip': ips[adm], 'ua': uas[adm], 't': ts[adm]})
    adm_ip, adm_ua = A.groupby('ip')['t'].min(), A.groupby('ua')['t'].min()
    tr = _cat_mask(R, G['transfer_rx'])[codes] & (st < 400)
    Tr = pd.DataFrame({'ip': ips[tr], 'ua': uas[tr], 't': ts[tr]})
    probe_ = sens | _cat_mask(R, probe_rx(('однозначный', 'неоднозначный')))[codes]
    miss = probe_ & ((st == 403) | (st == 404))
    Mi = pd.DataFrame({'ip': ips[miss], 'b': codes[miss], 't': ts[miss]})
    D = pd.DataFrame({'ip': ips[got], 'ua': uas[got], 't': ts[got], 'b': codes[got], 'vid': vid[got]})
    many = D.groupby('b')['ip'].nunique()
    lim_many, lim_search = value('backup_many_ips', 3), value('backup_search_min_paths', 2)
    facts = []
    for (ip, ua, b), g in D.groupby(['ip', 'ua', 'b'], sort=False):
        t = int(g['t'].min())
        t_adm = min([x for x in (adm_ip.get(ip), adm_ua.get(ua)) if x is not None], default=None)
        admin_before = t_adm is not None and t_adm <= t
        transfer = admin_before and bool((Tr.loc[(Tr['ip'] == ip) | (Tr['ua'] == ua), 't'] >= t_adm).any())
        searched = Mi.loc[(Mi['ip'] == ip) & (Mi['t'] < t), 'b'].nunique() >= lim_search
        crowd = int(many.get(b, 0)) >= lim_many
        if admin_before and transfer:
            grp, verdict = 'Свои', 'свой перенос: вход в админку, затем перенос'
        elif searched or crowd:
            grp, verdict = 'Боты', ('искал бэкапы перед скачиванием' if searched else f'бэкап скачан многими IP ({int(many.get(b, 0))})')
        else:
            grp, verdict = 'Подозрительные лица', 'разовое скачивание без связи с админкой и без поиска бэкапов'
        vs = g['vid'].unique()
        mv = V.index.isin(vs) & ~V['group'].isin(['Роботы', 'Системы мониторинга']).values
        # одна и та же пара (IP, браузер) — один вывод; «дело» сильнее «подозрения», «свои» — сильнее всего
        rank = {'Подозрительные лица': 0, 'Боты': 1, 'Свои': 2}
        cur = V.loc[mv, 'subgroup'].astype(str) == 'скачал бэкап'
        keep = cur & (V.loc[mv, 'group'].map(rank).fillna(-1) > rank[grp])
        idx = V.index[mv][~keep.values]
        V.loc[idx, 'group'] = grp; V.loc[idx, 'subgroup'] = 'скачал бэкап'
        pe = ['вход в админку перед скачиванием'] if admin_before else []
        pe += ['перенос: restore.php или архив частями'] if transfer else []
        be = (['искал бэкапы по разным адресам'] if searched else []) + (['бэкап скачан многими IP'] if crowd else [])
        V.loc[idx, 'evidence_people'] = '; '.join(pe); V.loc[idx, 'evidence_bot'] = '; '.join(be)
        facts.append(dict(ip=ip, ua=ua, файл=cats[b], время=t, категория=grp, вывод=verdict, улики_за_людей='; '.join(pe), улики_за_бота='; '.join(be)))
    return V, facts


def mark_files_only(V, R, own_hosts=(), page_form=None):
    """Визит «Людей» без страниц, без POST и подгружаемых блоков — только файлы (служебные файлы: robots.txt, sitemap*, favicon,
    apple-touch-icon, стандартные /.well-known/ — не в счёт; визиты с чувствительными адресами — mark_backups, не сюда).
    Решает поведение, сеть — слабая подсказка. Улики (пороги — data/thresholds.json, files_*):
      за людей: соседи по адресу (сильно: с этого IP в окне смотрят страницы визиты «Люди»); офис (слабо: много браузеров на IP,
                рабочие часы, будни); домашняя или мобильная сеть (слабо);
      за бота:  выдуманный браузер (твёрдо); обход по списку, повторы, много 404 (сильно); дата-центр (слабо).
    Боты — сильная улика за бота и нет сильной за людей; Люди — есть признаки людей и нет улик за бота; иначе — Подозрительные лица.
    Ярлыки по порядку: выдуманный браузер → «Боты · только файлы: выдуманный браузер»; реферер — хост из own_hosts → «Свои · свои
    системы»; соседи по адресу → «Люди»; скачивание (file_groups.json) → «Люди · скачал документ» / «Боты · только файлы: скрапер»
    (обход по списку или повторы) / «Подозрительные лица · скачал документ»; обвес: поисковик → «Люди · из поиска по картинкам»;
    почти одни 404 → «Люди» / «Боты · только файлы: запрашивает несуществующие файлы» / «Подозрительные лица»; страницы своего
    сайта → «Люди» / «Боты · только файлы: скрапер» / «Подозрительные лица»; внешний сайт → «Люди · хотлинк» / скрапер /
    «Внешние сайты · хотлинк»; без реферера → «Люди · открыл файл по прямой ссылке» / скрапер / «Подозрительные лица».
    Улики за обе версии — в V['evidence_people'] и V['evidence_bot']."""
    from .thresholds import value
    import warnings
    V = V.copy()
    for col in ('evidence_people', 'evidence_bot'):
        V[col] = V[col].fillna('') if col in V else ''
    G = file_groups()
    vid = R['vid'].values
    codes = R['base'].cat.codes.values
    st = R['status'].values
    pagey = _page_form(R, page_form)[codes]
    svc = _cat_mask(R, G['service_rx'])[codes]
    sens = _cat_mask(R, G['sensitive_rx'])[codes]
    per = lambda x: pd.Series(x).groupby(vid)
    has_page = per(pagey).any().reindex(V.index).fillna(False).values
    has_file = per(~pagey & ~svc).any().reindex(V.index).fillna(False).values
    has_sens = per(sens).any().reindex(V.index).fillna(False).values
    m = ((V['group'] == 'Люди').values & ~has_page & has_file & ~has_sens & (V['n_post'] == 0).values & (V['n_embedded'] == 0).values)
    if not m.any(): return V
    m = pd.Series(m, index=V.index)
    rows = np.isin(vid, V.index[m]) & ~svc   # файлы визитов «только файлы», без служебных
    cats = R['base'].cat.categories.to_series().astype(str).reset_index(drop=True)
    # группы файлов: скачивание или обвес
    leaf = cats.str.rsplit('/', n=1).str[-1].str.lower()
    ext_c = np.where(leaf.str.endswith('.tar.gz'), 'tar.gz', leaf.str.extract(r'\.([a-z0-9]{1,10})$')[0].fillna('').values)
    lc = cats.str.lower()
    dl_c = np.zeros(len(cats), bool); media_c = np.zeros(len(cats), bool)
    for g in G['download_groups']:
        e_ = np.isin(ext_c, g['ext'])
        if g['key'] == 'media':
            media_c |= e_ | np.isin(ext_c, g.get('photo_ext', []))
            continue
        if g.get('dirs'):
            e_ &= lc.str.contains('|'.join(re.escape(d) for d in g['dirs']), regex=True).values
        if g.get('not_dirs'):
            e_ &= ~lc.str.contains('|'.join(re.escape(d) for d in g['not_dirs']), regex=True).values
        dl_c |= e_
    ok = (st >= 200) & (st < 300)
    dl = rows & ((dl_c[codes] & ok) | (media_c[codes] & (st == 200) & (R['bytes'].values >= value('files_media_download_min_bytes', 2000000))))
    asset = rows & np.isin(ext_c, G['page_assets'])[codes]
    e4 = rows & (st >= 400) & (st < 500)
    # рефереры файлов визита
    rh = R['ref_host'].astype(str).str.lower().str.removeprefix('www.')
    has_ref = ~R['ref'].astype(str).isin(['-', '']).values
    own = {h.lower().removeprefix('www.') for h in own_hosts}
    own_sys = rows & has_ref & rh.isin(own).values
    inner = rows & has_ref & R['ref_internal'].values.astype(bool) & ~own_sys
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        search_ref = rows & has_ref & ~inner & ~own_sys & rh.str.contains(SEARCH, regex=True).values
    ext_ref = rows & has_ref & ~inner & ~own_sys & ~search_ref
    vany = lambda x: per(x).any().reindex(V.index).fillna(False).values
    vsum = lambda x: per(x).sum().reindex(V.index).fillna(0).values
    # улики по адресу (IP + браузер) за период — по файлам его визитов «только файлы»
    key = V['ip'].astype(str) + '|' + V['ua'].astype(str)
    rk = key.reindex(vid[rows]).values
    F = pd.DataFrame({'k': rk, 'b': codes[rows], 't': R['ts'].values[rows], 'st': st[rows], 'asset': asset[rows],
                      'day': R['ts'].values[rows] // 86400})
    n404 = F[(F['st'] >= 400) & (F['st'] < 500)].groupby('k').size()
    rep = F[F['st'] == 200].groupby(['k', 'b', 'day']).size().groupby(level=0).max()
    num = cats.str.extract(r'(\d+)(?=\.[A-Za-z0-9]+$)')[0].astype(float).values
    dir_c = cats.str.replace(r'[^/]*$', '', regex=True).values
    lst_min, lst_share = value('files_list_min', 10), value('files_list_share', 0.8)
    crawl_k = set()
    Fo = F[(F['st'] >= 200) & (F['st'] < 300)]
    no_assets = ~F.groupby('k')['asset'].any()
    for k, g in Fo.groupby('k'):
        u = g.sort_values('t').drop_duplicates('b')['b'].values
        if len(u) < lst_min or not no_assets.get(k, True): continue
        n_ = num[u]
        seq = float(np.mean(np.diff(n_) == 1)) if len(n_) > 1 else 0.0
        dshare = pd.Series(dir_c[u]).value_counts().iloc[0] / len(u)
        if seq >= lst_share or dshare >= lst_share: crawl_k.add(k)
    crawl = key.isin(crawl_k).values
    repeats = key.map(rep).fillna(0).values >= value('files_repeat_min', 3)
    many404 = key.map(n404).fillna(0).values >= value('files_404_min', 5)
    year = int(pd.to_datetime(V['end'].max(), unit='s').year)
    imp = np.array([impossible_ua(u, year) if mm else False for u, mm in zip(V['ua'], m)])
    # соседи по адресу: с этого IP в окне до и после визита смотрят страницы визиты «Люди» (браузер любой)
    W = value('files_neighbors_window_min', 30) * 60
    P = V[(V['group'] == 'Люди').values & has_page & ~m.values][['ip', 'start', 'end']]
    neigh = np.zeros(len(V), bool)
    if len(P):
        ipcode = pd.Index(pd.unique(pd.concat([P['ip'], V.loc[m, 'ip']]).astype(str)))
        P = P.assign(c=ipcode.get_indexer(P['ip'].astype(str))).sort_values(['c', 'start'])
        P['cmax'] = P.groupby('c')['end'].cummax()
        BIG = np.int64(10 ** 11)
        pk = P['c'].values.astype(np.int64) * BIG + P['start'].values.astype(np.int64)
        C = V.loc[m, ['ip', 'start', 'end']]
        cc = ipcode.get_indexer(C['ip'].astype(str)).astype(np.int64)
        j = np.searchsorted(pk, cc * BIG + C['end'].values.astype(np.int64) + W, 'right') - 1
        okj = j >= 0
        jj = np.clip(j, 0, None)
        hit = okj & (P['c'].values[jj] == cc) & (P['cmax'].values[jj] >= C['start'].values - W)
        neigh[np.where(m.values)[0]] = hit
    # офис: много браузеров на IP у визитов «Люди», рабочие часы, будни
    nua = V[V['group'] == 'Люди'].groupby(V['ip'].astype(str))['ua'].nunique()
    h0, h1 = value('files_office_hours', [9, 19])
    office = ((V['ip'].astype(str).map(nua).fillna(0).values >= value('files_office_browsers_min', 3))
              & (V['hour'].values >= h0) & (V['hour'].values < h1) & (V['weekday'].values < 5))
    net = V['nettype'].astype(str)
    dc = net.str.startswith(DC_NETS).values
    home = net.isin(HOME_NETS).values
    strong_bot = imp | crawl | repeats | many404
    strong_ppl = neigh
    any_bot = strong_bot | dc
    any_ppl = strong_ppl | office | home
    is_bot = strong_bot & ~strong_ppl
    is_ppl = any_ppl & ~any_bot
    ev_p = [', '.join(x for x, f in (('соседи по адресу', a), ('офис: много браузеров, рабочие часы, будни', b_), ('домашняя или мобильная сеть', c_)) if f)
            for a, b_, c_ in zip(neigh, office, home)]
    ev_b = [', '.join(x for x, f in (('выдуманный браузер', a), ('обход по списку', b_), ('повторы', c_), ('много 404', d_), ('дата-центр', e_)) if f)
            for a, b_, c_, d_, e_ in zip(imp, crawl, repeats, many404, dc)]
    V.loc[m, 'evidence_people'] = pd.Series(ev_p, index=V.index)[m]
    V.loc[m, 'evidence_bot'] = pd.Series(ev_b, index=V.index)[m]
    has_dl, n_files, n4 = vany(dl), vsum(rows), vsum(e4)
    almost404 = (n4 >= 1) & (n4 >= value('files_almost_all_404_share', 0.8) * np.maximum(n_files, 1))
    a_own, a_search, a_inner, a_ext = vany(own_sys), vany(search_ref), vany(inner), vany(ext_ref)
    left = m.values.copy()
    def put(mask, grp, sub):
        nonlocal left
        mask = mask & left
        V.loc[mask, 'group'] = grp; V.loc[mask, 'subgroup'] = sub
        left &= ~mask
    def verdict(mask, ppl, bot, other):
        put(mask & is_ppl, *ppl); put(mask & is_bot, *bot); put(mask, *other)
    SCR = ('Боты', 'только файлы: скрапер')
    put(imp, 'Боты', 'только файлы: выдуманный браузер')                                                 # 1
    put(a_own, 'Свои', 'свои системы')                                                                    # 9: реферер — хост из own_hosts
    put(neigh, 'Люди', '')                                                                                # 2
    dlm = has_dl & left                                                                                   # 3
    put(dlm & is_ppl, 'Люди', 'скачал документ'); put(dlm & (crawl | repeats), *SCR); put(dlm, 'Подозрительные лица', 'скачал документ')
    put(a_search, 'Люди', 'из поиска по картинкам')                                                       # 4
    # 8 — раньше 5–7: те покрывают любой обвес (свой, внешний реферер, без реферера), и после них правило не сработало бы ни разу
    verdict(almost404, ('Люди', ''), ('Боты', 'только файлы: запрашивает несуществующие файлы'), ('Подозрительные лица', ''))   # 8
    verdict(a_inner, ('Люди', ''), SCR, ('Подозрительные лица', ''))                                       # 5
    verdict(a_ext, ('Люди', 'хотлинк'), SCR, ('Внешние сайты', 'хотлинк'))                                 # 6
    verdict(left, ('Люди', 'открыл файл по прямой ссылке'), SCR, ('Подозрительные лица', ''))              # 7
    return V


def mark_system_agents(V, R):
    """Системный агент на устройстве человека (data/reference/system_agents.json: автозаполнение паролей Apple и родственные),
    который в визите запрашивает только стандартные /.well-known/ (extensions.json, «Служебные (.well-known)»), — «Люди».
    Тот же UA с любым другим адресом — обычные правила."""
    import json, os
    ref = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference'))
    A = json.load(open(os.path.join(ref, 'system_agents.json'), encoding='utf-8')).get('agents', [])
    ext = json.load(open(os.path.join(ref, 'extensions.json'), encoding='utf-8'))
    rx = next((g['шаблон'] for g in ext.get('по_адресу', []) if g.get('группа') == 'Служебные (.well-known)'), None)
    if not A or rx is None: return V
    V = V.copy()
    only_wk = pd.Series(_cat_mask(R, rx)[R['base'].cat.codes.values]).groupby(R['vid'].values).all().reindex(V.index).fillna(False).values
    ua_rx = '|'.join(f"(?:{a['ua_pattern']})" for a in A)
    agent = V['ua'].astype(str).str.contains(ua_rx, regex=True).values
    m = only_wk & agent & (V['group'] != 'Свои').values
    V.loc[m, 'group'] = 'Люди'
    V.loc[m, 'subgroup'] = ''
    return V


def mark_service_checks(V, R):
    """Визит, в котором только запросы к стандартным файлам /.well-known/ (extensions.json, «Служебные (.well-known)»), из сети
    самого сервиса (data/reference/service_checks.json: Google, Apple, Akamai…) — «Роботы · проверка сервиса», не зонд и не бот."""
    import json, os
    ref = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference'))
    nets = {int(k) for k in json.load(open(os.path.join(ref, 'service_checks.json'), encoding='utf-8')).get('сети', {})}
    ext = json.load(open(os.path.join(ref, 'extensions.json'), encoding='utf-8'))
    rx = next((g['шаблон'] for g in ext.get('по_адресу', []) if g.get('группа') == 'Служебные (.well-known)'), None)
    if rx is None: return V
    V = V.copy()
    cats = R['base'].cat.categories.to_series().astype(str)
    wk = cats.str.contains(rx, regex=True).values[R['base'].cat.codes.values]
    only_wk = pd.Series(wk).groupby(R['vid'].values).all().reindex(V.index).fillna(False).values
    svc = only_wk & pd.to_numeric(V['asn'], errors='coerce').fillna(0).astype(int).isin(nets).values & (V['group'] != 'Свои').values
    V.loc[svc, 'group'] = 'Роботы'
    V.loc[svc, 'subgroup'] = 'проверка сервиса'
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
    cls[nopage & (V['n_static'] > 0) & V['entry_ref_internal'] & ~same_user & (V['nettype'].astype(str).str.startswith('дата-центр') | (V['nettype'] == 'VPN/прокси-релей')) & (cls == '')] = 'спам форм: страницу открыл другой IP'
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
