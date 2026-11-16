"""NXLD: выводы и свидетельства — в таблицы базы проверки (work/nxld.duckdb).

Выводы (группа «суждения и выводы» схемы) — findings, cases, case_members, signatures, ip_measures. Пишутся в конце analyze и при сборке отчёта
(после правок edits.json): таблицы пересобираются целиком из results. results.pkl остаётся; из таблиц восстанавливается то же самое (read).
Свидетельства (группа «свидетельства и правки») — testimony, experiments, net_checks, ip_overrides, case_overrides, finding_overrides:
содержимое edits.json раскладывается как есть (load_edits); файл остаётся входом и не меняется.
learned — записи справочников data/reference/learned/*.json, в которых участвует этот сайт (sync_learned); запись в папку движка остаётся.

Пустое значение колонки — у записи этого поля нет. Числа карточки лежат отдельно от текста (findings.params).
Запись — через временную таблицу: вставка из таблицы pandas напрямую на порядок медленнее."""
import json, os, re
import numpy as np, pandas as pd
from . import db

CONCLUSIONS = ('findings', 'cases', 'case_members', 'signatures', 'ip_measures')
EVIDENCE = ('testimony', 'experiments', 'net_checks', 'ip_overrides', 'case_overrides', 'finding_overrides')
# поле карточки → колонка
FINDING_TEXT = {'блок': 'block', 'важность': 'severity', 'заголовок': 'title', 'что_происходит': 'what', 'факты': 'facts', 'где_править': 'where_fix', 'что_сделать': 'action',
                'лист': 'sheet', 'статус': 'status', 'доказательство': 'evidence', 'тема': 'topic'}
FINDING_PARAMS = ('главная_цифра', 'было', 'стало', 'окно')
CASE_COLS = {'дело': 'case_id', 'кличка': 'alias', 'вид': 'kind', 'важность': 'severity', 'запросов': 'n_req', 't0': 'ts_first', 't1': 'ts_last'}
MEMBER_COLS = {'дело': 'case_id', 'кличка': 'alias', 'ip': 'ip', 'подсеть': 'subnet', 'сеть': 'network', 'страна': 'country', 'роль': 'role', 'запросов': 'n_req',
               'первый': 'first_day', 'последний': 'last_day', 'пометка': 'note'}
SIG_COLS = {'id': 'sig_id', 'правило': 'rule', 'вид': 'kind', 'дело': 'case_id', 'кличка': 'alias', 'проверка': 'fp_check', 'ложных': 'n_false', 'IP': 'n_ip', 'запросов': 'n_req'}   # порядок — как колонки «сигнатуры» в results
MEASURE_COLS = {'ip': 'ip', 'дело': 'case_id', 'кличка': 'alias', 'подсеть': 'subnet', 'сеть': 'network', 'asn': 'asn', 'страна': 'country', 'тип_сети': 'net_type', 'визитов': 'n_visits',
                'запросов': 'n_req', 'отправок': 'n_submits', 'приговор': 'verdict', 'основание': 'reason', 'первый': 'first_day', 'последний': 'last_day'}


# ---------- JSON ----------
def _plain(x):
    """Значение → то, что умеет JSON: числа numpy — числами, кортежи и множества — списками, NaN — пустым."""
    if x is None: return None
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating, float)): return None if x != x else float(x)
    if isinstance(x, (np.bool_,)): return bool(x)
    if isinstance(x, dict): return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)): return [_plain(v) for v in x]
    if isinstance(x, np.ndarray): return [_plain(v) for v in x.tolist()]
    if isinstance(x, pd.Timestamp): return str(x)
    if isinstance(x, pd.DataFrame): return _plain(x.to_dict('records'))
    return x


def jdump(x):
    return None if x is None else json.dumps(_plain(x), ensure_ascii=False)


def _text(v):
    return None if v is None or (isinstance(v, float) and v != v) else str(v)


def _int(v):
    try: return None if v is None or v != v else int(v)
    except (TypeError, ValueError): return None


def _insert(con, table, df, cols):
    """Таблица заменяется целиком: строки — из таблицы pandas через временную таблицу базы."""
    con.execute(f'DELETE FROM {table}')
    if len(df):
        con.register('cn_df', df[cols])
        con.execute('CREATE OR REPLACE TEMP TABLE cn_tmp AS SELECT * FROM cn_df')
        con.unregister('cn_df')
        con.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM cn_tmp")
        con.execute('DROP TABLE cn_tmp')
    db.mark_built(con, table)


def _open(workdir, con):
    own = con is None
    if own: con = db.connect(workdir)
    return con, own


# ---------- выводы: запись ----------
def _findings_frame(F):
    rows = []
    for i, x in enumerate(F or []):
        r = {'key': _text(x.get('key')), 'code': None, 'also_in': None, 'pos': i}
        extra = {}
        for k, v in x.items():
            if k == 'key': continue
            if k in FINDING_TEXT and (v is None or isinstance(v, str)): r[FINDING_TEXT[k]] = v
            elif k == 'также_в': r['also_in'] = jdump(v)
            elif k in FINDING_PARAMS: pass
            else: extra[k] = v
        r['params'] = jdump({k: x[k] for k in FINDING_PARAMS if k in x}) if any(k in x for k in FINDING_PARAMS) else None
        r['extra'] = jdump(extra) if extra else None
        parts = str(x.get('key', '')).split(':')
        r['code'] = parts[1] if len(parts) > 1 else None
        rows.append(r)
    cols = ['key', 'block', 'code', 'severity', 'title', 'what', 'facts', 'where_fix', 'action', 'sheet', 'also_in', 'status', 'evidence', 'topic', 'params', 'extra', 'pos']
    return pd.DataFrame(rows, columns=cols).astype({'pos': 'int64'}) if rows else pd.DataFrame(columns=cols), cols


def _cases_frame(D):
    rows = []
    for i, x in enumerate(D or []):
        r = {CASE_COLS[k]: x.get(k) for k in CASE_COLS if k not in ('t0', 't1', 'запросов')}
        r.update(n_ip=len(x.get('ips') or []), n_req=_int(x.get('запросов')), ts_first=_int(x.get('t0')), ts_last=_int(x.get('t1')), pos=i)
        r['card'] = jdump({k: v for k, v in x.items() if k not in CASE_COLS})
        rows.append(r)
    cols = ['case_id', 'alias', 'kind', 'severity', 'n_ip', 'n_req', 'ts_first', 'ts_last', 'card', 'pos']
    return (pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)), cols


def _by_columns(df, mapping, extra_cols=()):
    """Таблица результатов (русские колонки) → таблица базы (латинские колонки): числа — числами, остальное — текстом."""
    out = pd.DataFrame({new: df[old].values for old, new in mapping.items() if old in df})
    return out


def _ip_ids(con, ips):
    d = con.execute('SELECT ip, ip_id FROM dim_ip').fetchdf()
    return pd.Series(ips).map(dict(zip(d['ip'], d['ip_id']))).astype('Int64')


def write(workdir, res, con=None):
    """Выводы из results — в таблицы базы: карточки, дела, состав, сигнатуры, меры по IP. Возвращает {таблица: строк}."""
    if not db.exists(workdir): return {}
    con, own = _open(workdir, con)
    try:
        db.ensure(con, list(CONCLUSIONS))
        Pf = res.get('profiles') or {}
        df, cols = _findings_frame(res.get('findings'))
        _insert(con, 'findings', df, cols)
        df, cols = _cases_frame(Pf.get('дела'))
        _insert(con, 'cases', df, cols)
        # состав дел
        M = Pf.get('состав')
        cols = ['case_id', 'ip_id', 'ip', 'alias', 'subnet', 'network', 'country', 'role', 'n_req', 'first_day', 'last_day', 'note', 'pos']
        if isinstance(M, pd.DataFrame) and len(M):
            df = _by_columns(M, MEMBER_COLS)
            df['ip_id'] = _ip_ids(con, df['ip']).values
            df['pos'] = np.arange(len(df))
        else: df = pd.DataFrame(columns=cols)
        _insert(con, 'case_members', df, cols)
        # сигнатуры
        S = Pf.get('сигнатуры')
        cols = ['sig_id', 'case_id', 'alias', 'rule', 'kind', 'fp_check', 'n_false', 'n_ip', 'n_req', 'pos']
        if isinstance(S, pd.DataFrame) and len(S):
            df = _by_columns(S, SIG_COLS); df['pos'] = np.arange(len(df))
        else: df = pd.DataFrame(columns=cols)
        _insert(con, 'signatures', df, cols)
        # меры по IP: строки «Мер по IP» и IP с обычными визитами людей, которых в мерах нет
        MI = Pf.get('меры_ip')
        people = sorted(set(map(str, Pf.get('меры_ip_люди') or [])))
        cols = ['ip', 'ip_id', 'case_id', 'alias', 'verdict', 'reason', 'subnet', 'network', 'asn', 'country', 'net_type', 'n_visits', 'n_req', 'n_submits', 'first_day', 'last_day', 'has_people', 'pos']
        if isinstance(MI, pd.DataFrame) and len(MI):
            df = _by_columns(MI, MEASURE_COLS); df['pos'] = np.arange(len(df))
            df['case_id'] = df['case_id'].where(df['case_id'].astype(str) != '', None) if 'case_id' in df else None
        else: df = pd.DataFrame({'ip': pd.Series(dtype=object)})
        have = set(df['ip'].astype(str))   # один раз: на сотнях тысяч IP людей пересборка множества на каждый IP — минуты
        only = [ip for ip in people if ip not in have]
        if only: df = pd.concat([df, pd.DataFrame({'ip': only})], ignore_index=True)
        if len(df):
            df['has_people'] = df['ip'].astype(str).isin(people)
            df['ip_id'] = _ip_ids(con, df['ip']).values
            for c in cols:
                if c not in df: df[c] = None
        else: df = pd.DataFrame(columns=cols)
        _insert(con, 'ip_measures', df, cols)
        out = {t: con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in CONCLUSIONS}
    finally:
        if own: con.close()
    return out


# ---------- выводы: чтение ----------
def _load(s):
    return None if s is None or (isinstance(s, float) and s != s) else json.loads(s)


def read(workdir, con=None):
    """Выводы из таблиц — в том виде, в каком они лежат в results (findings и profiles); значения проходят через JSON: кортежи — списки, числа numpy — числа Python."""
    con, own = _open(workdir, con)
    try:
        F = con.execute('SELECT * FROM findings ORDER BY pos').fetchdf()
        findings = []
        rev = {v: k for k, v in FINDING_TEXT.items()}
        for r in F.to_dict('records'):
            x = {'key': r['key']}
            for col, k in rev.items():
                if r.get(col) is not None and r[col] == r[col]: x[k] = r[col]
            if r.get('also_in') is not None and r['also_in'] == r['also_in']: x['также_в'] = _load(r['also_in'])
            x.update(_load(r.get('params')) or {})
            x.update(_load(r.get('extra')) or {})
            findings.append(x)
        cases = []
        for r in con.execute('SELECT * FROM cases ORDER BY pos').fetchdf().to_dict('records'):
            x = {'дело': r['case_id'], 'кличка': r['alias'], 'вид': r['kind'], 'важность': r['severity'], 'запросов': _int(r['n_req'])}
            if _int(r['ts_first']) is not None: x['t0'] = _int(r['ts_first'])
            if _int(r['ts_last']) is not None: x['t1'] = _int(r['ts_last'])
            x.update(_load(r['card']) or {})
            cases.append(x)
        inv = {v: k for k, v in MEMBER_COLS.items()}
        M = con.execute('SELECT * FROM case_members ORDER BY pos').fetchdf()
        M = M[[c for c in MEMBER_COLS.values() if c in M]].rename(columns=inv)[list(MEMBER_COLS)]
        S = con.execute('SELECT * FROM signatures ORDER BY pos').fetchdf()
        S = S[list(SIG_COLS.values())].rename(columns={v: k for k, v in SIG_COLS.items()})[list(SIG_COLS)]
        I = con.execute('SELECT * FROM ip_measures').fetchdf()
        MI = I[I['pos'].notna()].sort_values('pos')
        MI = MI[list(MEASURE_COLS.values())].rename(columns={v: k for k, v in MEASURE_COLS.items()})[list(MEASURE_COLS)].reset_index(drop=True)
        MI['дело'] = MI['дело'].fillna('')
        people = sorted(I.loc[I['has_people'] == True, 'ip'].astype(str))
    finally:
        if own: con.close()
    return dict(findings=findings, профили=dict(дела=cases, состав=M.reset_index(drop=True), сигнатуры=S.reset_index(drop=True), меры_ip=MI, меры_ip_люди=people))


# ---------- свидетельства: загрузка edits.json ----------
def _when(v):
    """Время записи: строка в разных видах → отметка времени; не разобралось — пусто (исходная строка остаётся в extra)."""
    if v is None or v == '': return None
    t = pd.to_datetime(str(v), errors='coerce', dayfirst=bool(re.match(r'^\d{1,2}\.\d{1,2}\.\d{4}', str(v))))
    return None if pd.isna(t) else t


def _pick(e, *names):
    for n in names:
        if n in e and e[n] is not None: return e[n]
    return None


def load_edits(workdir, edits, con=None):
    """Содержимое edits.json — в таблицы свидетельств, как есть. Таблицы заменяются целиком. edits пуст — ничего не меняется."""
    if not edits or not db.exists(workdir): return {}
    con, own = _open(workdir, con)
    try:
        db.ensure(con, list(EVIDENCE))
        # показания
        rows = []
        known = {'n', 'who', 'кто', 'when', 'когда', 'time', 'question', 'вопрос', 'answer', 'ответ', 'conflict', 'расхождение'}
        for e in edits.get('показания') or []:
            w = _pick(e, 'when', 'когда', 'time')
            extra = {k: v for k, v in e.items() if k not in known}
            if w is not None and _when(w) is None: extra['when'] = w
            rows.append(dict(n=_int(e.get('n')), who=_text(_pick(e, 'who', 'кто')), made_at=_when(w), question=_text(_pick(e, 'question', 'вопрос')),
                             answer=_text(_pick(e, 'answer', 'ответ')), conflict=_text(_pick(e, 'conflict', 'расхождение')), extra=jdump(extra) if extra else None))
        cols = ['n', 'who', 'made_at', 'question', 'answer', 'conflict', 'extra']
        _insert(con, 'testimony', pd.DataFrame(rows, columns=cols), cols)
        # эксперименты
        rows = []
        known = {'n', 'who', 'when', 'goal', 'steps', 'observed', 'ip', 'time', 'conclusion', 'level', 'changes'}
        for e in edits.get('experiments') or []:
            extra = {k: v for k, v in e.items() if k not in known}
            w = e.get('when')
            if w is not None and _when(w) is None: extra['when'] = w
            tm = _when(e.get('time'))
            if e.get('time') is not None and tm is None: extra['time'] = e['time']
            rows.append(dict(n=_int(e.get('n')), who=_text(e.get('who')), made_at=_when(w), goal=_text(e.get('goal')), steps=jdump(e.get('steps')), observed=jdump(e.get('observed')),
                             ip=_text(e.get('ip')), ts=_int((tm - pd.Timestamp(0)).total_seconds()) if tm is not None else None, conclusion=_text(e.get('conclusion')),
                             level=_text(e.get('level')), trace_events=None, changes=jdump(e.get('changes')), extra=jdump(extra) if extra else None))
        cols = ['n', 'who', 'made_at', 'goal', 'steps', 'observed', 'ip', 'ts', 'conclusion', 'level', 'trace_events', 'changes', 'extra']
        _insert(con, 'experiments', pd.DataFrame(rows, columns=cols), cols)
        # проверки из сети
        rows = []
        for f, ch in (edits.get('проверка_утечек') or {}).items():
            rows.append(dict(kind='leak', url=str(f), made_at=_when(ch.get('когда')), status=_text(ch.get('итог')), result=_text(ch.get('внутри')), details=jdump(ch)))
        for f, ch in (edits.get('проверка_сайта') or {}).items():
            rows.append(dict(kind='site_file', url=str(f), made_at=_when(ch.get('когда')), status=_text(ch.get('итог')), result=_text(ch.get('что')), details=jdump(ch)))
        for h, why in (edits.get('встраивание') or {}).items():
            rows.append(dict(kind='embedding', url=str(h), made_at=None, status=None, result=_text(why), details=jdump(why)))
        cols = ['kind', 'url', 'made_at', 'status', 'result', 'details']
        _insert(con, 'net_checks', pd.DataFrame(rows, columns=cols), cols)
        # решения об IP, делах и карточках
        cols = ['ip', 'decision', 'note']
        _insert(con, 'ip_overrides', pd.DataFrame([dict(ip=str(i), decision='people', note=None) for i in edits.get('люди_ip') or []], columns=cols), cols)
        rows = []
        for case, e in (edits.get('дела') or {}).items():
            rows.append(dict(case_id=str(case), decision='оправдано' if e.get('оправдано') else None, severity=_text(e.get('важность')), note=_text(e.get('почему'))))
        cols = ['case_id', 'decision', 'severity', 'note']
        _insert(con, 'case_overrides', pd.DataFrame(rows, columns=cols), cols)
        rows = [dict(key=str(k), op='remove', patch=None) for k in edits.get('remove') or []]
        rows += [dict(key=str(k), op='update', patch=jdump(p)) for k, p in (edits.get('update') or {}).items()]
        rows += [dict(key=str(a.get('key') or f"{a.get('блок')}:ии:{i}"), op='add', patch=jdump(a)) for i, a in enumerate(edits.get('add') or [])]
        cols = ['key', 'op', 'patch']
        _insert(con, 'finding_overrides', pd.DataFrame(rows, columns=cols), cols)
        out = {t: con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in EVIDENCE}
    finally:
        if own: con.close()
    return out


def read_edits(workdir, con=None):
    """Свидетельства из таблиц — списками записей (для сверки с edits.json)."""
    con, own = _open(workdir, con)
    try:
        return {t: con.execute(f'SELECT * FROM {t}').fetchdf().to_dict('records') for t in EVIDENCE}
    finally:
        if own: con.close()


# ---------- learned ----------
LEARNED_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'reference', 'learned'))


def _mine(e, site):
    """Запись справочника касается этого сайта: записал он или подтвердил, оспорил."""
    if e.get('сайт') == site: return True
    return any(c.get('сайт') == site for c in (e.get('подтверждения') or []) + (e.get('конфликты') or []))


def sync_learned(workdir, site, con=None, folder=None):
    """Найденное за прогон и не известное справочникам — в таблицу learned (накопительно). Папка движка остаётся как была (запись в неё — прежним кодом)."""
    if not db.exists(workdir): return 0
    from .reference import anon
    fp = anon(site)
    folder = folder or LEARNED_DIR
    rows = []

    def rd(name):
        try: return json.load(open(os.path.join(folder, name), encoding='utf-8'))
        except Exception: return {}
    for e in rd('params.json').get('параметры') or []:
        if _mine(e, fp): rows.append(('param', str(e.get('ключ')), e, 'detective' if e.get('источник') == 'поиск' else 'engine'))
    for e in rd('extensions.json').get('расширения') or []:
        if e.get('сайт') == fp: rows.append(('extension', str(e.get('расширение')), e, 'detective'))
    for e in rd('monitors.json').get('сервисы') or []:
        if e.get('сайт') == fp: rows.append(('monitor', str(e.get('сервис')), e, 'detective'))
    for sid, e in (rd('signatures.json').get('сигнатуры') or {}).items():
        if fp in (e.get('сайты') or {}): rows.append(('signature', str(sid), dict(e, **{'на_этом_сайте': e['сайты'][fp]}), 'engine'))
    con, own = _open(workdir, con)
    try:
        db.ensure(con, ['learned'])
        old = con.execute('SELECT kind, key, value, source FROM learned').fetchdf()   # накопленное не теряется: новые записи добавляются, найденные снова — обновляются
        df = pd.concat([old, pd.DataFrame([dict(kind=k, key=key, value=jdump(v), source=s) for k, key, v, s in rows], columns=['kind', 'key', 'value', 'source'])], ignore_index=True)
        df = df.drop_duplicates(['kind', 'key'], keep='last')
        _insert(con, 'learned', df, ['kind', 'key', 'value', 'source'])
    finally:
        if own: con.close()
    return len(rows)
