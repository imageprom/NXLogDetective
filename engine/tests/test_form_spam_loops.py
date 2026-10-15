"""Три цикла в visits.mark_form_spam без выборки по всей таблице V на каждый визит: результат тот же, число обращений к V не растёт с числом визитов."""
import random
import re

import numpy as np
import pandas as pd

from nxld import visits
from nxld.visits import SEARCH  # noqa: F401  (старая реализация берёт SEARCH из модуля)

SEARCH_ = visits.SEARCH


def old_mark_form_spam(V, R):
    """Прежняя реализация (три цикла с выборкой по всей таблице V на каждый визит) — для сравнения."""
    V = V.copy()
    g = V['n_goal'] > 0
    direct = V['entry_ref'].isin(['-', ''])
    ext_nosearch = ~V['entry_ref_internal'] & ~direct & ~V['entry_ref_host'].str.contains(SEARCH_, regex=True)
    cls = pd.Series('', index=V.index, dtype=object)
    cls[g & (V['entry_status'] == 404) & (direct | ext_nosearch) & (V['n_pages'] <= 6)] = 'спам форм: битый адрес → главная → форма'
    nopage = g & (V['n_pages'] == 0) & (cls == '')
    # исключение: тот же человек сменил IP (мобильная сеть, прокси браузера) — страницу из реферера за ≤30 мин до отправки
    # открыл другой IP с тем же самым UA и это обычный визит человека; путь «/» не в счёт — слишком частый
    same_user = pd.Series(False, index=V.index)
    for vid in V.index[nopage & V['entry_ref_internal']]:
        path = re.sub(r'^https?://[^/]+', '', V.at[vid, 'entry_ref']).split('?')[0]
        if path in ('', '/'): continue
        t, ua, ip = V.at[vid, 'start'], V.at[vid, 'ua'], V.at[vid, 'ip']
        o = V[(V['ua'] == ua) & (V['ip'] != ip) & (V['group'] == 'Люди') & (V['start'] <= t) & (V['end'] >= t - 1800) & (V['n_pages'] > 0)]
        if len(o) and path in set(R.loc[R['vid'].isin(o.index) & (R['base'] == path), 'base'].astype(str)):
            same_user[vid] = True
    cls[nopage & (V['n_static'] == 0) & ~same_user] = 'спам форм: отправка без просмотра страниц'
    # страница открыта другим IP: этот IP грузил только картинки/скрипты и отправил форму, а саму страницу не открывал (хостинг/VPN)
    cls[nopage & (V['n_static'] > 0) & V['entry_ref_internal'] & ~same_user & (V['nettype'].astype(str).str.startswith('дата-центр') | (V['nettype'] == 'VPN/прокси-релей')) & (cls == '')] = 'спам форм: страницу открыл другой IP'
    fast = g & (V['n_goal'] >= 2) & (V['n_pages'] >= 5) & (V['n_pages'] / V['dur'].clip(lower=1) > 0.4)
    cls[fast & (cls == '')] = 'спам форм: быстрый обход и пачка отправок'
    # смена IP посреди визита: вход со страницы сайта, которую за <= 2 ч до этого открыл ДРУГОЙ IP и получил 404
    e404 = V[(V['entry_status'] == 404)][['ip', 'start', 'entry']]
    if len(e404):
        last404 = e404.sort_values('start').groupby('entry').agg(list)
        cand = V[g & V['entry_ref_internal'] & (cls == '')]
        for vid, r in cand.iterrows():
            path = re.sub(r'^https?://[^/]+', '', r['entry_ref']).split('?')[0]
            if path in last404.index:
                ips, ts_ = last404.loc[path, 'ip'], last404.loc[path, 'start']
                if any(i != r['ip'] and 0 <= r['start'] - t <= 7200 for i, t in zip(ips, ts_)):
                    cls[vid] = 'спам форм: смена IP посреди визита'
    # тот же IP уже пойман (±7 дней) — его быстрые заявки с прямого захода тоже спам
    caught = V.loc[cls != '', ['ip', 'start']]
    quick = g & direct & (V['n_pages'] <= 2) & (V['dur'] < 120) & (cls == '')
    for vid in V.index[quick]:
        t = caught.loc[caught['ip'] == V.at[vid, 'ip'], 'start']
        if len(t) and (abs(t - V.at[vid, 'start']) <= 7 * 86400).any():
            cls[vid] = 'спам форм: быстрая заявка с IP, уже пойманного за неделю'
    m = (cls != '') & (V['group'].isin(['Люди', 'Боты']))
    V.loc[m, 'group'] = 'Боты'
    V.loc[m, 'subgroup'] = cls[m]
    return V


PATHS = ['/', '/a/', '/b/', '/c/', '/d/', '/e/'] + [f'/p{i}/' for i in range(24)]


def _data(n, seed):
    r = random.Random(seed)
    ips = [f'198.51.100.{i}' for i in range(1, 41)]
    uas = [f'UA{i}' for i in range(8)]
    rows = []
    for vid in range(n):
        human = r.random() < 0.55
        t = 1_790_000_000 + r.randint(0, 3 * 86400)
        pages = r.choice([0, 0, 1, 2, 3, 5, 7]) if not human else r.choice([1, 2, 4, 6])
        ref = r.choice(['-', 'https://yandex.ru/', 'https://example.com' + r.choice(PATHS) + r.choice(['', '?x=1']), 'https://other.example.org/x'])
        rows.append(dict(ua=r.choice(uas), ip=r.choice(ips), start=t, end=t + r.choice([5, 20, 90, 600, 1500]), group='Люди' if human else 'Боты',
                         n_pages=pages, n_static=r.choice([0, 0, 2]), n_goal=r.choice([0, 0, 1, 1, 2]), entry=r.choice(PATHS), entry_status=r.choice([200, 200, 404, 404]),
                         entry_ref=ref, entry_ref_internal=ref.startswith('https://example.com'), entry_ref_host=re.sub(r'^https?://([^/]+).*', r'\\1', ref) if ref != '-' else '',
                         nettype=r.choice(['дата-центр: Example', 'домашний интернет', 'VPN/прокси-релей']), subgroup=''))
    V = pd.DataFrame(rows)
    V['dur'] = V['end'] - V['start']
    Rr = []
    for vid in V.index[V['n_pages'] > 0]:
        for _ in range(r.randint(1, 3)): Rr.append((vid, r.choice(PATHS)))
    R = pd.DataFrame(Rr, columns=['vid', 'base'])
    R['base'] = pd.Categorical(R['base'], categories=sorted(set(PATHS)))
    return V, R


def test_same_result_as_per_visit_selection():
    total, kinds = 0, set()
    for seed in range(6):
        V, R = _data(900, seed)
        new, old = visits.mark_form_spam(V, R), old_mark_form_spam(V, R)
        pd.testing.assert_frame_equal(new, old)
        total += int(new['subgroup'].str.startswith('спам форм').sum())
        kinds |= set(new['subgroup']) - {''}
    assert total > 200 and len(kinds) >= 4, (total, kinds)   # данные действительно задевают ветки правила: смена IP, быстрая заявка, без страниц, битый адрес


def test_no_selection_over_whole_table_per_visit(monkeypatch):
    """Сравнений по всей колонке V (V['ua'] == ua и т. п.) — константа, а не по числу визитов."""
    V, R = _data(6000, 1)
    big, calls = len(V) // 2, []
    orig = pd.Series.__eq__

    def spy(self, other):
        if len(self) >= big: calls.append(1)
        return orig(self, other)
    monkeypatch.setattr(pd.Series, '__eq__', spy)
    visits.mark_form_spam(V, R)
    assert len(calls) < 60, len(calls)   # прежняя реализация: тысячи
