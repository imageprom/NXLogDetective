"""NXLD: таблицы для расчётов — из базы проверки (work/nxld.duckdb).

База — единственное хранилище: запросы R, визиты V, сети T и error-лог E собираются из неё в том виде, в каком их оставил prepare
(до правил analyze — поэтому analyze можно запускать повторно). Для своих расчётов Детектива:

    from nxld import frames
    R, V = frames.requests('work'), frames.visits('work')
"""
import numpy as np, pandas as pd
from . import db, ingest, load, dims


def _con(src):
    return (db.connect(src, read_only=True), True) if isinstance(src, str) else (src, False)


def _cat(codes_source, values):
    return pd.Categorical(np.asarray(values, dtype=object)[codes_source])


def requests(src, with_ip_table=False):
    """Запросы (R): строка — запрос; копии сайта на других доменах не входят. Порядок — по времени."""
    con, own = _con(src)
    try:
        R = ingest.requests_frame(con, without_copies=True)
        R = load.read_features(R, con)
        H = dims.per_category(con, 'dim_host', 'host', ['scope'], R['vhost'].cat.categories)
        R['host_site'] = (H['scope'].values.astype(object) == 'site')[R['vhost'].cat.codes.values]
        R['ip'] = R['ip'].cat.remove_unused_categories()
        T = load.ip_table(R, con)
        R = load.attach_ip(R, T)
        f = con.execute("""SELECT e.vid, e.is_embedded, e.is_dup, e.is_redirect_hop, coalesce(p.is_page, e.is_page) is_page, e.form_key,
                                  coalesce(p.goal_success, e.goal_success) goal_success, e.is_order, e.order_step
                           FROM access_events e JOIN dim_host h USING (host_id) LEFT JOIN prepared_events p USING (eid)
                           WHERE coalesce(h.scope, 'site') <> 'off' ORDER BY e.ts, e.eid""").fetchnumpy()
        R['vid'] = np.asarray(f['vid']).astype('int64')
        for c in ('is_embedded', 'is_dup', 'is_redirect_hop', 'is_page'):
            R[c] = np.asarray(f[c]).astype(bool)
        P = dims.per_category(con, 'dim_path JOIN path_site USING (path_id)', 'path', ['tpl', 'is_admin', 'is_catalog'], R['base'].cat.categories)
        codes = R['base'].cat.codes.values
        R['tpl'] = pd.Categorical(P['tpl'].values.astype(object)[codes])
        R['is_admin'] = P['is_admin'].values.astype(bool)[codes]
        R['is_catalog'] = P['is_catalog'].values.astype(bool)[codes] & R['is_page'].values
        fk = np.asarray(f['form_key'], dtype=object)
        R['goal'] = pd.Categorical(np.where(pd.isna(fk), '', fk).astype(object))
        for c in ('goal_success', 'is_order', 'order_step'):
            R[c] = np.asarray(f[c]).astype(bool)
        for c, t in (('ts', 'uint32'), ('bytes', 'uint32'), ('asn', 'uint32'), ('vid', 'int32')):   # узкие типы и только встреченные значения — как хранилось раньше
            if len(R) and R[c].max() < np.iinfo(t).max: R[c] = R[c].astype(t)
        for c in R.columns:
            if str(R[c].dtype) == 'category': R[c] = R[c].cat.remove_unused_categories()
        return (R, T) if with_ip_table else R
    finally:
        if own: con.close()


def visits(src):
    """Визиты (V) после prepare: первичные категории, до правил analyze."""
    from .visits import freeze
    con, own = _con(src)
    try:
        D = con.execute("""SELECT v.vid, i.ip, u.ua, u.fam, u.fam_cat, v.fam_verified, i.asn, i.nettype, i.cc, u.is_browser ua_browser, u.is_old ua_old, u.is_mobile ua_mobile, u.is_webview ua_webview,
                                  v.ts_start "start", v.ts_end "end", v.n_req, v.n_pages, v.n_pages_raw, v.n_dup, v.n_redirect, v.n_embedded, v.n_static, v.bytes, v.scope = 'site' host_site,
                                  v.n_post, v.n_head, v.n_err4, v.n_err5, v.ts_end - v.ts_start dur, p.path entry, q.query entry_query, v.entry_status, f.ref entry_ref, f.ref_host entry_ref_host,
                                  f.is_internal entry_ref_internal, v.channel, v.channel_sub, v.category "group", v.type subgroup, v.n_catalog, v.n_goal, v.n_conv
                           FROM prepared_visits v JOIN dim_ip i USING (ip_id) JOIN dim_ua u USING (ua_id) JOIN dim_path p ON p.path_id = v.entry_path_id
                           JOIN dim_query q ON q.query_id = v.entry_query_id JOIN dim_ref f ON f.ref_id = v.entry_ref_id ORDER BY v.vid""").fetchdf()
    finally:
        if own: con.close()
    V = D.set_index('vid')
    for c in V.columns:   # счётчики и коды — целые, как при расчёте
        if c.startswith('n_') or c in ('entry_status', 'start', 'end', 'dur', 'bytes', 'asn'): V[c] = V[c].astype('int64')
    start = V['start'].astype('int64')
    V.insert(V.columns.get_loc('channel_sub') + 1, 'day', pd.to_datetime(start, unit='s').dt.strftime('%Y-%m-%d'))
    V.insert(V.columns.get_loc('day') + 1, 'hour', (start // 3600) % 24)
    V.insert(V.columns.get_loc('hour') + 1, 'weekday', pd.to_datetime(start, unit='s').dt.dayofweek)
    return freeze(V)


def ip_table(src):
    return requests(src, with_ip_table=True)[1]


def errors(src):
    """Error-лог (E)."""
    con, own = _con(src)
    try: return ingest.errors_frame(con)
    finally:
        if own: con.close()


def pd_requests(R):
    """Запросы с персональными данными в адресе (G)."""
    from . import recon
    G = recon.detect_get_pd(R).copy()
    if 'ts' in G: G['ts'] = G['ts'].astype('int64')
    for c in G.columns:
        if str(G[c].dtype) == 'category': G[c] = G[c].astype(str)
    return G
