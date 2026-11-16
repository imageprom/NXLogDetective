"""Выводы и свидетельства — в таблицах базы проверки.

1. Из таблиц выводов (findings, cases, case_members, signatures, ip_measures) восстанавливается то же, что лежит в results.pkl: карточки, дела, состав, сигнатуры, меры по IP.
2. IP с обычными визитами людей: ip_measures.has_people = истина, и такого IP нет в STIX.
3. edits.json (оправдать дело, признать IP людьми, убрать, изменить и добавить карточку, показания, эксперименты, проверки из сети) — в таблицах свидетельств как есть,
   а после пересборки отчёта — и в таблицах выводов. Файл не меняется.
4. learned: найденное за прогон — в таблице, запись в папку движка остаётся."""
import hashlib, json, os, pickle, sys, tempfile
from datetime import timedelta

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth, test_summaries as ts
from nxld import conclusions, db

PEOPLE_IP = '95.165.0.250'   # обычные визиты людей и одновременно зонды: в деле он улика, не обвиняемый


def make_log():
    L = ts.make_log()
    T0 = synth.T0
    for d in range(3):   # человек: страницы, файлы, переходы; тот же IP потом гоняет зонды curl-ом
        ts._human(L, PEOPLE_IP, T0 + timedelta(days=d, hours=9), ts.MAIN, '/catalog/', n_pages=3)
        ts._human(L, PEOPLE_IP, T0 + timedelta(days=d, hours=10), ts.MAIN, '/about/', n_pages=3)
        for k, u in enumerate(('/.env', '/wp-login.php', '/phpinfo.php', '/.git/config', '/admin/', '/backup.zip', '/phpmyadmin/', '/.aws/credentials', '/config.php', '/wp-admin/', '/xmlrpc.php', '/shell.php')):
            L.line(PEOPLE_IP, T0 + timedelta(days=d, hours=11, seconds=k), u, 404, ua='curl/8.4.0', host=ts.MAIN)
    return L


def norm(x):
    """Сравнение «значение в значение»: через JSON — кортежи как списки, числа numpy как числа Python."""
    return json.loads(json.dumps(conclusions._plain(x), ensure_ascii=False, sort_keys=True))


@pytest.fixture(scope='module')
def run():
    with tempfile.TemporaryDirectory() as d:
        log = make_log()
        synth.run(log, d)   # подготовка, анализ и отчёт
        res, out, _ = synth.run(log, d, '--stage', 'analyze')   # таблицы после analyze — сверка с results.pkl этого же прогона
        work = os.path.join(d, 'work')
        got = conclusions.read(work)
        yield dict(res=res, got=got, work=work, d=d, log=log)


def test_findings_restore_from_table(run):
    F = run['res']['findings']
    assert len(F) >= 8 and len({x['важность'] for x in F}) >= 3   # карточки нескольких уровней важности
    assert norm(run['got']['findings']) == norm(F)


def test_cases_members_signatures_measures_restore(run):
    P, G = run['res']['profiles'], run['got']['профили']
    assert len(P['дела']) >= 3 and len(P['состав']) and len(P['сигнатуры']) and len(P['меры_ip'])
    assert norm(G['дела']) == norm(P['дела'])
    for k in ('состав', 'сигнатуры', 'меры_ip'):
        assert list(G[k].columns) == list(P[k].columns), k
        assert norm(G[k]) == norm(P[k]), k
    assert G['меры_ip_люди'] == sorted(P['меры_ip_люди'])


def test_numbers_of_card_are_kept_apart_from_text(run):
    con = db.connect(run['work'], read_only=True)
    T = con.execute("SELECT key, params FROM findings").fetchdf()
    con.close()
    byk = {x['key']: x for x in run['res']['findings']}
    for k, p in zip(T['key'], T['params']):
        assert (json.loads(p) if p else {}).get('главная_цифра') == norm(byk[k].get('главная_цифра')) if p else 'главная_цифра' not in byk[k], k
    assert T['params'].notna().all()


def test_people_ip_measures_and_stix(run):
    """В ip_measures — только IP, по которым есть мера; «у IP есть обычные визиты людей» — признак в ip_period и в строке меры."""
    con = db.connect(run['work'], read_only=True)
    M = con.execute("SELECT ip, case_id, verdict, has_people, pos FROM ip_measures").fetchdf()
    P = con.execute("SELECT i.ip, p.* FROM ip_period p JOIN dim_ip i USING (ip_id)").fetchdf()
    con.close()
    assert M['pos'].notna().all() and M['verdict'].notna().all()   # строк «без меры» в таблице мер нет
    ppl = P[P['has_people']]
    assert PEOPLE_IP in set(ppl['ip']) and len(ppl) > len(M[M['has_people']])   # IP людей без дела — только в ip_period
    assert set(M.loc[M['has_people'], 'ip']) <= set(ppl['ip'])
    inc = M[M['has_people'] & M['case_id'].notna()]
    assert len(inc), 'IP с визитами людей в деле — случай, который проверяем'
    assert set(inc['verdict']) == {'не трогать'}
    assert not M[M['has_people'] & M['verdict'].isin(['заблокировать', 'ограничить частоту'])].shape[0]
    # в STIX таких IP нет — ни объектом, ни в шаблонах
    out = os.path.join(run['d'], 'out')
    stix = next(f for f in os.listdir(out) if f.endswith('.stix.json'))
    text = open(os.path.join(out, stix), encoding='utf-8').read()
    for ip in ppl['ip']:
        assert f"'{ip}'" not in text and f'"{ip}"' not in text, ip


def _edits(res):
    cases = res['profiles']['дела']
    keys = [x['key'] for x in res['findings'] if x['важность'] not in ('Тревога', 'Срочно')]   # тревоги по открытым файлам пересчитываются при сборке отчёта и правку важности не держат
    cases_ips = [ip for x in cases for ip in x['ips'] if ip != PEOPLE_IP]
    return {
        'дела': {cases[0]['дело']: {'оправдано': True, 'почему': 'вернувшиеся вкладки покупателей'}, cases[1]['дело']: {'важность': 'Важно'}},
        'люди_ip': [cases_ips[0]],
        'remove': [keys[0]],
        'update': {keys[1]: {'важность': 'К сведению', 'факты': 'правка Детектива'}},
        'add': [{'блок': 'Маркетинг', 'важность': 'Важно', 'что_происходит': 'Добавлено Детективом', 'факты': 'из расследования', 'где_править': 'кабинет рекламы', 'что_сделать': 'проверить', 'главная_цифра': 7, 'лист': 'Каналы'}],
        'показания': [{'n': 1, 'who': 'владелец сайта', 'when': '2026-09-02 10:00', 'question': 'Есть ли корзина?', 'answer': 'да, своя', 'conflict': ''},
                      {'n': 2, 'who': 'программист', 'when': 'вчера вечером', 'question': 'Кто ходит по ночам?', 'answer': 'наш обмен', 'conflict': 'в логе чужой IP', 'доп': 'x'}],
        'experiments': [{'n': 1, 'who': 'разработчик', 'when': '2026-09-02 10:00', 'goal': 'найти обработчик корзины', 'steps': ['открыть сайт', 'добавить в корзину'],
                         'observed': {'url': '/ajax/basket.php', 'method': 'POST', 'status': 200}, 'ip': '95.165.0.1', 'time': '2026-09-02 10:00:05', 'conclusion': 'корзина — свой обработчик', 'level': 'browser'},
                        {'n': 4, 'level': 'browser', 'ref': {'type': 'testimony', 'n': 4}}],
        'проверка_утечек': {'/backup.sql': {'итог': 'открыт', 'когда': '06.10.2026', 'внутри': 'дамп базы', 'тревога': True}},
        'проверка_сайта': {'/robots.txt': {'итог': 'открыт', 'когда': '06.10.2026', 'что': 'правила для роботов'}},
        'встраивание': {'example-dev.ru': 'лежит на нашем сервере'},
        'справочник': [{'ключ': 'yhid', 'группа': 'Поисковики и Яндекс', 'что': 'метка Яндекса', 'ссылка': 'https://example.com/doc/yhid'}],
        'расширения': [{'расширение': 'glb', 'группа': 'Графика и шрифты', 'что': '3D-модели', 'ссылка': 'https://example.com/doc/glb'}],
        'мониторинги': [{'сервис': 'Overseer', 'шаблон': 'Overseer', 'ссылка': 'https://example.com/doc/overseer'}],
    }


@pytest.fixture(scope='module')
def edited(run):
    ed = _edits(run['res'])
    path = os.path.join(run['d'], 'edits.json')
    open(path, 'w', encoding='utf-8').write(json.dumps(ed, ensure_ascii=False, indent=1))
    h0 = hashlib.sha1(open(path, 'rb').read()).hexdigest()
    synth.run(run['log'], run['d'], '--stage', 'analyze', '--edits', path)   # при analyze правки — в таблицы свидетельств
    con = db.connect(run['work'], read_only=True)
    after_analyze = {t: con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in conclusions.EVIDENCE}
    con.close()
    synth.run(run['log'], run['d'], '--stage', 'report', '--edits', path)   # пересборка отчёта с правками — и в таблицы выводов
    return dict(ed=ed, path=path, h0=h0, after_analyze=after_analyze, tables=conclusions.read_edits(run['work']), got=conclusions.read(run['work']))


def test_edits_file_is_input_and_stays(run, edited):
    assert hashlib.sha1(open(edited['path'], 'rb').read()).hexdigest() == edited['h0']


def test_evidence_tables_hold_edits_as_is(run, edited):
    ed, T, n0 = edited['ed'], edited['tables'], edited['after_analyze']
    assert n0 == {'testimony': 2, 'experiments': 2, 'net_checks': 3, 'ip_overrides': 1, 'case_overrides': 2, 'finding_overrides': 3}   # уже после analyze
    assert [(r['n'], r['who'], r['question'], r['answer'], r['conflict']) for r in T['testimony']] == [(1, 'владелец сайта', 'Есть ли корзина?', 'да, своя', ''), (2, 'программист', 'Кто ходит по ночам?', 'наш обмен', 'в логе чужой IP')]
    t1, t2 = T['testimony']
    assert str(t1['made_at']).startswith('2026-09-02 10:00') and pd.isna(t2['made_at']) and json.loads(t2['extra']) == {'доп': 'x', 'when': 'вчера вечером'}
    e1, e4 = T['experiments']
    assert (e1['n'], e1['who'], e1['goal'], e1['ip'], e1['conclusion'], e1['level']) == (1, 'разработчик', 'найти обработчик корзины', '95.165.0.1', 'корзина — свой обработчик', 'browser')
    assert json.loads(e1['steps']) == ed['experiments'][0]['steps'] and json.loads(e1['observed']) == ed['experiments'][0]['observed']
    assert e1['ts'] == int((pd.Timestamp('2026-09-02 10:00:05') - pd.Timestamp(0)).total_seconds())
    assert e4['n'] == 4 and json.loads(e4['extra']) == {'ref': {'type': 'testimony', 'n': 4}}
    nc = {(r['kind'], r['url']): r for r in T['net_checks']}
    assert set(nc) == {('leak', '/backup.sql'), ('site_file', '/robots.txt'), ('embedding', 'example-dev.ru')}
    assert nc[('leak', '/backup.sql')]['status'] == 'открыт' and nc[('leak', '/backup.sql')]['result'] == 'дамп базы' and json.loads(nc[('leak', '/backup.sql')]['details'])['тревога'] is True
    assert [(r['ip'], r['decision']) for r in T['ip_overrides']] == [(ed['люди_ip'][0], 'people')]
    co = {r['case_id']: r for r in T['case_overrides']}
    c0, c1 = list(ed['дела'])
    assert (co[c0]['decision'], co[c0]['note']) == ('оправдано', 'вернувшиеся вкладки покупателей') and pd.isna(co[c1]['decision']) and co[c1]['severity'] == 'Важно'
    fo = {(r['key'], r['op']): r for r in T['finding_overrides']}
    k_rm, k_up = ed['remove'][0], list(ed['update'])[0]
    assert (k_rm, 'remove') in fo and json.loads(fo[(k_up, 'update')]['patch']) == ed['update'][k_up] and any(op == 'add' for _, op in fo)


def test_edits_are_seen_in_conclusions_after_rebuild(run, edited):
    ed, G = edited['ed'], edited['got']
    F = {x['key']: x for x in G['findings']}
    k_rm, k_up = ed['remove'][0], list(ed['update'])[0]
    assert k_rm not in F, 'убранная карточка осталась'
    assert F[k_up]['важность'] == 'К сведению' and F[k_up]['факты'] == 'правка Детектива'
    assert any(x['блок'] == 'Маркетинг' and x['что_происходит'] == 'Добавлено Детективом' and x['главная_цифра'] == 7 for x in F.values())
    cases = {x['дело']: x for x in G['профили']['дела']}
    c0, c1 = list(ed['дела'])
    assert cases[c0]['важность'] == 'К сведению' and cases[c0].get('оправдано') == 'вернувшиеся вкладки покупателей'
    assert cases[c1]['важность'] == 'Важно'
    ip = ed['люди_ip'][0]
    M, MI = G['профили']['состав'], G['профили']['меры_ip']
    assert ip not in set(M['ip']) and ip not in set(MI['ip'])
    old_c0_ips = {r['ip'] for r in run['res']['profiles']['меры_ip'].to_dict('records') if r['дело'] == c0}
    assert old_c0_ips and not (old_c0_ips & set(MI.loc[MI['дело'] == c0, 'ip'])) or not len(MI[MI['дело'] == c0])   # IP оправданного дела — люди: из мер ушли
    assert ip not in {x for c in G['профили']['дела'] for x in c['ips']}


def test_learned_in_table_and_in_engine_folder(run, edited):
    con = db.connect(run['work'], read_only=True)
    L = con.execute('SELECT kind, key, source FROM learned').fetchdf()
    con.close()
    got = {(r.kind, r.key): r.source for r in L.itertuples()}
    assert got.get(('param', 'yhid')) == 'detective' and got.get(('extension', 'glb')) == 'detective' and got.get(('monitor', 'Overseer')) == 'detective'
    assert any(k == 'signature' for k, _ in got)   # сигнатуры дел — тоже найденное прогоном


def test_ip_period_counters_match_visits_and_events(run):
    """IP за период: счётчики равны посчитанным по итоговым визитам и событиям; строка на каждый IP с визитами."""
    con = db.connect(run['work'], read_only=True)
    P = con.execute("SELECT i.ip, p.* FROM ip_period p JOIN dim_ip i USING (ip_id)").fetchdf().set_index('ip')
    V = con.execute("SELECT i.ip, v.category, v.type, v.n_req, v.n_pages, v.bytes, v.ts_start, v.ts_end FROM visits v JOIN dim_ip i USING (ip_id)").fetchdf()
    E = con.execute("SELECT i.ip, e.ts, e.status, e.form_key FROM access_events e JOIN dim_ip i USING (ip_id) WHERE e.vid IS NOT NULL").fetchdf()
    G = con.execute("SELECT i.ip, count(*) n FROM error_events e JOIN dim_ip i USING (ip_id) GROUP BY 1").fetchdf().set_index('ip')['n']
    con.close()
    assert len(P) == V['ip'].nunique() and P.index.is_unique
    g = V.groupby('ip')
    for col, want in (('n_visits', g.size()), ('n_req', g['n_req'].sum()), ('n_pages', g['n_pages'].sum()), ('bytes', g['bytes'].sum()), ('ts_first', g['ts_start'].min()),
                      ('ts_last', g['ts_end'].max()), ('n_categories', g['category'].nunique()), ('n_days', E.groupby('ip')['ts'].apply(lambda s: (s // 86400).nunique())),
                      ('n_submits', E[E['form_key'].notna()].groupby('ip').size()), ('n_refused', E[E['status'].isin([403, 429, 444])].groupby('ip').size()), ('n_errlog', G)):
        assert (P[col].astype('int64') == want.reindex(P.index).fillna(0).astype('int64')).all(), col
    top = V.sort_values('n_req', ascending=False).drop_duplicates('ip').set_index('ip')
    one = P.index[P['n_visits'] == 1]   # у IP с одним визитом основная категория однозначна
    assert (P.loc[one, 'category'] == top.loc[one, 'category']).all()
    assert (P['is_live'] == (P['category'].isin(['Люди', 'Свои']) & (P['type'].fillna('') != 'сервер сайта'))).all()
    assert P.loc[PEOPLE_IP, 'n_categories'] >= 2 and bool(P.loc[PEOPLE_IP, 'has_people'])
