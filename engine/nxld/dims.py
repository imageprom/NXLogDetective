"""NXLD: словари базы проверки — признаки значения считаются один раз на значение, а не на строку лога.

Общие признаки (сеть IP, семейство браузера, расширение и форма адреса) считаются только для новых значений словаря
и пересчитываются, когда изменился справочник, от которого они зависят. Признаки, зависящие от сайта
(внутренний реферер, тип хоста, шаблон и роль адреса), записываются при каждом prepare."""
import hashlib, os, re
import numpy as np, pandas as pd
from . import ipdb, uafam, classify

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data')
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_EXT = set('css js mjs map png jpg jpeg gif webp avif svg ico bmp tif tiff woff woff2 ttf otf eot mp4 webm mov avi mp3 ogg wav pdf zip rar 7z gz txt xml json csv doc docx xls xlsx ppt pptx'.split())
FORM_PARAM = r'(?:^|&)(?:form|form_id|WEB_FORM_ID|formid|form_name)=([^&]+)'
# от каких файлов зависит словарь: изменился файл — признаки словаря считаются заново
DEPENDS = {'dim_ip': [os.path.join(DATA, f) for f in ('asn-ipv4-num.csv.gz', 'country-ipv4-num.csv.gz', 'hosting_rules.json', 'reference/gov_robots.json')] + [os.path.join(HERE, f) for f in ('ipdb.py', 'gov.py')],
           'dim_ua': [os.path.join(HERE, 'uafam.py'), os.path.join(HERE, 'dims.py')],
           'dim_path': [os.path.join(DATA, 'reference', f) for f in ('extensions.json', 'file_groups.json')] + [os.path.join(HERE, f) for f in ('classify.py', 'dims.py')]}
RESET = {'dim_ip': 'nettype', 'dim_ua': 'fam', 'dim_path': 'shape'}   # колонка-признак «посчитано»


def _fingerprint(files):
    h = hashlib.md5()
    for f in files:
        h.update(os.path.basename(f).encode())
        if os.path.exists(f):
            with open(f, 'rb') as fh:
                for b in iter(lambda: fh.read(1 << 20), b''): h.update(b)
    return h.hexdigest()[:16]


def sync_refs(con):
    """Сверяет отпечатки справочников с записанными в базе; у словаря с изменившимся справочником признаки сбрасываются."""
    changed = []
    for dim, files in DEPENDS.items():
        fp = _fingerprint(files)
        old = con.execute('SELECT hash FROM ref_versions WHERE name = ?', [dim]).fetchone()
        if old and old[0] != fp:
            con.execute(f'UPDATE {dim} SET {RESET[dim]} = NULL'); changed.append(dim)
        if not old or old[0] != fp:
            con.execute('DELETE FROM ref_versions WHERE name = ?', [dim])
            con.execute('INSERT INTO ref_versions VALUES (?, ?, now()::TIMESTAMP)', [dim, fp])
    return changed


def _update(con, table, key, df):
    """Записывает колонки df в строки таблицы по ключу."""
    if not len(df): return
    con.register('upd_df', df)
    con.execute('CREATE OR REPLACE TEMP TABLE upd_tmp AS SELECT * FROM upd_df')   # сначала в таблицу базы: обновление прямо из таблицы pandas на порядок медленнее
    con.unregister('upd_df')
    for c in df.columns:   # по колонке за раз: обновление нескольких колонок одним запросом в DuckDB в десятки раз медленнее
        if c != key: con.execute(f'UPDATE {table} t SET {c} = u.{c} FROM upd_tmp u WHERE t.{key} = u.{key}')
    con.execute('DROP TABLE upd_tmp')


def ua_features(uas):
    """Признаки строки User-Agent: семейство и вид браузера."""
    fam = [uafam.family(u) for u in uas]
    s = pd.Series(list(uas), dtype=object)
    browser = s.str.contains(r'^Mozilla/5\.0 \(', regex=True) & ~s.str.contains(r'HeadlessChrome|PhantomJS|Lightpanda', regex=True)
    old = s.str.contains(r'MSIE [1-9]\.|Chrome/[1-5]\d\.|Firefox/[1-4]\d\.|Windows NT [45]\.|Android [1-4]\.', regex=True)
    famname = np.array([f[0] if f else '' for f in fam], dtype=object)
    return pd.DataFrame({'fam': famname, 'fam_cat': np.array([f[1] if f else '' for f in fam], dtype=object),
                         'is_browser': (browser & ~old).values.astype(bool) & (famname == ''), 'is_old': old.values.astype(bool),
                         'is_mobile': s.str.contains(r'Mobile|Android|iPhone|iPad', regex=True).values.astype(bool),
                         'is_webview': s.str.contains(r'; wv\)|YaApp|FBAN|Instagram|VKAndroidApp|com\.vk|Telegram', regex=True).values.astype(bool)})


def fill_common(con):
    """Признаки, не зависящие от сайта, — для значений словарей, у которых они ещё не посчитаны."""
    sync_refs(con)
    d = con.execute('SELECT ua_id, ua FROM dim_ua WHERE fam IS NULL').fetchdf()
    if len(d): _update(con, 'dim_ua', 'ua_id', pd.concat([d[['ua_id']], ua_features(d['ua'].tolist())], axis=1))
    d = con.execute('SELECT ip_id, ip FROM dim_ip WHERE nettype IS NULL').fetchdf()
    if len(d):
        from . import gov
        T = ipdb.lookup(d['ip'].tolist())
        T['operator'] = np.asarray(gov.operators(T['ip'], T['asn']), dtype=object)
        T['ip_id'] = d['ip_id'].values
        _update(con, 'dim_ip', 'ip_id', T[['ip_id', 'asn', 'org', 'cc', 'nettype', 'net_first', 'net_last', 'operator']])
    d = con.execute('SELECT path_id, path FROM dim_path WHERE shape IS NULL').fetchdf()
    if len(d):
        ext = d['path'].astype(object).str.extract(r'\.([A-Za-z0-9]{1,5})$')[0].str.lower().fillna('')
        f = [classify.form_of(p) for p in d['path'].tolist()]
        _update(con, 'dim_path', 'path_id', pd.DataFrame({'path_id': d['path_id'].values, 'ext': ext.values.astype(object), 'is_static': ext.isin(STATIC_EXT).values,
                                                         'shape': np.array([x[0] for x in f], dtype=object), 'file_group': np.array([x[1] for x in f], dtype=object)}))
    # параметры: значение параметра формы и разбор строки на пары — для новых строк параметров
    con.execute(f"UPDATE dim_query SET form_param = coalesce(regexp_extract(query, '{FORM_PARAM}', 1, 'i'), '') WHERE form_param IS NULL")
    con.execute("""INSERT INTO query_params
        SELECT query_id, pos::SMALLINT, CASE WHEN contains(kv, '=') THEN left(kv, strpos(kv, '=') - 1) ELSE kv END, CASE WHEN contains(kv, '=') THEN substr(kv, strpos(kv, '=') + 1) ELSE NULL END
        FROM (SELECT query_id, unnest(string_split(query, '&')) kv, generate_subscripts(string_split(query, '&'), 1) pos FROM dim_query
              WHERE query <> '' AND query_id NOT IN (SELECT DISTINCT query_id FROM query_params)) WHERE pos <= 200""")


def fill_ref(con, site_hosts):
    """Реферер: хост, путь и «внутренний» (с хоста этого же сервера) — зависит от списка хостов сайта."""
    d = con.execute('SELECT ref_id, ref FROM dim_ref').fetchdf()
    if not len(d): return
    ref = d['ref'].astype(object)
    host = ref.str.extract(r'^https?://([^/:?#]+)')[0].str.lower().str.replace(r'^www\.', '', regex=True).fillna('')
    rx = '|'.join(re.escape(h) for h in site_hosts) if site_hosts else r'^$'
    internal = host.str.fullmatch(rf'(?:.+\.)?(?:{rx})').fillna(False).astype(bool)
    rpath = ref.str.replace(r'^https?://[^/]+', '', regex=True).str.split('?').str[0]
    _update(con, 'dim_ref', 'ref_id', pd.DataFrame({'ref_id': d['ref_id'].values, 'ref_host': host.values.astype(object), 'ref_path': rpath.where(internal, '').values.astype(object), 'is_internal': internal.values}))


def store_hosts(con, host_table, normalize):
    """Тип, причина и область хоста — из таблицы хостов (hosts.classify). Область: site — сайт, off — копии на других доменах (вне отчёта), server — остальное на том же сервере."""
    d = con.execute('SELECT host_id, host FROM dim_host').fetchdf()
    if not len(d): return
    kind = {('' if r['хост'] == '(не записан)' else r['хост']): (r['тип'], r['причина']) for r in host_table}
    name = [normalize(h) for h in d['host'].tolist()]
    k = [kind.get(n, ('сайт', 'имя хоста не записано') if not host_table else (None, None)) for n in name]
    copies_off = any(x[0] == 'сайт' for x in kind.values()) or not host_table
    scope = ['site' if t == 'сайт' else None if t is None else 'off' if why == 'другой домен' and copies_off else 'server' for t, why in k]
    _update(con, 'dim_host', 'host_id', pd.DataFrame({'host_id': d['host_id'].values, 'name': np.array(name, dtype=object), 'type': np.array([x[0] for x in k], dtype=object),
                                                     'reason': np.array([x[1] for x in k], dtype=object), 'scope': np.array(scope, dtype=object),
                                                     'how': np.array(['override' if str(x[1]).startswith('поправка') else 'behavior' if x[0] else None for x in k], dtype=object)}))


def store_path_site(con, paths, tpl, is_admin, catalog_templates):
    """Роль адреса на этом сайте: шаблон, раздел, админка, элемент каталога."""
    df = pd.DataFrame({'path': np.asarray(paths, dtype=object), 'tpl': np.asarray(tpl, dtype=object), 'is_admin': np.asarray(is_admin, dtype=bool)})
    df['section'] = df['path'].str.extract(r'^(/[^/]*/?)')[0].fillna('').values.astype(object)
    df['is_catalog'] = df['tpl'].isin(list(catalog_templates)).values
    con.register('ps_df', df)
    con.execute('DELETE FROM path_site')
    con.execute('INSERT INTO path_site (path_id, tpl, section, is_admin, is_catalog) SELECT p.path_id, s.tpl, s.section, s.is_admin, s.is_catalog FROM ps_df s JOIN dim_path p ON p.path = s.path')
    con.unregister('ps_df')


def per_category(con, table, key, cols, categories):
    """Признаки словаря в порядке категорий колонки R."""
    d = con.execute(f"SELECT {key}, {', '.join(cols)} FROM {table}").fetchdf().set_index(key)
    return d.reindex(pd.Index(list(categories), dtype=object))
