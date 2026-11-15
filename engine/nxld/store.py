"""NXLD: запись результатов расчёта в базу проверки — признаки событий, визиты, карта сайта.

Пока визиты и карта считаются прежним кодом (pandas), их результат записывается в базу: дальше блоки читают базу, а не таблицы в памяти.
Вызывается дважды: в конце prepare (первичные категории) и в analyze после всех правил (итоговые категории и типы)."""
import json
import numpy as np, pandas as pd
from . import db

FLAGS = ['vid', 'is_dup', 'is_redirect_hop', 'is_embedded', 'is_page', 'form_key', 'goal_success', 'is_order', 'order_step']
SITE_TABLES = ['site_overrides', 'site_facts', 'site_forms', 'site_pages', 'site_actions', 'site_staff', 'site_monitors', 'site_embedded', 'site_ad_params']
HOW_BY_TEXT = {'справочник движка': 'engine'}


def _eids(con, n):
    """Номера событий в порядке строк R: все запросы, кроме копий сайта на других доменах, по времени."""
    e = con.execute("SELECT e.eid FROM access_events e JOIN dim_host h USING (host_id) WHERE coalesce(h.scope, 'site') <> 'off' ORDER BY e.ts, e.eid").fetchnumpy()['eid']
    if len(e) != n: raise RuntimeError(f'база проверки и таблица запросов разошлись: событий {len(e)}, строк {n}')
    return e


def event_flags(con, R, prepared=False):
    """Признаки события, которым нужен порядок во времени и карта сайта, — в колонки access_events.
    prepared — запись из prepare: состояние «до правил analyze» запоминается в prepared_events (с него analyze начинает при каждом запуске)."""
    df = pd.DataFrame({'eid': _eids(con, len(R))})
    df['vid'] = R['vid'].values.astype('int64')
    for c in ('is_dup', 'is_redirect_hop', 'is_embedded', 'is_page', 'goal_success', 'is_order', 'order_step'):
        df[c] = R[c].values.astype(bool) if c in R else False
    g = R['goal'].astype(object).values if 'goal' in R else np.full(len(R), '', dtype=object)
    df['form_key'] = np.where(g == '', None, g)
    con.register('fl_df', df)
    con.execute('CREATE OR REPLACE TEMP TABLE fl_tmp AS SELECT * FROM fl_df')   # сначала в таблицу базы: обновление прямо из таблицы pandas на порядок медленнее
    con.unregister('fl_df')
    for c in FLAGS:   # по колонке за раз: обновление нескольких колонок одним запросом в DuckDB в десятки раз медленнее
        con.execute(f'UPDATE access_events e SET {c} = f.{c} FROM fl_tmp f WHERE e.eid = f.eid')
    if prepared: con.execute('CREATE OR REPLACE TABLE prepared_events AS SELECT eid, is_page, goal_success FROM fl_tmp')
    con.execute('DROP TABLE fl_tmp')
    db.mark_built(con, 'access_events')


def visits(con, V, prepared=False):
    """Визиты: счётчики, вход, канал, категория и тип. prepared — запись из prepare: копия «до правил analyze» в prepared_visits."""
    db.ensure(con, ['visits'])
    df = pd.DataFrame({'vid': np.asarray(V.index, dtype='int64')})
    for a, b in (('ts_start', 'start'), ('ts_end', 'end'), ('entry_status', 'entry_status'), ('bytes', 'bytes')):
        df[a] = V[b].values.astype('int64')
    for c in ('n_req', 'n_pages', 'n_pages_raw', 'n_dup', 'n_redirect', 'n_embedded', 'n_static', 'n_post', 'n_head', 'n_err4', 'n_err5', 'n_catalog', 'n_goal', 'n_conv'):
        df[c] = V[c].fillna(0).values.astype('int64') if c in V else 0
    for a, b in (('ip', 'ip'), ('ua', 'ua'), ('entry', 'entry'), ('entry_query', 'entry_query'), ('entry_ref', 'entry_ref'), ('channel', 'channel'), ('channel_sub', 'channel_sub'),
                 ('fam', 'fam'), ('fam_verified', 'fam_verified'), ('category', 'group'), ('type', 'subgroup')):
        df[a] = V[b].astype(object).values if b in V else None
    df['scope'] = np.where(V['host_site'].values.astype(bool), 'site', 'server') if 'host_site' in V else 'site'
    con.register('v_df', df)
    con.execute('DELETE FROM visits')
    con.execute("""INSERT INTO visits (vid, ip_id, ua_id, ts_start, ts_end, n_req, n_pages, n_pages_raw, n_dup, n_redirect, n_embedded, n_static, n_post, n_head, n_err4, n_err5, n_catalog, n_goal, n_conv,
                                       bytes, scope, entry_path_id, entry_query_id, entry_status, entry_ref_id, channel, channel_sub, fam, fam_verified, category, type, category_before)
        SELECT v.vid, i.ip_id, u.ua_id, v.ts_start, v.ts_end, v.n_req, v.n_pages, v.n_pages_raw, v.n_dup, v.n_redirect, v.n_embedded, v.n_static, v.n_post, v.n_head, v.n_err4, v.n_err5, v.n_catalog, v.n_goal, v.n_conv,
               v.bytes, v.scope, p.path_id, q.query_id, v.entry_status, f.ref_id, v.channel, v.channel_sub, v.fam, v.fam_verified, v.category, v.type, NULL
        FROM v_df v LEFT JOIN dim_ip i ON i.ip = v.ip LEFT JOIN dim_ua u ON u.ua = v.ua LEFT JOIN dim_path p ON p.path = v.entry LEFT JOIN dim_query q ON q.query = v.entry_query
        LEFT JOIN dim_ref f ON f.ref = v.entry_ref ORDER BY v.vid""")
    con.unregister('v_df')
    if prepared: con.execute('CREATE OR REPLACE TABLE prepared_visits AS SELECT * FROM visits')
    db.mark_built(con, 'visits')


# уровень доказанности по правилу: log — по поведению в логе, pattern — по подписи или справочнику, network — по сети (и почерку)
RULE_LEVEL = {'regroup': 'pattern', 'web_archive': 'network', 'gov_robots': 'network', 'app_agents': 'pattern', 'scanners': 'log', 'backups': 'log', 'files_only': 'log', 'unrendered': 'log',
              'service_checks': 'network', 'system_agents': 'pattern', 'own_server': 'log', 'form_spam': 'log', 'gov_robots_finish': 'network'}


class Trail:
    """След правил analyze: какое правило последним изменило категорию или тип визита и какой категория была до него."""

    def __init__(self, V):
        self.g, self.s = V['group'].astype(str).copy(), V['subgroup'].astype(str).copy()
        self.index = V.index
        self.rule = np.full(len(V), '', dtype=object)
        self.before = np.full(len(V), '', dtype=object)

    def step(self, V, rule):
        g, s = V['group'].astype(str).reindex(self.g.index), V['subgroup'].astype(str).reindex(self.g.index)
        ch = ((g != self.g) | (s != self.s)).values
        if ch.any():
            self.rule[ch] = rule
            self.before[ch] = self.g.values[ch]
            self.g, self.s = g, s
        return V

    def write(self, con):
        df = pd.DataFrame({'vid': np.asarray(self.index, dtype='int64'), 'rule': self.rule, 'category_before': self.before})
        df = df[df['rule'] != '']
        df['level'] = df['rule'].map(RULE_LEVEL)
        con.register('tr_df', df)
        con.execute('CREATE OR REPLACE TEMP TABLE tr_tmp AS SELECT * FROM tr_df')
        con.unregister('tr_df')
        for c in ('rule', 'level', 'category_before'):
            con.execute(f'UPDATE visits v SET {c} = t.{c} FROM tr_tmp t WHERE v.vid = t.vid')
        con.execute('DROP TABLE tr_tmp')


def _rows(con, table, cols, rows):
    con.execute(f'DELETE FROM {table}')
    if rows: con.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)


def _j(v):
    return json.dumps(v, ensure_ascii=False, default=str)


def site_map(con, m, override=None):
    """Карта сайта — в таблицы site_*. Файл site_map.json остаётся распечаткой для Детектива."""
    db.ensure(con, SITE_TABLES)
    if override is None:   # поправки уже загружены (prepare): читаем их из базы
        override = {}
        for k, pos, v in con.execute('SELECT key, pos, value FROM site_overrides ORDER BY key, pos').fetchall():
            override.setdefault(k, []).append(json.loads(v))
    else:
        _rows(con, 'site_overrides', ['key', 'pos', 'value'], [(k, i, _j(x)) for k, v in override.items() for i, x in enumerate(v if isinstance(v, list) else [v])])
    okeys = set((override or {}).keys())
    facts = [(k, _j(m[k]), 'override' if k in okeys else 'behavior') for k in ('site_hosts', 'server', 'engines', 'engines_all', 'admin_regex', 'catalog_templates', 'top_sections', 'service_files', 'get_pd_requests', 'shop')
             if k in m]
    if isinstance(m.get('orders'), dict): facts.append(('orders', _j({k: v for k, v in m['orders'].items() if k in ('движки', 'заказов', 'to_verify')}), 'engine'))
    _rows(con, 'site_facts', ['key', 'value', 'how'], facts)
    rules = m.get('form_success_rules') or {}
    forms = {}
    for f in m.get('forms') or []:
        k = str(f.get('адрес'))
        tpl, _, fp = k.partition('?form=')
        forms[k] = (k, tpl, fp or None, str(f.get('вывод') or ''), rules.get(k), k in rules, 'override' if 'form_success_rules' in okeys and k in rules else 'behavior')
    for k, r in rules.items():   # цель из поправки карты, которой нет среди найденных форм
        if k not in forms:
            tpl, _, fp = k.partition('?form=')
            forms[k] = (k, tpl, fp or None, '', r, True, 'override')
    _rows(con, 'site_forms', ['form_key', 'tpl', 'form_param', 'verdict', 'success_rule', 'is_goal', 'how'], list(forms.values()))
    pages = {}
    for role, key in (('cart', 'cart'), ('checkout', 'checkout'), ('order_success', 'success')):
        for p in (m.get('orders') or {}).get(key) or []:
            if isinstance(p, dict) and p.get('path'):
                pages[(role, p['path'])] = (role, p['path'], p.get('param'), p.get('how'), p.get('pattern'), bool(p.get('to_verify')))
    _rows(con, 'site_pages', ['role', 'pattern', 'param', 'how', 'ref', 'to_verify'], list(pages.values()))
    rule_of = {(r.get('kind'), r.get('path')): r for r in (m.get('shop') or {}).get('rules') or [] if isinstance(r, dict)}
    acts = {}
    for a in m.get('site_actions_found') or []:
        r = rule_of.get((a.get('kind'), a.get('path'))) or {}
        acts[(a.get('path'), a.get('kind'))] = (a.get('path'), a.get('kind'), a.get('background') or 'none', r.get('select'), a.get('visits'), a.get('lift'), a.get('level'), a.get('how'), a.get('pattern'), a.get('level') not in ('log', 'experiment'))
    _rows(con, 'site_actions', ['pattern', 'kind', 'background', 'rule', 'visits', 'lift', 'level', 'how', 'ref', 'to_verify'], list(acts.values()))
    staff = [(ip, 'сотрудник', 'override' if ip in ((override or {}).get('staff_ips') or []) else 'behavior') for ip in dict.fromkeys(m.get('staff_ips') or [])] + \
            [(ip, 'сервер сайта', 'behavior') for ip in dict.fromkeys(m.get('server_ips') or []) if ip not in (m.get('staff_ips') or [])]
    con.execute('DELETE FROM site_staff')
    if staff:
        con.register('st_df', pd.DataFrame(staff, columns=['ip', 'role', 'how']))
        con.execute('INSERT INTO site_staff (ip_id, role, how) SELECT i.ip_id, s.role, s.how FROM st_df s JOIN dim_ip i ON i.ip = s.ip')
        con.unregister('st_df')
    con.execute('DELETE FROM site_monitors')
    mons = [(x.get('ip'), x.get('ua'), x.get('адрес'), x.get('интервал_с'), x.get('запросов')) for x in m.get('monitors') or []]
    if mons:
        con.register('mn_df', pd.DataFrame(mons, columns=['ip', 'ua', 'path', 'interval_s', 'n_req']))
        con.execute("""INSERT INTO site_monitors (ip_id, ua_id, path_id, interval_s, n_req, how)
            SELECT i.ip_id, u.ua_id, p.path_id, s.interval_s, s.n_req, 'behavior' FROM mn_df s JOIN dim_ip i ON i.ip = s.ip JOIN dim_ua u ON u.ua = s.ua JOIN dim_path p ON p.path = s.path""")
        con.unregister('mn_df')
    _rows(con, 'site_embedded', ['tpl', 'share_after_page', 'n_req', 'how'], [(e.get('шаблон'), e.get('доля_сразу_после_страницы'), e.get('запросов'), 'behavior') for e in m.get('embedded_templates') or []])
    _rows(con, 'site_ad_params', ['param', 'system', 'n_req', 'how'], [(k, 'реклама', int(v), 'engine') for k, v in (m.get('ad_params') or {}).items()] +
          [(k, 'прочее', int(v), 'behavior') for k, v in (m.get('other_entry_params') or {}).items() if k not in (m.get('ad_params') or {})])
    for t in SITE_TABLES: db.mark_built(con, t)


def all_of(workdir, R, V, m, override=None, con=None, prepared=False, trail=None):
    own = con is None
    if own: con = db.connect(workdir)
    event_flags(con, R, prepared); visits(con, V, prepared); site_map(con, m, override)
    if trail is not None: trail.write(con)
    if own: con.close()
