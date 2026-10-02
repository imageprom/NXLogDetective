"""NXLD: лист «Проблемы» карточками (ТЗ, раздел 16.5).

Срочно и Важно — карточка на проблему: заголовок с цветом важности и меткой статуса, затем строки
«Что происходит / Доказательство / Как найдено / Что сделать / Где править / Как проверить / Подробно».
К сведению — по строке на проблему. В конце (при повторной проверке) — «Исправлено» и «Отмечено как норма».
Оформление — как у индексного листа (общий класс Sheet).
"""
import re
from openpyxl.styles import Font, Alignment, Border, PatternFill
from .report_index import Sheet, ORANGE, ORANGE2, GREY, DARK, INK, F_NOTE, F_CARD, SEP, BLOCK_FILES, cap, row_height
from .findings import SEV_ORDER
from .findings_meta import meta

STATUS_STYLE = {'стала хуже': (ORANGE, True, None), 'новая': (ORANGE, False, None), 'исправлена частично': (DARK, False, F_NOTE), 'сохраняется': (DARK, False, None)}


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
    sub = f"Срочно — {cnt['Срочно']} · Важно — {cnt['Важно']} · К сведению — {cnt['К сведению']}"
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
        S.section(f'{sev} — {len(xs)}')
        for x in xs:
            n += 1
            card(S, x, n, sev, here_file, with_block)
    xs = sorted([x for x in act if x['важность'] == 'К сведению'], key=key)
    if xs:
        S.section(f"К сведению — {len(xs)}")
        for x in xs:
            n += 1
            text, target = link_for(x, here_file)
            line = f"{n}. {cap(x['что_происходит'])}" + (f" — {'[' + x['блок'] + '] ' if with_block else ''}подробно: {text} →" if text else '')
            one_line(S, line, target, status=x.get('статус_вид'), status_text=x.get('статус'))
    fixed = [x for x in items if x.get('статус_вид') == 'исправлена']
    if fixed:
        S.section(f'Исправлено с прошлой проверки — {len(fixed)}')
        for x in fixed:
            one_line(S, f"✓ {cap(x['что_происходит'])} — в новом периоде не обнаружено (если запросов к этим адресам не было, исправление не подтверждено)", None)
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
    ws = S.ws
    fill, color = (ORANGE, 'FFFFFF') if sev == 'Срочно' else (F_NOTE, '000000')
    # заголовок карточки: номер и проблема; справа — метка статуса (повторная проверка)
    st_kind, st_text = x.get('статус_вид'), x.get('статус')
    last = 'F' if not st_kind else 'E'
    ws.merge_cells(f'B{S.r}:{last}{S.r}')
    for col in 'BCDEF':
        ws[f'{col}{S.r}'].fill = PatternFill('solid', fgColor=fill)
    title = f"{n}. {cap(x['что_происходит'])}"
    S.cell('B', title, Font(name='Arial', size=11, bold=True, color=color), fill, Alignment(vertical='center', wrap_text=True, indent=1))
    if st_kind:
        c_, b_, f_ = STATUS_STYLE.get(st_kind, (DARK, False, None))
        S.cell('F', cap(st_text), Font(name='Arial', size=10, bold=b_ or True, color='FFFFFF' if fill == ORANGE else c_), f_ if fill != ORANGE else fill,
               Alignment(horizontal='right', vertical='center', wrap_text=True, indent=1))
    ws.row_dimensions[S.r].height = row_height(title, 95 if not st_kind else 62) + 2
    S.r += 1
    crit, check = meta(x)
    if with_block: S.pair('Блок', x['блок'])
    if x.get('факты'): S.pair('Что происходит', cap(x['факты']))
    if x.get('доказательство'): S.pair('Доказательство', x['доказательство'])
    if crit: S.pair('Как найдено', crit)
    if x.get('что_сделать'): S.pair('Что сделать', cap(x['что_сделать']))
    if x.get('где_править'): S.pair('Где править', cap(x['где_править']))
    if check and check != '—': S.pair('Как проверить', check)
    text, target = link_for(x, here_file)
    if text: S.pair('Подробно', text + ' →', link=target)
    if x.get('также_в'): S.pair('Также в блоках', x['также_в'])
    ws.row_dimensions[S.r].height = 10
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
