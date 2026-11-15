"""NXLD: сборка всех запросов в одну таблицу R (по времени, без дублей) и базовые признаки."""
import glob, hashlib, json, os, re
import numpy as np, pandas as pd
from pandas.api.types import union_categoricals
from . import ingest, ipdb, uafam

STATIC_EXT = set('css js mjs map png jpg jpeg gif webp avif svg ico bmp tif tiff woff woff2 ttf otf eot mp4 webm mov avi mp3 ogg wav pdf zip rar 7z gz txt xml json csv doc docx xls xlsx ppt pptx'.split())
MEDIA_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'avif', 'svg', 'ico', 'bmp'}
DOC_EXT = {'pdf', 'zip', 'rar', '7z', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}
CAT_COLS = ('ip', 'user', 'method', 'base', 'query', 'proto', 'ref', 'ua', 'tail', 'src')


def load_requests(con):
    """Таблица запросов из базы проверки и сведения о строках, которые уже были в других файлах."""
    R = ingest.requests_frame(con)
    rep = con.execute("SELECT name, lines - bad - new_rows FROM sources WHERE kind = 'access' AND copy_of IS NULL AND lines - bad - new_rows > 0 ORDER BY source_id").fetchall()
    return R, [dict(source=n, lines_duplicate=int(k)) for n, k in rep]


def add_features(R, con, site_hosts):
    """Признаки запроса — из словарей базы проверки (dims): расширение адреса, реферер, семейство и вид браузера.
    site_hosts — хосты этого сервера (реферер с любого из них — внутренний переход)."""
    from . import dims
    dims.fill_common(con)
    dims.fill_ref(con, site_hosts)
    return read_features(R, con)


def read_features(R, con):
    """Признаки запроса из уже заполненных словарей (без записи в базу)."""
    from . import dims
    P = dims.per_category(con, 'dim_path', 'path', ['ext', 'is_static'], R['base'].cat.categories)
    codes = R['base'].cat.codes.values
    R['ext'] = P['ext'].values.astype(object)[codes]
    R['ext'] = R['ext'].astype('category')
    R['is_static'] = P['is_static'].values.astype(bool)[codes]
    F = dims.per_category(con, 'dim_ref', 'ref', ['ref_host', 'ref_path', 'is_internal'], R['ref'].cat.categories)
    codes = R['ref'].cat.codes.values
    h = pd.Categorical(F['ref_host'].values.astype(object))
    R['ref_host'] = pd.Categorical.from_codes(h.codes[codes], categories=h.categories)
    R['ref_internal'] = F['is_internal'].values.astype(bool)[codes]
    rp = pd.Categorical(F['ref_path'].values.astype(object))
    R['ref_path'] = pd.Categorical.from_codes(rp.codes[codes], categories=rp.categories)
    U = dims.per_category(con, 'dim_ua', 'ua', ['fam', 'fam_cat', 'is_browser', 'is_old', 'is_mobile', 'is_webview'], R['ua'].cat.categories)
    fcodes = R['ua'].cat.codes.values
    R['fam'] = pd.Categorical(U['fam'].values.astype(object)[fcodes])
    R['fam_cat'] = pd.Categorical(U['fam_cat'].values.astype(object)[fcodes])
    for c, k in (('ua_browser', 'is_browser'), ('ua_old', 'is_old'), ('ua_mobile', 'is_mobile'), ('ua_webview', 'is_webview')):
        R[c] = U[k].values.astype(bool)[fcodes]
    R['day'] = pd.to_datetime(R['ts'], unit='s').dt.strftime('%Y-%m-%d').astype('category')
    R['hour'] = ((R['ts'] // 3600) % 24).astype('int8')
    return R


def ip_table(R, con):
    """Сведения о сети по IP запросов — из словаря IP базы проверки, в порядке категорий R.ip."""
    from . import dims
    D = dims.per_category(con, 'dim_ip', 'ip', ['asn', 'org', 'cc', 'net_first', 'net_last', 'nettype'], R['ip'].cat.categories)
    return pd.DataFrame({'ip': list(R['ip'].cat.categories), 'asn': D['asn'].values.astype(np.int64), 'org': D['org'].values.astype(object), 'cc': D['cc'].values.astype(object),
                         'net_first': D['net_first'].values.astype(np.int64), 'net_last': D['net_last'].values.astype(np.int64), 'nettype': D['nettype'].values.astype(object)})


def attach_ip(R, T):
    c = R['ip'].cat.codes.values
    R['asn'] = T['asn'].values[c]
    R['nettype'] = pd.Categorical(T['nettype'].values[c])
    R['cc'] = pd.Categorical(T['cc'].values[c])
    # подлинность объявленного робота
    fam = R['fam'].astype(str).values
    ver = np.full(len(R), '', dtype=object)
    for f, allowed in ipdb.VERIFIED.items():
        m = fam == f
        if m.any():
            ver[m] = np.where(np.isin(R['asn'].values[m], list(allowed)), 'да', 'нет')
    R['fam_verified'] = pd.Categorical(ver)
    return R
