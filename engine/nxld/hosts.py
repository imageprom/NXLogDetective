"""NXLD: тип хоста — сайт или не сайт (#23). Считается один раз в prepare по запросам к хосту и хранится в данных:
колонка R['host_site'] (True — сайт), таблица хостов site_map['hosts'], V['host_site'] — у визитов (визит не смешивает хосты разных типов).

Сайт — основной домен, www., поддомены основного домена, которые отдают страницы (региональные, вход для B2B; страницы с ответом 2xx считаются от всех, а не только от людей).
Не сайт — IP вместо имени, другие домены (копии, dev-версии), поддомены почти без страниц (имена, которые подбирают сканеры).
Запросы к «не сайту» не входят в «Люди», заявки и заказы, ошибки (02), маркетинг (05), SEO (06), страницы, разделы и файлы (01);
входят в нагрузку и безопасность (03) и ботов (04): нагрузка и атаки на сервер настоящие."""
import re

import numpy as np
import pandas as pd

from .thresholds import value

IP_RX = re.compile(r'^(?:\d{1,3}\.){3}\d{1,3}$')


def is_ip(h):
    h = str(h)
    return bool(IP_RX.match(h)) or (h.count(':') >= 2 and re.fullmatch(r'[0-9a-f:.]+', h) is not None)


def normalize(h):
    """Имя хоста: строчные буквы, без порта и без ведущего www."""
    h = str(h or '').strip().lower()
    if h == '-': return ''   # пустой запрос: имя хоста не записано
    if h.count(':') == 1: h = h.split(':')[0]
    return re.sub(r'^www\.', '', h)


def names_only(hosts):
    """Домены сайта без IP-адресов."""
    out = []
    for h in hosts or []:
        n = normalize(h)
        if n and not is_ip(n) and n not in out: out.append(n)
    return out


def classify(R, site_hosts, not_site=(), pages_min=None):
    """(маска «сайт» по запросам, таблица хостов, маска «копии»). Маски — numpy bool по строкам R; без имён хостов в логе все запросы считаются сайтом.
    Копии — хосты с причиной «другой домен» (копии сайта у разработчика, технические имена хостинга): к сайту клиента не относятся, их запросы вне всех блоков отчёта.
    IP сервера и подобранные поддомены основного домена — не копии: они идут по общему правилу хостов вне сайта."""
    pages_min = value('host_site_pages_min', 10) if pages_min is None else pages_min
    n = len(R)
    if 'vhost' not in R or n == 0: return np.ones(n, bool), [], np.zeros(n, bool)
    cats = [str(c) for c in R['vhost'].cat.categories]
    codes = R['vhost'].cat.codes.values
    if not any(normalize(c) for c in cats): return np.ones(n, bool), [], np.zeros(n, bool)   # формат лога без имени хоста
    ncat = len(cats)
    ok_page = (R['method'].values == 'GET') & ~R['is_static'].values & (R['status'].values >= 200) & (R['status'].values < 300)   # страницы с ответом 2xx — от всех: региональные поддомены обходят и одни поисковики
    sel = codes >= 0
    req = np.bincount(codes[sel], minlength=ncat)
    pages = np.bincount(codes[sel & ok_page], minlength=ncat)
    by_name = {}
    for i, c in enumerate(cats):
        d = by_name.setdefault(normalize(c), dict(запросов=0, страниц=0, cats=[]))
        d['запросов'] += int(req[i]); d['страниц'] += int(pages[i]); d['cats'].append(i)
    sites = set(names_only(site_hosts))
    off = {normalize(h) for h in not_site or []}
    if not sites:   # имён сайта нет (лог без имени файла и рефереров): сайт — хост, который чаще всех отдаёт страницы людям
        named = {k: v for k, v in by_name.items() if k and not is_ip(k) and k not in off}
        if named: sites = {max(named, key=lambda k: (named[k]['страниц'], named[k]['запросов']))}
    kind = {}
    for name, d in by_name.items():
        if name == '': t, why = 'сайт', 'имя хоста не записано'
        elif name in off: t, why = 'не сайт', 'поправка карты (not_site_hosts)'
        elif is_ip(name): t, why = 'не сайт', 'IP вместо имени'
        elif name in sites: t, why = 'сайт', 'основной домен'
        elif any(name.endswith('.' + s) for s in sites):
            if d['страниц'] >= pages_min: t, why = 'сайт', 'поддомен отдаёт страницы'
            else: t, why = 'не сайт', 'поддомен без страниц (имя подобрано сканером)'
        else: t, why = 'не сайт', 'другой домен'
        kind[name] = (t, why)
    is_site_cat = np.ones(ncat, bool)
    for name, d in by_name.items():
        for i in d['cats']: is_site_cat[i] = kind[name][0] == 'сайт'
    mask = np.where(sel, is_site_cat[np.where(sel, codes, 0)], True)
    copy_cat = np.zeros(ncat, bool)
    for name, d in by_name.items():
        for i in d['cats']: copy_cat[i] = kind[name] == ('не сайт', 'другой домен')
    copy = np.where(sel, copy_cat[np.where(sel, codes, 0)], False)
    table = sorted([dict(хост=name or '(не записан)', тип=kind[name][0], причина=kind[name][1], запросов=d['запросов'], страниц=d['страниц']) for name, d in by_name.items()],
                   key=lambda r: (r['тип'] != 'сайт', -r['запросов']))
    return mask, table, copy


def summary(table):
    """Сколько запросов и к каким хостам исключено из сайта: для журнала запуска и выжимки."""
    off = [r for r in table if r['тип'] != 'сайт']
    return dict(хостов=len(off), запросов=int(sum(r['запросов'] for r in off)), хосты=[dict(хост=r['хост'], запросов=r['запросов'], причина=r['причина']) for r in off[:20]])
