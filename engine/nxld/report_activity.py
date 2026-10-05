"""NXLD: лист «Активность» — сводка по реестру обращающихся (actors.py), в стиле «Обзора» и «Анатомии».

Блоки: Каналы → Посетители → Сотрудники → Системы мониторинга (топ-10) → Роботы (топ-10) → Боты по сигнатурам (топ-10).
Под каждым блоком — ссылка на полный лист: те же цифры, подробно."""
import pandas as pd
from openpyxl.styles import Font, Alignment, Border, PatternFill
from .report_index import Sheet, ORANGE, ORANGE2, RED, ru_num, plural, thin, F_NOTE
from .report_tables import split_codes

from .report_index import Wide, WIDE_COLS as COLS


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
        S.table(['Канал', 'Визитов (люди)', 'Доля', 'Уникальных IP (люди)', 'Заявок отправлено', 'Конверсия'], rows, ['BC', 'D', 'E', 'F', 'G', 'HI'], num=(1, 2, 3, 4, 5))
        S.total(8)
    # 2. посетители
    G = A.get('группы')
    if G is not None and len(G):
        S.section('Посетители', 'Все визиты за период: люди, роботы, системы мониторинга, утилиты, боты и свои. Подгруппа показывает, по какому признаку визит отнесён к группе.')
        rows = [[r['группа'], r['подгруппа'] or '—', int(r['визитов']), int(r['IP']), int(r['запросов']), size(r['байт'])] for _, r in G.iterrows()]
        rows.append(['Итого', '', int(G['визитов'].sum()), '', int(G['запросов'].sum()), size(G['байт'].sum())])
        S.table(['Группа', 'Подгруппа', 'Визитов', 'Уникальных IP', 'Запросов', 'Трафик'], rows, ['B', 'CD', 'E', 'F', 'G', 'HI'], num=(2, 3, 4, 5))
        S.total(8)
    # 3. сотрудники
    St = A.get('сотрудники')
    if St is not None and len(St):
        S.section('Сотрудники', f"{ru_num(len(St))} {plural(len(St), 'IP-адрес', 'IP-адреса', 'IP-адресов')}, с которых успешно работали в админке движка. "
                                f"Их визиты не входят в число людей, а их заявки считаются тестовыми.")
        rows = [[r['IP'], r['сеть'], int(r['визитов']), int(r['запросов']), int(r['дней']), period(r['первый'], r['последний']), int(r['в_админке']), int(r['заявок'])]
                for _, r in St.iterrows()]
        rows.append(['Итого', '', int(St['визитов'].sum()), int(St['запросов'].sum()), '', '', int(St['в_админке'].sum()), int(St['заявок'].sum())])
        S.table(['IP', 'Сеть', 'Визитов', 'Запросов', 'Дней', 'Период', 'Запросов в админке', 'Тестовых'], rows, list(COLS), num=(2, 3, 4, 6, 7), center=(5,))
        S.total(8)
    # 4. системы мониторинга
    M = A.get('мониторинг')
    if M is not None and len(M):
        S.section('Системы мониторинга', 'Сервисы, которые проверяют, работает ли сайт. Опознаются по названию в User-Agent или по ритму: один и тот же адрес через равные промежутки времени. Не обязательно наши.')
        r0 = S.r + 1
        rows = [[r['система'], r['как'], r['проверяет'], int(r['IP']), every(r['интервал']), int(r['запросов']), split_codes(r['коды'])[1], size(r['байт'])] for _, r in M.iterrows()]
        S.table(['Система', 'Как опознана', 'Что проверяет', 'Уникальных IP', 'Интервал', 'Запросов', 'Ошибки', 'Трафик'], rows, list(COLS), num=(3, 5, 7), center=(1, 4))
        S.red(r0, 'H')
        if bots_file: S.link('Все роботы и системы мониторинга', (bots_file, 'Роботы — семейства'))
    # 4а. утилиты
    U = A.get('утилиты')
    if U is not None and len(U):
        S.section('Утилиты', 'Программы, которые обращаются к сайту без браузера: curl, wget, Python, PHP и другие. За ними может стоять разработчик, интеграция или сканер — вывод по поведению каждого IP.')
        r0 = S.r + 1
        cut = lambda t: '\n'.join((x[:45] + '…' if len(x) > 46 else x) for x in str(t).split(', '))
        rows = [[r['утилита'], int(r['запросов']), int(r['IP']), int(r['зондов']), cut(r['что']), str(r['похоже']).replace(', ', '\n')] for _, r in U.iterrows()]
        S.table(['Утилита', 'Запросов', 'Уникальных IP', 'Зондов', 'Что запрашивали чаще всего', 'Похоже на (по IP)'], rows, ['B', 'C', 'D', 'E', 'FGH', 'I'], num=(1, 2, 3), wrap=0.95)
    # 5. роботы
    Rb = A.get('роботы')
    if Rb is not None and len(Rb):
        S.section('Роботы', 'Топ-10 по числу запросов: поисковики, сервисы и SEO-боты, которые честно себя называют. Подлинность — доля запросов из официальных сетей робота; «—» — у робота нет опубликованного списка сетей.')
        r0 = S.r + 1
        rows = [[r['робот'], r['категория'], pct(r['подлинных'], 0) if r['подлинных'] is not None and not pd.isna(r['подлинных']) else '—',
                 int(r['запросов']), int(r['IP']), int(r['дней']), size(r['байт']), split_codes(r['коды'])[1]] for _, r in Rb.iterrows()]
        S.table(['Робот', 'Категория', 'Подлинность', 'Запросов', 'Уникальных IP', 'Дней', 'Трафик', 'Ошибки'], rows, list(COLS), num=(2, 3, 4, 5, 6))
        S.red(r0, 'I')
        if bots_file: S.link('Все роботы', (bots_file, 'Роботы — семейства'))
    # 6. боты по сигнатурам
    B = A.get('сигнатуры')
    if B is not None and len(B):
        B = B.head(10)
        S.section('Боты', 'Топ-10 сигнатур. Сигнатура — поведение, по которому бот себя выдал; одна сигнатура объединяет много IP-адресов и сетей.')
        rows = [[r['сигнатура'], r['вид'], int(r['визитов']), int(r['IP']), int(r['сетей']), int(r['дней']), int(r['заявок']), r['сеть']] for _, r in B.iterrows()]
        S.table(['Сигнатура', 'Вид', 'Визитов', 'Уникальных IP', 'Сетей', 'Дней', 'Заявок', 'Чаще всего из сети'], rows, list(COLS), num=(2, 3, 4, 5, 6))
        if bots_file: S.link('Все боты и их улики', (bots_file, 'Боты — классы'))
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws
