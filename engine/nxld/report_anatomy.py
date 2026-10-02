"""NXLD: лист «Анатомия сайта» (ТЗ, решение 3 октября). Карточки и таблицы в стиле индекса."""
from openpyxl.styles import Font
from .report_index import Sheet, ORANGE, INK, ru_num, plural, cap


def n(x): return ru_num(x)


def link(name): return f"#'{name}'!A1"


def build_anatomy(wb, res, names, index=2, title='Анатомия сайта'):
    A = res.get('anatomy') or {}
    if not A or A.get('ошибка'): return None
    ws = wb.create_sheet(title, index)
    S = Sheet(ws)
    ws.row_dimensions[1].height = 12
    S.r = 2
    ws.merge_cells('B2:F2')
    S.cell('B', 'АНАТОМИЯ САЙТА', Font(name='Montserrat', size=16, bold=True, color=ORANGE)); ws.row_dimensions[2].height = 30
    ws.merge_cells('B3:F3')
    sp = res.get('site_profile') or {}
    sub = ' · '.join(x for x in (A.get('движок'), sp.get('назначение'), f"{n(A.get('всего_страниц', 0))} страниц открывали люди", f"главная — {n(A.get('главная', 0))} визитов") if x)
    S.cell('B', sub, Font(name='Arial', size=11, color=INK), row=3); ws.row_dimensions[3].height = 20
    S.r = 4
    ref = lambda nm: (f'лист «{nm}» →', link(nm)) if nm in names else (None, None)
    # 1. админка и закрытые зоны
    if A.get('зоны'):
        S.section('Админка и закрытые зоны')
        for z in A['зоны']:
            S.pair(z['что'], f"{z['адрес']} — {z['подробно']}")
        t, l = ref('Люди и боты')
        if t: S.pair('Сотрудники и мониторинги', t, link=l, level=2)
    # 2. каталоги и ленты
    for key, head in (('каталоги', 'Каталоги'), ('ленты', 'Ленты')):
        if not A.get(key): continue
        S.section(head)
        for c in A[key]:
            el = c['элемент']
            S.pair(f"{'Каталог' if key == 'каталоги' else 'Лента'} {c['раздел']}",
                   f"{n(c['визитов'])} визитов · {n(c['страниц'])} страниц · {n(c['элементов'])} адресов уровня «{el}»")
            for lv in c['уровни']:
                lab = cap(lv['название']) if not str(lv['название']).startswith('Уровень') else lv['название']
                val = f"{lv['пример']}" + (f" ({lv['слова']})" if lv.get('слова') else '') + f" — {n(lv['адресов'])} {plural(lv['адресов'], 'адрес', 'адреса', 'адресов')}, {n(lv['визитов'])} визитов"
                S.pair(lab, val, level=2)
            if c.get('шаблоны'): S.pair('Шаблоны адресов', '\n'.join(c['шаблоны']), level=2)
            if c.get('фильтры') or c.get('страниц_фильтра'):
                f = ', '.join(c['фильтры'])
                if c.get('страниц_фильтра'): f = (f + '; ' if f else '') + f"страниц фильтра с отдельным адресом — {n(c['страниц_фильтра'])}"
                S.pair('Фильтры', f, level=2)
            t, l = ref('Шаблоны страниц')
            if t: S.pair('Статистика', t, link=l, level=2)
            S.r += 1
    # 3. простые разделы
    if A.get('простые'):
        S.section('Простые разделы')
        rows = [[x['раздел'], int(x['визитов']), int(x['страниц']), x.get('пометки', '')] for x in A['простые']]
        S.table(['Раздел', 'Визитов людей', 'Страниц', 'Особенности'], rows, ['B', 'C', 'D', 'EF'], num=(1, 2))
        t, l = ref('Разделы')
        if t: S.pair('Статистика по разделам', t, link=l, level=2)
    # 4. формы и заявки
    if A.get('формы') or A.get('не_цели'):
        S.section('Формы и заявки')
        for f in A.get('формы', []):
            S.pair(cap(f['форма']), f"от людей: отправлено {n(f['отправлено'])}, принято {n(f['принято'])}" + (f"; от ботов — {n(f['ботов'])}" if f['ботов'] else ''))
            if f.get('где'): S.pair('Где', f['где'], level=2)
            S.pair('Признак успеха', f['успех'], level=2)
            S.pair('Обработчик' if len(f['адреса']) == 1 else 'Обработчики', '\n'.join(f['адреса'][:4]) + (f"\nи ещё {len(f['адреса']) - 4}" if len(f['адреса']) > 4 else ''), level=2)
        if A.get('не_цели'):
            S.pair('Не заявки', '; '.join(f"{g['группа']} — {n(g['отправок'])}" for g in A['не_цели']), level=2)
        t, l = ref('Конверсии')
        if t: S.pair('Все отправки', t, link=l, level=2)
    # 5. папки движка
    if A.get('папки'):
        S.section(f"Папки движка ({A.get('движок')})")
        S.table(['Папка', 'Что в ней', 'Запросов', 'Типы файлов'], [[x['папка'], x['что'], f"{n(x['запросов'])} ({str(x['доля']).replace('.', ',')}%)", x['типы']] for x in A['папки']], ['B', 'CD', 'E', 'F'])
    # 6. медиа
    if A.get('медиа'):
        S.section('Медиа')
        S.table(['Папка', 'Запросов', 'Объём, ГБ', 'Что лежит'], [[x['папка'], int(x['запросов']), f"{x['ГБ']:.1f}".replace('.', ','), f"{x['виды']}\nподпапки: {x['подпапки']}"] for x in A['медиа']], ['B', 'C', 'D', 'EF'], num=(1, 2))
    # 7. служебные файлы
    if A.get('служебные'):
        S.section('Служебные файлы')
        S.table(['Группа', 'Файлов', 'Запросов', 'Ошибок', 'Например'], [[x['группа'], int(x['файлов']), int(x['запросов']), int(x['ошибок']), '\n'.join(x['примеры'])] for x in A['служебные']],
                ['B', 'C', 'D', 'E', 'F'], num=(1, 2, 3))
    # 8. подгружаемые блоки
    if A.get('подгружаемые'):
        S.section('Подгружаемые блоки')
        S.note('Блоки, которые страница подгружает после открытия. Просмотрами страниц не считаются.')
        S.table(['Группа', 'Шаблонов', 'Подгрузок', 'Папка'], [[x['группа'], int(x['шаблонов']), int(x['подгрузок']), x['папка']] for x in A['подгружаемые']], ['B', 'C', 'D', 'EF'], num=(1, 2))
    # 9. параметры
    if A.get('параметры'):
        S.section('Параметры в адресах')
        S.table(['Группа', 'Параметров', 'Применений', 'Например'], [[x['группа'], int(x['параметров']), int(x['применений']), x['примеры']] for x in A['параметры']], ['B', 'C', 'D', 'EF'], num=(1, 2))
        t, l = ref('Фильтры и поиск')
        if t: S.pair('Фильтры подробно', t, link=l, level=2)
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws
