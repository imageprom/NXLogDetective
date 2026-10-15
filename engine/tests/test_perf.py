"""Ускорение 0.3a: результаты совпадают с прежними расчётами, тесты ловят возврат к перебору по одному."""
import os
import random
import sys

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
from nxld import errors  # noqa: E402

SRC_ORDER = ('страницы сайта', 'реклама', 'поиск', 'сайты', 'напрямую')


def _old_sources_text(S_b):
    """Прежняя реализация (для сравнения): по одному адресу."""
    parts = []
    for k in SRC_ORDER:
        g = S_b[S_b['вид'] == k]
        if not len(g): continue
        n = int(g['n'].sum())
        det = g[g['деталь'] != ''].groupby('деталь')['n'].sum().sort_values(ascending=False)
        tail = f" ({', '.join(det.index[:2])}{' и др.' if len(det) > 2 else ''})" if len(det) else ''
        parts.append(f'{k}: {n}{tail}')
    return ' · '.join(parts)


def _sources(n_b=300, seed=3):
    r = random.Random(seed)
    rows = []
    for b in range(n_b):
        for _ in range(r.randint(1, 12)):
            k = r.choice(SRC_ORDER + ('прочее',))
            d = '' if k in ('напрямую', 'реклама') else r.choice(['/a/', '/b/*', 'example.com', 'yandex.ru', 't.example.com'])   # мало деталей: много равных чисел
            rows.append((b, r.choice([404, 410, 500]), k, d, r.choice([1, 1, 2, 5])))
    return pd.DataFrame(rows, columns=['b', 'код', 'вид', 'деталь', 'n'])


def test_sources_texts_same_as_per_address():
    Sx = _sources()
    new = errors.sources_texts(Sx)
    old = {b: _old_sources_text(g) for b, g in Sx[Sx['вид'].isin(SRC_ORDER)].groupby('b')}
    assert new == {b: t for b, t in old.items() if t}
    assert len(new) > 250


def test_sources_texts_tail_and_order():
    Sx = pd.DataFrame([(1, 404, 'поиск', 'z.ru', 3), (1, 404, 'поиск', 'a.ru', 3), (1, 500, 'поиск', 'm.ru', 3), (1, 404, 'напрямую', '', 2), (1, 404, 'реклама', '', 7)],
                      columns=['b', 'код', 'вид', 'деталь', 'n'])
    # равные числа — по алфавиту; порядок видов — как в SRC_ORDER; деталей больше двух — «и др.»
    assert errors.sources_texts(Sx) == {1: 'реклама: 7 · поиск: 9 (a.ru, m.ru и др.) · напрямую: 2'}
    assert errors.sources_texts(Sx.iloc[0:0]) == {} and errors.sources_texts(None) == {}


def test_sources_texts_no_per_address_filtering(monkeypatch):
    """Тексты считаются одним расчётом: число обращений к таблице не растёт с числом адресов."""
    calls = []
    orig = pd.DataFrame.groupby
    monkeypatch.setattr(pd.DataFrame, 'groupby', lambda self, *a, **k: (calls.append(1), orig(self, *a, **k))[1])
    errors.sources_texts(_sources(3000))
    assert len(calls) <= 4, len(calls)


# ---------- 2. важные IP ----------
from types import SimpleNamespace  # noqa: E402

from nxld import analyze, blocks, ipdb  # noqa: E402


def _old_important_ips(c, S_bots):
    """Прежняя реализация: выборка визитов по каждому IP отдельно."""
    V, T = c.V, c.T.set_index('ip')
    rows = []
    def add(ips, cat, action):
        for ip in ips:
            vv = V[V['ip'] == ip]
            t = T.loc[ip] if ip in T.index else None
            rows.append(dict(ip=ip, категория=cat, сеть=t['org'] if t is not None else '', ASN=int(t['asn']) if t is not None else 0,
                             страна=t['cc'] if t is not None else '', тип_сети=t['nettype'] if t is not None else '',
                             визитов=len(vv), запросов=int(vv['n_req'].sum()), отправок=int(vv['n_goal'].sum()), принято=int(vv['n_conv'].sum()),
                             первый=blocks.dt(vv['start'].min()) if len(vv) else None, последний=blocks.dt(vv['end'].max()) if len(vv) else None,
                             действие=action if t is None or ipdb.is_dc(t['nettype']) else ('проверить/метка' if action.startswith('бан') else action)))
    spam = V[V['subgroup'].str.startswith('спам форм')]['ip'].unique()
    add(spam, 'спам форм', 'бан')
    if 'Подделки' in S_bots: add(S_bots['Подделки']['ip'].astype(str).unique(), 'поддельный робот', 'бан')
    if 'Операторы' in S_bots and len(S_bots['Операторы']):
        rc = set(x for x in ','.join(S_bots['Операторы'].get('адреса_разведки', pd.Series(dtype=str)).fillna('')).replace(' ', '').split(',') if x) - set(spam)
        add(sorted(rc), 'разведка оператора', 'наблюдение')
    add(c.m.get('staff_ips', []), 'свои: сотрудники', 'не трогать')
    add([m_['ip'] for m_ in c.m.get('monitors', [])], 'свои: мониторинг', 'не трогать')
    return pd.DataFrame(rows, columns=['ip', 'категория', 'сеть', 'ASN', 'страна', 'тип_сети', 'визитов', 'запросов', 'отправок', 'принято', 'первый', 'последний', 'действие']).drop_duplicates('ip')


def _ctx(n_ip=400, seed=5):
    r = random.Random(seed)
    ips = [f'198.51.{i // 250}.{i % 250 + 1}' for i in range(n_ip)]
    rows = []
    for ip in ips:
        for _ in range(r.randint(1, 4)):   # у IP по несколько визитов
            t = 1_790_000_000 + r.randint(0, 10 ** 6)
            rows.append((ip, r.randint(1, 30), r.randint(0, 2), r.randint(0, 1), t, t + r.randint(1, 600), r.choice(['спам форм', 'люди', 'спам форм · массовый', 'прочие'])))
    V = pd.DataFrame(rows, columns=['ip', 'n_req', 'n_goal', 'n_conv', 'start', 'end', 'subgroup'])
    tips = ips[::2]
    T = pd.DataFrame({'ip': tips, 'org': 'Example Net', 'asn': 64500, 'cc': 'RU', 'nettype': [('дата-центр', 'домашний интернет')[i % 2] for i in range(len(tips))]})
    m = dict(staff_ips=ips[:5] + ['203.0.113.250'], monitors=[dict(ip=ips[7]), dict(ip='203.0.113.251')])   # последние в таблицах визитов и сетей отсутствуют
    return SimpleNamespace(V=V, T=T, m=m)


def test_important_ips_same_as_per_ip_selection():
    c = _ctx()
    S_bots = {'Подделки': pd.DataFrame({'ip': c.V['ip'].unique()[10:20]}),
              'Операторы': pd.DataFrame({'адреса_разведки': [', '.join(c.V['ip'].unique()[30:34]), '']})}
    new, old = analyze.important_ips(c, S_bots), _old_important_ips(c, S_bots)
    assert len(new) > 100
    pd.testing.assert_frame_equal(new.reset_index(drop=True), old.reset_index(drop=True))


def test_important_ips_not_quadratic(monkeypatch):
    """Сравнений V['ip'] == ip по числу IP быть не должно."""
    c = _ctx(3000)
    calls = []
    orig = pd.Series.__eq__
    monkeypatch.setattr(pd.Series, '__eq__', lambda self, other: (calls.append(1), orig(self, other))[1])
    analyze.important_ips(c, {})
    assert len(calls) < 20, len(calls)
