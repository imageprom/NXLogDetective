"""NXLD: полнота проверки (ТЗ, «Полнота проверки»).

Реестр — что ищем (по ТЗ, не по одному сайту) и где. Для каждого типа — состояние:
найдено / проверено, не найдено / не применимо / детектора пока нет.
Сигналы без проблемы — признак проблемы на листе есть, а карточки нет: решает Детектив.
"""
import re
import pandas as pd


def _sh(res, b, k):
    return res.get('sheets', {}).get(b, {}).get(k, pd.DataFrame())


def _has_ads(res):
    return len(_sh(res, 'Маркетинг', 'Реклама: Кампании')) > 0 or len(_sh(res, 'Маркетинг', 'Реклама: посадочные')) > 0


def _has_forms(res):
    return len(_sh(res, 'Общий анализ', 'Конверсии')) > 0


def _has_errlog(res):
    return len(_sh(res, 'Ошибки', 'Error-лог')) > 0


# сигналы на листах: функция возвращает короткое описание или ''
def sig_hotlink(res):
    h = _sh(res, 'Нагрузка и безопасность', 'Хотлинк')
    h = h[h['байт'] >= 50 * 1024 ** 2] if len(h) else h
    return f"{len(h)} сайтов забрали больше 50 МБ картинками" if len(h) else ''


def sig_labels(res):
    m = _sh(res, 'Маркетинг', 'Метки: проблемы')
    return '; '.join(f"{r['проблема']} — {r['кликов']}" for _, r in m.iterrows()) if len(m) else ''


def sig_search(res):
    f = _sh(res, 'Ошибки', 'Ошибки у поисковиков')
    f = f[(f['запросов'] >= 30) & (f['ошибок'] >= 20) & (f['ошибок'] / f['запросов'] >= 0.3)] if len(f) else f
    return f"{len(f)} шаблонов, где у робота больше 30% ошибок" if len(f) else ''


def sig_flood(res):
    f = _sh(res, 'Нагрузка и безопасность', 'Флуд')
    f = f[f['запросов_в_минуту'] >= 1000] if len(f) else f
    return f"{f['ip'].nunique()} адресов давали больше 1000 запросов в минуту" if len(f) else ''


def sig_soft404(res):
    f = _sh(res, 'Ошибки', 'Одинаковые ответы')
    f = f[f['разных_адресов'] >= 500] if len(f) else f
    return f"одинаковый ответ {int(f.iloc[0]['размер_байт'])} байт на {int(f.iloc[0]['разных_адресов'])} разных адресах" if len(f) else ''


def sig_errlog(res):
    e = _sh(res, 'Ошибки', 'Error-лог')
    if not len(e): return ''
    e = e[~e['тип'].astype(str).str.contains(r'норма|Запрещено правилом|таймаут|PHP Fatal', regex=True)]
    return ', '.join(f"{r['тип']} — {r['сообщений']}" for _, r in e.head(4).iterrows())


def sig_status_change(res):
    c = _sh(res, 'Ошибки', 'Изменения статусов')
    c = c[(c['было'] == 'OK') & (c['стало'].isin(['5xx', '404']))] if len(c) else c
    c = c[~c['шаблон'].astype(str).str.match(r'^/\.')] if len(c) else c
    return f"{len(c)} шаблонов перешли из рабочих в ошибку" if len(c) else ''


def sig_tokens(res):
    t = _sh(res, 'Нагрузка и безопасность', 'Токены в адресах')
    t = t[~t['параметр'].astype(str).str.lower().eq('sessid')] if len(t) else t
    t = t[t['запросов'] >= 20] if len(t) else t
    return f"{len(t)} адресов с токеном или паролем в параметрах" if len(t) else ''


def sig_ad_bots(res):
    v = res.get('summary', {}).get('Маркетинг', {}).get('Доля ботов в рекламном трафике, %')
    return f"боты — {v}% рекламного трафика" if v and v >= 10 else ''


def sig_cache(res):
    v = res.get('summary', {}).get('Нагрузка и безопасность', {}).get('Доля 304 у статики (кэш), %')
    return f"повторные запросы статики почти не кэшируются: 304 — {v}%" if v is not None and v < 1 else ''


def sig_filter_people(res):
    t = _sh(res, 'Нагрузка и безопасность', 'Серверный фильтр')
    if t is None or not len(t): return ''
    k = int(t.loc[t['группа'] == 'Люди', 'ответов'].sum())
    return f"людям — {k} отказов серверного фильтра" if k else ''


# реестр: тип · что ищем · блок · применимость · сигнал (тип '' — сигнал без детектора)
REGISTRY = [
    ('outage', 'Сбои: сайт не отвечал', 'Ошибки', None, None),
    ('degradation', 'Перебои: рост ошибок или провал трафика', 'Ошибки', None, None),
    ('gaps', 'Пропуски в логе', 'Общий анализ', None, None),
    ('5xx', 'Страницы отдают ошибку сервера', 'Ошибки', None, None),
    ('5xx_section', 'Раздел отдаёт ошибку сервера', 'Ошибки', None, None),
    ('404_entry', 'Входы извне на несуществующие страницы', 'Ошибки', None, None),
    ('broken_links', 'Битые ссылки внутри сайта', 'Ошибки', None, None),
    ('missing_static', 'Отсутствующие файлы оформления', 'Ошибки', None, None),
    ('no_service', 'Нет robots.txt или sitemap.xml', 'Ошибки', None, None),
    ('ai_index', 'Нет файлов для ИИ-поиска (llms.txt)', 'Ошибки', None, None),
    ('service_err', 'Фид или служебный файл отдаёт ошибку', 'Ошибки', None, None),
    ('search_errors', 'Поисковые роботы получают ошибки', 'Ошибки', None, sig_search),
    ('errlog', 'Ошибки в error-логе', 'Ошибки', _has_errlog, sig_errlog),
    ('blocked_people', 'Защита отказывает людям', 'Нагрузка и безопасность', None, sig_filter_people),
    ('search_blocked', 'Серверный фильтр отказывает поисковым роботам', 'Нагрузка и безопасность', None, None),
    ('ad_checker_blocked', 'Серверный фильтр отказывает роботу проверки объявлений', 'Нагрузка и безопасность', None, None),
    ('attack_500', 'Атака в параметрах вызывает ошибку сервера', 'Нагрузка и безопасность', None, None),
    ('exposed', 'Служебные файлы и бэкапы отданы посторонним', 'Нагрузка и безопасность', None, None),
    ('webshell', 'Признаки веб-шелла', 'Нагрузка и безопасность', None, None),
    ('admin_foreign', 'Вход в админку из нетипичной сети', 'Нагрузка и безопасность', None, None),
    ('open_section', 'Служебный раздел отдаётся без входа', 'Нагрузка и безопасность', None, None),
    ('login_bruteforce', 'Подбор пароля к форме входа', 'Нагрузка и безопасность', None, None),
    ('login_indexed', 'Форма входа видна поисковикам', 'Нагрузка и безопасность', None, None),
    ('pd_in_get', 'Персональные данные в адресах (GET)', 'Нагрузка и безопасность', None, None),
    ('heavy_images', 'Тяжёлые картинки', 'Нагрузка и безопасность', None, None),
    ('heavy_robot', 'Робот создаёт заметную нагрузку', 'Нагрузка и безопасность', None, None),
    ('trap', 'Ловушки для роботов в фильтрах', 'Нагрузка и безопасность', None, None),
    ('hotlink', 'Хотлинк: чужие сайты берут картинки', 'Нагрузка и безопасность', None, sig_hotlink),
    ('bot_leads', 'Боты сдают заявки', 'Общий анализ', _has_forms, None),
    ('operator', 'Оператор спама форм', 'Боты', _has_forms, None),
    ('fake_crawlers', 'Подделки поисковых роботов', 'Боты', None, sig_flood),
    ('unknown_robot', 'Неопознанные роботы и мониторинги', 'Боты', None, None),
    ('ad_landing_errors', 'Реклама ведёт на ошибки', 'Маркетинг', _has_ads, None),
    ('campaign_zero', 'Кампании без заявок', 'Маркетинг', _has_ads, None),
    ('placements_off', 'Площадки без заявок', 'Маркетинг', _has_ads, None),
    ('placement_type_low', 'Типы площадок с низкой конверсией', 'Маркетинг', _has_ads, None),
    ('broken_labels', 'Сломанные рекламные метки', 'Маркетинг', _has_ads, sig_labels),
    # детектора пока нет — только сигнал на листе
    ('', 'Мягкие 404 (одинаковый ответ на разных адресах)', 'Ошибки', None, sig_soft404),
    ('', 'Выкладка сломала шаблоны (смена статусов)', 'Ошибки', None, sig_status_change),
    ('', 'Токены и пароли в адресах', 'Нагрузка и безопасность', None, sig_tokens),
    ('', 'Боты в рекламном трафике', 'Маркетинг', _has_ads, sig_ad_bots),
    ('', 'Не работает кэш статики', 'Нагрузка и безопасность', None, sig_cache),
    ('', 'Медленные страницы (нужно время ответа в логе)', 'Ошибки', None, None),
    ('', 'Цепочки переадресаций', 'Ошибки', None, None),
    ('', 'Закончилось место на диске', 'Ошибки', _has_errlog, None),
    ('', 'Роботы игнорируют robots.txt', 'Боты', None, None),
]


def check(res, items):
    """Возвращает (таблица покрытия, сигналы без проблемы)."""
    found = {}
    for x in items:
        found.setdefault(x['key'].split(':')[1], []).append(x)
    blocks = set(res.get('selected') or res.get('sheets', {}).keys())
    rows, loose = [], []
    for t, what, block, appl, sig in REGISTRY:
        if block not in blocks:
            state = 'блок не выбран'
        elif appl is not None and not appl(res):
            state = 'не применимо'
        elif not t:
            state = 'детектора пока нет'
        elif t in found:
            state = 'найдено'
        else:
            state = 'проверено, не найдено'
        s = ''
        if sig is not None and state not in ('блок не выбран', 'не применимо'):
            try: s = sig(res)
            except Exception: s = ''
        if s and state != 'найдено':
            loose.append(dict(проверка=what, блок=block, сигнал=s))
        rows.append(dict(проверка=what, блок=block, тип=t, состояние=state, проблем=len(found.get(t, [])), сигнал=s))
    known = {t for t, *_ in REGISTRY if t}
    for t in sorted(set(found) - known):
        rows.append(dict(проверка=f'(нет в реестре) {t}', блок=found[t][0]['блок'], тип=t, состояние='найдено', проблем=len(found[t]), сигнал=''))
    return pd.DataFrame(rows), loose
