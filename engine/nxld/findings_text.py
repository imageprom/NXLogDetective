"""NXLD: проблемы человеческим языком — тема, заголовок, факт (ТЗ, раздел 16.5).

Движок собирает черновик, который читается и без ИИ: главное — цифра в контексте, когда началось, продолжается ли.
ИИ при расследовании может улучшить формулировки через edits.json (поля «заголовок», «факт», «что_сделать»).
"""
import re
import pandas as pd

THEME = {
    'bot_leads': 'Заявки', 'operator': 'Заявки', 'lost_leads': 'Заявки',
    'ad_landing_errors': 'Реклама', 'campaign_zero': 'Реклама', 'placements_off': 'Реклама', 'placement_type_low': 'Реклама', 'placement_type_zero': 'Реклама',
    '5xx': 'Сайт', '5xx_section': 'Сайт', 'soft_errors': 'Сайт', 'broken_links': 'Сайт', 'missing_static': 'Сайт',
    'outage': 'Сервер', 'degradation': 'Сервер', 'errlog': 'Сервер', 'gaps': 'Сервер',
    'exposed': 'Безопасность', 'open_section': 'Безопасность', 'login_indexed': 'Поиск', 'pd_in_get': 'Безопасность', 'login_bruteforce': 'Безопасность', 'open_section_unknown': 'Безопасность', 'attack_500': 'Безопасность', 'webshell': 'Безопасность',
    'admin_foreign': 'Безопасность', 'open_redirect': 'Безопасность', 'fake_crawlers': 'Безопасность', 'blocked_people': 'Безопасность', 'search_blocked': 'Поиск', 'ad_checker_blocked': 'Реклама',
    'heavy_images': 'Нагрузка', 'heavy_robot': 'Нагрузка', 'trap': 'Нагрузка', 'unknown_robot': 'Нагрузка',
    'search_errors': 'Поиск', 'no_service': 'Поиск', 'ai_index': 'Поиск', 'hotlink': 'Нагрузка', 'broken_labels': 'Реклама',
}
GRADE = {'Тревога': 'Тревога', 'Срочно': 'Приоритетные', 'Важно': 'Важные', 'К сведению': 'Остальные', 'Замечание': 'Замечания'}
MON = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']


ORD = {2: 'вторая', 3: 'третья', 4: 'четвёртая', 5: 'пятая', 6: 'шестая', 7: 'седьмая', 8: 'восьмая', 9: 'девятая', 10: 'десятая'}


def pl(k, one, few_, many):
    k = abs(int(k)) % 100
    if 11 <= k <= 19: return many
    k %= 10
    return one if k == 1 else few_ if 2 <= k <= 4 else many


def nw(k, one, few_, many):
    return f'{n(k)} {many if float(k) >= 1e4 else pl(k, one, few_, many)}'


def n(x):
    x = float(x)
    if x >= 1e6: return f'{x / 1e6:.1f}'.replace('.', ',') + ' млн'
    if x >= 1e4: return f'{x / 1e3:.0f} тыс.'
    return f'{int(round(x)):,}'.replace(',', '\u00a0')


def d(s):
    t = pd.Timestamp(str(s)); return f'{t.day}.{t.month:02d}'


def dt(s):
    t = pd.Timestamp(str(s)); return f'{t.day:02d}.{t.month:02d} {t:%H:%M}'


def few(items, k=3):
    items = [str(i) for i in items if str(i)]
    return ', '.join(items[:k]) + (f' и ещё {len(items) - k}' if len(items) > k else '')


def nums(s):
    return [float(v.replace(',', '.')) for v in re.findall(r'(\d+(?:[.,]\d+)?)', str(s))]


def ftype(x):
    return x['key'].split(':')[1]


def humanize(items, sheets, summary):
    S = lambda b, k: sheets.get(b, {}).get(k, pd.DataFrame())
    sm = summary.get('Общий анализ', {})
    for x in items:
        t = ftype(x)
        obj = x['key'].split(':', 2)[2] if x['key'].count(':') >= 2 else ''
        x['тема'] = THEME.get(t, x['блок'])
        if t == '404_entry': x['тема'] = 'Реклама' if obj == 'Реклама' else 'Сайт'
        if t == 'service_err': x['тема'] = 'Реклама' if re.search(r'yandex|direct|market|google|feed|\.yml', obj, re.I) else 'Сайт'
        h, f = None, None
        try:
            if t == 'bot_leads':
                b, p = sm.get('Принято от ботов', 0), sm.get('Принято от людей', 0)
                tot = b + p
                C = S('Общий анализ', 'Конверсии')
                last = C[(C['группа'] == 'Боты') & (C['принята'] == 'да')]['время'].max() if len(C) else None
                h = 'Боты сдают заявки через формы сайта'
                f = f"Каждая {ORD.get(round(tot / b), str(round(tot / b)) + '-я') if b else '—'} принятая заявка — от бота: {b} из {tot}." + (f" Последняя бот-заявка принята {dt(last)}." if last is not None else '')
            elif t == 'operator':
                O = S('Боты', 'Операторы')
                o = O[O['оператор'].astype(str).str.startswith('Оператор')].iloc[0] if len(O) else None
                if o is not None:
                    h = 'Один оператор рассылает спам через формы'
                    f = (f"{int(o['IP_спама'])} адресов спама и {int(o['IP_разведки'])} адресов разведки связаны между собой уликами; "
                         f"отправлено {int(o['отправок'])} форм, принято {int(o['принято'])}. Адреса — домашние, мобильные сети и арендованные серверы ({str(o['сети']).split(':')[0]} и другие).")
            elif t in ('outage', 'degradation'):
                W = S('Ошибки', 'Сбои')
                w = W[W['начало'].astype(str).str.startswith(obj[:16])] if len(W) and t == 'outage' else W[W['деградация_с'].astype(str).str.startswith(obj[:16])] if len(W) else W
                if len(w):
                    w = w.iloc[0]; t0 = pd.Timestamp(w['начало'])
                    if t == 'outage':
                        h = f"Сбой {t0.day} {MON[t0.month - 1]}: сайт почти не отвечал {int(w['пик_минут'])} мин"
                        f = (f"С {pd.Timestamp(w['начало']):%H:%M} до {pd.Timestamp(w['конец']):%H:%M} страницы отдавали ошибку сервера: {int(w['страниц_с_5xx'])} страниц, "
                             f"{int(w['обрывов_499'])} посетителей не дождались ответа; сервер принимал {int(w['запросов_в_мин'])} запросов в минуту вместо обычных {int(w['обычно_запросов_в_мин'])}. "
                             f"Перебои с {pd.Timestamp(w['деградация_с']):%H:%M} до {pd.Timestamp(w['деградация_по']):%H:%M}. Причина по логам: {w['вероятная_причина'].split(';')[0]}.")
                    else:
                        mins = int(w['минут_всего'])
                        h = f"Сервер {nw(mins, 'минуту', 'минуты', 'минут')} работал с перебоями {t0.day} {MON[t0.month - 1]}"
                        why = str(w['вероятная_причина']).split(';')[0]
                        why = 'сервер не успевал ответить' if re.search(r'таймаут|не отвечает', why) else re.sub(r'\s*\(\d+\)$', '', why)
                        f = (f"С {pd.Timestamp(w['деградация_с']):%H:%M} до {pd.Timestamp(w['деградация_по']):%H:%M}: "
                             f"{nw(w['страниц_с_5xx'], 'страница отдала', 'страницы отдали', 'страниц отдали')} ошибку сервера, "
                             f"{nw(w['обрывов_499'], 'запрос оборвался', 'запроса оборвались', 'запросов оборвались')}: {why}.")
                    if x['важность'] == 'К сведению' and str(x.get('почему', '')).startswith('короткий'):
                        f += ' Сбой единичный, после него сайт работает: возможно, перезагрузка или плановые работы — уточнить у хостинга.'
            elif t == '5xx_section':
                T5 = S('Ошибки', '5xx по шаблонам'); g = T5[T5['шаблон'].astype(str).str.startswith(obj)] if len(T5) else T5
                ch = S('Ошибки', 'Изменения статусов'); ch = ch[ch['шаблон'].astype(str).str.startswith(obj) & (ch['стало'].astype(str) == '404')] if len(ch) else ch
                v = nums(x['факты'])
                h = f"Раздел {obj} отдаёт ошибку сервера"
                f = (f"{len(g) or ''} страниц раздела {obj} отдавали людям ошибку сервера с {d(g['первый_день'].min())} по {d(g['последний_день'].max())}: "
                     f"{n(v[0])} ошибок в {n(v[1])} визитах." if len(g) else x['факты'])
                if len(ch): f += f" С {d(ch['день'].min())} эти адреса отвечают «не найдено»."
                f += f" Например: {few(g['пример'].astype(str).tolist(), 2)}." if len(g) else ''
            elif t == '5xx':
                T5 = S('Ошибки', '5xx по шаблонам'); g = T5[T5['шаблон'].astype(str) == obj] if len(T5) else T5
                if len(g):
                    r = g.iloc[0]
                    h = f"Страница {obj} отдаёт ошибку сервера"
                    f = (f"{nw(r['у_людей'], 'ошибка', 'ошибки', 'ошибок')} у {nw(r['людей_задето'], 'посетителя', 'посетителей', 'посетителей')}, {int(r['дней_с_ошибкой'])} дн. из периода ({d(r['первый_день'])}–{d(r['последний_день'])})"
                         + (f"; успешно страница открылась всего {nw(r['успешных_ответов'], 'раз', 'раза', 'раз')}." if r['успешных_ответов'] < r['ошибок'] / 10 else '.'))
            elif t == '404_entry':
                v = nums(x['факты'])
                adr = re.search(r'адреса: (.*)$', x['факты'])
                h = f"Входы на несуществующие страницы: {obj.lower()}"
                f = f"{n(v[0])} визитов из канала «{obj}» пришли на адреса, которых нет: {few(adr.group(1).split(', ') if adr else [], 3)}."
                if any(not a.endswith('/') for a in (adr.group(1).split(', ') if adr else [])):
                    f += ' Часть адресов — без «/» в конце, а с «/» страницы работают.'
            elif t == 'ad_landing_errors':
                v = [(k, int(c_)) for k, c_ in re.findall(r'(\d{3}): (\d+)', x['факты'])]
                five = [(k, c_) for k, c_ in v if k.startswith('5')]
                parts = [f"{c_} — {k}" + (', человек не дождался ответа' if k == '499' else '') for k, c_ in v if not k.startswith('5')]
                if five: parts.append(f"{sum(c_ for _, c_ in five)} — {'/'.join(sorted(k for k, _ in five))}")
                h = 'Клики по рекламе ведут на страницы с ошибкой'
                f = f"{n(x['главная_цифра'])} рекламных кликов не открыли страницу: " + '; '.join(parts) + '.'
            elif t == 'service_err':
                v = re.findall(r'(\d{3}): (\d+)', x['факты']); who = re.search(r'кто запрашивает: ([^:;]+)', x['факты'])
                h = f"Фид {obj} не отдаётся" if re.search(r'\.(xml|yml|csv)$', obj) else f"{obj} отдаёт ошибку"
                f = f"{obj} отвечает ошибкой ({', '.join(f'{k} — {c_}' for k, c_ in v)} из {n(nums(x['факты'])[0])} запросов)" + (f"; его запрашивает {who.group(1).strip()}." if who else '.')
            elif t == 'broken_links':
                top = re.search(r'Главные: (.*)$', x['факты'])
                h = 'Битые ссылки внутри сайта'
                f = f"{n(x['главная_цифра'])} визитов людей упёрлись в «не найдено», перейдя по ссылке на сайте. Чаще всего: {few(top.group(1).split(', ') if top else [], 3)}."
            elif t == 'missing_static':
                M = S('Ошибки', 'Отсутствующие ресурсы')
                h = 'Страницы запрашивают файлы, которых нет на сервере'
                if len(M):
                    fl = set(x.get('файлы') or [])
                    M = M[M['файл'].astype(str).isin(fl)] if fl else M
                    g = M.groupby('группа').agg(визитов=('визитов', 'max'), пример=('файл', 'first')).sort_values('визитов', ascending=False)
                    hv = sm.get('Визитов людей') or 0
                    f = 'Файлы не найдены (404): ' + '; '.join(f"{r['пример']} — {nw(r['визитов'], 'визит', 'визита', 'визитов')}" + (f" ({r['визитов'] / hv * 100:.0f}% визитов людей)" if hv and r['визитов'] / hv >= 0.01 else '') for _, r in g.head(3).iterrows()) + '.'
                    if str(x.get('почему', '')).startswith('файл-заглушка'):
                        h = f"Не найден файл-заглушка {obj}"
                        f += ' Это заглушка для подгружаемых картинок: человек её, скорее всего, не видит, но страницы делают лишний запрос.'
            elif t == 'blocked_people':
                h = 'Серверный фильтр отказывает людям'
                f = f"Люди, которые смотрели сайт, {nw(x['главная_цифра'], 'раз', 'раза', 'раз')} получили отказ в доступе: {x['факты'].split(' отказов ', 1)[-1]}."
            elif t in ('search_blocked', 'ad_checker_blocked'):
                h = x['что_происходит']
                f = 'Отказы в доступе: ' + x['факты'].rstrip('.') + '.'
            elif t == 'errlog':
                v = nums(x['факты']); per = re.findall(r'(\d{4}-\d\d-\d\d)', x['факты'])
                h = f"Ошибки в error-логе: {obj}"
                f = f"{n(v[0])} сообщений «{obj}»" + (f" с {d(per[0])} по {d(per[1])}" if len(per) >= 2 else '') + '.'
            elif t == 'attack_500':
                A = S('Нагрузка и безопасность', 'Атаки в параметрах'); A = A[A['status'] >= 500] if len(A) else A
                parts = []
                for kind, g in (A.assign(вид=A['пример'].map(attack_kind)).groupby('вид') if len(A) else []):
                    prm = attack_param(str(g.iloc[0]['пример']))
                    who = g.iloc[0]['адрес'] if g['IP'].sum() == 1 and 'адрес' in g else nw(g['IP'].sum(), 'адреса', 'адресов', 'адресов')
                    codes = '/'.join(sorted(set(str(int(c_)) for c_ in g['status'])))
                    parts.append(f"{kind}" + (f" в параметре {prm}" if prm else '') + f": {nw(g['запросов'].sum(), 'запрос', 'запроса', 'запросов')} с {who}, ответ {codes}")
                kinds = sorted(set(attack_kind(q) for q in A['пример'])) if len(A) else []
                h = (f"{kinds[0]} вызывает ошибку сервера" if len(kinds) == 1 else 'Атаки через параметры вызывают ошибку сервера')
                f = '; '.join(parts) + '.' if parts else x['факты']
            elif t == 'login_indexed':
                v = nums(x['факты'])
                h = f"Страница входа {obj} видна поисковикам"
                f = f"Поисковые роботы открывали форму входа {nw(v[0], 'раз', 'раза', 'раз')}; к ней обращались {nw(v[1], 'посторонний адрес', 'посторонних адреса', 'посторонних адресов')}."
            elif t == 'open_section':
                v = re.match(r'(\d+) ответов 200 для (\d+) адресов', x['факты']); pages = re.search(r'страницы: (.*)$', x['факты'])
                h = f"Страницы раздела {obj} отдаются без входа"
                who = re.search(r'кто: ([^;]+);', x['факты'])
                f = (f"{nw(int(v.group(1)), 'ответ', 'ответа', 'ответов')} 200 получили {nw(int(v.group(2)), 'адрес', 'адреса', 'адресов')}, которые в разделе не входили"
                     + (f" ({who.group(1)})" if who else '') + (f". Страницы: {pages.group(1)}." if pages else '.'))
            elif t == 'search_errors' and obj == 'templates':
                g = re.findall(r'(\S+) (/\S*) — (\d+) из (\d+) \(([^)]*)\)', x['факты'])
                h = 'Поисковые роботы получают ошибки в отдельных разделах'
                f = 'Ошибки у роботов: ' + '; '.join(f"{rb} на {tp} — {e} из {q} запросов ({cd})" for rb, tp, e, q, cd in g[:4]) + '.'
            elif t == 'no_service':
                who = re.search(r'запрашивают: (.*)$', x['факты'])
                h = f"На сайте нет {obj}"
                f = f"{obj} отвечает 404: {nw(nums(x['факты'])[0], 'запрос', 'запроса', 'запросов')} за период" + (f", его ищут {who.group(1)}." if who else '.')
            elif t == 'ai_index':
                who = re.search(r'запрашивают: (.*)$', x['факты'])
                h = 'Нет файлов для ИИ-поиска'
                f = 'Файлы-описания сайта для ИИ-поиска не найдены (404): ' + re.sub(r' — (\d+) запросов', lambda m: f" — {nw(int(m.group(1)), 'запрос', 'запроса', 'запросов')}", x['факты'].split('; запрашивают')[0]).replace(';', ',') \
                    + ('; запрашивают ' + re.sub(r': (\d+)', r' (\1)', who.group(1)) + '.' if who else '.') + ' По желанию; практической пользы для большинства сайтов нет.'
            elif t == 'hotlink':
                h = 'Внешние сайты показывают картинки сайта'
                f = x['факты'].replace('; тестовые копии:', '. Похоже на тестовую копию сайта:') + '.'
            elif t == 'broken_labels':
                h = 'Рекламные метки сломаны'
                f = x['факты'].replace('Макрос не подставился ({...} в адресе)', 'макросы Директа не подставились').replace('yclid без UTM-меток', 'метка yclid без UTM') + '. Эти клики теряют кампанию и объявление в статистике.'
                f = f[0].upper() + f[1:]
            elif t == 'pd_in_get':
                v = re.match(r'(\d+) запросов с (\d+) адресов; адреса: (.*)$', x['факты'])
                h = 'Телефоны и почты уходят в адресе страницы'
                f = (f"{nw(int(v.group(1)), 'отправка', 'отправки', 'отправок')} с {nw(int(v.group(2)), 'адреса', 'адресов', 'адресов')} передали персональные данные прямо в адресе (GET): {v.group(3)}. "
                     'Такие данные оседают в логах сервера, аналитике и истории браузера.') if v else x['факты']
            elif t == 'exposed':
                h = 'Служебные файлы отданы посторонним'; f = x['факты']
            elif t == 'fake_crawlers':
                rep = re.search(r'Представлялись: ([^;]+)', x['факты'])
                h = 'Сканеры притворяются поисковыми роботами'
                f = f"Поисковыми роботами представлялись адреса не из их сетей — {nw(x['главная_цифра'], 'адрес', 'адреса', 'адресов')}" + (f" ({rep.group(1)})." if rep else '.')
            elif t == 'heavy_images':
                v = nums(x['факты'])
                h = 'Тяжёлые картинки съедают трафик'
                f = f"{nw(nums(x['что_происходит'])[0], 'картинка', 'картинки', 'картинок')} тяжелее 500 КБ — вместе {n(x['главная_цифра'])} ГБ трафика; самая тяжёлая — {int(v[-1])} КБ."
            elif t == 'heavy_robot':
                v = nums(x['факты'])
                h = f"Робот {obj} создаёт заметную нагрузку"
                f = f"{n(v[0])} запросов и {n(v[1] / 1024)} ГБ трафика за период."
            elif t == 'trap':
                g = re.findall(r'(/[^\s—]+) — (\d+) вариантов', x['факты'])
                h = 'Роботы застревают в фильтрах каталога'
                f = 'Роботы перебирают тысячи вариантов параметров: ' + '; '.join(f"{a} — {n(c_)}" for a, c_ in g[:3]) + '.' if g else x['факты']
            elif t == 'unknown_robot':
                g = re.findall(r'Неопознанный робот или мониторинг: ([^—]+?) — на усмотрение оптимизатора — (\d+) запросов', x['факты'])
                h = 'Неопознанные роботы и мониторинги'
                f = ('Не опознаны: ' + '; '.join(f"{a.strip()} — {n(c_)} запросов" for a, c_ in g) + '. Решение — на усмотрение оптимизатора.') if g else x['факты']
            elif t == 'placements_off':
                top = re.search(r'крупнейшие: (.*)$', x['факты'])
                h = 'Рекламные площадки без единой заявки'
                f = f"{nw(nums(x['что_происходит'])[0], 'площадка', 'площадки', 'площадок')} — {n(x['главная_цифра'])} визитов и ни одной заявки. Крупнейшие: {few(top.group(1).split(', ') if top else [], 4)}."
            elif t == 'placement_type_low':
                g = re.findall(r'/ (.+?): конверсия в (\d+) раз ниже, чем у поиска — (\d+) визитов, (\d+) заяв', x['факты'])
                h = 'РСЯ приводит людей, но почти не даёт заявок'
                f = '; '.join(f"{a.strip()}: {n(v_)} визитов и {nw(z, 'заявка', 'заявки', 'заявок')} — в {k} раз хуже поиска" for a, k, v_, z in g) + '.' if g else x['факты']
            elif t == 'campaign_zero':
                g = re.findall(r'Кампания (\d+)\.([^:]+): (\d+) визитов', x['факты'])
                h = 'Кампании с заметным трафиком и без заявок'
                f = (f"{len(g)} кампаний дали {n(sum(int(v_) for _, _, v_ in g))} визитов и ни одной заявки: " + '; '.join(f"{i} {nm} — {n(v_)}" for i, nm, v_ in g[:3]) + (f" и ещё {len(g) - 3}" if len(g) > 3 else '') + '.') if g else x['факты']
        except Exception:
            h, f = None, None
        if re.search(r':(группа|мелочи)$', x['key']) and t == '5xx':
            vs = re.findall(r'— (\d+) ошибок у людей', x['факты'])
            T5 = S('Ошибки', '5xx по шаблонам'); T5 = T5[T5['у_людей'] < 20].sort_values('у_людей', ascending=False) if len(T5) else T5
            h = f"Ещё {nw(len(vs), 'страница изредка отдаёт', 'страницы изредка отдают', 'страниц изредка отдают')} ошибку сервера" if vs else 'Редкие ошибки сервера на отдельных страницах'
            f = (f"На каждой от {min(map(int, vs))} до {nw(max(map(int, vs)), 'ошибки', 'ошибок', 'ошибок')} за период"
                 + (f", чаще всего на {T5.iloc[0]['пример']}" if len(T5) else '') + '. Это единичные случаи, а не поломка раздела.') if vs else x['факты']
        if re.search(r':(группа|мелочи)$', x['key']) and t == '404_entry':
            g = re.findall(r'страницы: ([^—]+) — (\d+) визитов', x['факты'])
            E = S('Ошибки', '404: входы извне'); E = E[E['канал'].isin([a.strip() for a, _ in g])].sort_values('визитов', ascending=False) if len(E) else E
            chs = [a.strip() for a, _ in g]
            h = ('Люди изредка приходят' if x['важность'] == 'К сведению' else 'Люди приходят') + ' на несуществующие страницы' + (f" из {' и '.join({'Карты': 'Карт', 'Поиск': 'Поиска'}.get(c_, c_) for c_ in chs)}" if chs else '')
            tot = sum(int(c_) for _, c_ in g)
            f = (f"За период {nw(tot, 'такой вход', 'таких входа', 'таких входов')}"
                 + (f", больше всего на {E.iloc[0]['адрес']} ({nw(E.iloc[0]['визитов'], 'переход', 'перехода', 'переходов')})" if len(E) else '')
                 + '. Скорее всего, старые адреса остались в выдаче или в карточке организации.') if g else x['факты']
        x['заголовок'] = h or clean(x['что_происходит'])
        x['факт'] = f or clean(x['факты'])
    return items


def clean(s):
    """Запасной вариант: даты по-человечески, длинные перечни короче."""
    s = re.sub(r'(\d{4})-(\d\d)-(\d\d) (\d\d:\d\d)(:\d\d)?', lambda m: f'{m.group(3)}.{m.group(2)} {m.group(4)}', str(s))
    s = re.sub(r'(\d{4})-(\d\d)-(\d\d)', lambda m: f'{m.group(3)}.{m.group(2)}', s)
    s = s.replace('5xx', 'ошибка сервера')
    return s[:400] + ('…' if len(s) > 400 else '')


def attack_kind(q):
    q = str(q)
    from urllib.parse import unquote
    u = unquote(unquote(q)).lower()
    if re.search(r"union\s+select|select\s.+from|\b(and|or)\s+\d+=\d+|sleep\(|benchmark\(|'--|information_schema", u): return 'SQL-инъекция'
    if re.search(r'<script|onerror=|onload=|javascript:|<svg', u): return 'XSS'
    if re.search(r'\.\./|etc/passwd|win\.ini', u): return 'Обход каталогов'
    if re.search(r'\$\{jndi', u): return 'Log4Shell'
    if re.search(r'\{\{|\$\{', u): return 'Инъекция шаблона'
    return 'Атака'


def attack_param(q):
    from urllib.parse import unquote
    for part in str(q).split('&'):
        k, _, v = part.partition('=')
        if v and attack_kind(v) != 'Атака': return unquote(k)
    return ''


# ---- чистовая правка текстов карточек: согласование числа и слова, десятичная запятая ----
FORMS = {'адресов': ('адрес', 'адреса'), 'запросов': ('запрос', 'запроса'), 'страниц': ('страница', 'страницы'), 'файлов': ('файл', 'файла'),
         'визитов': ('визит', 'визита'), 'сообщений': ('сообщение', 'сообщения'), 'ответов': ('ответ', 'ответа'), 'отправок': ('отправка', 'отправки'),
         'заявок': ('заявка', 'заявки'), 'роботов': ('робот', 'робота'), 'ботов': ('бот', 'бота'), 'дней': ('день', 'дня'),
         'посетителей': ('посетитель', 'посетителя'), 'кликов': ('клик', 'клика'), 'обрывов': ('обрыв', 'обрыва'), 'входов': ('вход', 'входа')}
GEN_PREP = r'с|со|из|до|от|для|около|более|больше|меньше|свыше|менее|без|кроме'
_NUM_WORD = re.compile(r'(?:\b(' + GEN_PREP + r') )?(?<![\d., ])(\d{1,3}(?: \d{3})+|\d+) (' + '|'.join(FORMS) + r')\b')
_DEC = re.compile(r'(?<![\d.])(\d+)\.(\d+)(\s?(?:%|МБ|ГБ|КБ|ТБ))')


def _agree(m):
    prep, num, word = m.group(1), m.group(2), m.group(3)
    k = int(num.replace(' ', ''))
    one, few_ = FORMS[word]
    if prep:   # после «с, из, до…» — родительный: 1 → «адреса», остальное — «адресов»
        form = few_ if k % 10 == 1 and k % 100 != 11 else word
    else:
        form = pl(k, one, few_, word)
    return (prep + ' ' if prep else '') + num + ' ' + form


def tidy(s):
    """«1501 адресов» → «1501 адрес», «0.7%» → «0,7%». Только текст карточек; числа в таблицах не трогаются."""
    if not isinstance(s, str) or not s: return s
    return _DEC.sub(r'\1,\2\3', _NUM_WORD.sub(_agree, s))


def tidy_items(items, fields=('что_происходит', 'факты', 'что_сделать', 'где_править', 'обстоятельства', 'заголовок')):
    for x in items:
        for f in fields:
            if f in x: x[f] = tidy(x[f])
    return items
