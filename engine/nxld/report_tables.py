"""NXLD: простые листы-таблицы в общем стиле (заголовок, пояснение, оранжевая шапка, фильтр, закреплённая шапка)."""
import numbers
import pandas as pd
from openpyxl.styles import Font, Alignment, Border, PatternFill, Side
from .report_index import ORANGE, INK, F_NOTE, NUM_FMT

SEP = Side(style='thin', color='D9D9D9')
WHITE = Side(style='thin', color='FFFFFF')


def data_sheet(wb, name, df, title, note='', widths=None, wrap=(), fill_rule=None, bold_rule=None, center=(), sort_by=None):
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
    if note:
        ws['B2'] = note; ws['B2'].font = Font(name='Arial', size=10, color=INK)
        ws['B2'].alignment = Alignment(vertical='center', wrap_text=False)
    X = 1   # сдвиг колонок
    H = 4
    for j, c in enumerate(cols, 1):
        cell = ws.cell(H, j + X, c)
        cell.font = Font(name='Arial', size=10, bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor=ORANGE)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = Border(left=WHITE, right=WHITE)
    ws.cell(H, 1 + X)
    ws.row_dimensions[H].height = 32
    for i, row in enumerate(df.itertuples(index=False), H + 1):
        for j, v in enumerate(row, 1):
            if isinstance(v, float) and pd.isna(v): v = None
            if hasattr(v, 'item'): v = v.item()
            cell = ws.cell(i, j + X, v)
            col = cols[j - 1]
            isnum = isinstance(v, numbers.Number) and not isinstance(v, bool)
            cell.font = Font(name='Arial', size=10, bold=bool(bold_rule and bold_rule(col, v)), color='000000')
            hz = 'center' if col in center else ('right' if isnum else 'left')
            cell.alignment = Alignment(horizontal=hz, vertical='top', wrap_text=col in wrap, indent=1 if hz != 'center' else 0)
            if isnum and isinstance(v, int) and abs(v) >= 1000: cell.number_format = NUM_FMT
            cell.border = Border(bottom=SEP)
            f = fill_rule(col, v) if fill_rule else None
            if f: cell.fill = PatternFill('solid', fgColor=f)
    for j, c in enumerate(cols, 1):
        letter = ws.cell(H, j + X).column_letter
        ws.column_dimensions[letter].width = (widths or {}).get(c) or min(45, max(10, len(str(c)) + 2, int(df[c].astype(str).str.len().quantile(0.9)) + 2 if len(df) else 10))
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
        'Кто': C['группа'].astype(str).replace({'Свои': 'Свои (сотрудники)'}),
        'Форма': C['цель'].astype(str).map(lambda g: (name_of(g, FORM_NAME) or ('общий обработчик форм' if re.search(r'/form\.php$', g) else 'форма')).capitalize()),
        'Принята': C['принята'].astype(str),
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
    note = (f"Все отправки форм за период — {len(C)}: люди — {n_('Люди')}, боты — {n_('Боты')}, свои — {n_('Свои')}. "
            f"Принято у людей — {int(((C['группа'] == 'Люди') & (C['принята'] == 'да')).sum())}. Сводка по формам — на листе «Анатомия сайта».")
    widths = {'Время': 17, 'Кто': 13, 'Форма': 22, 'Принята': 10, 'Код ответа': 9, 'Канал': 18, 'Страница входа': 40, 'Откуда пришёл': 30,
              'Страниц до отправки': 11, 'Секунд от входа': 10, 'Почему бот': 34, 'IP': 16, 'Сеть': 22, 'Обработчик': 50}
    fill = lambda col, v: F_NOTE if (col == 'Кто' and v == 'Боты') else ('EFEFEF' if (col == 'Кто' and str(v).startswith('Свои')) else None)
    bold = lambda col, v: col == 'Принята' and v == 'да'
    data_sheet(wb, name, d, 'Конверсии', note, widths,
               wrap=('Почему бот',), fill_rule=fill, bold_rule=bold, center=('IP', 'Код ответа', 'Принята'))
