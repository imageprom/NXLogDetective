"""Схема базы проверки (data/schema/db_schema.json): выполняется в DuckDB, ссылки ведут в существующие колонки,
порядок построения таблиц существует (нет круговых зависимостей), имена — латиницей, у каждой колонки есть описание."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import duckdb
from nxld import db


def test_schema_executes_and_links_resolve():
    S = db.schema()
    con = duckdb.connect()
    cols = {t['name']: [c['name'] for c in t['columns']] for t in S['tables']}
    for t in S['tables']:
        con.execute(db.ddl(t['name']))
        assert re.fullmatch(r'[a-z][a-z0-9_]*', t['name']), t['name']
        assert len(set(cols[t['name']])) == len(cols[t['name']]), t['name']
        assert t['grain_ru'] and set(t['pk']) <= set(cols[t['name']]), t['name']
        for c in t['columns']:
            assert re.fullmatch(r'[a-z][a-z0-9_]*', c['name']) and c.get('ru'), (t['name'], c['name'])
            if 'fk' in c:
                ft, fc = c['fk'].split('.')
                assert fc in cols.get(ft, []), (t['name'], c['name'], c['fk'])
            if 'enum' in c: assert c['enum'] in S['enums'], (t['name'], c['name'])


def test_build_order_exists():
    S = db.schema()
    deps = {t['name']: {d for d in t['depends_on'] if not d.startswith('ref:')} for t in S['tables']}
    for t in S['tables']:
        for part, p in (t.get('parts') or {}).items():
            deps[f"{t['name']}#{part}"] = {t['name']} | {d for d in p['depends_on'] if not d.startswith('ref:')}
    for n, ds in deps.items():
        assert ds <= set(deps), (n, ds - set(deps))
    done = set()
    while len(done) < len(deps):
        ready = {n for n in deps if n not in done and deps[n] <= done}
        assert ready, 'круговая зависимость: ' + ', '.join(sorted(set(deps) - done))
        done |= ready
