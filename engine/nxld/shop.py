"""NXLD: магазин опознаётся сам — страницы корзины, оформления и обработчики действий с товаром (корзина, сравнение, избранное).

Порядок опознания: поправки карты (map_override) → справочник движка (стандарт: словарь data/reference/action_vocab.json) →
экзотические сигнатуры (data/reference/action_patterns.json, каждая — гипотеза с проверкой) → общее поведение → не опознано.
Результат: правила действий (rules) и найденное (found) — в site_map.json: orders (cart, checkout, success) и site_actions_found; ключи латиницей, подписи — data/locale/<язык>/shop.json.

Правило действия: {kind: cart|compare|favorite|unknown, path, query, method, background: none|per_page, select: all|burst|single|single_on_card|param:имя=значение, how, ...}.
Как найдено (how): override, engine, name, behavior, pattern, experiment. Фоновый вызов при загрузке страницы (мини-корзина, счётчики) действием не считается — только лишние вызовы."""
import json
import os
import re

import numpy as np
import pandas as pd

from . import orders as orders_, thresholds

_REF = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference'))
_CACHE = {}
KINDS = ('cart', 'compare', 'favorite')
CART_RX = r'(?:^|[/_.-])(?:cart|basket|korzin\w*|bag)(?:[/_.-]|$)'
CHECKOUT_RX = r'(?:^|[/_.-])(?:order|checkout|oformlen\w*|make)(?:[/_.-]|$)'
NOT_PAGE_RX = r'ajax|/api/|handler|\.json$'


def _ref(name):
    if name not in _CACHE:
        try: _CACHE[name] = json.load(open(os.path.join(_REF, name + '.json'), encoding='utf-8'))
        except Exception: _CACHE[name] = {}
    return _CACHE[name]


def vocab(): return _ref('action_vocab')
def patterns(): return _ref('action_patterns').get('patterns', [])


def _eq(R, col, val):
    cats = R[col].cat.categories
    if val not in cats: return np.zeros(len(R), bool)
    return R[col].cat.codes.values == cats.get_loc(val)


def _rx(R, col, rx):
    """Маска строк, у которых значение категориального столбца подходит под выражение (или любое из списка)."""
    if isinstance(rx, (list, tuple)):
        if not rx: return np.zeros(len(R), bool)
        rx = '|'.join(f'(?:{p})' for p in rx)
    if not rx: return np.ones(len(R), bool)
    cats = R[col].cat.categories.to_series().astype(str)
    hit = cats.str.contains(rx, regex=True, case=False).fillna(False).values
    return hit[R[col].cat.codes.values]


class Ctx:
    """Страницы людей (GET, 200, не статика) в порядке визитов: по ним ищется загрузка страницы перед вызовом скрипта."""
    def __init__(self, R, rh, catalog_templates=()):
        self.R, self.rh = R, rh
        m = _eq(R, 'method', 'GET') & (R['status'].values == 200) & rh & R['is_page'].values & ~R['is_static'].values
        idx = np.flatnonzero(m)
        vid, ts = R['vid'].values[idx].astype(np.int64), R['ts'].values[idx].astype(np.int64)
        o = np.lexsort((ts, vid))
        self.pvid, self.pts = vid[o], ts[o]
        self.pk = self.pvid * 10**10 + self.pts
        self.templates = list(catalog_templates or [])
        self._card = None

    def card_ref_mask(self):
        """Страницы-источники, которые являются карточкой товара: самый глубокий шаблон каталога."""
        if self._card is None:
            R = self.R
            tpl = self.templates
            card = max(tpl, key=lambda t: (str(t).strip('/').count('/'), -tpl.index(t))) if tpl else None
            hit = np.zeros(len(R['ref_path'].cat.categories), bool)
            if card is not None:   # шаблон каталога: * — любое имя уровня
                rx = '^' + re.escape(str(card)).replace(r'\*', '[^/]+') + '$'
                hit = R['ref_path'].cat.categories.to_series().astype(str).str.contains(rx, regex=True).fillna(False).values
            self._card = hit
        return self._card[self.R['ref_path'].cat.codes.values]


def profile(ctx, idx):
    """Вызовы скрипта (позиции строк R) → фон при загрузке страницы или лишний вызов; пачка или одиночный; на карточке ли.
    Возвращает dict(idx, vid, extra, burst, card, per_page, pages_with_call, pages)."""
    R = ctx.R
    win = float(thresholds.value('action_background_seconds', 3))
    bs = float(thresholds.value('action_burst_seconds', 2))
    vid, ts = R['vid'].values[idx].astype(np.int64), R['ts'].values[idx].astype(np.int64)
    o = np.lexsort((ts, vid))
    idx, vid, ts = idx[o], vid[o], ts[o]
    j = np.searchsorted(ctx.pk, vid * 10**10 + ts, side='right') - 1
    jc = np.clip(j, 0, max(0, len(ctx.pk) - 1))
    near = (j >= 0) & (len(ctx.pk) > 0)
    if len(ctx.pk): near &= (ctx.pvid[jc] == vid) & ((ts - ctx.pts[jc]) <= win)
    first = np.zeros(len(idx), bool)
    if near.any():
        first[np.flatnonzero(near)] = ~pd.Series(j[near]).duplicated().values
    extra = ~first
    ei = np.flatnonzero(extra)
    burst = np.zeros(len(idx), bool)
    if len(ei) > 1:
        ev, et = vid[ei], ts[ei]
        close = (ev[1:] == ev[:-1]) & ((et[1:] - et[:-1]) <= bs)
        b = np.zeros(len(ei), bool); b[1:] |= close; b[:-1] |= close
        burst[ei] = b
    card = ctx.card_ref_mask()[idx]
    pages = len(ctx.pk)
    return dict(idx=idx, vid=vid, extra=extra, burst=burst, card=card, pages_with_call=int(first.sum()), pages=pages,
                per_page=bool(pages and first.sum() / pages >= float(thresholds.value('action_background_share', 0.7))))


def _select(select, p, R):
    """Какие вызовы профиля считаются действием вида."""
    if select == 'burst': return p['extra'] & p['burst']
    if select == 'single': return p['extra'] & ~p['burst']
    if select == 'single_on_card': return p['extra'] & ~p['burst'] & p['card']
    if str(select).startswith('param:'):
        name, _, val = str(select)[6:].partition('=')
        q = R['query'].astype(str).values[p['idx']]
        return p['extra'] & np.array([bool(re.search(r'(?:^|&)' + re.escape(name) + '=' + re.escape(val) + r'(?:&|$)', x)) for x in q], bool)
    return p['extra']


def rule_rows(R, rule, rh, ctx=None):
    """Строки R, которые правило считает действием людей: адрес, метод, ответ, запрос; фоновые вызовы исключены."""
    m = _rx(R, 'base', rule['path']) & rh
    if rule.get('query'): m &= _rx(R, 'query', rule['query'])
    meth = rule.get('method', 'POST')
    if meth != 'any': m &= _eq(R, 'method', meth)
    m &= (R['status'].values == 200) if meth == 'POST' else (R['status'].values < 400)
    out = np.zeros(len(R), bool)
    idx = np.flatnonzero(m)
    if not len(idx): return out
    if rule.get('background') == 'per_page':
        ctx = ctx or Ctx(R, rh)
        p = profile(ctx, idx)
        out[p['idx'][_select(rule.get('select', 'all'), p, R)]] = True
    else:
        out[idx] = True
    return out


# ---------------- опознание ----------------

def _tokens(s):
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    return [t for t in re.split(r'[^A-Za-z]+', s.lower()) if t]


def classify(base, action_val='', has_qty=False, has_prod=False, flag_cart=False):
    """Вид и сила признака по названию адреса и параметрам: (kind|None, 'strong'|'weak'|None). Словарь — data/reference/action_vocab.json."""
    v = vocab()
    val = str(action_val or '').upper()
    for kind, vals in v.get('action_values', {}).items():
        if val and val in {x.upper() for x in vals}:
            if val in {x.upper() for x in v.get('weak_action_values', [])} and not (has_prod or has_qty): continue
            return kind, 'strong'
    if flag_cart: return 'cart', 'strong'
    low = base.lower()
    toks = _tokens(base)
    subj = {k: any(w in low or w in toks for w in ws) for k, ws in v.get('subjects', {}).items() if k != 'generic'}
    kind = next((k for k in ('compare', 'favorite', 'cart') if subj.get(k)), None)
    verb = any(t == w or t.startswith(w) for t in toks for w in v.get('verbs', [])) or any(w in low for w in ('v_korzinu', 'dobavit'))
    if kind: return kind, 'strong' if (verb or has_qty) else 'weak'
    if has_qty and has_prod: return 'cart', 'strong'
    return None, None


def _page_candidates(R, rh, rx, exclude=None):
    """Страницы людей (GET, 200), чей путь подходит под rx: адрес → визитов. Статика, ajax и файлы — не страницы."""
    m = _eq(R, 'method', 'GET') & (R['status'].values == 200) & rh & R['is_page'].values & ~R['is_static'].values
    m &= _rx(R, 'base', rx) & ~_rx(R, 'base', NOT_PAGE_RX)
    if exclude is not None: m &= ~exclude
    if not m.any(): return pd.Series(dtype='int64', index=pd.Index([], dtype=object))
    s = pd.DataFrame({'base': R['base'].astype(str).values[m], 'vid': R['vid'].values[m]})
    return s.groupby('base')['vid'].nunique().sort_values(ascending=False)


def _entry(path, how, **kw): return dict(path=path, how=how, **kw)


def detect_pages(R, rh, spec, override):
    """Корзина, оформление, успех: поправки карты → справочник движка → страница, с которой уходят на успех → название."""
    out = {'cart': [], 'checkout': [], 'success': [], 'spec_add': {'cart_pages': [], 'checkout_pages': []}}
    ov = override or {}
    for e in spec.get('order_success') or []:
        out['success'].append(_entry(e.get('path', ''), 'override' if ov.get('order_success') else 'engine', param=e.get('param', '')))
    om = R['is_order'].values & rh
    for key, spec_key, rx in (('checkout', 'checkout_pages', CHECKOUT_RX), ('cart', 'cart_pages', CART_RX)):
        have = spec.get(spec_key) or []
        if have:
            how = 'override' if ov.get(spec_key) else 'engine'
            m = _eq(R, 'method', 'GET') & rh & (R['status'].values < 400) & ~R['is_order'].values
            ents = [_entry(p, how, visits=int(pd.Series(R['vid'].values[m & _rx(R, 'base', [p])]).nunique())) for p in have]
            if how == 'override' or any(e['visits'] for e in ents):   # адрес движка, которого в логе нет, ничего не подтверждает: ищем дальше
                out[key] += ents
                continue
        found = None
        if key == 'checkout' and om.any():   # страница, с которой уходят на страницу успеха с номером заказа
            refs = pd.Series(R['ref_path'].astype(str).values[om]); refs = refs[refs != '']
            if len(refs):
                top = refs.value_counts()
                found = _entry('^' + re.escape(top.index[0]), 'behavior', refs=int(top.iloc[0]), visits=int(top.iloc[0]))
        if found is None and key == 'cart' and out['checkout']:   # страница, с которой чаще всего приходят на оформление, и с неё зовут обработчики
            cm = _eq(R, 'method', 'GET') & rh & _rx(R, 'base', [e['path'] for e in out['checkout']]) & ~R['is_order'].values
            refs = pd.Series(R['ref_path'].astype(str).values[cm]); refs = refs[refs != '']
            refs = refs[refs.isin(set(R['ref_path'].astype(str).values[_eq(R, 'method', 'POST') & rh]))]
            if len(refs):
                top = refs.value_counts()
                found = _entry('^' + re.escape(top.index[0]), 'behavior', refs=int(top.iloc[0]), visits=int(top.iloc[0]))
        if found is None:
            c = _page_candidates(R, rh, rx, exclude=R['is_order'].values)
            if key == 'cart': c = c[~c.index.str.contains(CHECKOUT_RX, case=False, regex=True)]
            if len(c): found = _entry('^' + re.escape(c.index[0]), 'name', visits=int(c.iloc[0]))
        if found:
            out[key].append(found); out['spec_add'][spec_key].append(found['path'])
    return out


def _qinfo(R):
    """Признаки строки запроса по категориям: значение и имя параметра действия, есть ли количество, товар, флаг корзины."""
    v = vocab()
    q = R['query'].cat.categories.to_series().astype(str)
    act = pd.Series('', index=q.index); actn = pd.Series('', index=q.index)
    for name in v.get('action_params', []):   # параметр действия — по порядку словаря: action раньше ajax_action
        e = q.str.extract(r'(?:^|&)(' + re.escape(name) + r')=([^&]*)', flags=re.I)
        fill = (act == '') & e[1].notna() & (e[1] != '')
        act = act.where(~fill, e[1]); actn = actn.where(~fill, e[0])
    qty = q.str.contains(r'(?:^|&)(?:' + '|'.join(v.get('quantity_params', [])) + r')=', regex=True, case=False)
    prod = q.str.contains(r'(?:^|&)(?:' + '|'.join(v.get('product_params', [])) + r')=', regex=True, case=False)
    flag = q.str.contains(r'(?:^|&)(?:' + '|'.join(v.get('flag_params', {}).get('cart', ['ajax_basket'])) + r')=', regex=True, case=False)
    return act.values, actn.values, qty.values, prod.values, flag.values


def _lift(R, rh, rows, cart_rx):
    """Во сколько раз визиты с вызовами чаще доходят до корзины, чем все визиты людей: (раз, % визитов с вызовом, % базы). None — корзины нет или нечем сравнить."""
    if not cart_rx: return None
    cart_v = set(R['vid'].values[_eq(R, 'method', 'GET') & rh & _rx(R, 'base', cart_rx)])
    all_v = pd.Series(R['vid'].values[rh]).nunique()
    v = pd.unique(R['vid'].values[rows])
    if not cart_v or not all_v or not len(v): return None
    part = float(np.isin(v, list(cart_v)).mean())
    base = len(cart_v) / all_v
    return round(part / base, 2), round(part * 100, 1), round(base * 100, 1)


def detect_actions(R, rh, spec, eng_spec, override, pages, templates):
    """Правила действий с товаром и найденное для site_map.json. Возвращает (rules, found)."""
    ov = override or {}
    rules, found = [], []
    ctx = Ctx(R, rh, templates)

    def add(rule, rows, extra=None):
        rules.append(rule)
        d = dict(kind=rule['kind'], path=(rule['path'] or '*') + (('?' + rule['query']) if rule.get('query') else ''), how=rule['how'], background=rule.get('background', 'none'))
        d['visits'] = int(pd.Series(R['vid'].values[rows]).nunique()) if rows.any() else 0
        if rows.any():
            d['refs'] = int(pd.Series(R['ref_path'].astype(str).values[rows]).nunique())
            if 'bytes' in R: d['size_median'] = int(np.median(R['bytes'].values[rows]))
        if rule.get('pattern'): d['pattern'] = rule['pattern']
        d.update(extra or {})
        found.append(d)

    # 1. поправки карты важнее всего: есть они — остальное не ищется
    ov_rules = []
    for a in ov.get('site_actions') or []:
        bg, kinds = a.get('background', 'none'), a.get('kinds') or {}
        for kind, sel in (kinds.items() if kinds else [('unknown', 'all')]):
            ov_rules.append(dict(kind=kind, path=a['path'], query='', method='POST', background=bg, select=sel, how='experiment' if a.get('source') == 'experiment' else 'override',
                                 source=a.get('source', ''), ref=a.get('ref')))
    for p in ov.get('product_action') or []:
        ov_rules.append(dict(kind='unknown', path=p, query='', method='POST', background='none', select='all', how='override'))
    if ov_rules:
        for r in ov_rules: add(r, rule_rows(R, r, rh, ctx))
        return rules, found
    # 2. справочник движка: product_action в json движка и стандартные адреса из словаря
    for p in eng_spec.get('product_action') or []:
        r = dict(kind='unknown', path=p, query='', method='POST', background='none', select='all', how='engine')
        rows = rule_rows(R, r, rh, ctx)
        if rows.any(): add(r, rows)
    handled = np.zeros(len(R), bool)
    for e in vocab().get('engines', []):
        if not (e.get('path') or e.get('query')): continue
        r = dict(kind=e['kind'], path=e.get('path', ''), query=e.get('query', ''), method=e.get('method', 'POST'), background='none', select='all', how='engine', engine=e['engine'])
        rows = rule_rows(R, r, rh, ctx)
        if e.get('role') == 'cart_handler': handled |= rows
        elif rows.any(): add(r, rows)
    cart_rx = [e['path'] for e in pages.get('cart', [])]
    co_rx = [e['path'] for e in pages.get('checkout', [])]
    # 3. кандидаты: POST, 200, люди; кроме корзины, оформления и их обработчиков, целей-форм и «не целей» движка
    cand = _eq(R, 'method', 'POST') & (R['status'].values == 200) & rh & (R['goal'].astype(str).values == '') & ~orders_.not_goals(R, spec) & ~orders_.steps(R, spec) & ~handled
    if cart_rx or co_rx: cand &= ~_rx(R, 'ref_path', cart_rx + co_rx)
    for r in rules: cand &= ~rule_rows(R, r, rh, ctx)
    if not cand.any(): return rules, found
    act, actn, qty, prod, flag = _qinfo(R)
    qc = R['query'].cat.codes.values[cand]
    df = pd.DataFrame({'pos': np.flatnonzero(cand), 'b': R['base'].cat.codes.values[cand], 'act': act[qc], 'actn': actn[qc], 'qty': qty[qc], 'prod': prod[qc], 'flag': flag[qc],
                       'ref': R['ref_path'].cat.codes.values[cand]})
    bases = R['base'].cat.categories
    min_refs, lift_min = int(thresholds.value('action_refs_min', 20)), float(thresholds.value('action_lift_min', 2))
    weak = []
    df['pkind'] = None
    for (a, qy, pr, fl), g in df.groupby(['act', 'qty', 'prod', 'flag'], sort=False):
        kind, strength = classify('', a, bool(qy), bool(pr), bool(fl))
        if strength == 'strong': df.loc[g.index, 'pkind'] = kind
    byp = df[df['pkind'].notna()]
    for (kind, an, a, fl), g in byp.groupby(['pkind', 'actn', 'act', 'flag'], sort=False):   # действие в параметрах: адрес страницы значения не имеет (карточка, раздел)
        q = (r'(?:^|&)' + re.escape(an) + '=' + re.escape(a) + r'(?:&|$)') if a else r'(?:^|&)ajax_basket='
        rows = np.zeros(len(R), bool); rows[g['pos'].values] = True
        add(dict(kind=kind, path='', query=q, method='POST', background='none', select='all', how='name'), rows)
    rest = df[df['pkind'].isna()]
    for (b, a), g in rest.groupby(['b', 'act'], sort=False):   # название адреса: у одного адреса разные action — разные виды
        base = str(bases[b])
        kind, strength = classify(base, a, bool(g['qty'].any()), bool(g['prod'].any()), bool(g['flag'].any()))
        rule = dict(kind=kind or 'unknown', path='^' + re.escape(base) + '$', query='', method='POST', background='none', select='all', how='name')
        if strength == 'strong':
            rows = np.zeros(len(R), bool); rows[g['pos'].values] = True
            add(rule, rows)
        else:
            weak.append((rule, g))
    # 4. остальные: фон при загрузке страницы (сигнатуры, иначе лишние вызовы) или поведение
    for rule, g in weak:
        pos = g['pos'].values
        if g['ref'].nunique() < min_refs: continue
        p = profile(ctx, pos)
        if p['per_page']:
            ex = p['extra']
            if not ex.any(): continue
            hit = _signature(R, rh, p, rule, cart_rx)
            if hit:
                for r, rows, info in hit: add(r, rows, info)
            else:
                rows = np.zeros(len(R), bool); rows[p['idx'][ex]] = True
                add(dict(rule, background='per_page', select='all', how='behavior'), rows,
                    dict(background_info=dict(calls=int(len(p['idx'])), extra=int(ex.sum()), bursts=int((ex & p['burst']).sum()), singles=int((ex & ~p['burst']).sum()),
                                              on_cards=int((ex & p['card']).sum()), on_lists=int((ex & ~p['card']).sum()), pages_with_call=p['pages_with_call'], pages=p['pages'])))
            continue
        rows = np.zeros(len(R), bool); rows[pos] = True
        lf = _lift(R, rh, rows, cart_rx)
        if lf is None and rule['kind'] == 'unknown': continue   # нечем подтвердить: корзины нет
        if lf is not None and lf[0] < lift_min: continue
        add(dict(rule, how='behavior'), rows, dict(lift=lf[0] if lf else None))
    return rules, found


def _signature(R, rh, p, rule, cart_rx):
    """Экзотические сигнатуры (action_patterns.json): адрес с фоном на каждой странице, пачки и одиночные вызовы. Подтверждена — [(правило, строки, найденное)], нет — []."""
    for pat in patterns():
        kinds = pat.get('kinds') or {}
        if (pat.get('match') or {}).get('background') != 'per_page' or 'cart' not in kinds: continue
        sel = _select(kinds['cart'], p, R)
        if not sel.any(): continue
        rows = np.zeros(len(R), bool); rows[p['idx'][sel]] = True
        lf = _lift(R, rh, rows, cart_rx)
        if lf is None or lf[0] < float((pat.get('check') or {}).get('lift_min') or thresholds.value('action_lift_min', 2)): continue
        info = dict(pattern=pat['code'], lift=lf[0], cart_pct=lf[1], base_pct=lf[2], bursts=int(pd.Series(p['vid'][sel]).nunique()), level='signature')
        out = []
        for kind, s in kinds.items():
            sl = _select(s, p, R)
            if not sl.any(): continue
            rw = np.zeros(len(R), bool); rw[p['idx'][sl]] = True
            out.append((dict(rule, kind=kind, background='per_page', select=s, how='pattern', pattern=pat['code']), rw, dict(info)))
        if out: return out
    return []


def detect(R, V, spec, eng_spec, override, templates=()):
    """Опознание магазина по запросам и визитам людей к сайту. Результат: pages и found — в site_map.json; rules и spec_add — для воронки."""
    hv = V.index[(V['group'] == 'Люди').values]
    rh = np.isin(R['vid'].values, hv) & R['host_site'].values
    pages = detect_pages(R, rh, spec, override)
    spec2 = effective_spec(spec, pages)
    rules, found = detect_actions(R, rh, spec2, eng_spec, override, pages, templates)
    cart = any(r['kind'] == 'cart' for r in rules)
    return dict(pages={k: pages[k] for k in ('cart', 'checkout', 'success')}, spec_add=pages['spec_add'], rules=rules, found=found,
                cart_separable=cart, step='cart_add' if cart else ('action' if any(r['kind'] == 'unknown' for r in rules) else None))


def effective_spec(spec, shop):
    """Справочник заказов с опознанным: к адресам поправок и движка добавляются найденные по логу."""
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in spec.items()}
    for k, v in ((shop or {}).get('spec_add') or {}).items():
        out[k] = list(out.get(k) or []) + [x for x in v if x not in (out.get(k) or [])]
    return out


def with_text(items):
    """Записи найденного с подписью «как найдено» для человека (data/locale/<язык>/shop.json); код how остаётся латиницей."""
    from . import texts
    t = texts.file('shop').get('how_text', {})
    out = []
    for e in items:
        e = dict(e)
        tpl = t.get('pattern_confirmed' if e.get('how') == 'pattern' else e.get('how'), '')
        if tpl:
            try: e['how_text'] = tpl.format(**{k: ('' if v is None else v) for k, v in {**{'refs': '', 'lift': '', 'visits': '', 'pattern': '', 'bursts': '', 'cart_pct': '', 'base_pct': ''}, **e}.items()})
            except Exception: e['how_text'] = tpl
        out.append(e)
    return out


def trace_experiments(R, experiments, period):
    """Следственные эксперименты (edits.json → experiments): номер — число, подпись из data/locale/<язык>/experiments.json.
    Есть время и IP, и они в периоде лога — ищем след: запросы этого IP в окне ± 1 мин. След найден — уровень «подтверждён по логу», иначе — как записал Детектив (по умолчанию «браузер»).
    Возвращает список записей для выжимки (ключи латиницей)."""
    from . import texts
    tx = texts.file('experiments')
    out = []
    t0, t1 = (pd.Timestamp(period[0]), pd.Timestamp(period[1])) if period else (None, None)
    for e in experiments or []:
        typ = (e.get('ref') or {}).get('type') or 'experiment'
        n = e.get('n')
        d = dict(n=n, type=typ, label=tx.get(typ + '_label', '{n}').format(n=n), who=e.get('who', ''), when=e.get('when', ''), conclusion=e.get('conclusion', ''),
                 level=e.get('level') or 'browser', changes=e.get('changes'))
        trace = dict(searched=False, found=False)
        if e.get('ip') and e.get('time'):
            t = pd.Timestamp(e['time'])
            if t0 is not None and t0 <= t <= t1:
                sec = (t - pd.Timestamp(0)).total_seconds()
                code = R['ip'].cat.categories.get_indexer([str(e['ip'])])[0]
                m = (R['ip'].cat.codes.values == code) & (np.abs(R['ts'].values.astype(float) - sec) <= 60) if code >= 0 else np.zeros(len(R), bool)
                rows = R.loc[m, ['ts', 'method', 'base', 'query', 'status', 'bytes']].sort_values('ts').head(20)
                trace = dict(searched=True, found=bool(m.any()), requests=int(m.sum()), window_seconds=60,
                             sample=[dict(time=str(pd.to_datetime(r.ts, unit='s')), method=str(r.method), url=str(r.base) + (('?' + str(r.query)) if str(r.query) else ''), status=int(r.status), bytes=int(r.bytes))
                                     for r in rows.itertuples()])
                if m.any(): d['level'] = 'log_confirmed'
            else:
                trace['outside_period'] = True
        d['trace'] = trace
        d['level_text'] = tx.get('levels', {}).get(d['level'], d['level'])
        d['trace_text'] = tx.get('trace', {}).get('found' if trace['found'] else ('outside' if trace.get('outside_period') else ('not_found' if trace['searched'] else 'none')), '')
        out.append(d)
    return out
