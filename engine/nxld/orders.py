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


def product_action_rows(R, human, spec, min_calls=20, min_refs=5, share=0.7):
    """Строки «действий с товаром» (корзина, избранное, сравнение — по логу не различить): POST на обработчик.
    Адрес — из справочника движка (product_action); нет — по поведению: POST, ответ 200, вызов со страниц сайта (не корзина и не оформление),
    один адрес даёт не меньше share всех таких вызовов, не меньше min_calls вызовов с не меньше min_refs разных страниц. Не определить — None (шаг не выводится)."""
    post = (R['method'].astype(str).values == 'POST') & (R['status'].values == 200) & human
    if spec.get('product_action'): return post & _rows(R, spec['product_action'])
    cand = post & ~not_goals(R, spec) & ~steps(R, spec) & (R['goal'].astype(str).values == '') & (R['ref_path'].astype(str).values != '')
    cand &= ~_rows_ref(R, spec.get('cart_pages', []) + spec.get('checkout_pages', []))
    if cand.sum() < min_calls: return None
    b = R['base'].cat.codes.values[cand]
    top = pd.Series(b).value_counts()
    code = top.index[0]
    if top.iloc[0] < max(min_calls, share * cand.sum()): return None
    hit = cand & (R['base'].cat.codes.values == code)
    if len(set(R['ref_path'].astype(str).values[hit])) < min_refs: return None
    return hit


def _rows_ref(R, patterns):
    """Маска строк, у которых страница-источник (ref_path) подходит под выражения."""
    m = np.zeros(len(R), bool)
    if not patterns: return m
    cats = R['ref_path'].cat.categories.to_series().astype(str)
    hit = np.zeros(len(cats), bool)
    for p in patterns: hit |= cats.str.contains(p, regex=True).fillna(False).values
    return hit[R['ref_path'].cat.codes.values]


def funnel(R, V, spec):
    """Воронка заказа по визитам людей к сайту: Визиты людей → Действия с товаром → Корзина → Оформление → Заказ.
    Шаги не обязательно последовательны: у шага считаются визиты, где он был (в любом порядке). Нет заказов у движка — None.
    Возвращает dict(шаги=[(код, визитов)], заказ_через_корзину=число или None, действия_определены=bool)."""
    if not spec.get('order_success') or 'is_order' not in R: return None
    human = (V['group'] == 'Люди')
    hv = set(V.index[human.values]) if len(V) else set()
    rh = R['vid'].isin(hv).values
    get = (R['method'].astype(str).values == 'GET') & ~R['is_order'].values
    n = lambda mask: int(R['vid'][mask & rh].nunique())
    steps_ = [('people', int(human.sum()))]
    act = product_action_rows(R, rh, spec)
    if act is not None: steps_.append(('action', n(act)))
    cart_vid = set()
    if spec.get('cart_pages'):
        cm = get & _rows(R, spec['cart_pages']) & (R['status'].values < 400)
        steps_.append(('cart', n(cm))); cart_vid = set(R['vid'][cm & rh])
    if spec.get('checkout_pages'):
        km = get & _rows(R, spec['checkout_pages']) & ~R['order_step'].values & (R['status'].values < 400)
        steps_.append(('checkout', n(km)))
    om = R['is_order'].values & rh
    steps_.append(('order', int(R['vid'][om].nunique())))
    if not any(v for k, v in steps_ if k in ('cart', 'checkout', 'order')): return None   # в логе нет ни корзины, ни оформления, ни заказов — магазина в этом логе нет
    return dict(шаги=steps_, заказ_через_корзину=len(set(R['vid'][om]) & cart_vid) if spec.get('cart_pages') else None, действия_определены=act is not None)
