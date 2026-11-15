"""NXLD: база проверки — один файл DuckDB в рабочей папке (work/nxld.duckdb).

Состав таблиц описан в data/schema/db_schema.json: зерно, колонки, от чего зависит построение.
Ключи и ссылки из схемы — описание; ограничениями в базе не создаются (целостность проверяют тесты)."""
import json, os, time
import duckdb

FILE = 'nxld.duckdb'
SCHEMA_FN = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'schema', 'db_schema.json')
_schema = None


def schema():
    global _schema
    if _schema is None:
        j = json.load(open(SCHEMA_FN, encoding='utf-8'))
        j['by_name'] = {t['name']: t for t in j['tables']}
        _schema = j
    return _schema


def memory_limit():
    """Лимит памяти DuckDB: NXLD_DB_MEMORY (например, 3GB) или 60 % доступной памяти."""
    v = os.environ.get('NXLD_DB_MEMORY')
    if v: return v
    try:
        for line in open('/proc/meminfo'):
            if line.startswith('MemAvailable:'):
                return f"{max(512, int(int(line.split()[1]) / 1024 * 0.6))}MB"
    except OSError:
        pass
    return None


def connect(workdir, read_only=False):
    os.makedirs(workdir, exist_ok=True)
    fn = os.path.join(workdir, FILE)
    if not read_only and os.path.exists(fn):   # база другой версии схемы — строится заново (логи читаются ещё раз)
        c0 = duckdb.connect(fn)
        try: old = c0.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        except duckdb.Error: old = None
        c0.close()
        if not old or old[0] != schema()['schema_version']:
            for f in (fn, fn + '.wal'):
                if os.path.exists(f): os.remove(f)
    con = duckdb.connect(fn, read_only=read_only)
    lim = memory_limit()
    if lim: con.execute(f"SET memory_limit='{lim}'")
    tmp = os.path.join(workdir, 'db_tmp')
    con.execute(f"SET temp_directory='{tmp}'")
    if not read_only:
        ensure(con, ['meta', 'build_state', 'ref_versions'])
        set_meta(con, 'schema_version', schema()['schema_version'])
    return con


def ddl(name):
    t = schema()['by_name'][name]
    return f"CREATE TABLE IF NOT EXISTS {name} (" + ', '.join(f"{c['name']} {c['type']}" for c in t['columns']) + ')'


def ensure(con, names):
    for n in names: con.execute(ddl(n))


def set_meta(con, key, value):
    con.execute('DELETE FROM meta WHERE key = ?', [key])
    con.execute('INSERT INTO meta VALUES (?, ?)', [key, None if value is None else str(value)])


def get_meta(con, key, default=None):
    r = con.execute('SELECT value FROM meta WHERE key = ?', [key]).fetchone()
    return r[0] if r else default


def mark_built(con, table, inputs_hash='', seconds=0.0):
    """Запись о построении таблицы: по ней решается, что пересчитывать."""
    rows = con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
    con.execute('DELETE FROM build_state WHERE table_name = ?', [table])
    con.execute('INSERT INTO build_state VALUES (?, now()::TIMESTAMP, ?, ?, ?)', [table, inputs_hash, rows, round(seconds, 2)])
    return rows


def exists(workdir):
    return os.path.exists(os.path.join(workdir, FILE))
