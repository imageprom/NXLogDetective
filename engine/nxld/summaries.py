"""NXLD: сводки «Время» (sum_time) и «Минута» (sum_minute) в базе проверки — и чтение из них для блоков.

Сводки строятся в analyze после всех правил (store.all_of): итоговые категории и типы визитов уже в базе.
Пересобираются целиком при каждом analyze. Блоки читают их запросом и получают небольшую таблицу pandas — события в память не выгружаются.

Области. В сводках — события и визиты хостов сайта (scope = site) и того же сервера вне сайта (server); копий на других доменах (off) нет.
Отчёт читает сводки в одном из двух контекстов (как таблицы R и V в analyze.run):
  site — только сайт (файлы 01, 02, 05, 06);
  all  — сайт и сервер, кроме нераспознанных посетителей («Люди») хостов вне сайта (файлы 03, 04).

Счётчики разных IP (sum_minute.n_ip, sum_path_status.n_ip) и визитов (sum_path_status.n_visits) верны только на зерне сводки: при свёртке их складывать нельзя.
Где блоку нужно «разных IP по адресу и коду», — отдельный запрос по событиям (Sums.events), а не сумма по строкам сводки.
«Кто» — признаки визита: все запросы визита попадают в одну строку «кто» своего часа.

Сводки переходов и параметров:
  sum_links — переход: источник (страница сайта или внешний хост) → адрес × код × кто: все ответы с ошибкой, все переходы с внешних сайтов и все запросы к адресам-конструктам;
  sum_params — строка параметров × раздел × кто × признаки запроса: всё, из чего строится перечень «Параметры запросов».

Сводки по адресам:
  sum_path_status — адрес × хост × код × кто × откуда запрос; первое появление строки — (ts_first, eid_first): по нему при равных счётах
    воспроизводится порядок «кто встретился раньше», как у value_counts по таблице запросов;
  sum_path_day — адрес × день × область × категория: сколько запросов, сколько не от сотрудников и что отдано им последним (история «открыт сейчас» у утечек)."""
import os
import numpy as np, pandas as pd
from . import db

TABLES = ('sum_time', 'sum_minute', 'sum_path_status', 'sum_path_day', 'sum_links', 'sum_params')
CONTEXTS = {'site': "scope = 'site'", 'all': "NOT (scope = 'server' AND category = 'Люди')"}
SEARCH_FAMS = ('YandexBot', 'Googlebot', 'YandexRenderResourcesBot', 'Googlebot-Image', 'Bingbot')   # подлинные поисковые роботы: тот же список, что blocks.Ctx.search_ok
DAY = "strftime(day, '%Y-%m-%d')"
AD_MARK = r'(?:^|&)(?:yclid|gclid|fbclid|utm_source|utm_medium|utm_campaign|_openstat)='   # как errors.AD_MARK
SEARCH_HOST = r'(^|\.)(yandex\.[a-z.]+|ya\.ru|google\.[a-z.]+|bing\.com|go\.mail\.ru|duckduckgo\.com|search\.yahoo\.com|rambler\.ru|nova\.rambler\.ru)$'   # как visits.SEARCH
EPOCH_DAY = "(DATE '1970-01-01' + CAST({ts} // 86400 AS INTEGER))"   # день по часам лога: время в базе — секунды без пояса
WHO = """coalesce(v.category, '') AS category, coalesce(v.type, '') AS type, coalesce(v.fam, u.fam, '') AS fam, coalesce(u.fam_cat, '') AS fam_cat,
         coalesce(v.fam_verified, '') AS fam_verified, coalesce(v.channel, '') AS channel, coalesce(v.channel_sub, '') AS channel_sub"""

SQL_TIME = f"""CREATE OR REPLACE TABLE sum_time AS
WITH ev AS (
  SELECT {EPOCH_DAY.format(ts='e.ts')} AS day, CAST((e.ts // 3600) % 24 AS TINYINT) AS hour, coalesce(h.scope, 'site') AS scope, {WHO},
         count(*) AS n_req, count(*) FILTER (e.is_page) AS n_pages, 0 AS n_visits_started, 0 AS n_goal_started, 0 AS n_conv_started,
         coalesce(sum(e.bytes), 0) AS bytes,
         count(*) FILTER (e.status BETWEEN 200 AND 299) AS n_2xx, count(*) FILTER (e.status BETWEEN 300 AND 399) AS n_3xx,
         count(*) FILTER (e.status BETWEEN 400 AND 499) AS n_4xx, count(*) FILTER (e.status >= 500) AS n_5xx,
         count(*) FILTER (e.status = 403) AS n_403, count(*) FILTER (e.status = 404) AS n_404, count(*) FILTER (e.status = 499) AS n_499,
         count(*) FILTER (e.status = 502) AS n_502, count(*) FILTER (e.status = 504) AS n_504,
         count(*) FILTER (e.form_key IS NOT NULL) AS n_submits, count(*) FILTER (e.goal_success) AS n_accepted, count(*) FILTER (e.is_order) AS n_orders,
         min(e.ts) AS ts_first, max(e.ts) AS ts_last
  FROM access_events e JOIN dim_host h ON h.host_id = e.host_id JOIN visits v ON v.vid = e.vid LEFT JOIN dim_ua u ON u.ua_id = v.ua_id
  WHERE coalesce(h.scope, 'site') <> 'off'
  GROUP BY ALL),
vs AS (
  SELECT {EPOCH_DAY.format(ts='v.ts_start')} AS day, CAST((v.ts_start // 3600) % 24 AS TINYINT) AS hour, v.scope AS scope, {WHO},
         0 AS n_req, 0 AS n_pages, count(*) AS n_visits_started, coalesce(sum(v.n_goal), 0) AS n_goal_started, coalesce(sum(v.n_conv), 0) AS n_conv_started,
         0 AS bytes, 0 AS n_2xx, 0 AS n_3xx, 0 AS n_4xx, 0 AS n_5xx, 0 AS n_403, 0 AS n_404, 0 AS n_499, 0 AS n_502, 0 AS n_504, 0 AS n_submits, 0 AS n_accepted, 0 AS n_orders,
         NULL AS ts_first, NULL AS ts_last
  FROM visits v LEFT JOIN dim_ua u ON u.ua_id = v.ua_id
  WHERE v.scope IN ('site', 'server')
  GROUP BY ALL)
SELECT day, hour, scope, category, type, fam, fam_cat, fam_verified, channel, channel_sub,
       CAST(sum(n_req) AS BIGINT) AS n_req, CAST(sum(n_pages) AS BIGINT) AS n_pages, CAST(sum(n_visits_started) AS BIGINT) AS n_visits_started,
       CAST(sum(n_goal_started) AS BIGINT) AS n_goal_started, CAST(sum(n_conv_started) AS BIGINT) AS n_conv_started, CAST(sum(bytes) AS BIGINT) AS bytes,
       CAST(sum(n_2xx) AS BIGINT) AS n_2xx, CAST(sum(n_3xx) AS BIGINT) AS n_3xx, CAST(sum(n_4xx) AS BIGINT) AS n_4xx, CAST(sum(n_5xx) AS BIGINT) AS n_5xx,
       CAST(sum(n_403) AS BIGINT) AS n_403, CAST(sum(n_404) AS BIGINT) AS n_404, CAST(sum(n_499) AS BIGINT) AS n_499,
       CAST(sum(n_502) AS BIGINT) AS n_502, CAST(sum(n_504) AS BIGINT) AS n_504,
       CAST(sum(n_submits) AS BIGINT) AS n_submits, CAST(sum(n_accepted) AS BIGINT) AS n_accepted, CAST(sum(n_orders) AS BIGINT) AS n_orders,
       CAST(min(ts_first) AS BIGINT) AS ts_first, CAST(max(ts_last) AS BIGINT) AS ts_last
FROM (SELECT * FROM ev UNION ALL SELECT * FROM vs)
GROUP BY ALL ORDER BY ALL"""

SQL_MINUTE = """CREATE OR REPLACE TABLE sum_minute AS
SELECT CAST(e.ts // 60 AS INTEGER) AS minute, coalesce(h.scope, 'site') AS scope, coalesce(v.category, '') AS category,
       count(*) AS n_req, count(*) FILTER (e.is_page) AS n_pages,
       count(*) FILTER (e.is_page OR e.method = 'POST') AS n_page_post,
       count(*) FILTER ((e.is_page OR e.method = 'POST') AND e.status >= 500) AS n_page_post_5xx,
       count(*) FILTER ((e.is_page OR e.method = 'POST') AND e.status = 499) AS n_page_post_499,
       count(*) FILTER (p.is_static) AS n_static, count(*) FILTER (p.is_static AND e.status < 400) AS n_static_ok,
       count(*) FILTER (e.status >= 500) AS n_5xx, count(*) FILTER (e.status = 499) AS n_499,
       count(*) FILTER (e.status IN (403, 429, 444)) AS n_refused,
       CAST(coalesce(sum(e.bytes), 0) AS BIGINT) AS bytes, CAST(count(DISTINCT e.ip_id) AS INTEGER) AS n_ip
FROM access_events e JOIN dim_host h ON h.host_id = e.host_id JOIN visits v ON v.vid = e.vid LEFT JOIN dim_path p ON p.path_id = e.path_id
WHERE coalesce(h.scope, 'site') <> 'off'
GROUP BY ALL ORDER BY ALL"""


# Откуда запрос — по рефереру и параметрам (enum origin): ads — метки рекламы в адресе; internal — со страницы сайта (не обновление той же страницы);
# search — с поисковика; sites — с другого сайта; direct — без реферера или обновление той же страницы. ref_scope — только реферер: site / none / external.
EV_COLS = f"""e.path_id, e.host_id, coalesce(h.scope, 'site') AS scope, e.status, coalesce(v.category, '') AS category, coalesce(v.type, '') AS type,
       coalesce(v.fam, u.fam, '') AS fam, coalesce(u.fam_cat, '') AS fam_cat, coalesce(v.fam_verified, '') AS fam_verified,
       CASE WHEN coalesce(r.is_internal, false) THEN 'site' WHEN coalesce(r.ref_host, 'nan') IN ('', '-', 'nan') THEN 'none' ELSE 'external' END AS ref_scope,
       CASE WHEN coalesce(regexp_matches(q.query, '{AD_MARK}'), false) THEN 'ads'
            WHEN coalesce(r.is_internal, false) AND coalesce(r.ref_path, 'nan') <> p.path THEN 'internal'
            WHEN NOT coalesce(r.is_internal, false) AND coalesce(r.ref_host, 'nan') NOT IN ('', '-', 'nan') AND regexp_matches(trim(split_part(coalesce(r.ref_host, 'nan'), ',', 1)), '{SEARCH_HOST}') THEN 'search'
            WHEN NOT coalesce(r.is_internal, false) AND coalesce(r.ref_host, 'nan') NOT IN ('', '-', 'nan') THEN 'sites'
            ELSE 'direct' END AS origin,
       e.is_page, e.ip_id, e.vid, e.bytes, e.ts, e.eid, e.ref_id"""
EV_FROM = """access_events e JOIN dim_host h ON h.host_id = e.host_id JOIN visits v ON v.vid = e.vid LEFT JOIN dim_ua u ON u.ua_id = v.ua_id
       LEFT JOIN dim_ref r ON r.ref_id = e.ref_id LEFT JOIN dim_query q ON q.query_id = e.query_id JOIN dim_path p ON p.path_id = e.path_id"""
FIRST = "min(struct_pack(t := ts, i := eid, r := ref_id))"

SQL_PATH_STATUS = f"""CREATE OR REPLACE TABLE sum_path_status AS
SELECT path_id, host_id, scope, status, category, type, fam, fam_cat, fam_verified, origin, ref_scope, is_page,
       CAST(count(*) AS BIGINT) AS n_req, CAST(count(DISTINCT ip_id) AS INTEGER) AS n_ip, CAST(count(DISTINCT vid) AS INTEGER) AS n_visits, CAST(coalesce(sum(bytes), 0) AS BIGINT) AS bytes,
       {EPOCH_DAY.format(ts='min(ts)')} AS day_first, {EPOCH_DAY.format(ts='max(ts)')} AS day_last,
       CAST(f.t AS BIGINT) AS ts_first, CAST(f.i AS BIGINT) AS eid_first, f.r AS sample_ref_id
FROM (SELECT *, {FIRST} OVER (PARTITION BY path_id, host_id, status, category, type, fam, fam_cat, fam_verified, origin, ref_scope, is_page) AS f
      FROM (SELECT {EV_COLS} FROM {EV_FROM} WHERE coalesce(h.scope, 'site') <> 'off'))
GROUP BY ALL ORDER BY ALL"""

SQL_PATH_DAY = f"""CREATE OR REPLACE TABLE sum_path_day AS
SELECT path_id, {EPOCH_DAY.format(ts='ts')} AS day, scope, category,
       CAST(count(*) AS BIGINT) AS n_req, CAST(count(*) FILTER (NOT staff) AS BIGINT) AS n_ext, CAST(count(*) FILTER (NOT staff AND status = 200 AND bytes > 0) AS BIGINT) AS n_served_ext,
       CAST(l.t AS BIGINT) AS ts_last_ext, CAST(l.i AS BIGINT) AS eid_last_ext, CAST(l.s AS SMALLINT) AS last_status_ext, l.b AS last_served_ext
FROM (SELECT *, max(CASE WHEN NOT staff THEN struct_pack(t := ts, i := eid, s := status, b := (status = 200 AND bytes > 0)) END)
             OVER (PARTITION BY path_id, {EPOCH_DAY.format(ts='ts')}, scope, category) AS l
      FROM (SELECT e.path_id, coalesce(h.scope, 'site') AS scope, coalesce(v.category, '') AS category, e.ts, e.eid, e.status, e.bytes,
                   e.ip_id IN (SELECT ip_id FROM site_staff WHERE role = 'сотрудник') AS staff
            FROM access_events e JOIN dim_host h ON h.host_id = e.host_id JOIN visits v ON v.vid = e.vid WHERE coalesce(h.scope, 'site') <> 'off'))
GROUP BY ALL ORDER BY ALL"""


EXTERNAL = "NOT coalesce(r.is_internal, false) AND coalesce(r.ref_host, 'nan') NOT IN ('', '-', 'nan')"
SQL_LINKS = f"""CREATE OR REPLACE TABLE sum_links AS
SELECT src_kind, src, ref_host, dst_path_id, status, is_ad, scope, category, fam, fam_verified,
       CAST(count(*) AS BIGINT) AS n_req, CAST(count(DISTINCT ip_id) AS INTEGER) AS n_ip, CAST(count(DISTINCT vid) AS INTEGER) AS n_visits, CAST(coalesce(sum(bytes), 0) AS BIGINT) AS bytes,
       {EPOCH_DAY.format(ts='min(ts)')} AS day_first, {EPOCH_DAY.format(ts='max(ts)')} AS day_last, CAST(f.t AS BIGINT) AS ts_first, CAST(f.i AS BIGINT) AS eid_first
FROM (SELECT *, min(struct_pack(t := ts, i := eid)) OVER (PARTITION BY src_kind, src, ref_host, dst_path_id, status, is_ad, scope, category, fam, fam_verified) AS f
      FROM (SELECT CASE WHEN coalesce(r.is_internal, false) THEN 'site' WHEN coalesce(r.ref_host, 'nan') IN ('', '-', 'nan') THEN 'none' ELSE 'external' END AS src_kind,
                   CASE WHEN coalesce(r.is_internal, false) THEN coalesce(r.ref_path, 'nan') WHEN coalesce(r.ref_host, 'nan') NOT IN ('', '-', 'nan') THEN coalesce(r.ref_host, 'nan') ELSE '' END AS src,
                   coalesce(r.ref_host, 'nan') AS ref_host, e.path_id AS dst_path_id, e.status AS status, coalesce(regexp_matches(q.query, '{AD_MARK}'), false) AS is_ad,
                   coalesce(h.scope, 'site') AS scope, coalesce(v.category, '') AS category, coalesce(v.fam, u.fam, '') AS fam, coalesce(v.fam_verified, '') AS fam_verified,
                   e.ip_id AS ip_id, e.vid AS vid, e.bytes AS bytes, e.ts AS ts, e.eid AS eid
            FROM {EV_FROM} WHERE coalesce(h.scope, 'site') <> 'off' AND (e.status >= 400 OR ({EXTERNAL}) OR p.shape = 'конструкт')))
GROUP BY ALL ORDER BY ALL"""

SQL_PARAMS = f"""CREATE OR REPLACE TABLE sum_params AS
SELECT query_id, section, scope, category, fam, fam_cat, ref_internal, is_page, is_embedded, is_get, is_err,
       CAST(count(*) AS BIGINT) AS n_req, CAST(count(DISTINCT ip_id) AS INTEGER) AS n_ip, CAST(count(DISTINCT vid) AS INTEGER) AS n_visits
FROM (SELECT e.query_id AS query_id, regexp_extract(p.path, '^(/[^/?]*/?)', 1) AS section, coalesce(h.scope, 'site') AS scope, coalesce(v.category, '') AS category,
             coalesce(v.fam, u.fam, '') AS fam, coalesce(u.fam_cat, '') AS fam_cat, coalesce(r.is_internal, false) AS ref_internal, coalesce(e.is_page, false) AS is_page,
             coalesce(e.is_embedded, false) AS is_embedded, coalesce(e.method = 'GET', false) AS is_get, e.status >= 400 AS is_err, e.ip_id AS ip_id, e.vid AS vid
      FROM {EV_FROM} WHERE coalesce(h.scope, 'site') <> 'off' AND q.query <> '' AND q.query <> 'nan')
GROUP BY ALL ORDER BY ALL"""


def enabled():
    """NXLD_SUMMARIES=0 — блоки считают по-старому, по таблицам в памяти (для сверки); сводки при этом всё равно строятся."""
    return os.environ.get('NXLD_SUMMARIES', '1') != '0'


def build(workdir, con=None, log=None):
    """Сводки — заново из событий и визитов. Возвращает {таблица: строк}."""
    import time
    own = con is None
    if own: con = db.connect(workdir)
    out = {}
    try:
        for name, sql in (('sum_time', SQL_TIME), ('sum_minute', SQL_MINUTE), ('sum_path_status', SQL_PATH_STATUS), ('sum_path_day', SQL_PATH_DAY), ('sum_links', SQL_LINKS), ('sum_params', SQL_PARAMS)):
            t0 = time.time()
            con.execute(sql)
            out[name] = db.mark_built(con, name, seconds=time.time() - t0)
    finally:
        if own: con.close()
    if log: log('Сводки базы проверки: ' + ', '.join(f'{k} — {v:,} строк'.replace(',', ' ') for k, v in out.items()))
    return out


def ready(workdir):
    """Сводки построены: база есть и обе таблицы на месте."""
    if not db.exists(workdir): return False
    con = db.connect(workdir, read_only=True)
    try:
        have = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'sum_%'").fetchall()}
    finally:
        con.close()
    return set(TABLES) <= have


class Sums:
    """Чтение сводок в одном контексте отчёта: site — только сайт, all — сайт и распознанные обращения к хостам сервера вне сайта."""

    def __init__(self, workdir, context):
        self.workdir, self.context, self.where = workdir, context, CONTEXTS[context]

    def q(self, sql, params=None, frames=None):
        """Запрос к базе; frames — небольшие таблицы pandas, которые запрос видит по имени (список адресов и т. п.)."""
        con = db.connect(self.workdir, read_only=True)
        try:
            for k, df in (frames or {}).items(): con.register(k, df)
            return con.execute(sql, params or []).df()
        finally:
            con.close()

    def time(self, select, where=None, having=None):
        """Свёртка sum_time: select — колонки зерна и суммы; группировка — по всем колонкам без сумм, порядок — по ним же."""
        return self.q(f"SELECT {select} FROM sum_time WHERE {self.where}{' AND (' + where + ')' if where else ''} GROUP BY ALL{' HAVING ' + having if having else ''} ORDER BY ALL")

    def minute(self, select, where=None):
        return self.q(f"SELECT {select} FROM sum_minute WHERE {self.where}{' AND (' + where + ')' if where else ''} GROUP BY ALL ORDER BY ALL")

    def links(self, select, where=None, frames=None, params=None, group=False):
        """Свёртка sum_links с адресом цели (p.path), его шаблоном (ps.tpl) и шаблоном страницы-источника (st.tpl — только для страниц сайта среди адресов контекста)."""
        tpl = f"(SELECT DISTINCT p2.path AS path, ps2.tpl AS tpl FROM sum_path_status s2 JOIN dim_path p2 USING (path_id) JOIN path_site ps2 USING (path_id) WHERE {self.where})"
        return self.q(f"SELECT {select} FROM sum_links s JOIN dim_path p ON p.path_id = s.dst_path_id LEFT JOIN path_site ps ON ps.path_id = s.dst_path_id LEFT JOIN {tpl} st ON st.path = s.src AND s.src_kind = 'site' "
                      f"WHERE {self.where.replace('scope', 's.scope').replace('category', 's.category')}{' AND (' + where + ')' if where else ''}{' GROUP BY ALL' if group else ''}", params, frames)

    def path(self, select, where=None, having=None):
        """Свёртка sum_path_status (адрес — p.path из dim_path): группировка — по всем колонкам без сумм. Счётчики разных IP и визитов не складываются."""
        return self.q(f"SELECT {select} FROM sum_path_status s JOIN dim_path p USING (path_id) WHERE {self.where}{' AND (' + where + ')' if where else ''} GROUP BY ALL{' HAVING ' + having if having else ''} ORDER BY ALL")

    def path_day(self, select, where=None, params=None):
        """Свёртка sum_path_day."""
        return self.q(f"SELECT {select} FROM sum_path_day d JOIN dim_path p USING (path_id) WHERE {self.where}{' AND (' + where + ')' if where else ''} GROUP BY ALL ORDER BY ALL", params)

    def events(self, select, where=None, extra='', params=None):
        """Запрос по событиям (access_events) в контексте отчёта — для счётчиков, которые по сводке не сложить (разные IP по адресу и коду).
        Колонки событий — EV_COLS плюс p.path и extra; where — условие по ним."""
        return self.q(f"SELECT {select} FROM (SELECT {EV_COLS}, p.path AS path, e.is_redirect_hop AS is_hop{', ' + extra if extra else ''} FROM {EV_FROM} WHERE coalesce(h.scope, 'site') <> 'off') "
                      f"WHERE {self.where}{' AND (' + where + ')' if where else ''} GROUP BY ALL ORDER BY ALL", params)

    # ---- готовые свёртки, общие для нескольких блоков ----
    def days(self):
        """Дни, в которые были запросы, по порядку (YYYY-MM-DD)."""
        return list(self.time(f'{DAY} AS d', having='sum(n_req) > 0')['d'])

    def day_span(self):
        """Первый и последний запрос каждого дня (секунды) — какая часть суток попала в лог."""
        return self.time(f'{DAY} AS d, CAST(min(ts_first) AS BIGINT) AS t0, CAST(max(ts_last) AS BIGINT) AS t1', having='sum(n_req) > 0')

    def minutes(self):
        """По минутам, где были запросы: все счётчики sum_minute, сложенные по категориям и областям (кроме n_ip — он на зерне)."""
        cols = ('n_req', 'n_pages', 'n_page_post', 'n_page_post_5xx', 'n_page_post_499', 'n_static', 'n_static_ok', 'n_5xx', 'n_499', 'n_refused', 'bytes')
        return self.minute('CAST(minute AS BIGINT) AS m, ' + ', '.join(f'CAST(sum({c}) AS BIGINT) AS {c}' for c in cols))

    def minute_ips_5xx(self):
        """Разных IP со страницами (и POST) с ответом 5xx — по минутам. Счётчик разных IP по категориям не складывается: отдельный запрос по событиям."""
        return self.q(f"""SELECT CAST(e.ts // 60 AS BIGINT) AS m, CAST(count(DISTINCT e.ip_id) AS BIGINT) AS ip5
            FROM access_events e JOIN dim_host h ON h.host_id = e.host_id JOIN visits v ON v.vid = e.vid
            WHERE (e.is_page OR e.method = 'POST') AND e.status >= 500 AND coalesce(h.scope, 'site') <> 'off' AND {self.where.replace('scope', "coalesce(h.scope, 'site')").replace('category', 'v.category')}
            GROUP BY ALL ORDER BY ALL""")

    def visit_ips(self):
        """Разных IP у визитов по дню начала и категории, и за весь период по категории (день = '') — запрос по визитам: по дням IP не складываются."""
        w = self.where.replace('scope', 'v.scope').replace('category', 'v.category')
        return self.q(f"""SELECT strftime({EPOCH_DAY.format(ts='v.ts_start')}, '%Y-%m-%d') AS d, coalesce(v.category, '') AS category, CAST(count(DISTINCT v.ip_id) AS BIGINT) AS n_ip
            FROM visits v WHERE v.scope IN ('site', 'server') AND {w} GROUP BY ALL
            UNION ALL SELECT '' AS d, coalesce(v.category, '') AS category, CAST(count(DISTINCT v.ip_id) AS BIGINT) AS n_ip
            FROM visits v WHERE v.scope IN ('site', 'server') AND {w} GROUP BY ALL ORDER BY ALL""")


def base_codes(c, paths):
    """Адреса (текст) → коды категорий c.R['base']: блоки хранят адрес кодом строки таблицы запросов; порядок «по коду» — это порядок их группировок."""
    ix = getattr(c, '_base_index', None)
    if ix is None: ix = c._base_index = pd.Index(c.R['base'].cat.categories.astype(str))
    return ix.get_indexer(pd.Index(paths).astype(str))


def thousands(col):
    """SQL-текст числа с неразрывным пробелом между тысячами (как common.codes_text и common.who_text): 1 234 567."""
    return f"replace(format('{{:,}}', {col}), ',', '\u00a0')"


def who_sql(classes):
    """SQL-выражение класса «кто» для свёрток sum_time. classes — [(номер, условие)], последним — номер для остальных.
    Условия — по колонкам сводки; готовые: HUMAN, SEARCH_OK (подлинный поисковый робот, не «Люди»)."""
    *cond, rest = classes
    return 'CASE ' + ' '.join(f'WHEN {c} THEN {i}' for i, c in cond) + f' ELSE {rest} END'


HUMAN = "category = 'Люди'"
SEARCH_OK = "fam IN (" + ', '.join(f"'{f}'" for f in SEARCH_FAMS) + ") AND fam_verified = 'да'"


def for_contexts(workdir):
    """(сводки «всё», сводки «сайт») для analyze — или (None, None), если базы нет либо чтение сводок выключено."""
    if not enabled() or not ready(workdir): return None, None
    return Sums(workdir, 'all'), Sums(workdir, 'site')


def series2(T, k1, k2, val):
    """Таблица свёртки → Series с индексом (k1, k2), как после groupby([k1, k2]).size() по строкам запросов; нулевые строки не входят."""
    T = T[T[val] > 0]
    return T.groupby([k1, k2])[val].sum()
