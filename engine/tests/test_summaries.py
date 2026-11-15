"""Сводки базы проверки «Время» (sum_time) и «Минута» (sum_minute).

1. Числа сводок равны тем же числам, посчитанным pandas по таблицам запросов и визитов (R, V) — по областям site / server
   и с исключением нераспознанных «Людей» хостов вне сайта.
2. Блоки, переведённые на сводки, дают тот же результат, что и расчёт по-старому (NXLD_SUMMARIES=0).
3. Состав колонок в базе совпадает со схемой data/schema/db_schema.json.
Лог вымышленный: люди, роботы, боты, утилиты, сбой с 5xx и 499, отказы 403, хост вне сайта (IP вместо имени) и копия на другом домене."""
import os
import pickle
import sys
import tempfile
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth
from nxld import analyze, blocks, db, prepare, summaries, visits

MAIN, COPY, IPHOST = 'example.com', 'dev.example-copy.net', '198.51.100.9'
UA_GOOGLE = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
UA_CURL = 'curl/8.4.0'
SCAN_UA = 'Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0'
DAYS = 6


def _human(log, ip, t, host, entry, ref='https://yandex.ru/', n_pages=2):
    log.line(ip, t, entry, 200, ref=ref, host=host)
    log.line(ip, t + timedelta(seconds=1), '/local/templates/main/style.css', 200, ref=f'https://{host}{entry}', host=host)
    for k in range(n_pages): log.line(ip, t + timedelta(seconds=30 * (k + 1)), synth.PAGES[(k + 3) % len(synth.PAGES)], 200, ref=f'https://{host}{entry}', host=host)


def make_log():
    L = synth.Log(seed=3)
    T0 = synth.T0
    for d in range(DAYS):
        t = T0 + timedelta(days=d)
        for k in range(24):   # люди: из поиска, по рекламе, прямые
            ip = f'95.165.{d}.{k + 1}'
            if k % 4 == 1: _human(L, ip, t + timedelta(hours=8, minutes=11 * k), MAIN, '/akcii/?utm_source=yandex&utm_medium=cpc&yclid=1234567', ref='https://yandex.ru/')
            elif k % 4 == 2: _human(L, ip, t + timedelta(hours=8, minutes=11 * k), MAIN, synth.PAGES[k % len(synth.PAGES)], ref='-')
            else: _human(L, ip, t + timedelta(hours=8, minutes=11 * k), MAIN, synth.PAGES[k % len(synth.PAGES)], ref='https://www.google.com/' if k % 8 == 0 else 'https://yandex.ru/')
        _human(L, f'95.165.{d}.200', t + timedelta(hours=23, minutes=58), MAIN, '/catalog/', n_pages=6)   # визит через полночь: начался в один день, запросы — в двух
        for k in range(3):   # заявки
            ip = f'95.165.{d}.{k + 1}'
            L.line(ip, t + timedelta(hours=13 + k, minutes=3), '/contacts/', 200, ref='https://yandex.ru/', host=MAIN)
            L.line(ip, t + timedelta(hours=13 + k, minutes=4), '/ajax/form.php?form_id=callback', 200, ref=f'https://{MAIN}/contacts/', method='POST', size=60, host=MAIN)
        for k in range(30):   # поисковый робот из своей сети: страницы, переадресация, ошибка
            L.line('66.249.66.1', t + timedelta(hours=2, minutes=k), synth.PAGES[k % len(synth.PAGES)], 301 if k == 5 else 404 if k == 6 else 200, ua=UA_GOOGLE, host=MAIN)
        for k in range(12):   # утилита из дата-центра
            L.line('203.0.113.7', t + timedelta(hours=4, seconds=5 * k), f'/catalog/shary/item{k}/', 200, ua=UA_CURL, host=MAIN)
        for k, u in enumerate(('/.env', '/wp-login.php', '/phpinfo.php', '/.git/config', '/admin/')):   # сканер: зонды и отказы
            L.line('203.0.113.50', t + timedelta(hours=3, seconds=k), u, 403 if k >= 3 else 404, ua=SCAN_UA, host=MAIN)
        L.line(f'95.165.{d}.7', t + timedelta(hours=12), '/old-page/', 404, ref=f'https://{MAIN}/', host=MAIN)
        L.line(f'95.165.{d}.8', t + timedelta(hours=12, minutes=5), '/catalog/', 499, ref=f'https://{MAIN}/', host=MAIN)
        L.line(f'95.165.{d}.9', t + timedelta(hours=12, minutes=6), '/catalog/', 502, ref=f'https://{MAIN}/', host=MAIN)
        L.line(f'95.165.{d}.9', t + timedelta(hours=12, minutes=7), '/catalog/', 504, ref=f'https://{MAIN}/', host=MAIN)
        # хост вне сайта — IP вместо имени: сканер (распознан) и посетитель из браузера (не распознан: в отчёт не входит)
        for j, u in enumerate(('/', '/admin/', '/wp-login.php')):
            L.line('203.0.113.51', t + timedelta(hours=5, seconds=j), u, 404, ua=SCAN_UA, host=IPHOST)
        _human(L, f'95.165.{d + 30}.5', t + timedelta(hours=16), IPHOST, '/')
        # копия сайта на другом домене — вне отчёта
        _human(L, '203.0.113.77', t + timedelta(hours=17), COPY, '/')
        L.line('203.0.113.77', t + timedelta(hours=17, minutes=3), '/old-copy/', 404, ref=f'https://{COPY}/', host=COPY)
    # сбой на третий день: шесть минут страницы отдают 5xx разным посетителям, часть не дождалась
    t = T0 + timedelta(days=2, hours=15)
    for mnt in range(6):
        for k in range(8):
            ip = f'95.165.2.{100 + k}'
            L.line(ip, t + timedelta(minutes=mnt, seconds=3 * k), synth.PAGES[k % len(synth.PAGES)], 500 if k < 6 else 499, ref=f'https://{MAIN}/', host=MAIN)
            L.line(ip, t + timedelta(minutes=mnt, seconds=3 * k + 1), '/local/templates/main/style.css', 200, ref=f'https://{MAIN}/', host=MAIN)
    # всплеск на пятый день: один IP за две минуты
    t = T0 + timedelta(days=4, hours=6)
    for k in range(2600):
        L.line('203.0.113.99', t + timedelta(seconds=k * 120 / 2600), f'/catalog/shary/?PAGEN_1={k % 50 + 1}', 200 if k % 9 else 403, ua=UA_CURL, host=MAIN)
    return L


def _results(work, flag):
    os.environ['NXLD_SUMMARIES'] = flag
    try: analyze.run(work, log=lambda *a: None)
    finally: os.environ.pop('NXLD_SUMMARIES', None)
    return pickle.load(open(os.path.join(work, 'results.pkl'), 'rb'))


@pytest.fixture(scope='module')
def run():
    """Рабочая папка после prepare и двух analyze: по-старому и со сводками; таблицы R и V analyze — до среза для отчёта."""
    keep = {os.path.join(r, f): open(os.path.join(r, f), 'rb').read() for r, _, fs in os.walk(synth.LEARNED) for f in fs}
    grab = {}
    orig = summaries.build
    def build(workdir, *a, **k):   # таблицы на входе сводок: те самые R и V, что analyze записал в базу (store.all_of)
        import inspect
        fr = inspect.currentframe().f_back
        grab['R'], grab['V'] = fr.f_locals['R'].copy(), fr.f_locals['V'].copy()
        return orig(workdir, *a, **k)
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        make_log().write(path)
        try:
            prepare.run([path], work, log=lambda *a: None)
            old = _results(work, '0')
            summaries.build = build
            try: new = _results(work, '1')
            finally: summaries.build = orig
        finally:
            for r, _, fs in os.walk(synth.LEARNED):
                for f in fs:
                    if os.path.join(r, f) not in keep: os.remove(os.path.join(r, f))
            for f, b in keep.items(): open(f, 'wb').write(b)
        con = db.connect(work, read_only=True)
        ST, SM = con.execute('SELECT * FROM sum_time').df(), con.execute('SELECT * FROM sum_minute').df()
        cols = {t: con.execute(f'DESCRIBE {t}').df()[['column_name', 'column_type']].values.tolist() for t in summaries.TABLES}
        built = dict(con.execute("SELECT table_name, rows FROM build_state WHERE table_name LIKE 'sum_%'").fetchall())
        con.close()
        yield dict(old=old, new=new, R=grab['R'], V=grab['V'], ST=ST, SM=SM, cols=cols, built=built, work=work)


def _rv(run):
    """R с признаками визита по строкам и V — как видит их сводка: область, категория, тип, канал."""
    R, V = run['R'], run['V']
    X = pd.DataFrame({'ts': R['ts'].values, 'scope': np.where(R['host_site'].values.astype(bool), 'site', 'server'), 'status': R['status'].values, 'bytes': R['bytes'].values,
                      'is_page': R['is_page'].values.astype(bool), 'post': R['method'].values == 'POST', 'static': R['is_static'].values.astype(bool), 'ip': R['ip'].astype(str).values,
                      'goal': (R['goal'].astype(str).values != ''), 'ok': R['goal_success'].values.astype(bool), 'order': R['is_order'].values.astype(bool) if 'is_order' in R else False})
    for a, b in (('category', 'group'), ('type', 'subgroup'), ('channel', 'channel'), ('channel_sub', 'channel_sub'), ('fam_verified', 'fam_verified')):
        X[a] = V[b].astype(object).where(V[b].notna(), '').reindex(R['vid'].values).values
    X['day'] = pd.to_datetime(X['ts'], unit='s').dt.strftime('%Y-%m-%d'); X['hour'] = (X['ts'] // 3600) % 24; X['minute'] = X['ts'] // 60
    W = pd.DataFrame({'scope': np.where(V['host_site'].values.astype(bool), 'site', 'server'), 'category': V['group'].astype(str).values, 'type': V['subgroup'].astype(str).values,
                      'channel': V['channel'].astype(object).where(V['channel'].notna(), '').values, 'ip': V['ip'].astype(str).values, 'n_goal': V['n_goal'].values, 'n_conv': V['n_conv'].values,
                      'day': pd.to_datetime(V['start'], unit='s').dt.strftime('%Y-%m-%d').values, 'hour': (V['start'].values // 3600) % 24})
    return X, W


def test_log_has_everything(run):
    X, W = _rv(run)
    assert {'Люди', 'Роботы', 'Боты', 'Утилиты'} <= set(W['category']), set(W['category'])
    assert {'site', 'server'} == set(X['scope'])
    assert ((W['scope'] == 'server') & (W['category'] == 'Люди')).any()   # нераспознанный посетитель хоста вне сайта
    assert ((W['scope'] == 'server') & (W['category'] != 'Люди')).any()   # и распознанный сканер там же
    assert (X['status'] >= 500).any() and (X['status'] == 499).any() and (X['status'] == 403).any()
    con = db.connect(run['work'], read_only=True)
    off = con.execute("SELECT count(*) FROM access_events e JOIN dim_host h USING (host_id) WHERE h.scope = 'off'").fetchone()[0]
    total = con.execute('SELECT count(*) FROM access_events').fetchone()[0]
    con.close()
    assert off > 0 and total - off == len(X)   # копия на другом домене есть в базе, но не в сводках
    assert len(run['old']['sheets']['Ошибки']['Сбои']) >= 1   # сбой найден
    assert len(run['old']['security']['всплески']) >= 1   # и всплеск


def test_columns_match_schema(run):
    S = db.schema()['by_name']
    for t in summaries.TABLES:
        assert run['cols'][t] == [[c['name'], c['type']] for c in S[t]['columns']], t
        assert run['built'][t] == len(run['ST' if t == 'sum_time' else 'SM'])   # db.mark_built
    for t, T in (('sum_time', run['ST']), ('sum_minute', run['SM'])):
        assert not T.duplicated(S[t]['pk']).any(), t   # зерно: одна строка на ключ
        assert set(T['scope']) <= {'site', 'server'}


TIME_KEYS = ['day', 'hour', 'scope', 'category', 'type', 'channel', 'channel_sub', 'fam_verified']


def test_sum_time_equals_pandas(run):
    X, W = _rv(run)
    ST = run['ST'].assign(day=pd.to_datetime(run['ST']['day']).dt.strftime('%Y-%m-%d'))
    st = X['status']
    want = X.assign(n_req=1, n_pages=X['is_page'], n_2xx=(st >= 200) & (st < 300), n_3xx=(st >= 300) & (st < 400), n_4xx=(st >= 400) & (st < 500), n_5xx=st >= 500, n_403=st == 403,
                    n_404=st == 404, n_499=st == 499, n_502=st == 502, n_504=st == 504, n_submits=X['goal'], n_accepted=X['ok'], n_orders=X['order'])
    cols = ['n_req', 'n_pages', 'bytes', 'n_2xx', 'n_3xx', 'n_4xx', 'n_5xx', 'n_403', 'n_404', 'n_499', 'n_502', 'n_504', 'n_submits', 'n_accepted', 'n_orders']
    want = want.groupby(TIME_KEYS)[cols].sum().astype('int64')
    got = ST.groupby(TIME_KEYS)[cols].sum().astype('int64')
    got = got[got['n_req'] > 0]
    pd.testing.assert_frame_equal(got.sort_index(), want.sort_index(), check_names=False, check_index_type=False)
    span = X.groupby(TIME_KEYS)['ts'].agg(['min', 'max'])
    got_span = ST[ST['n_req'] > 0].groupby(TIME_KEYS).agg(min=('ts_first', 'min'), max=('ts_last', 'max')).astype('int64')
    pd.testing.assert_frame_equal(got_span.sort_index(), span.sort_index().astype('int64'), check_names=False, check_index_type=False)
    # визиты — по часу начала: число, отправки и принятые
    k = ['day', 'hour', 'scope', 'category', 'type', 'channel']
    wv = W.groupby(k).agg(n_visits_started=('ip', 'size'), n_goal_started=('n_goal', 'sum'), n_conv_started=('n_conv', 'sum')).astype('int64')
    gv = ST.groupby(k)[['n_visits_started', 'n_goal_started', 'n_conv_started']].sum().astype('int64')
    gv = gv[gv['n_visits_started'] > 0]
    pd.testing.assert_frame_equal(gv.sort_index(), wv.sort_index(), check_names=False, check_index_type=False)
    assert int(ST['n_visits_started'].sum()) == len(W) and int(ST['n_req'].sum()) == len(X)


def test_sum_time_contexts_equal_report_tables(run):
    """Два контекста чтения — те же срезы, что R и V в analyze: «сайт» и «всё» без нераспознанных «Людей» хостов вне сайта."""
    X, W = _rv(run)
    for ctx, xm, wm in (('site', X['scope'] == 'site', W['scope'] == 'site'),
                        ('all', ~((X['scope'] == 'server') & (X['category'] == 'Люди')), ~((W['scope'] == 'server') & (W['category'] == 'Люди')))):
        sm = summaries.Sums(run['work'], ctx)
        T = sm.time(f"{summaries.DAY} AS d, category, CAST(sum(n_req) AS BIGINT) AS n, CAST(sum(n_visits_started) AS BIGINT) AS nv")
        want = X[xm].groupby(['day', 'category']).size()
        got = T[T['n'] > 0].set_index(['d', 'category'])['n']
        assert got.to_dict() == want.to_dict(), ctx
        assert T[T['nv'] > 0].set_index(['d', 'category'])['nv'].to_dict() == W[wm].groupby(['day', 'category']).size().to_dict(), ctx
        I = sm.visit_ips()
        assert I[I['d'] != ''].set_index(['d', 'category'])['n_ip'].to_dict() == W[wm].groupby(['day', 'category'])['ip'].nunique().to_dict(), ctx
        assert I[I['d'] == ''].set_index('category')['n_ip'].to_dict() == W[wm].groupby('category')['ip'].nunique().to_dict(), ctx
        assert sm.days() == sorted(X.loc[xm, 'day'].unique()), ctx
    hidden = (X['scope'] == 'server') & (X['category'] == 'Люди')
    assert hidden.any()
    assert int(summaries.Sums(run['work'], 'all').time('CAST(sum(n_req) AS BIGINT) AS n')['n'][0]) == len(X) - int(hidden.sum())


def test_sum_minute_equals_pandas(run):
    X, _ = _rv(run)
    st, pp = X['status'], X['is_page'] | X['post']
    want = X.assign(n_req=1, n_pages=X['is_page'], n_page_post=pp, n_page_post_5xx=pp & (st >= 500), n_page_post_499=pp & (st == 499), n_static=X['static'],
                    n_static_ok=X['static'] & (st < 400), n_5xx=st >= 500, n_499=st == 499, n_refused=st.isin((403, 429, 444)))
    k = ['minute', 'scope', 'category']
    cols = ['n_req', 'n_pages', 'n_page_post', 'n_page_post_5xx', 'n_page_post_499', 'n_static', 'n_static_ok', 'n_5xx', 'n_499', 'n_refused', 'bytes']
    want = want.groupby(k)[cols].sum().astype('int64')
    want['n_ip'] = X.groupby(k)['ip'].nunique()
    got = run['SM'].set_index(k)[cols + ['n_ip']].astype('int64')
    pd.testing.assert_frame_equal(got.sort_index(), want.sort_index().astype('int64'), check_names=False, check_index_type=False)
    # разных IP со страницами 5xx по минутам — отдельный запрос по событиям, в обоих контекстах
    for ctx, xm in (('site', X['scope'] == 'site'), ('all', ~((X['scope'] == 'server') & (X['category'] == 'Люди')))):
        m5 = xm & pp & (st >= 500)
        got5 = summaries.Sums(run['work'], ctx).minute_ips_5xx().set_index('m')['ip5']
        assert got5.to_dict() == X[m5].groupby('minute')['ip'].nunique().to_dict(), ctx


def _diff(a, b, path='', out=None):
    """Расхождения двух результатов analyze: таблицы — по значениям (тип колонок и индексов не важен), остальное — как есть."""
    out = [] if out is None else out
    if isinstance(a, pd.DataFrame) and isinstance(b, pd.DataFrame):
        try: pd.testing.assert_frame_equal(a, b, check_dtype=False, check_index_type=False, check_column_type=False, check_names=False, check_categorical=False)
        except AssertionError as e: out.append((path, str(e)[:300]))
    elif isinstance(a, pd.Series) and isinstance(b, pd.Series):
        try: pd.testing.assert_series_equal(a, b, check_dtype=False, check_index_type=False, check_names=False, check_categorical=False)
        except AssertionError as e: out.append((path, str(e)[:300]))
    elif isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b: out.append((f'{path}/{k}', 'ключ только в одном результате'))
            else: _diff(a[k], b[k], f'{path}/{k}', out)
    elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b): out.append((path, f'длина {len(a)} / {len(b)}'))
        else:
            for i, (x, y) in enumerate(zip(a, b)): _diff(x, y, f'{path}[{i}]', out)
    elif isinstance(a, np.ndarray) and isinstance(b, np.ndarray):
        if a.shape != b.shape or not np.array_equal(a, b): out.append((path, 'массивы различаются'))
    elif isinstance(a, float) and isinstance(b, float):
        if not (a == b or (a != a and b != b)): out.append((path, f'{a} / {b}'))
    else:
        try:
            if type(a) != type(b) or a != b: out.append((path, f'{str(a)[:80]} / {str(b)[:80]}'))
        except Exception as e:
            out.append((path, f'не сравнить: {e}'))
    return out


# блок или лист, переведённый на сводки → где его результат в results.pkl
CONVERTED = {
    '01 Журнал активности': lambda r: r['sheets']['Общий анализ']['Журнал активности'],
    '02 Ошибки по дням': lambda r: r['sheets']['Ошибки']['Ошибки по дням'],
    '02 Сбои (окна сбоев)': lambda r: r['sheets']['Ошибки']['Сбои'],
    '02 Сбои с кодом': lambda r: r['errors']['сбои'],
    '02 журнал ошибок по дням': lambda r: r['errors']['журнал'],
    '02 Признаки торможения': lambda r: r['errors']['торможение'],
    '03 Нагрузка по часам (лист блока)': lambda r: r['sheets']['Нагрузка и безопасность']['Нагрузка по часам'],
    '03 Пики': lambda r: r['sheets']['Нагрузка и безопасность']['Пики'],
    '03 Нагрузка по часам': lambda r: r['security']['часы'],
    '03 Всплески нагрузки': lambda r: r['security']['всплески'],
    '03 журнал по дням': lambda r: r['security']['журнал'],
    '04 Расписание ботов': lambda r: r['bots_extra']['расписание'],
    '04 веб-архив и окна сбоев': lambda r: r['web_archive'],
    '05 Органика': lambda r: r['sheets']['Маркетинг']['Органика'],
    '05 журнал по дням': lambda r: r['marketing']['журнал'],
    '05 Время: день недели × час': lambda r: r['marketing']['время'],
    '06 журнал по дням': lambda r: r['seo']['журнал'],
}


@pytest.mark.parametrize('name', list(CONVERTED))
def test_converted_block_equals_old(run, name):
    old, new = CONVERTED[name](run['old']), CONVERTED[name](run['new'])
    assert old is not None and new is not None, name
    if isinstance(old, (pd.DataFrame, dict, list)): assert len(old), name   # сравниваем не пустое с пустым
    d = _diff(old, new)
    assert not d, d[:5]


def test_whole_result_equals_old(run):
    """Ничего, кроме переведённых расчётов, не изменилось: весь результат analyze совпадает с расчётом по-старому."""
    assert not run['old'].get('сбои_блоков') and not run['new'].get('сбои_блоков')
    d = _diff(run['old'], run['new'])
    assert not d, d[:10]


def test_blocks_read_summaries_when_db_exists(run, monkeypatch):
    """Со сводками блок не обращается к колонкам времени таблицы запросов; без базы (c.sums = None) — считает по-старому."""
    sm = summaries.Sums(run['work'], 'all')
    assert summaries.ready(run['work'])
    c = type('C', (), {})()
    c.sums = sm
    c.R = pd.DataFrame({'ts': [0]})   # ни дня, ни часа, ни кода ответа: расчёт идёт из сводок
    from nxld import security, common
    H = security.heat(c)
    assert int(H['Все'].values.sum()) == int(sm.time('CAST(sum(n_req) AS BIGINT) AS n')['n'][0])
    idx, full, norm = common.minute_norm_of(c)
    assert int(full.sum()) == int(H['Все'].values.sum()) and len(idx) == len(full) == len(norm)
    monkeypatch.setenv('NXLD_SUMMARIES', '0')
    assert summaries.for_contexts(run['work']) == (None, None)


def test_no_db_no_summaries():
    with tempfile.TemporaryDirectory() as d:
        assert not summaries.ready(d) and summaries.for_contexts(d) == (None, None)
