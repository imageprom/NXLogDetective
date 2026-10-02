"""NXLD: индексный (первый) лист NXLD_01_Overview — ТЗ, раздел 16.2.

Шапка → Проверка → Условия проверки → Технологии → Трафик и заявки (+ «Как считали») → Проблемы (строка-ссылка) → Оглавление.
Оформление по фирменному образцу Кибермеханики.
"""
import os
from datetime import date
import pandas as pd
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from .prepare import VERSION

ORANGE, ORANGE2, GREY, DARK = 'F57041', 'FF6D01', '666666', '333333'
INK = '404040'   # серый текст на белом фоне — контрастнее фирменного #666666
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


def row_height(text, chars):
    """Единая высота строк: 22 пт на одну строку текста, +15 пт на каждую следующую."""
    lines = sum(max(1, -(-len(part) // max(1, chars))) for part in str(text).split('\n'))
    return 22 + 15 * (lines - 1)


def cap(t):
    t = str(t or '')
    return t[:1].upper() + t[1:]


def plural(n, one, few, many):
    n = abs(int(n)) % 100
    if 11 <= n <= 19: return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


LINE = Side(style='thin', color='000000')       # сетка таблиц, как в фирменном образце
SEP = Side(style='thin', color='BFBFBF')        # разделитель строк в карточках
SEV_STYLE = {'Срочно': (ORANGE, 'FFFFFF'), 'Важно': (F_NOTE, DARK), 'К сведению': ('F3F3F3', DARK)}
SPANS = {'B': 'B', 'C': 'C', 'D': 'D', 'E': 'E', 'F': 'F'}


class Sheet:
    """Раскладка: A — поле, B — подписи / первая колонка таблиц, C:F — значения."""
    def __init__(self, ws):
        self.ws, self.r = ws, 1
        for col, w in zip('ABCDEFG', (2.5, 34, 18, 14, 16, 44, 2.5)):
            ws.column_dimensions[col].width = w
        ws.sheet_view.showGridLines = True

    def cell(self, col, text, font=None, fill=None, align=None, row=None):
        c = self.ws[f'{col}{row or self.r}']
        c.value = text
        if font: c.font = font
        if fill: c.fill = PatternFill('solid', fgColor=fill)
        c.alignment = align or Alignment(vertical='center', wrap_text=True)
        return c

    def section(self, title):
        self.r += 1
        self.ws.merge_cells(f'B{self.r}:F{self.r}')
        self.cell('B', title.upper(), Font(name='Montserrat', size=12, bold=True, color=ORANGE), align=Alignment(vertical='center'))
        for col in 'BCDEF':
            self.ws[f'{col}{self.r}'].border = Border(bottom=thin)
        self.ws.row_dimensions[self.r].height = 26
        self.r += 1

    def _fill_row(self, cols, fill, border):
        for col in cols:
            c = self.ws[f'{col}{self.r}']
            if fill: c.fill = PatternFill('solid', fgColor=fill)
            c.border = border

    def pair(self, label, value, fill=F_CARD, link=None, height=None, level=1):
        """Строка карточки: подпись слева, значение справа; тонкий разделитель снизу, текст не прилипает к линиям."""
        self._fill_row('BCDEF', fill, Border(bottom=SEP))
        lf = Font(name='Arial', size=11, bold=(level == 1), color='000000')   # подпись не мельче значения; подуровень — обычным и с отступом
        self.cell('B', label, lf, fill, Alignment(vertical='center', wrap_text=True, indent=1 if level == 1 else 3))
        self.ws.merge_cells(f'C{self.r}:F{self.r}')
        c = self.cell('C', value, Font(name='Arial', size=11, color=DARK), fill, Alignment(vertical='center', wrap_text=True, indent=1))
        if link:
            c.hyperlink = link; c.font = Font(name='Arial', size=11, color=ORANGE2, underline='single')
        self.ws.row_dimensions[self.r].height = height or row_height(str(value), 92)
        self.r += 1

    def table(self, headers, rows, spans, num=(), links=None, fills=None, center=()):
        """Таблица в стиле карточек: шапка — белый жирный на оранжевом; строки на светлом фоне с тонким светлым разделителем;
        первая колонка — подпись строки (чёрный жирный, как в карточках); числа справа. Без чёрной сетки.
        spans — для каждой колонки строка столбцов листа, например 'B', 'C', 'EF' (объединяются)."""
        def put(i, v, font, fill, al, border):
            cols = spans[i]
            if len(cols) > 1: self.ws.merge_cells(f'{cols[0]}{self.r}:{cols[-1]}{self.r}')
            for col in cols:
                cc = self.ws[f'{col}{self.r}']
                cc.border = border
                if fill: cc.fill = PatternFill('solid', fgColor=fill)
            return self.cell(cols[0], v, font, fill, al)
        white = Side(style='thin', color='FFFFFF')
        for i, h in enumerate(headers):
            put(i, h, Font(name='Arial', size=11, bold=True, color='FFFFFF'), ORANGE,
                Alignment(horizontal='left' if i == 0 else 'center', vertical='center', wrap_text=True, indent=1 if i == 0 else 0),
                Border(left=white, right=white))
        self.ws.row_dimensions[self.r].height = 24
        self.r += 1
        for k, row in enumerate(rows):
            for i, v in enumerate(row):
                isnum, sev = i in num, (fills or {}).get((k, i))
                fill = sev or F_CARD
                if i == 0 and not sev: font = Font(name='Arial', size=11, bold=True, color='000000')
                else: font = Font(name='Arial', size=11, bold=bool(sev), color='FFFFFF' if sev == ORANGE else DARK)
                al = Alignment(horizontal='center' if i in center else ('right' if isnum else 'left'), vertical='center', wrap_text=True,
                               indent=0 if i in center else 1)   # отступ от края и у чисел
                c = put(i, v, font, fill, al, Border(bottom=SEP))
                if isnum and isinstance(v, (int, float)) and not isinstance(v, bool): c.number_format = '#,##0' if isinstance(v, int) else '0%'
                if links and (k, i) in links:
                    c.hyperlink = links[(k, i)]; c.font = Font(name='Arial', size=11 if i else 10, bold=(i == 0), color=ORANGE2, underline='single')
            width = lambda cols: sum(self.ws.column_dimensions[c].width for c in cols) * 1.05
            shown = lambda v: f'{v:.0%}' if isinstance(v, float) else (f'{v:,}' if isinstance(v, int) else str(v))
            self.ws.row_dimensions[self.r].height = max(row_height(shown(v), int(width(spans[i])) - 3) for i, v in enumerate(row))
            self.r += 1

    def note(self, text):
        self.ws.merge_cells(f'B{self.r}:F{self.r}')
        self._fill_row('BCDEF', F_NOTE, Border())
        self.cell('B', text, Font(name='Arial', size=10, italic=True, color=DARK), F_NOTE, Alignment(vertical='center', wrap_text=True, indent=1))
        self.ws.row_dimensions[self.r].height = 15 * (len(text) // 115 + 1) + 12
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
    for i, h in enumerate((32.25, 23.25, 14, 8), start=1): ws.row_dimensions[i].height = h
    if os.path.exists(LOGO):
        from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
        from openpyxl.drawing.xdr import XDRPositiveSize2D
        img = XLImage(LOGO)
        cx, cy = 2000250, 457200                     # ~210×48 px: меньше прежнего, крупнее образца (EMU)
        img.anchor = OneCellAnchor(_from=AnchorMarker(col=1, colOff=1905, row=0, rowOff=123825), ext=XDRPositiveSize2D(cx, cy))
        ws.add_image(img)
    S.cell('F', COMPANY_URL, Font(name='Arial', size=11, color=GREY), align=Alignment(horizontal='right', vertical='center'), row=1)
    ws['F1'].hyperlink = COMPANY_URL; ws['F1'].font = Font(name='Arial', size=11, color=GREY)
    S.r = 5
    ws.merge_cells('B5:F5')
    S.cell('B', f'NX LOG DETECTIVE — САЙТ {site.upper()}', Font(name='Montserrat', size=16, bold=True, color=ORANGE)); ws.row_dimensions[5].height = 30
    ws.merge_cells('B6:F6')
    S.cell('B', 'Анализ логов сервера: что происходит на сайте, кто на него ходит и что работает не так', Font(name='Comfortaa', size=11, bold=True, color=GREY), row=6)
    ws.row_dimensions[6].height = 20
    S.r = 8
    kind = "ПОВТОРНАЯ ПРОВЕРКА" if res.get('prev_period') else 'ПЕРВИЧНАЯ ПРОВЕРКА'
    S.cell('B', kind, Font(name='Arial', size=11, bold=True, color='FFFFFF'), ORANGE, Alignment(horizontal='center', vertical='center'))
    ws.merge_cells('C8:F8')
    sub = f"Отчёт от {ru_date(date.today())} · NX Log Detective {VERSION}"
    if res.get('prev_period'): sub = f"Сравнение с проверкой за {ru_date(res['prev_period'][0])} — {ru_date(res['prev_period'][1])} · " + sub
    S.cell('C', sub, Font(name='Arial', size=10, color=INK), align=Alignment(vertical='center', indent=1))
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
    # --- что за сайт (только то, что видно по логу)
    sp = res.get('site_profile') or {}
    if sp.get('назначение') and sp.get('назначение') != 'не определено':
        S.section('Что за сайт')
        S.pair('Назначение', sp['назначение'])
        S.pair('Размер', f"{sp['размер']} — {ru_num(sp['страниц'])} {plural(sp['страниц'], 'страница', 'страницы', 'страниц')} открывали люди")
        S.pair('Аудитория', sp['аудитория'])
        if sp.get('признаки'):
            S.note('Как определили: ' + '; '.join(sp['признаки']) + '.')
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
    S.table(['Кто', 'Визитов', 'Доля', 'Кто это'], [(g, int(v), v / total, cap(note)) for g, v, note in grp], ['B', 'C', 'D', 'EF'], num=(1, 2))
    S.r += 1
    cl = res.get('cleaning', {})
    S.pair('Просмотров страниц', ru_num(sm.get('Просмотров страниц людьми', 0)))
    wv = cl.get('Визитов людей во встроенных браузерах приложений', 0)
    if wv: S.pair('Во встроенных браузерах', f"{ru_num(wv)} визитов — люди открыли сайт внутри приложений (соцсети, мессенджеры, игры)")
    ppl, bots, own = sm.get('Принято от людей', 0), sm.get('Принято от ботов', 0), sm.get('Принято от своих (тесты)', 0)
    S.pair('Отправок форм', f"{ru_num(sm.get('Отправок целей всего', 0))} — все отправки, включая непринятые, ботов и тесты")
    S.pair('Заявок от людей', f"{ru_num(ppl)} — приняты сервером", level=2)
    if bots: S.pair('Заявок от ботов', f"{ru_num(bots)} — приняты сервером, но фальшивые", level=2)
    if own: S.pair('Тестов своих', f"{ru_num(own)} — сотрудники и подрядчик, в заявки не входят", level=2)
    cr = sm.get('Конверсия людей (визит → принятая цель), %', 0)
    S.pair('Конверсия людей', f"{str(cr).replace('.', ',')}% — одна заявка на {ru_num(round(100 / cr))} визитов" if cr else 'Заявок от людей нет')
    raw, clean = cl.get('Просмотров у людей до очистки'), cl.get('Просмотров у людей после очистки')
    how = ('Как считали. Все визиты и просмотры людей в отчёте — после очистки: склеены двойные загрузки одной страницы и переадресации, '
           'подгрузки форм и блоков не считаются просмотрами, боты и свои отделены. Поэтому цифры меньше сырых')
    if raw and clean: how += f" (просмотров {ru_short(raw)} → {ru_short(clean)})"
    how += ' и ближе к Метрике. Заявкой считается отправка формы, которую сервер принял.'
    S.note(how)
    # --- проблемы: три строки-карточки со счётчиками и ссылка под ними (без шапки)
    S.section('Проблемы')
    act = [x for x in res['findings'] if x.get('статус') != 'отмечено как норма']
    cnt = {k: sum(1 for x in act if x['важность'] == k) for k in ('Срочно', 'Важно', 'К сведению')}
    pr = sheet_names.get('Проблемы', 'Проблемы')
    for k, color in (('Срочно', ORANGE), ('Важно', DARK), ('К сведению', DARK)):
        label = {'Срочно': 'Приоритетные', 'Важно': 'Важные', 'К сведению': 'Остальные'}[k]
        S._fill_row('BCDEF', F_CARD, Border(bottom=SEP))
        S.cell('B', label, Font(name='Arial', size=11, bold=True, color='000000'), F_CARD, Alignment(vertical='center', indent=1))
        S.cell('C', cnt[k], Font(name='Arial', size=12 if k == 'Срочно' else 11, bold=(k == 'Срочно'), color=color), F_CARD, Alignment(horizontal='left', vertical='center', indent=1))
        ws.merge_cells(f'C{S.r}:F{S.r}')
        ws.row_dimensions[S.r].height = 22
        S.r += 1
    c = S.cell('B', f'Факты, доказательства и шаги исправления — на листе «{pr}» →', align=Alignment(vertical='center', indent=1))
    ws.merge_cells(f'B{S.r}:F{S.r}')
    c.hyperlink = f"#'{pr}'!A1"; c.font = Font(name='Arial', size=10, italic=True, color=ORANGE2, underline='single')
    ws.row_dimensions[S.r].height = 24
    S.r += 1

    def listing(rows):
        """Список «ссылка — пояснение» без шапки и заливок, как в первом варианте."""
        for name, note, link in rows:
            c = S.cell('B', name, align=Alignment(vertical='center', wrap_text=True, indent=1))   # длинные названия переносятся
            if link:
                c.hyperlink = link; c.font = Font(name='Arial', size=11, bold=True, color=ORANGE2, underline='single')
            else:
                c.font = Font(name='Arial', size=11, bold=True, color='000000')
            ws.merge_cells(f'C{S.r}:F{S.r}')
            S.cell('C', cap(note), Font(name='Arial', size=11, color=INK), align=Alignment(vertical='center', wrap_text=True, indent=1))
            ws.row_dimensions[S.r].height = max(18, row_height(name, 28) - 4, row_height(cap(note), 88) - 4)
            S.r += 1

    # --- содержимое документа (листы этого файла, включая обзор)
    S.section('Содержимое документа')
    rows = [(title, 'этот лист: паспорт проверки, технологии, трафик', f"#'{title}'!A1")]
    for name, real in sheet_names.items():
        if real == title or real.startswith('_'): continue
        rows.append((real, SHEET_NOTES.get(real, ''), f"#'{real}'!A1"))
    listing(rows)
    # --- структура отчёта (файлы)
    S.section('Структура отчёта')
    rows = [('NXLD_01_Overview.xlsx', 'этот файл: общий обзор, устройство сайта, трафик, все проблемы', None)]
    for b, f in BLOCK_FILES.items():
        if b == 'Общий анализ' or b not in res['selected']: continue
        rows.append((f, FILE_NOTES.get(b, ''), f))
    rows += [('NXLD_Redmine.textile', 'связный отчёт Детектива для задачи в Redmine', None),
             ('*.snapshot.json', 'снимок проверки — понадобится для повторной проверки', None)]
    listing(rows)
    # печать
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f'A1:G{S.r}'
    wb.active = 0
    return ws
