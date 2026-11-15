"""Словари базы проверки (0.3, круг 2): признаки значения лежат в словаре и считаются один раз на значение.
Таблица запросов, собранная из событий и словарей базы, совпадает с прежней R по всем признакам. Данные вымышленные."""
import os, sys, tempfile
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import pandas as pd
import synth, test_golden_report
from nxld import db, dims, prepare, ingest

SQL = """SELECT e.ts, i.ip, i.asn, i.nettype, i.cc, p.ext, p.is_static, f.ref_host, f.is_internal, f.ref_path, u.fam, u.fam_cat, u.is_browser, u.is_old, u.is_mobile, u.is_webview,
                s.tpl, s.is_admin, h.scope = 'site' host_site
         FROM access_events e JOIN dim_ip i USING (ip_id) JOIN dim_path p USING (path_id) JOIN dim_ref f USING (ref_id) JOIN dim_ua u USING (ua_id)
         JOIN dim_host h USING (host_id) LEFT JOIN path_site s USING (path_id) WHERE h.scope <> 'off' ORDER BY e.ts, e.eid"""
PAIRS = [('ts', 'ts'), ('ip', 'ip'), ('asn', 'asn'), ('nettype', 'nettype'), ('cc', 'cc'), ('ext', 'ext'), ('is_static', 'is_static'), ('ref_host', 'ref_host'), ('is_internal', 'ref_internal'),
         ('ref_path', 'ref_path'), ('fam', 'fam'), ('fam_cat', 'fam_cat'), ('is_browser', 'ua_browser'), ('is_old', 'ua_old'), ('is_mobile', 'ua_mobile'), ('is_webview', 'ua_webview'),
         ('tpl', 'tpl'), ('is_admin', 'is_admin'), ('host_site', 'host_site')]


def _log():
    L = test_golden_report.golden_log()
    for k in range(40):   # хост по IP сервера и копия на другом домене
        L.line('203.0.113.50', synth.T0 + timedelta(hours=6, seconds=k), f'/p{k}/', 200, host='192.0.2.10')
        L.line('203.0.113.51', synth.T0 + timedelta(hours=7, seconds=k), '/', 200, host='copy.example.org')
    for ip in synth.RU[:3]:
        L.line(ip, synth.T0 + timedelta(hours=9), '/bitrix/admin/index.php', 200, host='site.ru')
    return L


def _prepare(d, L, name='access.log'):
    p = os.path.join(d, name); L.write(p)
    prepare.run([os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith('.log')], os.path.join(d, 'w'), log=lambda *_: None)
    return os.path.join(d, 'w')


def test_requests_from_database_match_old_table():
    with tempfile.TemporaryDirectory() as d:
        w = _prepare(d, _log())
        R = pd.read_pickle(os.path.join(w, 'R.pkl'))
        con = db.connect(w, read_only=True)
        D = con.execute(SQL).fetchdf()
        assert len(D) == len(R) and len(R) > 1000
        for a, b in PAIRS:
            x, y = D[a].astype(str).values, R[b].astype(str).values
            assert (x == y).all(), (a, b, [(u, v) for u, v in zip(x, y) if u != v][:3])
        # копия на другом домене — в базе остаётся, область «вне отчёта»; хост по IP — «тот же сервер»
        sc = dict(con.execute('SELECT host, scope FROM dim_host').fetchall())
        assert sc['copy.example.org'] == 'off' and sc['192.0.2.10'] == 'server' and sc['site.ru'] == 'site'
        assert con.execute("SELECT count(*) FROM access_events e JOIN dim_host h USING (host_id) WHERE h.scope = 'off'").fetchone()[0] == 40


def test_query_params_are_split_once_per_query():
    with tempfile.TemporaryDirectory() as d:
        L = synth.Log(); L.people(days=1, per_day=5)
        L.line(synth.RU[0], synth.T0 + timedelta(hours=9), '/catalog/?PAGEN_1=2&sort=price&flag', 200)
        L.line(synth.RU[1], synth.T0 + timedelta(hours=9, minutes=1), '/ajax/form.php?form_id=callback&x=1', 200, method='POST', ref='https://site.ru/')
        w = _prepare(d, L)
        con = db.connect(w, read_only=True)
        got = con.execute("SELECT key, value FROM query_params JOIN dim_query USING (query_id) WHERE query = 'PAGEN_1=2&sort=price&flag' ORDER BY pos").fetchall()
        assert got == [('PAGEN_1', '2'), ('sort', 'price'), ('flag', None)]
        assert con.execute("SELECT form_param FROM dim_query WHERE query = 'form_id=callback&x=1'").fetchone()[0] == 'callback'
        assert con.execute('SELECT count(*) FROM (SELECT query_id, pos FROM query_params GROUP BY ALL HAVING count(*) > 1)').fetchone()[0] == 0


def test_only_new_values_are_computed_on_reload(monkeypatch):
    """Дозагрузка куска: сеть ищется только для IP, которых не было; изменился справочник — словарь считается заново."""
    with tempfile.TemporaryDirectory() as d:
        L = synth.Log(); L.people(days=2, per_day=10)
        w = _prepare(d, L, 'a.log')
        asked = []
        real = dims.ipdb.lookup
        monkeypatch.setattr(dims.ipdb, 'lookup', lambda ips: (asked.append(list(ips)), real(ips))[1])
        L2 = synth.Log()
        L2.line('198.51.100.77', synth.T0 + timedelta(days=3), '/', 200); L2.line(synth.RU[0], synth.T0 + timedelta(days=3, minutes=1), '/about/', 200)
        _prepare(d, L2, 'b.log')
        assert asked == [['198.51.100.77']]
        con = db.connect(w)
        n = con.execute('SELECT count(*) FROM dim_ip').fetchone()[0]
        con.execute("UPDATE ref_versions SET hash = 'old' WHERE name = 'dim_ip'")
        asked.clear(); dims.fill_common(con)
        assert len(asked) == 1 and len(asked[0]) == n
        assert con.execute('SELECT count(*) FROM dim_ip WHERE nettype IS NULL').fetchone()[0] == 0


def test_visits_flags_and_site_map_are_in_database():
    """После prepare визиты и признаки событий в базе совпадают с прежними таблицами; карта сайта разложена по таблицам."""
    import json
    with tempfile.TemporaryDirectory() as d:
        L = _log()
        ovr = {'staff_ips': ['198.51.100.200'], 'not_site_hosts': ['old.example.net']}
        L.line('198.51.100.200', synth.T0 + timedelta(hours=11), '/about/', 200, host='site.ru')
        p = os.path.join(d, 'access.log'); L.write(p)
        w = os.path.join(d, 'w')
        prepare.run([p], w, log=lambda *_: None, map_override=ovr)
        R, V = pd.read_pickle(os.path.join(w, 'R.pkl')), pd.read_pickle(os.path.join(w, 'V.pkl'))
        m = json.load(open(os.path.join(w, 'site_map.json')))
        con = db.connect(w, read_only=True)
        D = con.execute("""SELECT e.vid, e.is_dup, e.is_redirect_hop, e.is_embedded, e.is_page, coalesce(e.form_key, '') goal, e.goal_success, e.is_order, e.order_step
                           FROM access_events e JOIN dim_host h USING (host_id) WHERE h.scope <> 'off' ORDER BY e.ts, e.eid""").fetchdf()
        for c in D.columns:
            assert (D[c].astype(str).values == R[c].astype(str).values).all(), c
        X = con.execute("""SELECT v.vid, i.ip, u.ua, v.ts_start "start", v.ts_end "end", v.n_req, v.n_pages, v.n_pages_raw, v.n_dup, v.n_redirect, v.n_embedded, v.n_static, v.n_post, v.n_head, v.n_err4, v.n_err5,
                                  v.n_catalog, v.n_goal, v.n_conv, v.bytes, v.scope = 'site' host_site, p.path entry, q.query entry_query, v.entry_status, f.ref entry_ref, v.channel, v.channel_sub,
                                  v.fam_verified, v.category "group", v.type subgroup
                           FROM visits v JOIN dim_ip i USING (ip_id) JOIN dim_ua u USING (ua_id) JOIN dim_path p ON p.path_id = v.entry_path_id JOIN dim_query q ON q.query_id = v.entry_query_id
                           JOIN dim_ref f ON f.ref_id = v.entry_ref_id ORDER BY v.vid""").fetchdf().set_index('vid')
        assert len(X) == len(V) and len(V) > 100
        for c in X.columns:
            assert (X[c].astype(str).values == V[c].astype(str).values).all(), c
        # счётчики визита сходятся с событиями
        assert con.execute("""SELECT count(*) FROM visits v JOIN (SELECT vid, count(*) n, count(*) FILTER (is_page) pg FROM access_events WHERE vid IS NOT NULL GROUP BY 1) e USING (vid)
                              WHERE v.n_req <> e.n OR v.n_pages <> e.pg""").fetchone()[0] == 0
        # карта сайта
        assert json.loads(con.execute("SELECT value FROM site_facts WHERE key = 'admin_regex'").fetchone()[0]) == m['admin_regex']
        assert con.execute("SELECT role, how FROM site_staff JOIN dim_ip USING (ip_id) WHERE ip = '198.51.100.200'").fetchone() == ('сотрудник', 'override')
        assert con.execute("SELECT count(*) FROM site_forms").fetchone()[0] == len(m['forms'])
        assert set(con.execute("SELECT form_key FROM site_forms WHERE is_goal").fetchnumpy()['form_key']) == set(m['form_success_rules'])
        assert dict(con.execute("SELECT key, count(*) FROM site_overrides GROUP BY 1").fetchall()) == {'staff_ips': 1, 'not_site_hosts': 1}


def test_final_categories_are_written_after_rules():
    """После analyze в базе итоговые категории и типы визитов (после всех правил), а число визитов людей к сайту совпадает со сводкой отчёта."""
    with tempfile.TemporaryDirectory() as d:
        res, _, _ = synth.run(_log(), d)
        con = db.connect(os.path.join(d, 'work'), read_only=True)
        s = res['summary']['Общий анализ']
        assert con.execute("SELECT count(*) FROM visits WHERE category = 'Люди' AND scope = 'site'").fetchone()[0] == s['Визитов людей']
        assert con.execute("SELECT count(*) FROM access_events e JOIN visits v USING (vid) WHERE v.category = 'Люди' AND v.scope = 'site' AND e.is_page").fetchone()[0] == s['Просмотров страниц людьми']
        assert con.execute("SELECT count(*) FROM access_events e JOIN visits v USING (vid) WHERE v.scope = 'site' AND e.form_key IS NOT NULL").fetchone()[0] == s['Отправок целей всего']
        cats = dict(con.execute('SELECT category, count(*) FROM visits GROUP BY 1').fetchall())
        assert cats.get('Утилиты') and cats.get('Роботы') and cats.get('Боты')
        assert con.execute("SELECT count(*) FROM visits WHERE category = 'Боты' AND type IS NOT NULL AND type <> ''").fetchone()[0] > 0
