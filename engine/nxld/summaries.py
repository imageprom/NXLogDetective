"""NXLD: сводки «Время» (sum_time) и «Минута» (sum_minute) в базе проверки — и чтение из них для блоков.

Сводки строятся в analyze после всех правил (store.all_of): итоговые категории и типы визитов уже в базе.
Пересобираются целиком при каждом analyze. Блоки читают их запросом и получают небольшую таблицу pandas — события в память не выгружаются.

Области. В сводках — события и визиты хостов сайта (scope = site) и того же сервера вне сайта (server); копий на других доменах (off) нет.
Отчёт читает сводки в одном из двух контекстов (как таблицы R и V в analyze.run):
  site — только сайт (файлы 01, 02, 05, 06);
  all  — сайт и сервер, кроме нераспознанных посетителей («Люди») хостов вне сайта (файлы 03, 04).

Счётчики разных IP (sum_minute.n_ip) верны только на зерне сводки: по минутам, областям и категориям их складывать нельзя.
«Кто» — признаки визита: все запросы визита попадают в одну строку «кто» своего часа."""
import os
import numpy as np, pandas as pd
from . import db

TABLES = ('sum_time', 'sum_minute')
CONTEXTS = {'site': "scope = 'site'", 'all': "NOT (scope = 'server' AND category = 'Люди')"}
SEARCH_FAMS = ('YandexBot', 'Googlebot', 'YandexRenderResourcesBot', 'Googlebot-Image', 'Bingbot')   # подлинные поисковые роботы: тот же список, что blocks.Ctx.search_ok
DAY = "strftime(day, '%Y-%m-%d')"
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


def enabled():
    """NXLD_SUMMARIES=0 — блоки считают по-старому, по таблицам в памяти (для сверки); сводки при этом всё равно строятся."""
    return os.environ.get('NXLD_SUMMARIES', '1') != '0'


def build(workdir, con=None, log=None):
    """Обе сводки — заново из событий и визитов. Возвращает {таблица: строк}."""
    import time
    own = con is None
    if own: con = db.connect(workdir)
    out = {}
    try:
        for name, sql in (('sum_time', SQL_TIME), ('sum_minute', SQL_MINUTE)):
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

    def q(self, sql, params=None):
        con = db.connect(self.workdir, read_only=True)
        try:
            return con.execute(sql, params or []).df()
        finally:
            con.close()

    def time(self, select, where=None, having=None):
        """Свёртка sum_time: select — колонки зерна и суммы; группировка — по всем колонкам без сумм, порядок — по ним же."""
        return self.q(f"SELECT {select} FROM sum_time WHERE {self.where}{' AND (' + where + ')' if where else ''} GROUP BY ALL{' HAVING ' + having if having else ''} ORDER BY ALL")

    def minute(self, select, where=None):
        return self.q(f"SELECT {select} FROM sum_minute WHERE {self.where}{' AND (' + where + ')' if where else ''} GROUP BY ALL ORDER BY ALL")

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
