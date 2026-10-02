"""NXLD: сборка всех запросов в одну таблицу R (по времени, без дублей) и базовые признаки."""
import glob, hashlib, json, os, re
import numpy as np, pandas as pd
from pandas.api.types import union_categoricals
from . import ingest, ipdb, uafam

STATIC_EXT = set('css js mjs map png jpg jpeg gif webp avif svg ico bmp tif tiff woff woff2 ttf otf eot mp4 webm mov avi mp3 ogg wav pdf zip rar 7z gz txt xml json csv doc docx xls xlsx ppt pptx'.split())
MEDIA_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'avif', 'svg', 'ico', 'bmp'}
DOC_EXT = {'pdf', 'zip', 'rar', '7z', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'}
CAT_COLS = ('ip', 'user', 'method', 'base', 'query', 'proto', 'ref', 'ua', 'tail', 'src')


def load_requests(workdir, state):
    drop, report = ingest.overlaps(workdir, state)
    parts = []
    for fn in sorted(glob.glob(os.path.join(workdir, 'req_*.pkl'))):
        df = pd.read_pickle(fn)
        sid = df['src'].iat[0]
        if sid in drop:
            df = df[~(df.ts // 60).isin(drop[sid])]
        parts.append(df)
    cats = {c: union_categoricals([p[c] for p in parts], ignore_order=True).categories for c in CAT_COLS}
    for p in parts:
        for c in CAT_COLS:
            p[c] = p[c].cat.set_categories(cats[c])
    R = pd.concat(parts, ignore_index=True)
    R = R.sort_values('ts', kind='stable').reset_index(drop=True)
    return R, report


def add_features(R, site_hosts):
    """Признаки запроса. site_hosts — домены сайта (для внутренних рефереров)."""
    base = R['base'].cat.categories.to_series()
    ext = base.str.extract(r'\.([A-Za-z0-9]{1,5})$')[0].str.lower().fillna('')
    R['ext'] = ext.values[R['base'].cat.codes.values]
    R['ext'] = R['ext'].astype('category')
    R['is_static'] = R['ext'].isin(STATIC_EXT).values
    # реферер: внутренний / внешний хост / путь
    ref = R['ref'].cat.categories.to_series()
    host = ref.str.extract(r'^https?://([^/:?#]+)')[0].str.lower().str.replace(r'^www\.', '', regex=True).fillna('')
    rx = '|'.join(re.escape(h) for h in site_hosts) if site_hosts else r'^$'
    internal = host.str.fullmatch(rf'(?:.+\.)?(?:{rx})').fillna(False)
    rpath = ref.str.replace(r'^https?://[^/]+', '', regex=True).str.split('?').str[0]
    codes = R['ref'].cat.codes.values
    R['ref_host'] = pd.Categorical.from_codes(pd.Categorical(host.values).codes[codes], categories=pd.Categorical(host.values).categories)
    R['ref_internal'] = internal.values[codes]
    rp = pd.Categorical(rpath.where(internal, '').values)
    R['ref_path'] = pd.Categorical.from_codes(rp.codes[codes], categories=rp.categories)
    # семейство робота по UA
    uas = R['ua'].cat.categories
    fam = [uafam.family(u) for u in uas]
    fcodes = R['ua'].cat.codes.values
    famname = np.array([f[0] if f else '' for f in fam], dtype=object)
    famcat = np.array([f[1] if f else '' for f in fam], dtype=object)
    R['fam'] = pd.Categorical(famname[fcodes])
    R['fam_cat'] = pd.Categorical(famcat[fcodes])
    uas_s = pd.Series(uas)
    browser = uas_s.str.contains(r'^Mozilla/5\.0 \(', regex=True) & ~uas_s.str.contains(r'HeadlessChrome|PhantomJS|Lightpanda', regex=True)
    old = uas_s.str.contains(r'MSIE [1-9]\.|Chrome/[1-5]\d\.|Firefox/[1-4]\d\.|Windows NT [45]\.|Android [1-4]\.', regex=True)
    mobile = uas_s.str.contains(r'Mobile|Android|iPhone|iPad', regex=True)
    webview = uas_s.str.contains(r'; wv\)|YaApp|FBAN|Instagram|VKAndroidApp|com\.vk|Telegram', regex=True)
    R['ua_browser'] = (browser & ~old).values[fcodes] & (famname[fcodes] == '')
    R['ua_old'] = old.values[fcodes]
    R['ua_mobile'] = mobile.values[fcodes]
    R['ua_webview'] = webview.values[fcodes]
    R['day'] = pd.to_datetime(R['ts'], unit='s').dt.strftime('%Y-%m-%d').astype('category')
    R['hour'] = ((R['ts'] // 3600) % 24).astype('int8')
    return R


def ip_table(R):
    ips = R['ip'].cat.categories
    T = ipdb.lookup(list(ips))
    T.index = range(len(T))
    return T


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
