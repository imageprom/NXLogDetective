"""NXLD: лист «Анатомия сайта» (ТЗ, решение 3 октября). Карточки и таблицы в стиле индекса.

Порядок: системные папки и админка → закрытые зоны → каталоги → ленты → простые разделы → медиа → служебные файлы →
подгружаемые блоки → формы и заявки → параметры в адресах. Ссылки на подробности — строкой под блоком.
"""
from openpyxl.styles import Font, Alignment, Border
from .report_index import Sheet, ORANGE, ORANGE2, ru_num, plural, cap, SEP, F_CARD, NUM_FMT

F_LIGHT = 'F7F7F7'   # второй уровень


def n(x): return ru_num(x)


def link_row(S, text, name, names):
    """Ссылка под блоком — как на других листах."""
    if name not in names: return
    S.ws.merge_cells(f'B{S.r}:F{S.r}')
    c = S.cell('B', f'{text}: лист «{name}» →', align=Alignment(vertical='center', indent=1))
    c.hyperlink = f"#'{name}'!A1"; c.font = Font(name='Arial', size=10, color=ORANGE2, underline='single')
    S.ws.row_dimensions[S.r].height = 20
    S.r += 1


def row4(S, label, c, d, ef, fill=F_CARD, bold=False):
    """Строка таблицы уровней: B — подпись, C — страниц, D — визитов, E:F — адреса или пояснение."""
    S._fill_row('BCDEF', fill, Border(bottom=SEP))
    S.cell('B', label, Font(name='Arial', size=11, bold=bold, color='000000'), fill, Alignment(vertical='center', wrap_text=True, indent=1 if bold else 3))
    for col, v in (('C', c), ('D', d)):
        x = S.cell(col, int(v) if isinstance(v, (int, float)) and v != '' else v, Font(name='Arial', size=11, bold=bold, color='000000' if bold else '333333'), fill,
                   Alignment(horizontal='right', vertical='center', indent=1))
        if isinstance(v, (int, float)): x.number_format = NUM_FMT
    S.ws.merge_cells(f'E{S.r}:F{S.r}')
    S.cell('E', ef, Font(name='Arial', size=11, color='333333'), fill, Alignment(vertical='center', wrap_text=True, indent=1))
    from .report_index import row_height
    S.ws.row_dimensions[S.r].height = max(row_height(label, 28), row_height(ef, 50)) + 2
    S.r += 1


ROMAN = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII']


def roman(d): return ROMAN[d] if d < len(ROMAN) else str(d)


def level_label(lv, kind='каталога'):
    """Ур. I: Индексная каталога · Ур. II: Раздел — Проект · Ур. III: Подразделы · Ур. VII: Элементы — Квартира."""
    role = lv.get('роль')
    if role == 'промежуточные':
        return f"Ур. {roman(lv['глубина'])}–{roman(lv['до'])}: Подразделы\nпромежуточные"
    nm = '' if str(lv['название']).startswith('Уровень') or role == 'подраздел' else cap(lv['название'])
    head = {'индексная': f'Индексная {kind}', 'раздел': 'Раздел', 'подраздел': 'Подразделы', 'элемент': 'Элементы'}.get(role, cap(role or ''))
    if role == 'подраздел' and lv.get('примеры'):
        from .anatomy import slug_name
        return f"Ур. {roman(lv['глубина'])}: {head}\n" + '\n'.join(cap(slug_name(w, 1) or w) for w in lv['примеры'])
    return f"Ур. {roman(lv['глубина'])}: {head}" + (f" — {nm}" if nm and role != 'индексная' else '')


def level_addr(lv):
    if lv['адресов'] == 1: return lv['пример']
    if lv.get('роль') == 'индексная':   # индексная — это сами адреса, без «Шаблон» и «Пример»
        return '\n'.join(lv.get('все') or [lv['пример']])
    lines = []
    if lv.get('шаблон') and lv['шаблон'] != lv['пример']: lines.append(f"Шаблон: {lv['шаблон']}")
    if lv.get('примеры'):
        from .anatomy import slug_name
        for w, a in lv['примеры'].items():
            lines.append(f"{cap(slug_name(w, 1) or w)}: {a}")
    else:
        lines.append(f"Пример: {lv['пример']}")
    return '\n'.join(lines)


def build_anatomy(wb, res, names, index=2, title='Анатомия сайта'):
    A = res.get('anatomy') or {}
    if not A or A.get('ошибка'): return None
    ws = wb.create_sheet(title, index)
    S = Sheet(ws)
    ws.row_dimensions[1].height = 12
    S.r = 2
    ws.merge_cells('B2:F2')
    S.cell('B', 'АНАТОМИЯ САЙТА', Font(name='Montserrat', size=16, bold=True, color=ORANGE)); ws.row_dimensions[2].height = 30
    S.r = 3
    zones = A.get('зоны') or []
    adm = [z for z in zones if z['что'] == 'Админка движка']
    rest = [z for z in zones if z['что'] != 'Админка движка']
    test = [z for z in rest if z['что'] == 'Тестовая копия']
    # 1. системные папки и админка
    if A.get('папки') or adm or test:
        S.section('Системные папки')
        if A.get('папки'):
            S.table(['Папка', 'Запросов', 'Типы файлов', 'Содержимое'], [[x['папка'], f"{n(x['запросов'])} ({str(x['доля']).replace('.', ',')}%)", x['типы'], x['что']] for x in A['папки']],
                    ['B', 'C', 'DE', 'F'], wrap=0.9)
        for z in adm:
            S.pair('Админка движка', z['адрес'])
            S.pair('Кто входил', f"сотрудники — с {n(z.get('входили', 0))} {plural(z.get('входили', 0), 'IP-адреса', 'IP-адресов', 'IP-адресов')}", fill=F_LIGHT, level=2)
        for z in [z for z in rest if z['что'] == 'Тестовая копия']:
            S.pair('Тестовая копия', z['адрес'] + (f" — {z['подробно']}" if z.get('подробно') else ''))
        link_row(S, 'Сотрудники и мониторинги', 'Люди и боты', names)
    # 2. закрытые зоны
    rest = [z for z in rest if z['что'] != 'Тестовая копия']
    if rest:
        S.section('Закрытые зоны')
        for z in rest:
            S.pair(z['что'], z['адрес'] + (f" — {z['подробно']}" if z.get('подробно') else ''))
            if z['что'] == 'Служебный раздел':
                S.pair('Кто входил', f"люди — с {n(z.get('входили', 0))} {plural(z.get('входили', 0), 'IP-адреса', 'IP-адресов', 'IP-адресов')}", fill=F_LIGHT, level=2)
                if z.get('неудачных'): S.pair('Неудачных входов', n(z['неудачных']), fill=F_LIGHT, level=2)
                if z.get('без_входа'):
                    S.pair('Открывались без входа', str(z['без_входа']).replace(', ', '\n'), fill=F_LIGHT, level=2)
                    S.pair('Что проверить', 'должны ли эти страницы открываться без входа', fill=F_LIGHT, level=2)
            if z['что'] == 'Личный кабинет':
                S.pair('Визиты', f"{n(z.get('визитов', 0))} (люди)", fill=F_LIGHT, level=2)
                if z.get('IP'): S.pair('Кто входил', f"люди — с {n(z['IP'])} {plural(z['IP'], 'IP-адреса', 'IP-адресов', 'IP-адресов')}", fill=F_LIGHT, level=2)
            for lv in z.get('уровни') or []:
                S.pair(f"Уровень {lv['глубина']}" + (f": {cap(lv['название'])}" if not str(lv['название']).startswith('Уровень') else ''),
                       f"{lv.get('шаблон') or lv['пример']} — {n(lv['адресов'])} {plural(lv['адресов'], 'адрес', 'адреса', 'адресов')}, {n(lv['визитов'])} визитов", fill=F_LIGHT, level=2)
    # 3. каталоги и ленты: шапка таблицы один раз, строка каталога — на сером жирным, уровни — светло-серые
    for key, head, word in (('каталоги', 'Каталоги', 'Каталог'), ('ленты', 'Ленты', 'Лента')):
        if not A.get(key): continue
        S.section(head)
        S.table(['Уровень', 'Страниц', 'Визитов', 'Адреса'], [], ['B', 'C', 'D', 'EF'])
        for c in A[key]:
            st = [f"разделов — {n(c['разделов'])}" if c.get('разделов') else '', f"подразделов — {n(c['подразделов'])}" if c.get('подразделов') else '',
                  f"элементов «{c['элемент']}» — {n(c['элементов'])}"]
            row4(S, f"{word} {c['раздел']}", c['страниц'], c['визитов'], '\n'.join(cap(x) for x in st if x), bold=True)
            for lv in c['уровни']:
                row4(S, level_label(lv, 'каталога' if key == 'каталоги' else 'ленты'), lv['адресов'], lv['визитов'], level_addr(lv), fill=F_LIGHT)
            if c.get('фильтры') or c.get('страниц_фильтра'):
                txt = ('Параметры: ' + ', '.join(c['фильтры'])) if c.get('фильтры') else ''
                if c.get('страниц_фильтра'): txt += ('\n' if txt else '') + 'Страницы фильтра: адреса вида …/filter/…/apply/'
                row4(S, 'Фильтры', c.get('страниц_фильтра') or '', c.get('визитов_фильтра') or '', txt, fill=F_LIGHT)
        link_row(S, 'Статистика по шаблонам', 'Шаблоны страниц', names)
    # 3. простые разделы (и главная)
    if A.get('простые') or A.get('главная'):
        S.section('Простые разделы')
        rows = ([['/ (главная)', int(A.get('главная', 0)), 1, '']] if A.get('главная') else []) + \
               [[x['раздел'], int(x['визитов']), int(x['страниц']), x.get('пометки', '')] for x in A.get('простые', [])]
        S.table(['Раздел', 'Визитов людей', 'Страниц', 'Особенности'], rows, ['B', 'C', 'D', 'EF'], num=(1, 2))
        link_row(S, 'Статистика по разделам', 'Разделы', names)
    # 5. медиа
    if A.get('медиа'):
        S.section('Медиа')
        S.table(['Папка', 'Запросов', 'Объём, ГБ', 'Что лежит'], [[x['папка'], int(x['запросов']), f"{x['ГБ']:.1f}".replace('.', ','), f"{x['виды']}\nподпапки:\n" + x['подпапки'].replace(', ', '\n')] for x in A['медиа']],
                ['B', 'C', 'D', 'EF'], num=(1, 2), wrap=0.9)
    # 6. служебные файлы
    if A.get('служебные'):
        S.section('Служебные файлы')
        S.table(['Группа', 'Файлов', 'Запросов', 'Ошибок', 'Например'], [[x['группа'], int(x['файлов']), int(x['запросов']), int(x['ошибок']), '\n'.join(x['примеры'])] for x in A['служебные']],
                ['B', 'C', 'D', 'E', 'F'], num=(1, 2, 3), wrap=0.9)
    # 7. подгружаемые блоки
    if A.get('подгружаемые'):
        S.section('Подгружаемые блоки')
        S.note('Блоки, которые страница подгружает после открытия. Просмотрами страниц не считаются.')
        S.table(['Группа', 'Шаблонов', 'Подгрузок', 'Папка'], [[x['группа'], int(x['шаблонов']), int(x['подгрузок']), x['папка']] for x in A['подгружаемые']], ['B', 'C', 'D', 'EF'], num=(1, 2), wrap=0.9)
    # 8. формы и заявки
    if A.get('формы') or A.get('не_цели'):
        S.section('Формы, заявки и вход')
        for f in A.get('формы', []):
            S.pair(cap(f['форма']), f"от людей: отправлено {n(f['отправлено'])}, принято {n(f['принято'])}" + (f"; от ботов — {n(f['ботов'])}" if f['ботов'] else ''))
            if f.get('где'): S.pair('Где', f['где'].replace(', ', '\n'), fill=F_LIGHT, level=2)
            S.pair('Признак успеха', f['успех'], fill=F_LIGHT, level=2)
            S.pair('Обработчик' if len(f['адреса']) == 1 else 'Обработчики', '\n'.join(f['адреса'][:4]) + (f"\nи ещё {len(f['адреса']) - 4}" if len(f['адреса']) > 4 else ''), fill=F_LIGHT, level=2)
        for z in [z for z in (A.get('зоны') or []) if z['что'] == 'Служебный раздел' and z.get('POST')]:
            S.pair(f"Вход в {z['адрес']}", f"успешных — с {n(z.get('входили', 0))} {plural(z.get('входили', 0), 'IP-адреса', 'IP-адресов', 'IP-адресов')}; неудачных попыток — {n(z.get('неудачных', 0))}")
        if A.get('не_цели'):
            S.pair('Не заявки', '; '.join(f"{g['группа']} — {n(g['отправок'])}" for g in A['не_цели']))
        link_row(S, 'Все отправки форм', 'Конверсии', names)
    # 9. параметры
    if A.get('параметры'):
        S.section('Параметры в адресах')
        S.table(['Группа', 'Параметров', 'Применений', 'Например'], [[x['группа'], int(x['параметров']), int(x['применений']), x['примеры']] for x in A['параметры']],
                ['B', 'C', 'D', 'EF'], num=(1, 2), wrap=0.8)
        link_row(S, 'Фильтры подробно', 'Фильтры и поиск', names)
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws
