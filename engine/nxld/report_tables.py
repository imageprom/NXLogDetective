"""NXLD: простые листы-таблицы в общем стиле (заголовок, пояснение, оранжевая шапка, фильтр, закреплённая шапка)."""
import numbers
import pandas as pd
from openpyxl.styles import Font, Alignment, Border, PatternFill, Side
from .report_index import ORANGE, ORANGE2, INK, GREY, F_NOTE, NUM_FMT, RED

SEP = Side(style='thin', color='D9D9D9')
WHITE = Side(style='thin', color='FFFFFF')


def data_sheet(wb, name, df, title, note='', widths=None, wrap=(), fill_rule=None, bold_rule=None, center=(), sort_by=None, kpi=None, kpi_col=None, links=(), size=9, row_rule=None, red=('Ошибки',)):
    """Пересобирает лист name: строка 1 — заголовок, 2 — пояснение, 4 — шапка, дальше данные.
    widths — ширины колонок; wrap — колонки с переносом; fill_rule(col, value) → цвет заливки или None."""
    idx = wb.sheetnames.index(name) if name in wb.sheetnames else len(wb.sheetnames)
    if name in wb.sheetnames: del wb[name]
    ws = wb.create_sheet(name, idx)
    ws.sheet_view.showGridLines = True
    cols = list(df.columns)
    ws.column_dimensions['A'].width = 2.5          # поле слева, как на остальных листах
    ws['B1'] = title.upper(); ws['B1'].font = Font(name='Montserrat', size=16, bold=True, color=ORANGE)
    ws.row_dimensions[1].height = 34
    if note:   # подзаголовок — фирменным Comfortaa, как на обзоре
        ws['B2'] = note; ws['B2'].font = Font(name='Comfortaa', size=11, bold=True, color=GREY)
        ws['B2'].alignment = Alignment(vertical='center', wrap_text=False)
    ws.row_dimensions[2].height = 24
    X = 1   # сдвиг колонок
    if kpi:   # цифры сводки — справа от заголовка: подпись мелко, число крупно
        c0 = (cols.index(kpi_col) if kpi_col in cols else max(0, len(cols) - len(kpi))) + 1 + X
        for k, (lab, val) in enumerate(kpi):
            a = ws.cell(1, c0 + k, lab); a.font = Font(name='Arial', size=9, color=INK); a.alignment = Alignment(horizontal='center', vertical='bottom', wrap_text=True)
            b = ws.cell(2, c0 + k, val); b.font = Font(name='Arial', size=14, bold=True, color='000000'); b.alignment = Alignment(horizontal='center', vertical='center')
            if isinstance(val, int) and val >= 1000: b.number_format = NUM_FMT
    H = 4
    for j, c in enumerate(cols, 1):
        cell = ws.cell(H, j + X, c)
        cell.font = Font(name='Arial', size=size, bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor=ORANGE)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = Border(left=WHITE, right=WHITE)
    ws.cell(H, 1 + X)
    ws.row_dimensions[H].height = 32
    for i, row in enumerate(df.itertuples(index=False), H + 1):
        rf = row_rule(dict(zip(cols, row))) if row_rule else None   # заливка всей строки
        for j, v in enumerate(row, 1):
            if isinstance(v, float) and pd.isna(v): v = None
            if hasattr(v, 'item'): v = v.item()
            cell = ws.cell(i, j + X, v)
            col = cols[j - 1]
            isnum = isinstance(v, numbers.Number) and not isinstance(v, bool)
            cell.font = Font(name='Arial', size=size, bold=bool(bold_rule and bold_rule(col, v)), color=RED if col in red else '000000')
            hz = 'center' if col in center else ('right' if isnum else 'left')
            cell.alignment = Alignment(horizontal=hz, vertical='top', wrap_text=col in wrap, indent=1 if hz != 'center' else 0)
            if isnum and isinstance(v, int) and abs(v) >= 1000: cell.number_format = NUM_FMT
            cell.border = Border(bottom=SEP)
            f = rf or (fill_rule(col, v) if fill_rule else None)
            if f: cell.fill = PatternFill('solid', fgColor=f)
    for j, c in enumerate(cols, 1):
        letter = ws.cell(H, j + X).column_letter
        ws.column_dimensions[letter].width = (widths or {}).get(c) or min(45, max(10, len(str(c)) + 2, int(df[c].astype(str).str.len().quantile(0.9)) + 2 if len(df) else 10))
    r_ = H + len(df) + 2   # ссылки — под таблицей, как на других листах
    for text, target in links:
        c = ws.cell(r_, 1 + X, f'{text}: лист «{target}» →'); c.hyperlink = f"#'{target}'!A1"
        c.font = Font(name='Arial', size=10, color=ORANGE2, underline='single'); r_ += 1
    ws.freeze_panes = ws.cell(H + 1, 1 + X)
    if len(df):
        ws.auto_filter.ref = f"{ws.cell(H, 1 + X).coordinate}:{ws.cell(H + len(df), len(cols) + X).coordinate}"
        if sort_by and sort_by in cols:   # отметка сортировки в фильтре — Excel покажет, по чему отсортировано
            c_ = cols.index(sort_by) + 1 + X
            ws.auto_filter.add_sort_condition(f"{ws.cell(H + 1, c_).coordinate}:{ws.cell(H + len(df), c_).coordinate}")
    return ws


def conversions(wb, C, name='Конверсии'):
    """Все отправки форм: кто, какая форма, принята ли, откуда пришёл."""
    if C is None or not len(C) or name not in wb.sheetnames: return
    from .anatomy import name_of, FORM_NAME
    import re
    d = pd.DataFrame({
        'Время': pd.to_datetime(C['время']).dt.strftime('%d.%m.%Y %H:%M'),
        '_t': pd.to_datetime(C['время']),
        'Кто': C['группа'].astype(str),
        'Форма': C['цель'].astype(str).map(lambda g: (name_of(g, FORM_NAME) or ('общий обработчик форм' if re.search(r'/form\.php$', g) else 'форма')).capitalize()),
        'Принята': C['принята'].astype(str),
        'Статус': C['статус'].astype(str) if 'статус' in C else '',
        'Код ответа': pd.to_numeric(C['код'], errors='coerce').astype('Int64'),
        'Канал': C['канал'].astype(str),
        'Страница входа': C['вход'].astype(str),
        'Откуда пришёл': C['вход_реферер'].astype(str).replace({'-': '', 'nan': ''}),
        'Страниц до отправки': pd.to_numeric(C['страниц_до'], errors='coerce').astype('Int64'),
        'Секунд от входа': pd.to_numeric(C['сек_от_входа'], errors='coerce').astype('Int64'),
        'Почему бот': C['подгруппа'].astype(str).where(C['группа'] == 'Боты', '').str.replace('спам форм: ', '', regex=False),
        'IP': C['ip'].astype(str),
        'Сеть': C['сеть'].astype(str),
        'Обработчик': C['цель'].astype(str),
    }).sort_values('_t').drop(columns='_t')   # по времени
    d = d.astype(object).where(d.notna(), None)
    n_ = lambda g: int((C['группа'] == g).sum())
    kpi = [('Отправок', len(C)), ('Люди', n_('Люди')), ('Принято у людей', int(((C['группа'] == 'Люди') & (C['принята'] == 'да')).sum())), ('Боты', n_('Боты')), ('Свои', n_('Свои'))]
    widths = {'Время': 17, 'Кто': 13, 'Форма': 22, 'Принята': 10, 'Статус': 44, 'Код ответа': 9, 'Канал': 18, 'Страница входа': 28, 'Откуда пришёл': 24,
              'Страниц до отправки': 11, 'Секунд от входа': 10, 'Почему бот': 34, 'IP': 16, 'Сеть': 22, 'Обработчик': 50}
    fill = None
    row_rule = lambda r: F_NOTE if r.get('Кто') == 'Боты' else ('EFEFEF' if r.get('Кто') == 'Свои' else None)
    bold = lambda col, v: col == 'Принята' and v == 'да'
    data_sheet(wb, name, d, 'Конверсии', 'Все отправки форм за период', widths, wrap=('Почему бот', 'Статус'), fill_rule=fill, bold_rule=bold,
               center=('IP', 'Код ответа', 'Принята'), kpi=kpi, kpi_col='Канал', links=[('Сводка по формам', 'Анатомия сайта')], row_rule=row_rule)


# ---- точки приёма данных и POST-отправки ----
SITE_KINDS = ('Заявка', 'Заявка?', 'Вход', 'Обмен с 1С', 'API', 'Вебхук', 'Фильтр каталога', 'Поиск по сайту', 'Форма (GET)', 'Пагинация', 'Тип отображения', 'Сортировка', 'Служебный скрипт', 'Подгрузка на странице', 'Админка', 'Загрузка файлов')


def _codes(s):
    import re
    return {int(k): int(v) for k, v in re.findall(r'(\d{3}):\s*(\d+)', str(s))}


def classify_post(r, login_roots, engine, ev=None, prof=None):
    """Что это за адрес и почему — человеческим языком."""
    import re
    a, out = str(r['адрес']), str(r.get('вывод', ''))
    cd = _codes(r.get('коды'))
    tot = max(1, sum(cd.values()))
    ok = sum(v for k, v in cd.items() if 200 <= k < 400 and k not in (301,)) / tot
    if out.startswith('цель'):
        e = (ev or {}).get(a)
        if e and e['редиректов']:
            how = ', '.join(f"{k} — {v}" for k, v in sorted(e['как'].items(), key=lambda x: -x[1]))
            if e['подтверждено'] == e['редиректов']:
                return 'Заявка', f"после отправки — переадресация (302), затем {how}: подтверждено {e['подтверждено']} из {e['редиректов']}"
            if e['подтверждено']:
                return 'Заявка', f"после отправки — переадресация (302), затем {how}: подтверждено {e['подтверждено']} из {e['редиректов']}; остальные не приняты"
            return 'Заявка', f"переадресация (302) есть, но подтверждения успеха нет ни в одном из {e['редиректов']} случаев — заявки не приняты"
        return 'Заявка', ('переадресация после отправки (3xx)' if '3xx' in out else 'успех по коду ответа не виден (всегда 200) — не подтверждено')
    if any(a == root or a.startswith(root) and a.rstrip('/') == root.rstrip('/') for root in login_roots) or (a in login_roots):
        return 'Вход', 'форма входа: неудачный вход возвращает ту же страницу, удачный — другую'
    if re.search(r'/bitrix/admin/|/wp-admin/|/administrator/', a):
        return 'Админка', 'запросы из админки движка (работа сотрудников)'
    if re.search(r'/wp-|wordpress|xmlrpc|^/wp/', a) and engine != 'WordPress':
        return 'Сканер', 'адрес WordPress, а сайт на другом движке'
    bad = cd.get(404, 0) + cd.get(405, 0) + cd.get(301, 0) + cd.get(302, 0)
    if cd and cd.get(404, 0) + cd.get(405, 0) >= 0.8 * tot:
        return 'Сканер', 'такой страницы нет на сайте (404)'
    if cd and bad >= 0.8 * tot:
        return 'Сканер', 'страницы нет (404) или перенаправление (301) — форму не принимает'
    if cd and cd.get(403, 0) >= 0.5 * tot:
        return 'Сканер', 'защита отказала (403)'
    if 'upload' in a:
        return 'Загрузка файлов', 'загрузка файлов на сервер'
    if any(a.startswith(root) for root in login_roots):
        return 'Служебный скрипт', 'скрипт внутри закрытого раздела'
    if re.search(r'ajax|/tools/|/services/|autosave|\.php$', a) and a not in ('/index.php',) and ok >= 0.5:
        return 'Служебный скрипт', 'скрипт сайта: подгружает данные, не заявка'
    p = (prof or {}).get(a, {})
    if p.get('свои', 0) >= 0.8:
        return 'Подгрузка на странице', f"POST шлют браузеры посетителей, которые уже на сайте ({int(p['свои'] * 100)}%) — страница подгружает данные (список, форму)"
    if p:
        tail = f", например параметр «{p['параметр']}»" if p.get('параметр') else ''
        return 'Сканер', f"POST на обычную страницу без перехода с сайта ({int((1 - p.get('свои', 0)) * 100)}% запросов){tail} — боты и сканеры"
    if ok >= 0.5:
        return 'Подгрузка на странице', 'обычная страница отвечает на POST'
    return 'Сканер', 'обычная страница, форму не принимает — отправляют боты и сканеры'


def _post_rows(res):
    m = res.get('site_map') or {}
    F = m.get('forms') or []
    if isinstance(F, str):
        try: F = eval(F)
        except Exception: F = []
    OS = res.get('sheets', {}).get('Нагрузка и безопасность', {}).get('Открытые служебные разделы', pd.DataFrame())
    roots = set(OS.loc[OS['форма_входа'] == 'да', 'раздел'].astype(str)) if len(OS) and 'форма_входа' in OS else set()
    engine = ((m.get('engines') or [{}])[0] or {}).get('движок', '')
    rows = []
    for f in F:
        if not isinstance(f, dict): continue
        kind, why = classify_post(f, roots, engine, res.get('form_evidence'), (res.get('anatomy') or {}).get('post_pages'))
        rows.append({'Адрес точки': f['адрес'], 'Метод': 'POST', 'Опознано как': kind, 'Запросов': int(f.get('отправок') or 0), 'Уникальных IP': int(f.get('IP') or 0), 'Улики': why,
                     'Коды ответа': str(f.get('коды', '')), '_t0': pd.to_datetime(f.get('первый')), '_t1': pd.to_datetime(f.get('последний'))})
    return rows


def _finish(rows):
    d = pd.DataFrame(rows)
    if not len(d): return d
    d['Первый'] = d['_t0'].dt.strftime('%d.%m.%Y %H:%M'); d['Последний'] = d['_t1'].dt.strftime('%d.%m.%Y %H:%M')
    sp_ = d['Коды ответа'].map(split_codes)
    d['Ответы'], d['Ошибки'] = sp_.str[0], sp_.str[1]
    d = d.sort_values('Запросов', ascending=False).drop(columns=['_t0', '_t1', 'Коды ответа'])   # по числу запросов; группы — фильтром
    order = ['Адрес точки', 'Запросов', 'Уникальных IP', 'Метод', 'Опознано как', 'Улики', 'Ответы', 'Ошибки', 'Первый', 'Последний']
    d = d[[c_ for c_ in order if c_ in d.columns]]
    return d


WIDTHS = {'Адрес точки': 55, 'Метод': 8, 'Опознано как': 22, 'Запросов': 10, 'Уникальных IP': 11, 'Улики': 50, 'Ответы': 30, 'Ошибки': 24, 'Первый': 16, 'Последний': 16}


def intake(wb, res, name='Точки приёма данных', before='Конверсии'):
    """Overview: только то, что сайт реально принимает — заявки, вход, фильтры и поиск, свои скрипты, админка."""
    rows = [r for r in _post_rows(res) if r['Опознано как'] != 'Сканер']
    for g in (res.get('anatomy') or {}).get('api', []) + (res.get('anatomy') or {}).get('get_приём', []):
        rows.append({'Адрес точки': g['адрес'], 'Метод': 'GET', 'Опознано как': g['что'], 'Запросов': g['отправок'], 'Уникальных IP': g['IP'], 'Улики': g['почему'],
                     'Коды ответа': g['коды'], '_t0': pd.to_datetime(g['первый']), '_t1': pd.to_datetime(g['последний'])})
    d = _finish(rows)
    if not len(d): return
    if name not in wb.sheetnames: wb.create_sheet(name, wb.sheetnames.index(before) if before in wb.sheetnames else len(wb.sheetnames))
    cnt = d['Опознано как'].value_counts()
    cat_ = int(sum(cnt.get(k, 0) for k in ('Фильтр каталога', 'Поиск по сайту', 'Форма (GET)', 'Пагинация', 'Тип отображения', 'Сортировка')))
    serv_ = int(sum(cnt.get(k, 0) for k in ('Служебный скрипт', 'Подгрузка на странице', 'Админка', 'Загрузка файлов')))
    api_ = int(sum(cnt.get(k, 0) for k in ('Обмен с 1С', 'API', 'Вебхук')))
    kpi = [('Точек приёма', len(d)), ('Заявки', int(cnt.get('Заявка', 0))), ('Поиск и навигация', cat_),
           ('Вход', int(cnt.get('Вход', 0))), ('Служебные', serv_), ('API и обмен', api_)]
    kpi = kpi[:1] + sorted(kpi[1:], key=lambda x: x[1] == 0)   # нули — в конец
    row_rule = lambda r: 'EFEFEF' if r.get('Опознано как') in ('Служебный скрипт', 'Подгрузка на странице', 'Админка', 'Загрузка файлов') else None
    bold = lambda col, v: col == 'Опознано как' and v in ('Заявка', 'Вход')
    data_sheet(wb, name, d, 'Точки приёма данных', 'Где сайт принимает данные', WIDTHS,
               wrap=('Улики', 'Адрес точки', 'Ответы', 'Ошибки'), bold_rule=bold, center=('Метод',), kpi=kpi, kpi_col='Метод', row_rule=row_rule,
               links=[('Все отправки форм', 'Конверсии'), ('Сводка по формам', 'Анатомия сайта')])
    ws = wb[name]   # сноска и чего нет — тоже результат
    if d['Адрес точки'].astype(str).str.contains('фасетн').any():
        r0 = ws.max_row + 2
        c = ws.cell(r0, 2, 'Основные страницы — адреса структуры сайта. Фасетные страницы — адреса, которые генерирует фильтр каталога из комбинаций условий (…/filter/…/apply/); в структуре сайта их нет.')
        c.font = Font(name='Arial', size=10, italic=True, color=INK)
    absent = [lab for lab, keys in (('Поиск по сайту', ('Поиск по сайту',)), ('API и обмен с 1С, CRM, вебхуки', ('Обмен с 1С', 'API', 'Вебхук'))) if not any(cnt.get(k, 0) for k in keys)]
    if absent:
        r_ = ws.max_row + 2
        c = ws.cell(r_, 2, 'Обращений не найдено: ' + '; '.join(absent) + '.')
        c.font = Font(name='Arial', size=10, italic=True, color=INK)


def post_all(wb, res, name='POST-отправки', after='GET-отправки'):
    """03 Безопасность: все POST-отправки, включая сканеры."""
    d = _finish(_post_rows(res))
    if not len(d): return
    d = d.drop(columns=['Метод'])
    if name not in wb.sheetnames:
        pos = wb.sheetnames.index(after) + 1 if after in wb.sheetnames else len(wb.sheetnames)
        wb.create_sheet(name, pos)
    sc = d[d['Опознано как'] == 'Сканер']
    kpi = [('Адресов', len(d)), ('Принимает сайт', len(d) - len(sc)), ('Адресов сканеров', len(sc)), ('Запросов сканеров', int(sc['Запросов'].sum()))]
    row_rule = lambda r: F_NOTE if r.get('Опознано как') == 'Сканер' else None
    data_sheet(wb, name, d, 'POST-отправки', 'Все адреса, куда за период отправляли данные методом POST, — и сайт, и сканеры', WIDTHS,
               wrap=('Улики', 'Адрес точки', 'Ответы', 'Ошибки'), center=(), kpi=kpi, kpi_col='Метод', row_rule=row_rule)
    ws = wb[name]   # ссылка на другой файл
    r_ = ws.max_row + 2
    c = ws.cell(r_, 2, 'Что сайт принимает на самом деле: лист «Точки приёма данных» в NXLD_01_Overview.xlsx →')
    c.hyperlink = "NXLD_01_Overview.xlsx#'Точки приёма данных'!A1"; c.font = Font(name='Arial', size=10, color=ORANGE2, underline='single')


def split_codes(s):
    """«200:65634, 404:12, 499:3» → («200 (65 634), 499 (3)», «404 (12)»): ответы и ошибки (4xx/5xx, кроме 499 — человек ушёл сам)."""
    ok, bad = [], []
    for k, v in _codes(s).items():
        (bad if k >= 400 and k != 499 else ok).append(f"{k} ({int(v):,})".replace(',', '\u00a0'))
    return ', '.join(ok), ', '.join(bad)


def fmt_codes(s):
    """«200:65634, 499:632» → «200 (65 634), 499 (632)» — чтобы не читалось как порт."""
    out = []
    for k, v in _codes(s).items():
        out.append(f"{k} ({int(v):,})".replace(',', '\u00a0'))
    return ', '.join(out) or str(s)



def facets_sheet(wb, F, name='Фасеты'):
    if F is None or not len(F) or name not in wb.sheetnames: return
    d = pd.DataFrame({'Раздел': F['раздел'], 'Ключ': F['ключ'], 'Значение': F['значение'], 'Условие': F['условие'], 'Расшифровка': F['расшифровка'],
                      'Запросов': F['запросов'].astype(int), 'IP (люди)': F['людей'].astype(int), 'Откуда': F['откуда']})
    kpi = [('Условий', int(d['Условие'].nunique())), ('Значений', len(d)), ('Запросов', int(d['Запросов'].sum()))]
    widths = {'Раздел': 14, 'Ключ': 26, 'Значение': 34, 'Условие': 16, 'Расшифровка': 30, 'Запросов': 11, 'IP (люди)': 10, 'Откуда': 30}
    data_sheet(wb, name, d, 'Фасеты', 'Что люди выбирают в фильтре каталога', widths, wrap=('Ключ', 'Значение', 'Условие', 'Расшифровка', 'Откуда'), kpi=kpi, kpi_col='Запросов',
               row_rule=lambda r: 'EFEFEF' if str(r.get('Откуда', '')).startswith('параметры') else None,
               links=[('Где фильтр принимает запросы', 'Точки приёма данных'), ('Устройство каталога', 'Анатомия сайта')])




def _who(s):
    """«браузеры/прочие:41384, Applebot:122» → «браузеры (41 384), Applebot (122)»."""
    import re
    out = []
    for part in str(s).split(', '):
        k, _, v = part.rpartition(':')
        if k and v.strip().isdigit():
            out.append(f"{k.replace('браузеры/прочие', 'браузеры')} ({int(v):,})".replace(',', '\u00a0'))
        elif part: out.append(part)
    return ', '.join(out)


def service_files(wb, res, name='Файлы'):
    """Файлы, которые забирают напрямую: для роботов, фиды, иконки, документы, данные виджетов, картинки не со страниц сайта."""
    import re
    from .recon import FILE_GROUPS
    sf = res.get('files')
    if sf is None:   # старый анализ: только служебные файлы из карты
        from .anatomy import SERVICE_GROUPS
        sf = (res.get('site_map') or {}).get('service_files') or []
        if isinstance(sf, str):
            try: sf = eval(sf)
            except Exception: sf = []
        for f in sf:
            if isinstance(f, dict): f.setdefault('группа', next((nm for nm, rx in SERVICE_GROUPS if re.search(rx, str(f.get('адрес', '')), re.I)), 'Прочие'))
    rows = []
    for f in sf:
        if not isinstance(f, dict): continue
        cd = _codes(f.get('коды'))
        err = sum(v for k, v in cd.items() if 400 <= k and k != 499)
        from urllib.parse import unquote
        a = unquote(str(f.get('адрес', '')), errors='replace') + (f"\n{f['внутри']}" if f.get('внутри') else '')
        day = lambda k: pd.to_datetime(f.get(k)).strftime('%d.%m.%Y') if f.get(k) else ''
        rows.append({'Файл': a, 'Размер, КБ': float(f.get('средний_размер_КБ') or 0), 'Группа': f.get('группа', 'Прочие'),
                     'Файлов': int(f.get('файлов') or 1), 'Запросов': int(f.get('запросов') or 0),
                     'Ответы': split_codes(f.get('коды'))[0], 'Ошибки': split_codes(f.get('коды'))[1], '_err': int(err),
                     **({'Браузеры': int(f.get('браузеры') or 0), 'Роботы': _who(f.get('роботы', '')) if f.get('роботы') else ''} if 'браузеры' in f
                        else {'Кто забирает': _who(f.get('кто_забирает', ''))}),
                     'Со страниц сайта': int(f.get('со_страниц') or 0), 'Напрямую': int(f.get('напрямую') or 0),
                     'Другие сайты': _who(f.get('другие_сайты', '')) if f.get('другие_сайты') else '',
                     'Первый': day('первый_день'), 'Последний': day('последний_день')})
    d = pd.DataFrame(rows)
    if not len(d): return None
    if 'со_страниц' not in (sf[0] if sf and isinstance(sf[0], dict) else {}) or (d['Со страниц сайта'].sum() == 0 and not d['Другие сайты'].astype(bool).any()):   # старый анализ или в логе нет Referer
        d = d.drop(columns=['Со страниц сайта', 'Напрямую', 'Другие сайты'])
    d = d.sort_values('Запросов', ascending=False)
    if name not in wb.sheetnames: wb.create_sheet(name)
    kpi = [('Файлов', int(d['Файлов'].sum())), ('Запросов', int(d['Запросов'].sum())), ('С ошибками', int((d['_err'] > 0).sum()))]
    d = d.drop(columns='_err')
    widths = {'Файл': 52, 'Размер, КБ': 10, 'Группа': 18, 'Файлов': 9, 'Запросов': 11, 'Ответы': 34, 'Ошибки': 26, 'Кто забирает': 44, 'Браузеры': 11, 'Роботы': 44, 'Со страниц сайта': 11, 'Напрямую': 11, 'Другие сайты': 40, 'Первый': 12, 'Последний': 12}
    missing = [nm for nm, _ in FILE_GROUPS if nm not in set(d['Группа']) and nm != 'Прочие файлы'] if res.get('files') is not None else []
    links = [('Сводка по группам', 'Анатомия сайта'), ('Логи, по которым всё посчитано', 'Логи')]
    data_sheet(wb, name, d, 'Файлы', 'Что забирают с сайта как отдельный файл', widths, wrap=('Файл', 'Кто забирает', 'Роботы', 'Другие сайты', 'Ответы', 'Ошибки'),
               kpi=kpi, kpi_col='Файлов', links=links)
    ws = wb[name]
    if missing:
        r = ws.max_row + 2
        ws.cell(r, 2, 'Не найдено: ' + ', '.join(missing).lower() + '. Обращения сканеров к несуществующим файлам сюда не попадают.')
        ws.cell(r, 2).font = Font(name='Arial', size=9, italic=True, color=GREY)
    return wb[name]


def _err_share(codes):
    """Доля ошибок 4xx/5xx без 499 (человек ушёл, не дождавшись) и есть ли 5xx."""
    cd = _codes(codes); tot = sum(cd.values()) or 1
    err = sum(v for k, v in cd.items() if k >= 400 and k != 499)
    return err / tot, any(k >= 500 for k in cd)


def embedded_sheet(wb, res, name='Динамические блоки'):
    """Блоки внутри страницы: что браузер подгружает сам и что человек вызывает действием."""
    E = res.get('embedded')
    if not E: return None
    def blk(e):
        n = int(e.get('блоков') or 1)
        w = 'адрес' if n % 10 == 1 and n % 100 != 11 else 'адреса' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'адресов'
        return e['блок'] + (f' — {n} {w}' if n > 1 else '')
    day = lambda v: pd.to_datetime(v).strftime('%d.%m.%Y') if v else ''
    d = pd.DataFrame([{'Блок': blk(e), 'Размер, КБ': float(e['средний_размер_КБ']), 'Вид': e['вид'], 'Загрузка': e['загрузка'],
                       'Запросов': int(e['запросов']), 'Визиты (люди)': int(e['визитов_людей']),
                       'Автозагрузка, %': e['автозагрузка'] if e.get('автозагрузка') is not None else '',
                       'Охват страниц': int(e['охват_страниц']), 'Ответы': split_codes(e['коды'])[0], 'Ошибки': split_codes(e['коды'])[1],
                       'Первый': day(e['первый_день']), 'Последний': day(e['последний_день'])} for e in E])
    bad = [bool(split_codes(e['коды'])[1]) for e in E]
    d['_bad'] = bad
    cnt = d['Загрузка'].value_counts()
    kpi = [('Блоков', len(d)), ('Подгрузок', int(d['Запросов'].sum())), ('Авто', int(cnt.get('авто', 0))), ('По действию', int(cnt.get('по действию', 0))), ('С ошибками', int(sum(bad)))]
    if name not in wb.sheetnames: wb.create_sheet(name)
    widths = {'Блок': 52, 'Размер, КБ': 10, 'Вид': 26, 'Загрузка': 13, 'Запросов': 13, 'Визиты (люди)': 13, 'Автозагрузка, %': 13,
              'Охват страниц': 11, 'Ответы': 34, 'Ошибки': 26, 'Первый': 12, 'Последний': 12}
    data_sheet(wb, name, d.drop(columns='_bad'), 'Динамические блоки', 'Что подгружается внутри страницы: само или по действию человека', widths,
               wrap=('Блок', 'Вид', 'Ответы', 'Ошибки'), center=('Загрузка',), kpi=kpi, kpi_col='Запросов',
               links=[('Сводка по видам', 'Анатомия сайта'), ('Куда формы отправляют данные', 'Точки приёма данных'), ('Сочетания фильтров', 'Фасеты')])
    ws = wb[name]
    for i, k_ in enumerate(d['Вид']):   # неопознанные — серым; ошибки видны красным в колонке «Ошибки», много это или мало — решает аналитик
        fill = 'EFEFEF' if k_ == 'Неопознанные' else None
        if fill:
            for c in range(2, 2 + len(d.columns) - 1): ws.cell(5 + i, c).fill = PatternFill('solid', fgColor=fill)
    return ws


SRC_LABEL = {'документация': 'Документация', 'сообщество': 'Сообщество', 'сборник': 'Сообщество', 'наблюдение': 'Сообщество',
             'поиск': 'Оперативный поиск', 'поиск, подтверждено': 'Оперативный поиск, подтверждено', 'дедукция': 'Дедукция', 'поведение': 'Дедукция', 'имя': 'Дедукция', '': ''}


def params_sheet(wb, res, name='Параметры запросов'):
    """Каждый ключ (семейство ключей) после «?»: группа, что это, откуда знаем, запросы, люди, значения, где встречается."""
    P = res.get('params')
    if not P: return None
    from .anatomy import PARAM_ORDER as order
    d = pd.DataFrame([{'Параметр': p['параметр'], 'Группа': p['группа'], 'Запросов': int(p['запросов']), 'Визиты (люди)': int(p['людей']),
                       'Опознание': p.get('что', ''), 'Основание': SRC_LABEL.get(p.get('источник', ''), p.get('источник', '')),
                       'Значений': int(p['значений']), 'Частое значение': p['частое_значение'],
                       'Точки обращения': _who(p['где']), 'Спутники': p.get('вместе_с', '')} for p in P])
    if not d['Спутники'].astype(bool).any(): d = d.drop(columns='Спутники')
    cnt = d['Группа'].value_counts()
    kpi = [('Параметров', len(d))] + [(g.split(',')[0], int(cnt[g])) for g in order if cnt.get(g)]
    kpi = [k for k in kpi if k[1]] + [k for k in kpi if not k[1]]
    if name not in wb.sheetnames: wb.create_sheet(name)
    widths = {'Параметр': 30, 'Группа': 24, 'Запросов': 11, 'Визиты (люди)': 11, 'Опознание': 50, 'Основание': 18, 'Значений': 10, 'Частое значение': 36, 'Точки обращения': 40, 'Спутники': 40}
    data_sheet(wb, name, d, 'Параметры запросов', 'Что передают в адресе после «?»', widths, wrap=('Параметр', 'Группа', 'Опознание', 'Основание', 'Частое значение', 'Точки обращения', 'Спутники'),
               kpi=kpi, kpi_col='Запросов', row_rule=lambda r: F_NOTE if r.get('Группа') == 'Атаки и зонды' else 'EFEFEF' if r.get('Группа') == 'Неизвестные' else 'F7F7F7' if r.get('Основание') == 'Дедукция' else None,
               links=[('Сводка по группам', 'Анатомия сайта'), ('Фильтры каталога по значениям', 'Фасеты')])
    ws = wb[name]
    return ws


ERR_TOKEN = None


def redden_codes(wb, skip=('_snapshot',)):
    """Во всех листах: в колонках с кодами ответа ошибки (4xx/5xx, кроме 499) — красным #C00000, остальное как было."""
    import re
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont
    tok = re.compile(r'(?<!\d)([1-5]\d\d)(\s*(?::\s*[\d\s\u00a0]+|\([\d\s\u00a0]+\)))')
    for ws in wb.worksheets:
        if ws.title in skip or ws.max_row < 2: continue
        hdr_rows = [r for r in range(1, min(ws.max_row, 6) + 1)]
        cols = {}
        for r in hdr_rows:
            for c in range(1, ws.max_column + 1):
                v = ws.cell(r, c).value
                if isinstance(v, str) and re.search(r'код|ответ', v, re.I) and v.strip() not in ('Ответы',):
                    cols[c] = r
        for c, hr in cols.items():
            for r in range(hr + 1, ws.max_row + 1):
                cell = ws.cell(r, c); v = cell.value
                if not isinstance(v, str) or not tok.search(v): continue
                parts, pos, any_bad = [], 0, False
                f0 = cell.font
                base = InlineFont(rFont=f0.name or 'Arial', sz=f0.sz or 9, b=f0.b, color=(f0.color.rgb if f0.color is not None and isinstance(f0.color.rgb, str) else None))
                redf = InlineFont(rFont=f0.name or 'Arial', sz=f0.sz or 9, b=f0.b, color=RED)
                for m in tok.finditer(v):
                    k = int(m.group(1)); bad = k >= 400 and k != 499
                    if not bad: continue
                    any_bad = True
                    if m.start() > pos: parts.append(TextBlock(base, v[pos:m.start()]))
                    parts.append(TextBlock(redf, m.group(0))); pos = m.end()
                if any_bad:
                    if pos < len(v): parts.append(TextBlock(base, v[pos:]))
                    cell.value = CellRichText(parts)
