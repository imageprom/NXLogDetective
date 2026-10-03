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
    return V


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
    gs = R['goal_success'].values.copy()
    demote = np.array([i for i in idx if st[i] in (302, 303) and gs[i] and not conf[i]], dtype=np.int64)
    if len(demote):
        gs[demote] = False
        R = R.assign(goal_success=gs)
        if 'vid' in R and 'n_conv' in V:
            dv = pd.Series(R['vid'].values[demote]).value_counts()
            V = V.copy(); V.loc[dv.index, 'n_conv'] = (V.loc[dv.index, 'n_conv'] - dv.values).clip(lower=0)
    return R, V, ev
