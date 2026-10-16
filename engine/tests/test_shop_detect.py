"""Магазин опознаётся сам: корзина, оформление и обработчик действий с товаром — свои у шаблона и стандартные у движков (shop.py). Синтетика, example.com."""
import json
import os
import tempfile
from datetime import timedelta

import pandas as pd

import synth
from nxld import analyze, prepare

T0 = synth.T0
ASSETS = synth.ASSETS
HOST = 'https://example.com'


def _ip(n): return f'95.{100 + n // 60000}.{(n // 250) % 250}.{n % 250 + 1}'


class Shop:
    """Журнал магазина: визиты людей по страницам, вызовы скриптов после страниц и в стороне."""
    def __init__(self):
        self.log = synth.Log()
        self.n = 0

    def visit(self, pages, calls=None, bg=None, day=0, minute=None):
        """pages — страницы по порядку (первая с картинками и стилями); calls — [(секунды от начала, метод, адрес, источник или None)];
        bg — адрес скрипта, который зовут через 2 с после каждой страницы (фон: мини-корзина, счётчики)."""
        self.n += 1
        ip = _ip(self.n)
        t = T0 + timedelta(days=day, hours=8, minutes=minute if minute is not None else (self.n * 3) % 600, seconds=self.n % 50)
        prev = 'https://yandex.ru/'
        for i, p in enumerate(pages):
            at = t + timedelta(seconds=20 * i)
            self.log.line(ip, at, p, 200, ref=prev)
            if i == 0:
                for a in ASSETS: self.log.line(ip, at + timedelta(seconds=1), a, 200, ref=HOST + p)
            if bg: self.log.line(ip, at + timedelta(seconds=2), bg, 200, ref=HOST + p, method='POST', size=40)
            prev = HOST + p
        for sec, method, url, ref in calls or []:
            self.log.line(ip, t + timedelta(seconds=sec), url, 200, ref=HOST + (ref if ref is not None else pages[-1]), method=method, size=552)
        self.last = (ip, t)
        return ip

    def crowd(self, k, bg=None):
        for i in range(k): self.visit([f'/catalog/c{i % 40}/', f'/about/{i % 5}/'], bg=bg)


def _run(log, override=None):
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        log.write(path)
        prepare.run([path], work, log=lambda *a: None, map_override=override)
        sm = json.load(open(os.path.join(work, 'site_map.json'), encoding='utf-8'))
        res = analyze.run(work, log=lambda *a: None)
        return sm, res['sheets']['Маркетинг']['Воронка заказа'], res


def _found(sm, kind=None):
    return [f for f in sm['site_actions_found'] if kind is None or f['kind'] == kind]


def _steps(of): return dict(of['шаги']) if of else {}


# ---------- свой обработчик по поведению ----------

def _own_handler():
    s = Shop()
    s.crowd(150)
    for k in range(30):   # обработчик /include/actions.php зовут с 30 разных страниц; 25 из этих визитов потом доходят до корзины
        pages = [f'/catalog/c{k}/', f'/catalog/c{k}/item{k}/'] + (['/personal/cart/'] if k < 25 else [])
        s.visit(pages, calls=[(30, 'POST', '/include/actions.php', f'/catalog/c{k}/item{k}/')])
    for k in range(12):   # фильтр каталога: POST на раздел с одной страницы
        s.visit(['/catalog/'], calls=[(30, 'POST', '/catalog/', '/catalog/')])
    for k in range(8):   # обработчик корзины: зовут только со страницы корзины
        s.visit(['/personal/cart/'], calls=[(25, 'POST', '/basket/recalc.php', '/personal/cart/'), (35, 'POST', '/basket/recalc.php', '/personal/cart/')])
    return s.log


def test_own_handler_found_by_behavior():
    sm, of, _ = _run(_own_handler())
    f = _found(sm)
    assert [x['path'] for x in f] == ['^/include/actions\\.php$'] and f[0]['how'] == 'behavior' and f[0]['kind'] == 'unknown' and f[0]['refs'] >= 25 and f[0]['lift'] >= 2, f
    assert f[0]['how_text'].startswith('по поведению')
    assert _steps(of)['action'] == 30 and 'cart_add' not in _steps(of), of   # «Действия с товаром»: корзину по логу не отделить
    assert 'не отделить' in sm['shop']['note']


def test_filter_and_cart_handler_are_not_actions():
    sm, of, _ = _run(_own_handler())
    paths = ' '.join(x['path'] for x in _found(sm))
    assert '/catalog/' not in paths and 'recalc' not in paths   # фильтр — одна страница-источник; обработчик корзины зовут со страницы корзины


# ---------- страницы корзины и оформления ----------

def _pages_log(cart, checkout=None):
    s = Shop()
    s.crowd(60)
    for k in range(20): s.visit([f'/catalog/c{k}/', cart] + ([checkout] if checkout and k < 8 else []))
    return s.log


def test_own_cart_by_name():
    for cart in ('/basket/', '/shop/korzina/', '/my_cart.php'):
        sm, of, _ = _run(_pages_log(cart))
        c = sm['orders']['cart']
        assert len(c) == 1 and c[0]['how'] == 'name' and cart.replace('.', '\\.') in c[0]['path'] and c[0]['visits'] == 20, (cart, c)
        assert _steps(of).get('cart') == 20, of


def test_checkout_by_name_and_cart_by_behavior():
    sm, of, _ = _run(_pages_log('/mycart2/', '/oformlenie/'))   # у корзины имени нет в словаре: ищется по тому, откуда приходят на оформление
    co, c = sm['orders']['checkout'], sm['orders']['cart']
    assert co and co[0]['how'] == 'name' and '/oformlenie/' in co[0]['path'], co
    assert not c or c[0]['how'] in ('behavior', 'name')


def test_map_override_wins_over_found():
    sm, of, _ = _run(_pages_log('/basket/'), {'cart_pages': ['^/about/']})
    c = sm['orders']['cart']
    assert c[0]['how'] == 'override' and c[0]['path'] == '^/about/' and c[0]['how_text'] == 'поправка карты', c


def test_site_without_shop_finds_nothing():
    s = Shop()
    s.crowd(150)
    for k in range(30): s.visit([f'/catalog/c{k}/'], calls=[(30, 'POST', '/include/ajax.php', None)])   # скрипт без признаков и без корзины, которой можно сверить
    sm, of, _ = _run(s.log)
    assert sm['site_actions_found'] == [] and not sm['orders']['cart'] and not sm['orders']['checkout'] and of is None


# ---------- стандартные признаки движков ----------

def _standard():
    s = Shop()
    s.crowd(150)
    for k in range(10):   # корзина: действие в параметрах адреса карточки
        s.visit([f'/catalog/c{k}/', f'/catalog/c{k}/item{k}/', '/personal/cart/'], calls=[(30, 'POST', f'/catalog/c{k}/item{k}/?action=ADD2BASKET&id={k}&ajax_basket=Y', f'/catalog/c{k}/item{k}/')])
    for k in range(10):   # сравнение: то же на адрес раздела
        s.visit([f'/catalog/c{k}/'], calls=[(30, 'POST', f'/catalog/c{k}/?action=ADD_TO_COMPARE_LIST&id={k}&ajax_action=Y', None)])
    for k in range(25):   # избранное: отдельный скрипт шаблона; зовут с 25 страниц, визиты с ним часто доходят до корзины
        s.visit([f'/catalog/c{k}/', f'/catalog/c{k}/item{k}/'] + (['/personal/cart/'] if k < 20 else []), calls=[(30, 'POST', '/local/ajax/action-favorites.php', f'/catalog/c{k}/item{k}/')])
    for k in range(15):   # POST на тот же раздел без action — фильтр
        s.visit(['/catalog/c1/'], calls=[(30, 'POST', '/catalog/c1/', None)])
    return s.log


def test_standard_bitrix_actions_by_kind():
    sm, of, _ = _run(_standard())
    kinds = {f['kind']: f for f in _found(sm)}
    assert set(kinds) == {'cart', 'compare', 'favorite'}, _found(sm)
    assert kinds['cart']['how'] == 'name' and 'ADD2BASKET' in kinds['cart']['path'] and kinds['cart']['visits'] == 10
    assert kinds['compare']['how'] == 'name' and 'ADD_TO_COMPARE_LIST' in kinds['compare']['path'] and kinds['compare']['visits'] == 10   # сравнение, не корзина
    assert kinds['favorite']['how'] == 'behavior' and kinds['favorite']['path'] == '^/local/ajax/action\\-favorites\\.php$'
    assert _steps(of)['cart_add'] == 10 and 'action' not in _steps(of)   # шаг «Добавили в корзину» считает только корзину; сравнение и избранное — в карте
    assert sm['shop']['cart_separable'] is True


def test_post_on_section_without_action_is_nothing():
    sm, _, _ = _run(_standard())
    assert not [f for f in _found(sm) if f['path'].startswith('^/catalog/c1/')]


# ---------- фон при загрузке страницы ----------

BG = '/tpl/counter.php'


def _background(extra=5):
    s = Shop()
    for k in range(120): s.visit([f'/catalog/c{k % 40}/', f'/about/{k % 6}/'], bg=BG)
    for k in range(extra):   # лишний вызов: не сразу после загрузки страницы
        s.visit([f'/catalog/c{k}/', f'/catalog/c{k}/item{k}/'], bg=BG, calls=[(45, 'POST', BG, None)])
    for k in range(3): s.visit(['/cart/'], bg=BG)
    return s.log


def test_background_call_is_not_an_action():
    sm, of, _ = _run(_background(5))
    f = _found(sm)
    assert len(f) == 1 and f[0]['background'] == 'per_page' and f[0]['how'] == 'behavior', f
    assert f[0]['background_info']['extra'] == 5 and f[0]['background_info']['singles'] == 5
    assert _steps(of)['action'] == 5 and _steps(of)['people'] > 120, of   # не число визитов со страницами


# ---------- экзотические сигнатуры и описание сайта ----------

def _signature(cart_for_bursts=True):
    """Один скрипт шаблона: фон на каждой странице, корзина — пачка из двух вызовов, избранное — одиночный на карточке."""
    s = Shop()
    sec = lambda k: f'/catalog/{100 + k}/'
    item = lambda k: f'/catalog/{100 + k}/{500 + k}/'
    for k in range(120): s.visit([sec(k % 40), f'/about/{k % 6}/'], bg=BG)
    for k in range(40): s.visit([sec(k), item(k)], bg=BG)   # шаблоны каталога: раздел и карточка (глубже)
    for k in range(20):
        pages = [sec(k), item(k)] + (['/personal/cart/'] if cart_for_bursts else [])
        s.visit(pages, bg=BG, calls=[(45, 'POST', BG, item(k)), (46, 'POST', BG, item(k))])
    for k in range(15): s.visit([sec(k), item(k)], bg=BG, calls=[(45, 'POST', BG, item(k))])
    for k in range(30): s.visit([sec(k % 40), '/personal/cart/'] if k < 6 else ([f'/about/{k}/', '/personal/cart/'] if not cart_for_bursts else [f'/about/{k}/']), bg=BG)
    return s.log


def test_signature_matches_without_site_actions():
    sm, of, _ = _run(_signature())
    f = {x['kind']: x for x in _found(sm)}
    assert 'cart' in f and f['cart']['how'] == 'pattern' and f['cart']['pattern'] == 'ACT-X-7F3A' and f['cart']['visits'] == 20, _found(sm)
    assert f['cart']['lift'] >= 3 and 'ACT-X-7F3A' in f['cart']['how_text'] and 'подтвердить экспериментом' in f['cart']['how_text']
    assert f['favorite']['visits'] == 15 and f['favorite']['how'] == 'pattern'   # одиночные на карточках; фон не считается
    assert _steps(of)['cart_add'] == 20


def test_signature_not_confirmed_when_bursts_do_not_lead_to_cart():
    sm, of, _ = _run(_signature(cart_for_bursts=False))
    f = _found(sm)
    assert f and all(x['how'] == 'behavior' and x['kind'] == 'unknown' for x in f), f
    assert 'cart_add' not in _steps(of) and _steps(of)['action'] == 35   # 20 пачек и 15 одиночных: «Действия с товаром»


def test_site_actions_override_cart_and_favorite():
    ov = {'site_actions': [{'path': '^/tpl/counter\\.php$', 'background': 'per_page', 'kinds': {'cart': 'burst', 'favorite': 'single_on_card'},
                            'source': 'experiment', 'ref': {'type': 'experiment', 'n': 1}}]}
    sm, of, _ = _run(_signature(), ov)
    f = {x['kind']: x for x in _found(sm)}
    assert f['cart']['how'] == 'experiment' and f['cart']['visits'] == 20 and f['favorite']['visits'] == 15 and 'pattern' not in f['cart'], f
    assert _steps(of)['cart_add'] == 20


# ---------- справочники ----------

def test_action_patterns_have_no_site_names_or_script_paths():
    ref = os.path.join(synth.ENGINE, '..', 'data', 'reference')
    d = json.load(open(os.path.join(ref, 'action_patterns.json'), encoding='utf-8'))
    text = json.dumps(d, ensure_ascii=False).lower()
    for bad in ('.php', 'http', '.ru', '.com', 'example', '/include', '/local', '/ajax'): assert bad not in text, bad
    import re
    assert all(re.fullmatch(r'ACT-X-[0-9A-F]{4}', p['code']) and p.get('title') and p.get('kinds') and 'check' in p and 'seen' in p and p.get('evidence') and p.get('to_verify') for p in d['patterns'])
    assert [p['code'] for p in d['patterns']] == ['ACT-X-7F3A'] and d['patterns'][0]['check']['lift_min'] == 3


def test_action_vocab_keys_latin_and_to_verify():
    ref = os.path.join(synth.ENGINE, '..', 'data', 'reference')
    d = json.load(open(os.path.join(ref, 'action_vocab.json'), encoding='utf-8'))
    import re
    def keys(x):
        if isinstance(x, dict):
            for k, v in x.items(): yield k; yield from keys(v)
        elif isinstance(x, list):
            for v in x: yield from keys(v)
    assert all(re.fullmatch(r'[A-Za-z0-9_\-]+', k) for k in keys(d)), [k for k in keys(d) if not re.fullmatch(r'[A-Za-z0-9_\-]+', k)]
    assert {'verbs', 'subjects', 'quantity_params', 'product_params', 'engines'} <= set(d) and all(e.get('to_verify') for e in d['engines'] if e['engine'] != 'woocommerce' or e['role'] != 'action')


# ---------- следственный эксперимент ----------

def _experiment_log():
    s = Shop()
    s.crowd(150)
    for k in range(30): s.visit([f'/catalog/c{k}/', f'/catalog/c{k}/item{k}/'], calls=[(30, 'POST', '/include/actions.php', f'/catalog/c{k}/item{k}/')])
    s.visit(['/catalog/c1/', '/catalog/c1/item1/'], calls=[(30, 'POST', '/include/actions.php', '/catalog/c1/item1/')], day=2, minute=200)
    return s


def test_experiment_trace_found_in_log_and_outside_period(tmp_path):
    from nxld import shop
    s = _experiment_log()
    ip, t = s.last
    path, work = str(tmp_path / 'a.log'), str(tmp_path / 'w')
    s.log.write(path)
    R, _, _, inv = prepare.run([path], work, log=lambda *a: None)
    ex = [dict(n=1, ip=ip, time=str(t + timedelta(seconds=30)), level='browser', conclusion='POST на обработчик', ref={'type': 'experiment', 'n': 1}),
          dict(n=2, ip=ip, time='2020-01-01 10:00:00', ref={'type': 'experiment', 'n': 2}),   # вне периода лога
          dict(n=3, ip='203.0.113.9', time=str(t + timedelta(seconds=30)), ref={'type': 'experiment', 'n': 3}),   # IP в логе нет
          dict(n=4, level='browser', ref={'type': 'testimony', 'n': 4})]   # времени и IP нет
    out = shop.trace_experiments(R, ex, inv['period'])
    a, b, c, d = out
    assert a['level'] == 'log_confirmed' and a['trace']['found'] and a['trace']['requests'] >= 1 and a['label'] == 'Э-1' and a['level_text'] == 'подтверждён по логу'
    assert any(x['method'] == 'POST' and x['url'] == '/include/actions.php' for x in a['trace']['sample'])
    assert b['level'] == 'browser' and b['trace'].get('outside_period') and not b['trace']['searched']   # вне периода — «браузер»
    assert c['level'] == 'browser' and c['trace']['searched'] and not c['trace']['found']
    assert d['label'] == 'П-4' and not d['trace']['searched']
    assert 'Э-1' not in json.dumps(ex, ensure_ascii=False)   # в данных номер — число, подпись из языка


def test_experiments_in_brief_with_edits(tmp_path):
    s = _experiment_log()
    ip, t = s.last
    ed = tmp_path / 'edits.json'
    ed.write_text(json.dumps({'experiments': [dict(n=1, ip=ip, time=str(t + timedelta(seconds=30)), who='разработчик', goal='найти обработчик', level='browser',
                                                    changes={'site_actions': [{'path': '^/include/actions\\.php$', 'background': 'none'}]}, ref={'type': 'experiment', 'n': 1})]}))
    _, out, _ = synth.run(s.log, str(tmp_path), '--edits', str(ed))
    brief = json.load(open(tmp_path / 'work' / 'brief.json', encoding='utf-8'))
    e = brief['experiments'][0]
    assert e['n'] == 1 and e['level'] == 'log_confirmed' and e['trace']['found'] and e['label'] == 'Э-1', e
    snap = json.load(open([os.path.join(out, f) for f in os.listdir(out) if f.endswith('.snapshot.json')][0], encoding='utf-8'))
    assert snap['правки']['experiments'][0]['n'] == 1   # хранится в снимке, повторно не просим


def test_background_share_counts_only_visits_with_script():
    """Фон определяется по страницам визитов, где скрипт вызывался: визиты без JS, быстрые уходы и предзагрузки его не вызывают.
    На реальном логе магазина доля по всем страницам людей — 0,56, по визитам со скриптом — 0,65; без этого почерк не узнаётся и каждый вызов считается действием."""
    log = _signature()
    s = Shop(); s.log = log; s.n = 10000
    for k in range(400): s.visit([f'/catalog/{100 + k % 40}/', f'/about/{k % 6}/'])   # без фонового вызова
    sm, of, _ = _run(s.log)
    f = {x['kind']: x for x in _found(sm)}
    assert 'cart' in f and f['cart']['pattern'] == 'ACT-X-7F3A' and f['cart']['visits'] == 20, _found(sm)
    assert _steps(of)['cart_add'] == 20 and 'action' not in _steps(of), of
