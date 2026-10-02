"""NXLD: что за сайт — назначение, размер, аудитория (ТЗ, Обзор, «Что за сайт»). Только то, что видно по логу."""
import re
import numpy as np

CART = r'/(cart|basket|korzina|order|checkout|personal/order)(/|$)'
CABINET = r'^/(personal|lk|cabinet|account|profile|my|dashboard|user|users|kabinet)(/|$)'
CONTENT = r'^/(news|blog|articles?|stati|journal|media|press|novosti|poleznoe|info)(/|$)'
UGC = r'^/(forum|topic|thread|community|board|obyavleniya|ads|questions?)(/|$)'
API = r'^/(api|rest|graphql|v\d+)(/|$)|\.json$'


def _share(cats, codes, rx, weights=None):
    hit = cats.to_series().str.contains(rx, regex=True, case=False).values[codes]
    return float(hit.mean()) if len(codes) else 0.0


def detect(c, site_map):
    R, V = c.R, c.V
    st = R['status'].values
    H = V[V['group'] == 'Люди']
    pg = c.human & R['is_page'].values & (st == 200) & (R['method'].values == 'GET')
    cats, codes = R['base'].cat.categories, R['base'].cat.codes.values
    pcodes = codes[pg]
    pages = int(len(np.unique(pcodes)))
    pv = len(pcodes)
    cnt = np.bincount(pcodes, minlength=len(cats)) if pv else np.array([0])
    top3 = float(np.sort(cnt)[-3:].sum() / pv) if pv else 0.0
    home = float(cnt[cats.get_loc('/')] / pv) if pv and '/' in cats else 0.0
    vids_pg = R['vid'].values[pg]
    def visits_share(rx):
        hit = cats.to_series().str.contains(rx, regex=True, case=False).values[pcodes]
        return len(np.unique(vids_pg[hit])) / max(1, len(H))
    cart = visits_share(CART)
    cab = visits_share(CABINET)
    content = _share(cats, pcodes, CONTENT)
    ugc = _share(cats, pcodes, UGC)
    hreq = c.human & ~R['is_static'].values
    api = _share(cats, codes[hreq], API)
    cat_share = float((H['n_catalog'] > 0).mean()) if len(H) and 'n_catalog' in H else 0.0
    ct = [t for t in (site_map.get('catalog_templates') or []) if not re.match(CONTENT, str(t))]
    tp = R['tpl'].values[pg] if 'tpl' in R else np.array([])
    in_cat = np.isin(np.asarray(tp, dtype=object), ct) if len(ct) and len(tp) else np.zeros(pv, bool)
    cat_pages = len(np.unique(pcodes[in_cat])) / max(1, pages)
    conv = int(H['n_conv'].sum()) if len(H) else 0
    forms = [f for f in (site_map.get('forms') or []) if isinstance(f, dict) and str(f.get('вывод', '')).startswith('цель')]
    ch = H['channel'].value_counts(normalize=True) if len(H) else {}
    ext = float(sum(ch.get(k, 0) for k in ('Поиск', 'Реклама', 'Карты', 'Соцсети')))
    why = []
    if api >= 0.5:
        kind = 'Веб-сервис или API'; why.append(f'{api * 100:.0f}% запросов людей — к API')
    elif cab >= 0.5:
        kind = 'Закрытая платформа (кабинет)'; why.append(f'{cab * 100:.0f}% визитов — в личном кабинете')
    elif cart >= 0.005 and cart * len(H) >= 20:
        kind = 'Интернет-магазин'; why.append(f'корзина или оформление заказа в {cart * 100:.1f}% визитов')
    elif pages <= 10 or (top3 >= 0.8 and pages <= 30):
        kind = 'Лендинг'; why.append(f'{pages} страниц, на три главные приходится {top3 * 100:.0f}% просмотров')
    elif (cat_pages >= 0.3 or cat_share >= 0.2) and (conv or forms):
        kind = 'Каталог с заявками'; why.append(f'{cat_pages * 100:.0f}% страниц — карточки каталога, корзины нет, заявки через формы')
    elif content >= 0.4:
        kind = 'Контентный сайт'; why.append(f'{content * 100:.0f}% просмотров — статьи и новости')
    elif ugc >= 0.2:
        kind = 'Портал или сообщество'; why.append(f'{ugc * 100:.0f}% просмотров — форум, объявления, профили')
    else:
        kind = 'Сайт компании'; why.append('несколько разделов, заявки через формы' if (conv or forms) else 'несколько разделов, целей не найдено')
    size = 'маленький' if pages <= 50 else 'средний' if pages <= 5000 else 'большой'
    aud = 'закрытый' if cab >= 0.5 else 'смешанный' if cab >= 0.1 else 'публичный'
    if aud != 'закрытый': why.append(f'{ext * 100:.0f}% визитов людей — из поиска, рекламы, карт и соцсетей')
    if cab >= 0.1 and kind != 'Закрытая платформа (кабинет)': why.append(f'личный кабинет — {cab * 100:.0f}% визитов')
    return dict(назначение=kind, размер=size, аудитория=aud, страниц=pages, признаки=why,
                метрики=dict(главная=round(home, 3), три_главные=round(top3, 3), корзина=round(cart, 4), кабинет=round(cab, 3),
                             контент=round(content, 3), сообщество=round(ugc, 3), api=round(api, 3), каталог=round(cat_share, 3), страниц_каталога=round(cat_pages, 3), заявок=conv))
