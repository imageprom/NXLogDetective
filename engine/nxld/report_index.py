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
RED = 'C00000'   # ошибочные ответы (4xx/5xx, кроме 499) — красным
INK = '404040'   # серый текст на белом фоне — контрастнее фирменного #666666
F_CARD, F_NOTE, F_HEAD = 'EFEFEF', 'FCE5CD', 'E5E5E5'
# тысячи — всегда пробелом, независимо от языка Excel (запятая путается с десятичным знаком)
NUM_FMT = '[>=1000000]#\\ ###\\ ###;[>=1000]#\\ ###;0'
LOGO = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'brand', 'logo_cybermechanica.png')
COMPANY_URL = 'https://cybermechanica.ru'
MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
BLOCK_FILES = {'Общий анализ': 'NXLD_01_Overview.xlsx', 'Ошибки': 'NXLD_02_Errors.xlsx', 'Нагрузка и безопасность': 'NXLD_03_Load_Security.xlsx',
               'Боты': 'NXLD_04_Bots.xlsx', 'Маркетинг': 'NXLD_05_Marketing.xlsx', 'SEO': 'NXLD_06_SEO.xlsx'}
FILE_NOTES = {'Ошибки': 'ошибки сервера, сбои, битые ссылки и входы, отсутствующие файлы, error-лог',
              'Нагрузка и безопасность': 'нагрузка, тяжёлые файлы, сканеры, служебные разделы, админка',
              'Боты': 'роботы и боты, подделки, спам форм, операторы с доказательствами',
              'Маркетинг': 'каналы, реклама, кампании и площадки, конверсии и разрезы',
              'SEO': 'как поисковики видят сайт: обход, файлы для роботов, паразитные адреса, поисковые ошибки, органика, ИИ'}
# пояснения к листам оглавления (пока список листов Overview не утверждён — по текущим именам)
SHEET_NOTES = {'Проблемы': 'все найденные проблемы по важности', 'Логи': 'какие файлы логов разобраны', 'Файлы': 'все файлы сайта, кроме страниц: кто забирает, откуда, коды', 'Анатомия сайта': 'как устроен сайт: закрытые зоны, каталоги, разделы, формы, папки, медиа, служебные файлы, параметры',
               'Карта — формы и цели': 'адреса отправки форм и как понять, что заявка принята', 'Динамические блоки': 'что браузер подгружает сам сразу после страницы: формы и окна, встроенные страницы, подгрузка фильтра',
               'Карта — служебные файлы': 'robots.txt, sitemap, фиды и кто их запрашивает', 'Активность': 'сводка: каналы, посетители, сотрудники, системы мониторинга, роботы, боты по сигнатурам', 'Журнал активности': 'визиты, уникальные IP и заявки по дням для людей, роботов, ботов и своих',
               'Разделы': 'запрашиваемые разделы: существуют ли, интерес, заявки, ошибки, каналы', 'Типы страниц': 'страницы одного вида по шаблону адреса', 'Страницы': 'TOP500 самых посещаемых страниц: заявки, ошибки, каналы',
               'Фасеты': 'что люди выбирают в фильтре каталога', 'Конверсии': 'все отправки форм с результатом', 'GET-отправки': 'персональные данные в адресах страниц', 'Точки приёма данных': 'куда сайт принимает данные: формы, вход, фильтры и поиск', 'POST-отправки': 'все POST-отправки, включая сканеры',
               'Анатомия — подгружаемые блоки': 'блоки, которые страница подгружает после открытия',
               'Параметры запросов': 'каждый параметр в адресах: группа, запросы, люди, где встречается',
               'IP': 'важные адреса: спам, подделки, разведка, свои',
               'Конструкты в адресах': 'запросы, которые не являются адресом: шаблоны JavaScript, склейка строк, кавычки — кто и откуда',
               'Битые адреса из скриптов': 'адреса, которые скрипты страниц собрали с ошибкой, и страницы, где это происходит',
               'Исследователи сайта': 'живые люди, которые систематически пробуют служебные адреса'}

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
    return 22 + 15 * (lines - 1) + (5 if lines > 1 else 0)   # запас на многострочный текст: не упирается в границы


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
SEV_STYLE = {'Тревога': ('C00000', 'FFFFFF'), 'Срочно': (ORANGE, 'FFFFFF'), 'Важно': (F_NOTE, DARK), 'К сведению': ('F3F3F3', DARK), 'Замечание': ('F3F3F3', DARK)}
SPANS = {'B': 'B', 'C': 'C', 'D': 'D', 'E': 'E', 'F': 'F'}


class Sheet:
    """Раскладка: A — поле, B — подписи / первая колонка таблиц, C:F — значения."""
    def __init__(self, ws):
        self.ws, self.r = ws, 1
        self.psize = 11   # шрифт строк карточек (pair); 9 — когда карточек много (04 «Разыскиваются»)
        self.tsize = 11   # шрифт таблиц; 9 — оформление большой таблицы (лист целиком или таблица, которая не влезает)
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

    def section(self, title, sub=''):
        """Заголовок блока; sub — подпись под ним: что в блоке и как читать."""
        self.r += 1
        self.ws.merge_cells(f'B{self.r}:F{self.r}')
        self.cell('B', title.upper(), Font(name='Montserrat', size=12, bold=True, color=ORANGE), align=Alignment(vertical='center'))
        for col in 'BCDEF':
            self.ws[f'{col}{self.r}'].border = Border(bottom=thin)
        self.ws.row_dimensions[self.r].height = 26
        self.r += 1
        if sub:
            self.ws.merge_cells(f'B{self.r}:F{self.r}')
            self.cell('B', sub, Font(name='Arial', size=10, italic=True, color='666666'), align=Alignment(vertical='center', wrap_text=True, indent=1))
            self.ws.row_dimensions[self.r].height = row_height(sub, 115)
            self.r += 1

    def _fill_row(self, cols, fill, border):
        for col in cols:
            c = self.ws[f'{col}{self.r}']
            if fill: c.fill = PatternFill('solid', fgColor=fill)
            c.border = border

    def pair(self, label, value, fill=F_CARD, link=None, height=None, level=1):
        """Строка карточки: подпись слева, значение справа; тонкий разделитель снизу, текст не прилипает к линиям."""
        self._fill_row('BCDEF', fill, Border(bottom=SEP))
        ps = self.psize
        lf = Font(name='Arial', size=ps, bold=(level == 1), color='000000')   # подпись не мельче значения; подуровень — обычным и с отступом
        self.cell('B', label, lf, fill, Alignment(vertical='center', wrap_text=True, indent=1 if level == 1 else 3))
        self.ws.merge_cells(f'C{self.r}:F{self.r}')
        c = self.cell('C', value, Font(name='Arial', size=ps, color=DARK), fill, Alignment(vertical='center', wrap_text=True, indent=1))
        if link:
            c.hyperlink = link; c.font = Font(name='Arial', size=ps, color=ORANGE2, underline='single')
        h_ = max(row_height(str(value), int(86 * 11 / ps)), row_height(str(label), int(30 * 11 / ps)))
        if ps < 11:   # мелкий шрифт — и строки ниже: 12 пт на строку вместо 15
            lines_ = (h_ - 22 - (5 if h_ > 22 else 0)) / 15 + 1
            h_ = 18 + 12 * (lines_ - 1) + (4 if lines_ > 1 else 0)
        self.ws.row_dimensions[self.r].height = height or h_
        self.r += 1

    def table(self, headers, rows, spans, num=(), links=None, fills=None, center=(), body=None, wrap=1.05):
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
        width = lambda cols: sum(self.ws.column_dimensions[c].width for c in cols) * wrap
        shown = lambda v: f'{v:.0%}' if isinstance(v, float) else (f'{v:,}' if isinstance(v, int) else str(v))
        # не влезает (слово шапки шире колонки или ячейка больше чем в 3 строки) — оформление большой таблицы, шрифт 9
        sz = self.tsize
        if sz > 9:
            longest = lambda t: max((len(w_) for w_ in str(t).replace('\n', ' ').split()), default=0)
            tight = any(longest(h) * 1.1 > width(spans[i]) - 1 for i, h in enumerate(headers)) or \
                    any(row_height(shown(v), int(width(spans[i])) - 3) > 22 + 15 * 2 + 5 for row in rows for i, v in enumerate(row))
            if tight: sz = 9
        k_ = 11 / sz   # во сколько раз больше знаков помещается при мелком шрифте
        hh = max(row_height(str(h), int((width(spans[i]) - 2) * k_)) for i, h in enumerate(headers))   # шапка — по самому длинному названию
        for i, h in enumerate(headers):
            put(i, h, Font(name='Arial', size=sz, bold=True, color='FFFFFF'), ORANGE,
                Alignment(horizontal='left' if i == 0 else 'center', vertical='center', wrap_text=True, indent=1 if i == 0 else 0),
                Border(left=white, right=white))
        self.ws.row_dimensions[self.r].height = max(24, hh * sz / 11 + 4)
        self.r += 1
        for k, row in enumerate(rows):
            for i, v in enumerate(row):
                isnum, sev = i in num, (fills or {}).get((k, i))
                fill = sev or body or F_CARD
                if i == 0 and not sev: font = Font(name='Arial', size=sz, bold=True, color='000000')
                else: font = Font(name='Arial', size=sz, bold=bool(sev), color='FFFFFF' if sev in (ORANGE, 'C00000') else DARK)
                al = Alignment(horizontal='center' if i in center else ('right' if isnum else 'left'), vertical='center', wrap_text=True,
                               indent=0 if i in center else 1)   # отступ от края и у чисел
                c = put(i, v, font, fill, al, Border(bottom=SEP))
                if isnum and isinstance(v, (int, float)) and not isinstance(v, bool): c.number_format = NUM_FMT if isinstance(v, int) or (hasattr(v, 'is_integer') and float(v).is_integer() and not isinstance(v, float)) else '0%'
                if links and (k, i) in links:
                    c.hyperlink = links[(k, i)]; c.font = Font(name='Arial', size=sz if i else sz - 1, bold=(i == 0), color=ORANGE2, underline='single')
            self.ws.row_dimensions[self.r].height = max(row_height(shown(v), int((width(spans[i]) - 3) * k_)) for i, v in enumerate(row)) * (1 if sz >= 11 else 0.85)
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
        rows.append(('Присланные адреса', f"{n} {plural(n, 'IP проверен', 'IP проверены', 'IP проверены')} — результат на листе «Подозреваемые» в NXLD_04_Bots.xlsx"))
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


def brand_header(ws, S, res, title, subtitle, last='F'):
    """Шапка первого листа каждого файла отчёта: логотип, адрес компании, заголовок, подзаголовок, плашка проверки и дата.
    last — последняя колонка листа (F на обычных, I на широких сводках)."""
    for i, h in enumerate((32.25, 23.25, 14, 8), start=1): ws.row_dimensions[i].height = h
    if os.path.exists(LOGO):
        from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
        from openpyxl.drawing.xdr import XDRPositiveSize2D
        img = XLImage(LOGO)
        cx, cy = 2000250, 457200                     # ~210×48 px: меньше прежнего, крупнее образца (EMU)
        img.anchor = OneCellAnchor(_from=AnchorMarker(col=1, colOff=1905, row=0, rowOff=123825), ext=XDRPositiveSize2D(cx, cy))
        ws.add_image(img)
    S.cell(last, COMPANY_URL, Font(name='Arial', size=11, color=GREY), align=Alignment(horizontal='right', vertical='center'), row=1)
    ws[f'{last}1'].hyperlink = COMPANY_URL; ws[f'{last}1'].font = Font(name='Arial', size=11, color=GREY)
    ws.merge_cells(f'B5:{last}5')
    S.cell('B', title, Font(name='Montserrat', size=16, bold=True, color=ORANGE), row=5); ws.row_dimensions[5].height = 30
    ws.merge_cells(f'B6:{last}6')
    S.cell('B', subtitle, Font(name='Comfortaa', size=11, bold=True, color=GREY), row=6)
    ws.row_dimensions[6].height = 20
    kind = "ПОВТОРНАЯ ПРОВЕРКА" if res.get('prev_period') else 'ПЕРВИЧНАЯ ПРОВЕРКА'
    S.cell('B', kind, Font(name='Arial', size=11, bold=True, color='FFFFFF'), ORANGE, Alignment(horizontal='center', vertical='center'), row=8)
    ws.merge_cells(f'C8:{last}8')
    sub = f"Отчёт от {ru_date(date.today())} · NX Log Detective {VERSION}"
    if res.get('prev_period'): sub = f"Сравнение с проверкой за {ru_date(res['prev_period'][0])} — {ru_date(res['prev_period'][1])} · " + sub
    S.cell('C', sub, Font(name='Arial', size=10, color=INK), align=Alignment(vertical='center', indent=1), row=8)
    ws.row_dimensions[8].height = 24
    S.r = 9


WIDE_COLS = 'BCDEFGHI'
WIDE_WIDTHS = dict(A=2.5, B=30, C=24, D=14, E=12, F=12, G=12, H=13, I=20, J=2.5)
F_TOTAL = 'E5E5E5'


class Wide(Sheet):
    """Сводный лист пошире (B:I): блоки с подписями, таблицы до восьми колонок, «Итого», ссылки под блоком.
    Общий для «Активности», «Обзора» файлов блоков и других сводок."""
    def __init__(self, ws):
        super().__init__(ws)
        for col, w in WIDE_WIDTHS.items(): ws.column_dimensions[col].width = w

    def section(self, title, sub=''):
        self.r += 1
        self.ws.merge_cells(f'B{self.r}:I{self.r}')
        self.cell('B', title.upper(), Font(name='Montserrat', size=12, bold=True, color=ORANGE), align=Alignment(vertical='center'))
        for col in WIDE_COLS: self.ws[f'{col}{self.r}'].border = Border(bottom=thin)
        self.ws.row_dimensions[self.r].height = 26
        self.r += 1
        if sub:
            self.ws.merge_cells(f'B{self.r}:I{self.r}')
            self.cell('B', sub, Font(name='Arial', size=10, italic=True, color='666666'), align=Alignment(vertical='center', wrap_text=True, indent=1))
            self.ws.row_dimensions[self.r].height = row_height(sub, 125)
            self.r += 1

    def note(self, text):
        self.ws.merge_cells(f'B{self.r}:I{self.r}')
        for col in WIDE_COLS: self.ws[f'{col}{self.r}'].fill = PatternFill('solid', fgColor=F_NOTE)
        self.cell('B', text, Font(name='Arial', size=10, italic=True, color=DARK), F_NOTE, Alignment(vertical='center', wrap_text=True, indent=1))
        self.ws.row_dimensions[self.r].height = row_height(text, 150)
        self.r += 1

    def table(self, headers, rows, spans, **kw):
        h0 = self.r
        super().table(headers, rows, spans, **kw)
        if any(len(h) > 11 for h in headers): self.ws.row_dimensions[h0].height = max(32, self.ws.row_dimensions[h0].height or 0)   # длинные названия — в две строки и больше

    def link(self, text, target, names=None):
        """Ссылка под блоком: на лист этого файла (строка) или на лист другого файла (кортеж «файл, лист»)."""
        if isinstance(target, tuple):
            file_, sheet_ = target
            ref, label = f"{file_}#'{sheet_}'!A1", f'{text}: {file_}, лист «{sheet_}» →'
        else:
            if names is not None and target not in names: return
            ref, label = f"#'{target}'!A1", f'{text}: лист «{target}» →'
        self.ws.merge_cells(f'B{self.r}:I{self.r}')
        c = self.cell('B', label, align=Alignment(vertical='center', indent=1))
        c.hyperlink = ref; c.font = Font(name='Arial', size=10, color=ORANGE2, underline='single')
        self.ws.row_dimensions[self.r].height = 20
        self.r += 1

    def related(self, res, block):
        """Блок «Связанное в других отчётах»: ссылки на листы других файлов этой проверки (каталог sheets.RELATED)."""
        from .sheets import RELATED
        rows = [(t, BLOCK_FILES[b], sh) for t, b, sh in RELATED.get(block, []) if b in (res.get('selected') or ()) and b in BLOCK_FILES]
        if not rows: return
        self.section('Связанное в других отчётах', 'Темы, которые разобраны в соседних файлах проверки.')
        for t, f, sh in rows: self.link(t, (f, sh))

    def alarm(self, n, names=None):
        """Плашка «Тревога» под шапкой Обзора: сколько тревог в этом файле и ссылка на карточки. Нет тревог — нет плашки."""
        if not n: return
        self.r += 1
        self.ws.merge_cells(f'B{self.r}:I{self.r}')
        for col in WIDE_COLS: self.ws[f'{col}{self.r}'].fill = PatternFill('solid', fgColor='C00000')
        word = 'тревога' if n % 10 == 1 and n % 100 != 11 else ('тревоги' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'тревог')
        c = self.cell('B', f'{n} {word}: подтверждённый вред, который идёт сейчас. Карточки — первыми на листе «Проблемы» →',
                      Font(name='Arial', size=11, bold=True, color='FFFFFF'), 'C00000', Alignment(vertical='center', indent=1))
        c.hyperlink = "#'Проблемы'!A1"
        self.ws.row_dimensions[self.r].height = 24
        self.r += 1

    def kpis(self, items):
        """Строка ключевых цифр: подпись мелко, число крупно — до восьми, по колонкам B:I."""
        cols = WIDE_COLS[:len(items)]
        for col, (lab, val) in zip(cols, items):
            a = self.cell(col, lab, Font(name='Arial', size=9, color=INK), align=Alignment(horizontal='center', vertical='bottom', wrap_text=True))
            b = self.cell(col, val, Font(name='Arial', size=16, bold=True, color='000000'), align=Alignment(horizontal='center', vertical='center'), row=self.r + 1)
            if isinstance(val, int) and val >= 1000: b.number_format = NUM_FMT
        self.ws.row_dimensions[self.r].height = 28; self.ws.row_dimensions[self.r + 1].height = 26
        self.r += 2

    def total(self, n=8):
        """Последняя строка таблицы — «Итого»: жирным на сером."""
        r = self.r - 1
        for col in WIDE_COLS[:n]:
            c = self.ws[f'{col}{r}']
            c.font = Font(name='Arial', size=c.font.sz if c.font and c.font.sz else 11, bold=True, color='000000'); c.fill = PatternFill('solid', fgColor=F_TOTAL)

    def red(self, rows_from, col):
        for r in range(rows_from, self.r):
            c = self.ws[f'{col}{r}']
            if c.value: c.font = Font(name='Arial', size=c.font.sz if c.font and c.font.sz else 11, color=RED)


SHOW_AUDIENCE = False
# строка «Подозрительные лица» в таблице «Трафик и заявки» — новая строка на сводке Обзора: выключена до согласования структуры
SHOW_SUSPECTS = False   # «Основная страна» и предупреждение на сводке 01 — выключено до согласования; данные (res['audience']) считаются


def build_index(wb, res, sheet_names, title='Обзор'):
    ws = wb.create_sheet(title, 0)
    S = Sheet(ws)
    inv, m, sm = res['inventory'], res['site_map'], res['summary'].get('Общий анализ', {})
    site = (m.get('site_hosts') or ['?'])[0]
    brand_header(ws, S, res, f'NX LOG DETECTIVE — САЙТ {site.upper()}', 'Анализ логов сервера: что происходит на сайте, кто на него ходит и что работает не так')
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
        S.section('О сайте', 'Что за сайт — только то, что видно по логам.')
        S.pair('Назначение', sp['назначение'])
        S.pair('Размер', f"{sp['размер']} — {ru_num(sp['страниц'])} {plural(sp['страниц'], 'страница', 'страницы', 'страниц')} открывали люди")
        S.pair('Аудитория', sp['аудитория'])
        if sp.get('признаки'):
            S.note('Как определили: ' + '; '.join(sp['признаки']) + '.')
    # --- технологии
    S.section('Технологии', 'Сервер, движок и хостинг — по путям файлов и ответам сервера в логах.')
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
    # --- трафик и заявки
    S.section('Трафик и заявки', 'Визиты за период по группам и заявки, отправленные через формы сайта.')
    grp = [('Люди', sm.get('Визитов людей', 0), f"{ru_num(sm.get('IP людей', 0))} адресов; {res.get('mobile_share') or 0:.0f}% с телефонов".replace('.', ',')),
           ('Роботы', sm.get('Визитов: Роботы', 0), 'поисковики, сервисы, SEO-боты — честно себя называют'),
           ('Системы мониторинга', sm.get('Визитов: Системы мониторинга', 0), 'проверяют, работает ли сайт; не обязательно наши'),
           ('Утилиты', sm.get('Визитов: Утилиты', 0), 'curl, wget, Python, PHP и другие утилиты: разработчик, интеграция или сканер'),
           ('Боты', sm.get('Визитов: Боты', 0), 'притворяются браузерами, спамят формы, сканируют'),
           ('Свои', sm.get('Визитов: Свои', 0), 'сотрудники: успешно работали в админке'),
           ('Внешние сайты', sm.get('Визитов: Внешние сайты', 0), 'наши файлы показываются на других сайтах (хотлинк): трафик тратится на чужих посетителей')]
    if SHOW_SUSPECTS:
        grp.append(('Подозрительные лица', sm.get('Визитов: Подозрительные лица', 0), 'только файлы: улики за людей и за бота противоречат друг другу или их нет'))
    total = sum(v for _, v, _ in grp) or 1
    S.table(['Кто', 'Визитов', 'Доля', 'Кто это'], [(g, int(v), v / total, cap(note)) for g, v, note in grp], ['B', 'C', 'D', 'EF'], num=(1, 2))
    S.r += 1
    au = res.get('audience') if SHOW_AUDIENCE else None
    if au:   # доля людей из страны основной аудитории: низкая — в «люди» могли попасть боты
        S.pair('Основная страна', f"{au['страна']} — {str(au['доля']).replace('.', ',')}% визитов людей")
        if au['предупреждение']:
            S.note(f"Внимание: из страны основной аудитории меньше {au['порог']}% визитов людей. Проверить, не попали ли в «Людей» боты и скраперы.")
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
    S.section('Проблемы', 'Сколько проблем найдено и насколько они важны. Каждая расписана на листе «Проблемы».')
    act = [x for x in res['findings'] if x.get('статус') != 'отмечено как норма']
    cnt = {k: sum(1 for x in act if x['важность'] == k) for k in ('Тревога', 'Срочно', 'Важно', 'К сведению', 'Замечание')}
    pr = sheet_names.get('Проблемы', 'Проблемы')
    for k, color in ((('Тревога', 'C00000'),) if cnt['Тревога'] else ()) + (('Срочно', ORANGE), ('Важно', DARK), ('К сведению', DARK), ('Замечание', DARK)):
        if k == 'Замечание' and not cnt[k]: continue
        label = {'Тревога': 'Тревога', 'Срочно': 'Приоритетные', 'Важно': 'Важные', 'К сведению': 'Остальные', 'Замечание': 'Замечания'}[k]
        S._fill_row('BCDEF', F_CARD, Border(bottom=SEP))
        S.cell('B', label, Font(name='Arial', size=11, bold=True, color='000000'), F_CARD, Alignment(vertical='center', indent=1))
        S.cell('C', cnt[k], Font(name='Arial', size=12 if k in ('Тревога', 'Срочно') else 11, bold=(k in ('Тревога', 'Срочно')), color=color), F_CARD, Alignment(horizontal='left', vertical='center', indent=1))
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
    S.section('Содержимое документа', 'Листы этого файла и что на каждом из них.')
    rows = [(title, 'этот лист: паспорт проверки, технологии, трафик', f"#'{title}'!A1")]
    for name, real in sheet_names.items():
        if real == title or real.startswith('_'): continue
        rows.append((real, SHEET_NOTES.get(real, ''), f"#'{real}'!A1"))
    listing(rows)
    # --- структура отчёта (файлы)
    S.section('Структура отчёта', 'Файлы, из которых состоит отчёт, и что в каждом из них.')
    rows = [('NXLD_01_Overview.xlsx', 'этот файл: общий обзор, устройство сайта, трафик, все проблемы', None)]
    for b, f in BLOCK_FILES.items():
        if b == 'Общий анализ' or b not in res['selected']: continue
        rows.append((f, FILE_NOTES.get(b, ''), f))
    rows += [('NXLD_Redmine.textile', 'связный отчёт Детектива для задачи в Redmine (если его нет — NXLD_Redmine_черновик.textile, сухой черновик движка)', None),
             ('*.snapshot.json', 'снимок проверки — понадобится для повторной проверки', None)]
    st_ = res.get('stix') or {}
    if st_:
        rows.append(('*.stix.json', f"выгрузка STIX 2.1: {st_.get('сигнатур', 0)} сигнатур, {st_.get('дел', 0)} дел, {st_.get('IP', 0)} IP и связи между ними. "
                                   'STIX — открытый стандарт OASIS для обмена данными об угрозах: файл принимают платформы анализа угроз (OpenCTI, MISP и другие), '
                                   'открыть его можно и в текстовом редакторе. Документация: https://docs.oasis-open.org/cti/stix/v2.1/stix-v2.1.html', None))
    listing(rows)
    # печать
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f'A1:G{S.r}'
    wb.active = 0
    return ws
