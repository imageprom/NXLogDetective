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
