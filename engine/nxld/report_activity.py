"""NXLD: лист «Активность» — сводка по реестру обращающихся (actors.py), в стиле «Обзора» и «Анатомии».

Блоки: Каналы → Посетители → Сотрудники → Системы мониторинга (топ-10) → Роботы (топ-10) → Боты по сигнатурам (топ-10).
Под каждым блоком — ссылка на полный лист: те же цифры, подробно."""
import pandas as pd
from openpyxl.styles import Font, Alignment, Border, PatternFill
from .report_index import Sheet, ORANGE, ORANGE2, RED, ru_num, plural, thin, F_NOTE
from .report_tables import split_codes

COLS = 'BCDEFGHI'
WIDTHS = dict(A=2.5, B=30, C=24, D=14, E=12, F=12, G=12, H=13, I=20, J=2.5)
F_TOTAL = 'E5E5E5'


class Wide(Sheet):
    """Та же раскладка, что у «Анатомии», но шире: таблицы до восьми колонок (B:I)."""
    def __init__(self, ws):
        super().__init__(ws)
        for col, w in WIDTHS.items(): ws.column_dimensions[col].width = w

    def section(self, title, sub=''):
        self.r += 1
        self.ws.merge_cells(f'B{self.r}:I{self.r}')
        self.cell('B', title.upper(), Font(name='Montserrat', size=12, bold=True, color=ORANGE), align=Alignment(vertical='center'))
        for col in COLS: self.ws[f'{col}{self.r}'].border = Border(bottom=thin)
        self.ws.row_dimensions[self.r].height = 26
        self.r += 1
        if sub:
            self.ws.merge_cells(f'B{self.r}:I{self.r}')
            self.cell('B', sub, Font(name='Arial', size=10, italic=True, color='666666'), align=Alignment(vertical='center', wrap_text=True, indent=1))
            from .report_index import row_height
            self.ws.row_dimensions[self.r].height = row_height(sub, 125)
            self.r += 1

    def link(self, text, target, names=None):
        """Ссылка под блоком: на лист этого файла или на лист другого файла отчёта."""
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

    def table(self, headers, rows, spans, **kw):
        h0 = self.r
        super().table(headers, rows, spans, **kw)
        if any(len(h) > 11 for h in headers): self.ws.row_dimensions[h0].height = 32   # длинные названия колонок — в две строки

    def total(self, row, n):
        """Строка «Итого» — жирным на сером, сразу под таблицей."""
        r = self.r - 1
        for col in COLS[:n]:
            c = self.ws[f'{col}{r}']
            c.font = Font(name='Arial', size=11, bold=True, color='000000'); c.fill = PatternFill('solid', fgColor=F_TOTAL)

    def red(self, rows_from, col):
        for r in range(rows_from, self.r):
            c = self.ws[f'{col}{r}']
            if c.value: c.font = Font(name='Arial', size=11, color=RED)


def pct(x, d=1):
    return (f'{x * 100:.{d}f}'.replace('.', ',') + '%') if x is not None and not pd.isna(x) else ''


def size(b):
    b = float(b or 0)
    if b >= 1024 ** 3: return f'{b / 1024 ** 3:.1f} ГБ'.replace('.', ',')
    if b >= 1024 ** 2: return f'{b / 1024 ** 2:.0f} МБ'
    if b == 0: return '0'
    return f'{b / 1024:.0f} КБ'


def every(sec):
    if not sec: return ''
    sec = int(sec)
    if sec < 120: return f'{sec} с'
    if sec < 7200: return f'{round(sec / 60)} мин'
    return f'{sec / 3600:.1f} ч'.replace('.', ',')


def period(a, b):
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    return a.strftime('%d.%m') if a == b else f"{a.strftime('%d.%m')}–{b.strftime('%d.%m')}"


def build_activity(wb, res, names, index=3, title='Активность', files=None):
    A = res.get('actors') or {}
    if not A: return None
    files = files or {}
    bots_file = files.get('Боты')
    ws = wb.create_sheet(title, index)
    S = Wide(ws)
    ws.row_dimensions[1].height = 12
    S.r = 2
    ws.merge_cells('B2:I2')
    S.cell('B', title.upper(), Font(name='Montserrat', size=16, bold=True, color=ORANGE)); ws.row_dimensions[2].height = 30
    S.r = 3
    ws.merge_cells('B3:I3')
    S.cell('B', 'Кто заходит на сайт и откуда', Font(name='Comfortaa', size=11, bold=True, color='666666')); ws.row_dimensions[3].height = 22
    S.r = 4
    # 1. каналы
    ch = A.get('каналы')
    if ch is not None and len(ch):
        S.section('Каналы', 'Визиты людей по источнику, с которого начался визит. Заявки — формы, отправленные в этих визитах.')
        rows = [[r['канал'], int(r['визитов']), pct(r['доля']), int(r['IP']), int(r['заявок']), pct(r['конверсия'], 2)] for _, r in ch.iterrows()]
        rows.append(['Итого', int(ch['визитов'].sum()), '100%', '', int(ch['заявок'].sum()), pct(ch['заявок'].sum() / max(1, ch['визитов'].sum()), 2)])
        S.table(['Канал', 'Визиты (люди)', 'Доля', 'IP (люди)', 'Заявок отправлено', 'Конверсия'], rows, ['BC', 'D', 'E', 'F', 'G', 'HI'], num=(1, 2, 3, 4, 5))
        S.total(rows[-1], 8)
    # 2. посетители
    G = A.get('группы')
    if G is not None and len(G):
        S.section('Посетители', 'Все визиты за период: люди, роботы, боты и свои. Подгруппа показывает, по какому признаку визит отнесён к группе.')
        rows = [[r['группа'], r['подгруппа'] or '—', int(r['визитов']), int(r['IP']), int(r['запросов']), size(r['байт'])] for _, r in G.iterrows()]
        rows.append(['Итого', '', int(G['визитов'].sum()), '', int(G['запросов'].sum()), size(G['байт'].sum())])
        S.table(['Группа', 'Подгруппа', 'Визиты', 'IP', 'Запросов', 'Трафик'], rows, ['B', 'CD', 'E', 'F', 'G', 'HI'], num=(2, 3, 4, 5))
        S.total(rows[-1], 8)
    # 3. сотрудники
    St = A.get('сотрудники')
    if St is not None and len(St):
        S.section('Сотрудники', f"{ru_num(len(St))} {plural(len(St), 'IP-адрес', 'IP-адреса', 'IP-адресов')}, с которых успешно работали в админке движка. "
                                f"Их визиты не входят в число людей, а их заявки считаются тестовыми.")
        rows = [[r['IP'], r['сеть'], int(r['визитов']), int(r['запросов']), int(r['дней']), period(r['первый'], r['последний']), int(r['в_админке']), int(r['заявок'])]
                for _, r in St.iterrows()]
        rows.append(['Итого', '', int(St['визитов'].sum()), int(St['запросов'].sum()), '', '', int(St['в_админке'].sum()), int(St['заявок'].sum())])
        S.table(['IP', 'Сеть', 'Визиты', 'Запросов', 'Дней', 'Период', 'В админке, запросов', 'Тесты форм'], rows, list(COLS), num=(2, 3, 4, 6, 7), center=(5,))
        S.total(rows[-1], 8)
    # 4. системы мониторинга
    M = A.get('мониторинг')
    if M is not None and len(M):
        S.section('Системы мониторинга', 'Сервисы, которые проверяют, работает ли сайт. Опознаются по названию в User-Agent или по ритму: один и тот же адрес через равные промежутки времени.')
        r0 = S.r + 1
        rows = [[r['система'], r['как'], r['проверяет'], int(r['IP']), every(r['интервал']), int(r['запросов']), split_codes(r['коды'])[1], size(r['байт'])] for _, r in M.iterrows()]
        S.table(['Система', 'Как опознана', 'Что проверяет', 'IP', 'Интервал', 'Запросов', 'Ошибки', 'Трафик'], rows, list(COLS), num=(3, 5, 7), center=(1, 4))
        S.red(r0, 'H')
        if bots_file: S.link('Все роботы и системы мониторинга', (bots_file, 'Роботы — семейства'))
    # 5. роботы
    Rb = A.get('роботы')
    if Rb is not None and len(Rb):
        S.section('Роботы', 'Топ-10 по числу запросов: поисковики, сервисы и SEO-боты, которые честно себя называют. Подлинность — доля запросов из официальных сетей робота; «—» — у робота нет опубликованного списка сетей.')
        r0 = S.r + 1
        rows = [[r['робот'], r['категория'], pct(r['подлинных'], 0) if r['подлинных'] is not None and not pd.isna(r['подлинных']) else '—',
                 int(r['запросов']), int(r['IP']), int(r['дней']), size(r['байт']), split_codes(r['коды'])[1]] for _, r in Rb.iterrows()]
        S.table(['Робот', 'Категория', 'Подлинность', 'Запросов', 'IP', 'Дней', 'Трафик', 'Ошибки'], rows, list(COLS), num=(2, 3, 4, 5, 6))
        S.red(r0, 'I')
        if bots_file: S.link('Все роботы', (bots_file, 'Роботы — семейства'))
    # 6. боты по сигнатурам
    B = A.get('сигнатуры')
    if B is not None and len(B):
        B = B.head(10)
        S.section('Боты', 'Топ-10 сигнатур. Сигнатура — поведение, по которому бот себя выдал; одна сигнатура объединяет много IP-адресов и сетей.')
        rows = [[r['сигнатура'], r['вид'], int(r['визитов']), int(r['IP']), int(r['сетей']), int(r['дней']), int(r['заявок']), r['сеть']] for _, r in B.iterrows()]
        S.table(['Сигнатура', 'Вид', 'Визиты', 'IP', 'Сетей', 'Дней', 'Заявок', 'Чаще всего из сети'], rows, list(COLS), num=(2, 3, 4, 5, 6))
        if bots_file: S.link('Все боты и их улики', (bots_file, 'Боты — классы'))
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws
