"""NXLD: индексный (первый) лист NXLD_01_Overview — ТЗ, раздел 16.2.

Шапка → Проверка → Условия проверки → Технологии → Трафик и заявки (+ «Как считали») → Проблемы (строка-ссылка) → Оглавление.
Оформление по фирменному образцу Кибермеханики.
"""
import os
from datetime import date
import pandas as pd
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from .prepare import VERSION

ORANGE, ORANGE2, GREY, DARK = 'F57041', 'FF6D01', '666666', '333333'
F_CARD, F_NOTE, F_HEAD = 'EFEFEF', 'FCE5CD', 'E5E5E5'
LOGO = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'brand', 'logo_cybermechanica.png')
COMPANY_URL = 'https://cybermechanica.ru'
MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
BLOCK_FILES = {'Общий анализ': 'NXLD_01_Overview.xlsx', 'Ошибки': 'NXLD_02_Errors.xlsx', 'Нагрузка и безопасность': 'NXLD_03_Load_Security.xlsx',
               'Боты': 'NXLD_04_Bots.xlsx', 'Маркетинг': 'NXLD_05_Marketing.xlsx'}
FILE_NOTES = {'Ошибки': 'ошибки сервера, сбои, битые ссылки и входы, отсутствующие файлы, error-лог',
              'Нагрузка и безопасность': 'нагрузка, тяжёлые файлы, сканеры, служебные разделы, админка',
              'Боты': 'роботы и боты, подделки, спам форм, операторы с доказательствами',
              'Маркетинг': 'каналы, реклама, кампании и площадки, конверсии и разрезы'}
# пояснения к листам оглавления (пока список листов Overview не утверждён — по текущим именам)
SHEET_NOTES = {'Проблемы': 'все найденные проблемы по важности', 'Файлы': 'какие файлы логов разобраны', 'Карта сайта': 'что Детектив узнал о сайте при разведке',
               'Карта — формы и цели': 'адреса отправки форм и как понять, что заявка принята', 'Карта — подгружаемые блоки': 'формы и блоки, которые грузятся на каждой странице',
               'Карта — служебные файлы': 'robots.txt, sitemap, фиды и кто их запрашивает', 'Люди и боты': 'из кого состоит трафик', 'По дням': 'визиты и заявки по дням',
               'Каналы': 'откуда приходят люди', 'Разделы': 'популярность разделов сайта', 'Шаблоны страниц': 'какие типы страниц смотрят', 'Спрос': 'что ищут и смотрят в каталоге',
               'Фильтры и поиск': 'какими фильтрами и поиском пользуются', 'Конверсии': 'все отправки форм с результатом', 'GET-отправки': 'данные форм в адресах страниц',
               'IP': 'важные адреса: спам, подделки, разведка, свои'}

thin = Side(style='thin', color=ORANGE)


def ru_date(ts):
    t = pd.Timestamp(ts)
    return f'{t.day} {MONTHS[t.month - 1]} {t.year}'


def ru_num(x):
    return f'{int(x):,}'.replace(',', ' ')


def ru_short(x):
    x = float(x)
    if x >= 1e6: return f'{x / 1e6:.1f}'.replace('.', ',') + ' млн'
    if x >= 1e4: return f'{x / 1e3:.0f} тыс.'
    if x >= 1e3: return f'{x / 1e3:.1f}'.replace('.', ',') + ' тыс.'
    return ru_num(x)


def plural(n, one, few, many):
    n = abs(int(n)) % 100
    if 11 <= n <= 19: return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


class Sheet:
    """Простая раскладка: колонка A — поле, B — подписи, C:F — значения."""
    def __init__(self, ws):
        self.ws, self.r = ws, 1
        for col, w in zip('ABCDEFG', (2.5, 30, 20, 16, 16, 34, 2.5)):
            ws.column_dimensions[col].width = w
        ws.sheet_view.showGridLines = False

    def cell(self, col, text, font=None, fill=None, align=None, row=None):
        c = self.ws[f'{col}{row or self.r}']
        c.value = text
        if font: c.font = font
        if fill: c.fill = PatternFill('solid', fgColor=fill)
        c.alignment = align or Alignment(vertical='center', wrap_text=True)
        return c

    def section(self, title):
        self.r += 1
        self.cell('B', title.upper(), Font(name='Montserrat', size=12, bold=True, color=ORANGE))
        for col in 'BCDEF':
            self.ws[f'{col}{self.r}'].border = Border(bottom=thin)
        self.ws.row_dimensions[self.r].height = 24
        self.r += 1

    def pair(self, label, value, fill=F_CARD, link=None, height=None):
        self.cell('B', label, Font(name='Arial', size=10, bold=True, color=GREY), fill, Alignment(vertical='top', wrap_text=True, indent=1))
        self.ws.merge_cells(f'C{self.r}:F{self.r}')
        c = self.cell('C', value, Font(name='Arial', size=11, color=DARK, underline='single' if link else None), fill, Alignment(vertical='top', wrap_text=True))
        for col in 'DEF':
            self.ws[f'{col}{self.r}'].fill = PatternFill('solid', fgColor=fill)
        if link:
            c.hyperlink = link; c.font = Font(name='Arial', size=11, color=ORANGE2, underline='single')
        lines = max(1, sum(len(s) // 95 + 1 for s in str(value).split('\n')))
        self.ws.row_dimensions[self.r].height = height or max(20, 15 * lines + 6)
        self.r += 1

    def note(self, text):
        self.ws.merge_cells(f'B{self.r}:F{self.r}')
        self.cell('B', text, Font(name='Arial', size=10, italic=True, color=DARK), F_NOTE, Alignment(vertical='top', wrap_text=True, indent=1))
        for col in 'CDEF':
            self.ws[f'{col}{self.r}'].fill = PatternFill('solid', fgColor=F_NOTE)
        self.ws.row_dimensions[self.r].height = 14 * (len(text) // 120 + 1) + 8
        self.r += 1


def conditions(res):
    """Только непустые строки «Условий проверки»."""
    rows, inv = [], res['inventory']
    skipped = [b for b in BLOCK_FILES if b not in res['selected']]
    if skipped: rows.append(('Не проверялось', ', '.join(skipped)))
    if res.get('prev_period'):
        rows.append(('База сравнения', f"снимок прошлой проверки за {ru_date(res['prev_period'][0])} — {ru_date(res['prev_period'][1])}"))
    if res.get('check_ips'):
        n = len(res['check_ips'])
        rows.append(('Присланные адреса', f"{n} {plural(n, 'IP проверен', 'IP проверены', 'IP проверены')} — результат на листе «Проверка IP» в NXLD_04_Bots.xlsx"))
    marked = sum(1 for x in res['findings'] if x.get('статус') == 'отмечено как норма')
    if marked: rows.append(('Отметки «это норма»', f'{marked} {plural(marked, "проблема отмечена", "проблемы отмечены", "проблем отмечено")} как норма и не считаются'))
    if res.get('signatures_note'): rows.append(('Чужие правила', res['signatures_note']))
    if res.get('internet'): rows.append(('Проверки в интернете', res['internet']))
    gaps = []
    if not inv.get('errors_lines'): gaps.append('error-лога нет — причины ошибок сервера по нему не проверялись')
    if inv.get('hour_gaps'): gaps.append('в логе нет данных за часы: ' + ', '.join(inv['hour_gaps'][:6]))
    end = pd.Timestamp(inv['period'][1])
    if end.hour < 23: gaps.append(f'лог обрывается {end.day} {MONTHS[end.month - 1]} в {end:%H:%M} — последний день неполный')
    if gaps: rows.append(('Пробелы в данных', '; '.join(gaps).capitalize() + '.'))
    return rows


def build_index(wb, res, sheet_names, title='Обзор'):
    ws = wb.create_sheet(title, 0)
    S = Sheet(ws)
    inv, m, sm = res['inventory'], res['site_map'], res['summary'].get('Общий анализ', {})
    site = (m.get('site_hosts') or ['?'])[0]
    # --- шапка
    for i, h in enumerate((26, 26, 26, 8), start=1): ws.row_dimensions[i].height = h
    if os.path.exists(LOGO):
        img = XLImage(LOGO); img.width, img.height = 263, 60
        ws.add_image(img, 'B1')
    S.cell('F', COMPANY_URL, Font(name='Arial', size=11, color=GREY), align=Alignment(horizontal='right', vertical='center'), row=1)
    ws['F1'].hyperlink = COMPANY_URL; ws['F1'].font = Font(name='Arial', size=11, color=GREY)
    S.r = 5
    ws.merge_cells('B5:F5')
    S.cell('B', f'NX LOG DETECTIVE — САЙТ {site.upper()}', Font(name='Montserrat', size=16, bold=True, color=ORANGE)); ws.row_dimensions[5].height = 30
    ws.merge_cells('B6:F6')
    S.cell('B', 'Анализ логов сервера: что происходит на сайте, кто на него ходит и что работает не так', Font(name='Comfortaa', size=11, bold=True, color=GREY), row=6)
    ws.row_dimensions[6].height = 20
    S.r = 8
    kind = f"ПОВТОРНАЯ ПРОВЕРКА" if res.get('prev_period') else 'ПЕРВИЧНАЯ ПРОВЕРКА'
    S.cell('B', kind, Font(name='Arial', size=11, bold=True, color='FFFFFF'), ORANGE, Alignment(horizontal='center', vertical='center'))
    ws.merge_cells('C8:F8')
    sub = f"Отчёт от {ru_date(date.today())} · NX Log Detective {VERSION}"
    if res.get('prev_period'): sub = f"Сравнение с проверкой за {ru_date(res['prev_period'][0])} — {ru_date(res['prev_period'][1])} · " + sub
    S.cell('C', sub, Font(name='Arial', size=10, color=GREY), align=Alignment(vertical='center', indent=1))
    ws.row_dimensions[8].height = 24
    S.r = 9
    # --- проверка
    S.section('Проверка')
    others = [h for h in (m.get('site_hosts') or [])[1:]]
    S.pair('Сайт', site + (f" (в логах также {', '.join(others)})" if others else ''))
    p0, p1 = pd.Timestamp(inv['period'][0]), pd.Timestamp(inv['period'][1])
    days = (p1.normalize() - p0.normalize()).days + 1
    S.pair('Период', f"{p0.day} {MONTHS[p0.month - 1]} — {ru_date(p1)}, {days} {plural(days, 'день', 'дня', 'дней')}")
    files = inv.get('files', [])
    na = sum(1 for f in files if f.get('тип') == 'access'); ne = sum(1 for f in files if f.get('тип') == 'error')
    src = f"access-лог: {ru_short(inv['requests'])} строк, {na} {plural(na, 'файл', 'файла', 'файлов')}"
    if inv.get('errors_lines'): src += f"\nerror-лог: {ru_short(inv['errors_lines'])} строк, {ne} {plural(ne, 'файл', 'файла', 'файлов')}"
    dup = sum(d.get('lines_duplicate', 0) for d in inv.get('duplicates', []))
    if dup: src += f"\nповторы на стыках файлов удалены: {ru_short(dup)} строк"
    S.pair('Исходные данные', src)
    # --- условия
    S.section('Условия проверки')
    rows = conditions(res)
    if rows:
        for k, v in rows: S.pair(k, v)
    else:
        S.pair('Итог', 'Проверены все блоки, данные полные.')
    # --- технологии
    S.section('Технологии')
    h = res.get('hosting') or {}
    host = h.get('тип', 'по логам не определён')
    if h.get('путь'): host = host[0].upper() + host[1:] + f" (по пути {h['путь']})"
    S.pair('Хостинг', host)
    S.pair('Операционная система', h.get('ос', 'по логам не видно'))
    srv = m.get('server', {})
    proto = srv.get('протокол') or {}
    tot = sum(proto.values()) or 1
    h2 = proto.get('HTTP/2.0', 0) / tot * 100
    web = str(srv.get('веб-сервер') or 'не определён').replace(' → ', ', PHP через ')
    S.pair('Веб-сервер', web + (f'; {h2:.0f}% запросов по HTTP/2' if h2 >= 1 else ''))
    eng = ', '.join(e['движок'] for e in m.get('engines', [])) or 'не определён (возможно, статический HTML или свой движок)'
    S.pair('Движок сайта', eng)
    adm = str(m.get('admin_regex') or '').lstrip('^').replace('\\', '')
    if adm: S.pair('Адрес админки', adm)
    # --- трафик и заявки
    S.section('Трафик и заявки')
    grp = [('Люди', sm.get('Визитов людей', 0), f"{ru_num(sm.get('IP людей', 0))} адресов; {res.get('mobile_share') or 0:.0f}% с телефонов".replace('.', ',')),
           ('Роботы', sm.get('Визитов: Роботы', 0), 'поисковики, сервисы, мониторинги — представляются честно'),
           ('Боты', sm.get('Визитов: Боты', 0), 'притворяются браузерами, спамят формы, сканируют'),
           ('Свои', sm.get('Визитов: Свои', 0), 'сотрудники, подрядчик, свои мониторинги')]
    total = sum(v for _, v, _ in grp) or 1
    hdr = Font(name='Arial', size=10, bold=True, color=GREY)
    for col, t in zip('BCDE', ('Кто', 'Визитов', 'Доля', 'Кто это')):
        S.cell(col, t, hdr, F_HEAD, Alignment(horizontal='left' if col in 'BE' else 'right', vertical='center', indent=1 if col == 'B' else 0))
    ws.merge_cells(f'E{S.r}:F{S.r}'); ws[f'F{S.r}'].fill = PatternFill('solid', fgColor=F_HEAD)
    S.r += 1
    for g, v, note in grp:
        S.cell('B', g, Font(name='Arial', size=11, bold=True, color=DARK), F_CARD, Alignment(vertical='center', indent=1))
        c = S.cell('C', v, Font(name='Arial', size=11, color=DARK), F_CARD, Alignment(horizontal='right', vertical='center')); c.number_format = '#,##0'
        c = S.cell('D', v / total, Font(name='Arial', size=11, color=DARK), F_CARD, Alignment(horizontal='right', vertical='center')); c.number_format = '0%'
        ws.merge_cells(f'E{S.r}:F{S.r}')
        S.cell('E', note, Font(name='Arial', size=10, color=GREY), F_CARD, Alignment(vertical='center', wrap_text=True)); ws[f'F{S.r}'].fill = PatternFill('solid', fgColor=F_CARD)
        ws.row_dimensions[S.r].height = 20
        S.r += 1
    S.r += 1
    cl = res.get('cleaning', {})
    S.pair('Просмотры страниц людьми', f"{ru_short(sm.get('Просмотров страниц людьми', 0))}; визитов во встроенных браузерах приложений — {ru_short(cl.get('Визитов людей во встроенных браузерах приложений', 0))}")
    ppl, bots, own = sm.get('Принято от людей', 0), sm.get('Принято от ботов', 0), sm.get('Принято от своих (тесты)', 0)
    leads = f"отправок форм: {ru_num(sm.get('Отправок целей всего', 0))}; принято заявок от людей — {ru_num(ppl)}"
    if bots: leads += f", от ботов — {ru_num(bots)}"
    if own: leads += f", тестов своих — {ru_num(own)}"
    S.pair('Заявки', leads)
    cr = sm.get('Конверсия людей (визит → принятая цель), %', 0)
    S.pair('Конверсия людей', f"{str(cr).replace('.', ',')}% — одна заявка на {ru_num(round(100 / cr))} визитов" if cr else 'заявок от людей нет')
    raw, clean = cl.get('Просмотров у людей до очистки'), cl.get('Просмотров у людей после очистки')
    how = ('Как считали. Все визиты и просмотры людей в отчёте — после очистки: склеены двойные загрузки одной страницы и переадресации, '
           'подгрузки форм и блоков не считаются просмотрами, боты и свои отделены. Поэтому цифры меньше сырых')
    if raw and clean: how += f" (просмотров {ru_short(raw)} → {ru_short(clean)})"
    how += ' и ближе к Метрике. Заявкой считается отправка формы, которую сервер принял.'
    S.note(how)
    # --- проблемы
    S.section('Проблемы')
    act = [x for x in res['findings'] if x.get('статус') != 'отмечено как норма']
    cnt = {k: sum(1 for x in act if x['важность'] == k) for k in ('Срочно', 'Важно', 'К сведению')}
    pr = sheet_names.get('Проблемы', 'Проблемы')
    S.pair('Найдено', f"срочных — {cnt['Срочно']}, важных — {cnt['Важно']}, к сведению — {cnt['К сведению']} → лист «{pr}»", link=f"#'{pr}'!A1")
    # --- оглавление
    S.section('Оглавление')
    for name, real in sheet_names.items():
        if real == title or real.startswith('_'): continue
        c = S.cell('B', real, align=Alignment(vertical='center', indent=1)); c.hyperlink = f"#'{real}'!A1"; c.font = Font(name='Arial', size=11, color=ORANGE2, underline='single')
        ws.merge_cells(f'C{S.r}:F{S.r}')
        S.cell('C', SHEET_NOTES.get(real, ''), Font(name='Arial', size=10, color=GREY))
        ws.row_dimensions[S.r].height = 18
        S.r += 1
    S.r += 1
    for b, f in BLOCK_FILES.items():
        if b == 'Общий анализ' or b not in res['selected']: continue
        c = S.cell('B', f, align=Alignment(vertical='center', indent=1)); c.hyperlink = f; c.font = Font(name='Arial', size=11, color=ORANGE2, underline='single')
        ws.merge_cells(f'C{S.r}:F{S.r}')
        S.cell('C', FILE_NOTES.get(b, ''), Font(name='Arial', size=10, color=GREY))
        ws.row_dimensions[S.r].height = 18
        S.r += 1
    for t, fn in (('Текст для Redmine', 'NXLD_Redmine.textile'),):
        S.cell('B', fn, Font(name='Arial', size=11, color=DARK), align=Alignment(vertical='center', indent=1))
        ws.merge_cells(f'C{S.r}:F{S.r}')
        S.cell('C', 'связный отчёт Детектива — для задачи в Redmine', Font(name='Arial', size=10, color=GREY))
        S.r += 1
    # печать
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f'A1:G{S.r}'
    wb.active = 0
    return ws
