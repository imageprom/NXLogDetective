"""NXLD: заказы магазина по номеру (#22). Для магазина основная конверсия — заказ: разные номера заказа на странице успеха оформления.
Признак успеха, шаги оформления и список «не целей» — в справочнике движка (reference.engine_orders). Нет признака у движка — цели как раньше, по формам.
Заказ считается один раз: в визите, где номер встретился впервые; в V.n_conv — число таких номеров в визите."""
import re

import numpy as np
import pandas as pd


def _rows(R, patterns):
    """Маска строк R, адрес которых подходит под любое из регулярных выражений."""
    m = np.zeros(len(R), bool)
    if not patterns: return m
    cats = R['base'].cat.categories.to_series()
    hit = np.zeros(len(cats), bool)
    for p in patterns: hit |= cats.str.contains(p, regex=True).fillna(False).values
    return hit[R['base'].cat.codes.values]


def not_goals(R, spec):
    """Строки, которые целями быть не могут (шаги оформления, проверка подписки, кабинет, админка)."""
    return _rows(R, spec.get('not_goals'))


def steps(R, spec):
    """Строки шагов и пересчётов оформления заказа."""
    return _rows(R, spec.get('order_steps'))


def first_orders(R, spec, site=None):
    """Индексы строк R (позиции), в которых номер заказа встретился впервые, и сами номера. Успех — любой ответ на странице успеха оформления (ответ 4xx/5xx — отдельная карточка, B1)."""
    pos, ids = [], []
    seen = set()
    ts = R['ts'].values
    cats = R['base'].cat.categories.to_series()
    bcodes = R['base'].cat.codes.values
    for k, e in enumerate(spec.get('order_success') or []):
        m = _rows(R, [e['path']])
        if site is not None: m &= site   # заказы на хостах вне сайта не считаются
        if not m.any(): continue
        idx = np.flatnonzero(m)
        if e.get('param'):
            q = R['query'].cat.categories.to_series().str.extract(r'(?:^|&)' + re.escape(e['param']) + r'=([^&]+)')[0]
            num = q.values[R['query'].cat.codes.values[idx]]
        else:
            g = cats.str.extract(e['path'])[0]   # номер — первая группа выражения
            num = g.values[bcodes[idx]]
        ok = pd.notna(num)
        idx, num = idx[ok], num[ok]
        order = np.argsort(ts[idx], kind='stable')
        for i, n in zip(idx[order], num[order]):
            key = (k, str(n))
            if key in seen: continue
            seen.add(key); pos.append(int(i)); ids.append(str(n))
    return np.array(pos, dtype=np.int64), ids
