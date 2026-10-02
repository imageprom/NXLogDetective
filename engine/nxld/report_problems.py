"""NXLD: лист «Проблемы» карточками (ТЗ, раздел 16.5).

Срочно и Важно — карточка на проблему: заголовок с цветом важности и меткой статуса, затем строки
«Что происходит / Доказательство / Как найдено / Что сделать / Где править / Как проверить / Подробно».
К сведению — по строке на проблему. В конце (при повторной проверке) — «Исправлено» и «Отмечено как норма».
Оформление — как у индексного листа (общий класс Sheet).
"""
import re
from collections import Counter
from openpyxl.styles import Font, Alignment, Border, PatternFill, Side
from .report_index import Sheet, ORANGE, ORANGE2, GREY, DARK, INK, F_NOTE, F_CARD, SEP, BLOCK_FILES, cap, row_height
from .findings import SEV_ORDER
from .findings_meta import meta
from .findings_text import GRADE

STATUS_STYLE = {'стала хуже': (ORANGE, True, None), 'новая': (ORANGE, False, None), 'исправлена частично': (DARK, False, F_NOTE), 'сохраняется': (DARK, False, None)}


PLAQUE = {'Срочно': (ORANGE, 'FFFFFF'), 'Важно': (F_NOTE, '000000'), 'К сведению': ('E5E5E5', '000000')}
OLINE = Side(style='thin', color=ORANGE)


def plaque(S, sev, count, xs, fixed=0):
    """Заголовок раздела в виде плашки, как «Первичная проверка» на индексе; справа — метаинформация."""
    ws = S.ws
    S.r += 1
    fill, color = PLAQUE[sev]
    S.cell('B', f'{GRADE[sev].upper()} — {count}', Font(name='Arial', size=11, bold=True, color=color), fill, Alignment(horizontal='center', vertical='center'))
    themes = Counter(x.get('тема', '') for x in xs)
    meta_ = ' · '.join(f'{t} — {k}' for t, k in themes.most_common())
    if fixed: meta_ = f'исправлено с прошлой проверки — {fixed} · ' + meta_
    ws.merge_cells(f'C{S.r}:F{S.r}')
    S.cell('C', meta_, Font(name='Arial', size=10, color=INK), align=Alignment(vertical='center', indent=1, wrap_text=True))
    ws.row_dimensions[S.r].height = 24
    S.r += 2


def sheet_ref(name):
    """Имя листа так, как его пишет сборка Excel."""
    return re.sub(r'[\[\]*?/\\]', ' ', str(name)).replace(':', ' —')[:31].strip()


def link_for(x, here_file):
    if not x.get('лист'): return None, None
    f = BLOCK_FILES.get(x['блок'])
    sh = sheet_ref(x['лист'])
    text = f'лист «{sh}»' + ('' if f == here_file else f' в {f}')
    target = f"#'{sh}'!A1" if f == here_file else f"{f}#'{sh}'!A1"
    return text, target


def build_problems(wb, res, items, here_file, with_block, index=0, title='Проблемы'):
    ws = wb.create_sheet(title, index)
    S = Sheet(ws)
    ws.row_dimensions[1].height = 12
    S.r = 2
    ws.merge_cells('B2:F2')
    S.cell('B', 'ПРОБЛЕМЫ', Font(name='Montserrat', size=16, bold=True, color=ORANGE)); ws.row_dimensions[2].height = 30
    act = [x for x in items if x.get('статус_вид') != 'исправлена' and x.get('статус') != 'отмечено как норма']
    cnt = {k: sum(1 for x in act if x['важность'] == k) for k in ('Срочно', 'Важно', 'К сведению')}
    ws.merge_cells('B3:F3')
    sub = f"Приоритетные — {cnt['Срочно']} · Важные — {cnt['Важно']} · Остальные — {cnt['К сведению']}"
    if not with_block: sub = f"Блок «{items[0]['блок'] if items else ''}» · " + sub
    S.cell('B', sub, Font(name='Arial', size=11, color=INK), row=3)
    ws.row_dimensions[3].height = 20
    S.r = 4
    order = list(BLOCK_FILES)
    key = lambda x: (SEV_ORDER[x['важность']], order.index(x['блок']) if x['блок'] in order else 9)
    n = 0
    for sev in ('Срочно', 'Важно'):
        xs = sorted([x for x in act if x['важность'] == sev], key=key)
        if not xs: continue
        plaque(S, sev, len(xs), xs, fixed=sum(1 for x in items if x.get('статус_вид') == 'исправлена' and x['важность'] == sev))
        for x in xs:
            n += 1
            card(S, x, n, sev, here_file, with_block)
    xs = sorted([x for x in act if x['важность'] == 'К сведению'], key=key)
    if xs:
        plaque(S, 'К сведению', len(xs), xs)
        for x in xs:
            n += 1
            text, target = link_for(x, here_file)
            line = f"{n}. {x.get('тема', '')}: {cap(x.get('заголовок') or x['что_происходит'])}" + (f" — подробно: {text} →" if text else '')
            one_line(S, line, target, status=x.get('статус_вид'), status_text=x.get('статус'))
    fixed = [x for x in items if x.get('статус_вид') == 'исправлена']
    if fixed:
        S.section(f'Исправлено с прошлой проверки — {len(fixed)}')
        for x in fixed:
            one_line(S, f"✓ {cap(x.get('заголовок') or x['что_происходит'])} — в новом периоде не обнаружено (если запросов к этим адресам не было, исправление не подтверждено)", None)
    norm = [x for x in items if x.get('статус') == 'отмечено как норма']
    if norm:
        S.section(f'Отмечено как норма — {len(norm)}')
        for x in norm:
            one_line(S, f"{cap(x['что_происходит'])}" + (f" — {x.get('отметка')}" if x.get('отметка') else ''), None)
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f'A1:G{S.r}'
    return ws


def card(S, x, n, sev, here_file, with_block):
    """Заголовок — оранжевый с оранжевой линией (как «Проверка» на индексе), тема — маркером справа.
    Строки: Факт → Что делать (персиковая) → Как проверить → «Расследование и улики» (второй уровень).
    Ссылка на подробности — курсивом под карточкой."""
    ws = S.ws
    title = f"{n}. {cap(x.get('заголовок') or x['что_происходит'])}"
    ws.merge_cells(f'B{S.r}:E{S.r}')
    S.cell('B', title, Font(name='Arial', size=12, bold=True, color=ORANGE), None, Alignment(vertical='center', wrap_text=True))
    st_kind = x.get('статус_вид')
    right = x.get('тема') or ''
    if st_kind: right = f"{right} · {cap(x.get('статус'))}"
    S.cell('F', right, Font(name='Arial', size=10, bold=True, color=ORANGE if st_kind in ('стала хуже', 'новая') else INK), None,
           Alignment(horizontal='right', vertical='center', wrap_text=True))
    for col in 'BCDEF':
        ws[f'{col}{S.r}'].border = Border(bottom=OLINE)
    ws.row_dimensions[S.r].height = max(26, row_height(title, 78) + 4)
    S.r += 1
    S.pair('Факт', cap(x.get('факт') or x.get('факты') or ''))
    todo = cap(x.get('что_сделать') or '')
    if x.get('где_править') and x['где_править'].lower() not in todo.lower(): todo += f" ({x['где_править']})"
    if todo: S.pair('Что делать', todo, fill=F_NOTE)
    crit, check = meta(x)
    if check and check != '—': S.pair('Как проверить', check)
    rows = [(k, v) for k, v in (('Доказательство', x.get('доказательство')), ('Как найдено', crit)) if v]
    if rows:
        S.pair('Расследование и улики', '', height=20)
        for k, v in rows: S.pair(k, v, level=2)
    text, target = link_for(x, here_file)
    if text:
        ws.merge_cells(f'B{S.r}:F{S.r}')
        c = S.cell('B', f'Подробно: {text} →', align=Alignment(vertical='center', indent=1))
        c.hyperlink = target; c.font = Font(name='Arial', size=10, italic=True, color=ORANGE2, underline='single')
        ws.row_dimensions[S.r].height = 20
        S.r += 1
    ws.row_dimensions[S.r].height = 14
    S.r += 1


def one_line(S, text, target, status=None, status_text=None):
    ws = S.ws
    last = 'F' if not status else 'E'
    ws.merge_cells(f'B{S.r}:{last}{S.r}')
    c = S.cell('B', text, Font(name='Arial', size=11, color='000000'), None, Alignment(vertical='center', wrap_text=True, indent=1))
    if target:
        c.hyperlink = target; c.font = Font(name='Arial', size=11, color='000000')
    if status:
        c_, b_, f_ = STATUS_STYLE.get(status, (DARK, False, None))
        S.cell('F', cap(status_text), Font(name='Arial', size=10, bold=b_, color=c_), f_, Alignment(horizontal='right', vertical='center', wrap_text=True, indent=1))
    for col in 'BCDEF':
        ws[f'{col}{S.r}'].border = Border(bottom=SEP)
    ws.row_dimensions[S.r].height = row_height(text, 95 if not status else 62)
    S.r += 1
