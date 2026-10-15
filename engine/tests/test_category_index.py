"""Поиск по метке в индексе, построенном из категориальной колонки (V, R), на логе с тысячами разных адресов, браузеров и рефереров.

На реальном логе (500 тыс. строк) analyze падал в operators.link: spam404_by_entry.get(путь) → OverflowError «Python integer 11412 out of bounds for int8» —
номер категории не помещается в узкие коды индекса. Здесь «сторож» воспроизводит это условие: поиск метки в CategoricalIndex с номером категории > 127 —
ошибка. Ключи группировки, по которым дальше ищут по метке, должны быть строками."""
import os
import pickle
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from pandas import CategoricalIndex

from nxld import analyze, common, operators, prepare, report

T0 = datetime(2026, 9, 1)


@pytest.fixture
def narrow_codes(monkeypatch):
    orig = CategoricalIndex._maybe_cast_indexer

    def narrow(self, key):
        try: code = self.categories.get_loc(key)
        except (KeyError, TypeError): code = None
        if isinstance(code, (int, np.integer)): np.int8(code)   # OverflowError при номере категории > 127
        return orig(self, key)
    monkeypatch.setattr(CategoricalIndex, '_maybe_cast_indexer', narrow)


def _wide_log(path, nv=6000, seed=11):
    """example.com, вымышленные IP: много разных входов, браузеров, рефереров; спам форм с референом на битый вход (названия битых входов идут в конце списка категорий)."""
    R = random.Random(seed)
    np_, span = max(200, nv // 40), 7 * 86400
    uas = [f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/{90 + i % 50}.0.{i}.{i % 97} Safari/537.36' for i in range(max(200, nv // 12))]
    refs = ['-', 'https://yandex.ru/', 'https://www.google.com/'] + [f'https://site{i}.example.org/page{i % 7}' for i in range(450)]
    L = []

    def line(t, ip, m, u, c, ref, ua): L.append(f'{ip} - - [{t:%d/%b/%Y:%H:%M:%S} +0300] "{m} {u} HTTP/1.1" {c} 9000 "{ref}" "{ua}"')
    for _ in range(nv):
        t = T0 + timedelta(seconds=R.randint(0, span)); ip = f'95.{R.randint(1, 250)}.{R.randint(1, 250)}.{R.randint(1, 250)}'; ua = R.choice(uas)
        p = f'/section{R.randint(1, 9)}/page{R.randint(0, np_)}/'
        if R.random() < 0.25: p += f'?utm_source=yandex&utm_medium=cpc&utm_campaign=camp{R.randint(0, 400)}&yclid={R.randint(1, 10 ** 6)}'
        line(t, ip, 'GET', p, R.choice([200] * 40 + [404, 500]), R.choice(refs), ua)
        for k in range(2): line(t + timedelta(seconds=1), ip, 'GET', f'/upload/i{R.randint(0, 300)}.jpg', 200, 'https://example.com' + p, ua)
        line(t + timedelta(seconds=40), ip, 'GET', f'/section{R.randint(1, 9)}/page{R.randint(0, np_)}/', 200, 'https://example.com' + p, ua)
        if R.random() < 0.03: line(t + timedelta(seconds=70), ip, 'POST', '/contacts/send/', 200, 'https://example.com/contacts/', ua)
    for k in range(40):   # служебные файлы: sitemap.xml стоит в конце списка категорий адресов (номер > 127)
        line(T0 + timedelta(seconds=R.randint(0, span)), f'95.{R.randint(1, 250)}.7.{k + 1}', 'GET', '/sitemap.xml', R.choice([200, 404]), '-', R.choice(uas))
    for k in range(max(40, nv // 150)):
        dead = f'/zz-old-{R.randint(0, np_)}/'
        t = T0 + timedelta(seconds=R.randint(0, span - 20000))
        for j in range(3):   # прямой заход на битый адрес → главная → форма
            ip = f'185.{100 + k % 100}.{j}.{k % 250 + 1}'; ua = R.choice(uas); tj = t + timedelta(seconds=600 * j)
            line(tj, ip, 'GET', dead, 404, '-', ua); line(tj + timedelta(seconds=2), ip, 'GET', '/', 200, '-', ua)
            line(tj + timedelta(seconds=5), ip, 'POST', '/contacts/send/', 200, 'https://example.com/', ua)
        line(t + timedelta(seconds=3000), f'185.{200 + k % 50}.9.{k % 250 + 1}', 'POST', '/contacts/send/', 200, 'https://example.com' + dead, R.choice(uas))   # реферер — битый вход
    L.sort(key=lambda s: s[s.index('[') + 1:s.index(' +')])
    with open(path, 'w') as f: f.write('\n'.join(L) + '\n')


def test_wide_log_full_cycle(tmp_path, narrow_codes, monkeypatch):
    """Полный цикл prepare → analyze → report на логе с тысячами категорий входов, браузеров и рефереров, при узких кодах индекса."""
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    keep = {os.path.join(r, f): open(os.path.join(r, f), 'rb').read() for r, _, fs in os.walk(common_learned()) for f in fs}
    try:
        log, work, out = str(tmp_path / 'access.log'), str(tmp_path / 'work'), str(tmp_path / 'out')
        _wide_log(log)
        prepare.run([log], work, log=lambda *a: None)
        V = pd.read_pickle(os.path.join(work, 'V.pkl'))
        for c in ('entry', 'ua', 'entry_ref', 'entry_query'): assert str(V[c].dtype) == 'category' and V[c].nunique() > 128, c   # тысячи категорий, как на реальном логе
        analyze.run(work, log=lambda *a: None)
        res = pickle.load(open(os.path.join(work, 'results.pkl'), 'rb'))
        assert res.get('spam_examples'), 'в синтетике должен быть спам форм'
        report.build(res, out, None, None, os.path.join(work, 'NXLD_Redmine.textile'), None, work, False)
        assert os.path.exists(os.path.join(out, 'NXLD_04_Bots.xlsx'))
    finally:
        for r, _, fs in os.walk(common_learned()):
            for f in fs:
                if os.path.join(r, f) not in keep: os.remove(os.path.join(r, f))
        for f, b in keep.items(): open(f, 'wb').write(b)


def common_learned():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'reference', 'learned')


def test_operators_link_with_thousands_of_entries(narrow_codes):
    """operators.link на визитах, где у entry тысячи категорий, а спам-вход и реферер — в конце списка (номер > 127 и > 32 767)."""
    n = 40000
    cats = [f'/a{i:06d}/' for i in range(n)] + ['/zz-dead/']
    entry = pd.Categorical(['/zz-dead/'] * 6 + cats[:n], categories=cats)
    V = pd.DataFrame({'entry': entry}).iloc[:12].copy()
    V['entry'] = pd.Categorical(['/zz-dead/'] * 6 + ['/a000001/'] * 6, categories=cats)
    V['ip'] = ['185.1.1.1', '185.1.1.2', '185.1.1.3', '185.1.1.4', '185.1.1.5', '185.1.1.6'] + ['95.1.1.%d' % i for i in range(6)]
    V['entry_status'] = [404] * 6 + [200] * 6
    V['fam_verified'] = ''
    V['entry_ref'] = ['-'] * 3 + ['https://example.com/zz-dead/'] * 3 + ['-'] * 6
    V['entry_ref_internal'] = [False] * 3 + [True] * 3 + [False] * 6
    V['group'] = ['Боты'] * 6 + ['Люди'] * 6
    V['subgroup'] = ['спам форм: битый адрес → главная → форма'] * 3 + ['спам форм: отправка без просмотра страниц'] * 3 + [''] * 6
    V['start'] = 1_790_000_000 + np.arange(12) * 60
    V['end'] = V['start'] + 30
    V['n_goal'] = [1] * 6 + [0] * 6
    V['n_conv'] = 0
    V['n_pages'] = 1
    V['ua'] = 'UA'
    V['asn'] = 64500
    V['entry_query'] = ''
    comp, recon, ev = operators.link(V, set(V['ip'][:6]))
    kinds = {e['улика'] for e in ev.to_dict('records')} if hasattr(ev, 'to_dict') else {e['улика'] for e in ev}
    # улики построены, а не оборвались на поиске по метке: общий битый вход и реферер — битый вход другого спамера
    assert any('общий битый вход' in k for k in kinds) and any('реферер — битый вход другого спамера' in k for k in kinds), kinds


def test_plain_turns_categories_into_strings():
    V = pd.DataFrame({'entry': pd.Categorical(['/a/', '/b/'], categories=[f'/{c}/' for c in 'abcdefg']), 'n': [1, 2]})
    P = common.plain(V)
    assert str(P['entry'].dtype) != 'category' and P['entry'].tolist() == ['/a/', '/b/'] and P['n'].tolist() == [1, 2]
    assert common.plain(P) is P   # без категорий — тот же объект, копий нет
    s = P.groupby('entry')['n'].sum()
    assert s.get('/zz/', 0) == 0 and s.get('/b/') == 2   # индекс строковый: поиск по метке безопасен
