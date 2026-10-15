"""п. 4: extra_table без квадратичного роста — объединения строк пачкой (таблица улик операторов на тысячах пар IP)."""
import openpyxl
import pandas as pd

from nxld import report_tables as RT
from openpyxl.worksheet.cell_range import MultiCellRange


def _ws(n):
    wb = openpyxl.Workbook()
    d = pd.DataFrame({'Оператор': ['Оператор 1'], 'Улики': ['x'], 'Слабых связей': [0], 'IP спама': [1], 'IP разведки': [0], 'Сети': ['n'], 'Отправок': [1], 'Принято': [0],
                      'Битые входы': ['/a/'], 'Дней': [1]})
    RT.data_sheet(wb, 'Операторы', d, {'Оператор': 18, 'Улики': 50, 'Сети': 34, 'Битые входы': 50}, wrap=('Улики', 'Сети', 'Битые входы'))
    E = pd.DataFrame({'IP A': [f'198.51.{i // 250}.{i % 250 + 1}' for i in range(n)], 'IP B': [f'203.0.{i // 250}.{i % 250 + 1}' for i in range(n)], 'Сила': 'сильная',
                      'Улика': 'общий битый вход; тот же браузер; та же сеть; одна волна', 'Доказательство': [f'оба входили на /zz-dead-{i}/ (404): ' + 'x' * 120 for i in range(n)],
                      'Учтена': 'да'})
    RT.extra_table(wb['Операторы'], E, 'link_evidence', wrap=('Улика', 'Доказательство', 'Учтена'))
    return wb['Операторы']


def _sides(cell):
    b = cell.border
    return tuple(getattr(getattr(b, s), 'style', None) for s in ('left', 'right', 'top', 'bottom'))


def _ws_one_by_one(n):
    """Та же таблица, но объединения — по одному обычным ws.merge_cells (как было)."""
    orig = RT.merge_bulk
    RT.merge_bulk = lambda ws, ranges: [ws.merge_cells(start_row=a, start_column=b, end_row=c, end_column=d) for a, b, c, d in ranges]
    try: return _ws(n)
    finally: RT.merge_bulk = orig


def test_merged_rows_same_as_one_by_one():
    ws = _ws(40)
    got = sorted(str(r) for r in ws.merged_cells.ranges)
    assert len(got) >= 40   # у каждой строки таблицы объединены широкие колонки
    # те же диапазоны, что дал бы merge_cells по одному
    wb2 = openpyxl.Workbook(); w2 = wb2.active
    for r in sorted(ws.merged_cells.ranges, key=lambda x: (x.min_row, x.min_col)): w2.merge_cells(str(r))
    assert sorted(str(r) for r in w2.merged_cells.ranges) == got
    # границы объединённых ячеек — как у merge_cells по одному
    ws1 = _ws_one_by_one(40)
    for rng in ws.merged_cells.ranges:
        for c in range(rng.min_col, rng.max_col + 1):
            a, b = ws.cell(rng.min_row, c), ws1.cell(rng.min_row, c)
            assert _sides(a) == _sides(b), (rng.coord, c)
    # объединённые ячейки оформлены как раньше: у всех кроме левой верхней — MergedCell
    r0 = next(r for r in ws.merged_cells.ranges if r.min_row > 8)
    assert type(ws.cell(r0.min_row, r0.max_col)).__name__ == 'MergedCell' and type(ws.cell(r0.min_row, r0.min_col)).__name__ == 'Cell'


def test_no_quadratic_merge_checks(monkeypatch):
    """Проверок «диапазон уже объединён» (перебор всех прежних) — константа, а не по числу строк."""
    calls = []
    orig = MultiCellRange.__contains__
    monkeypatch.setattr(MultiCellRange, '__contains__', lambda self, c: (calls.append(len(self.ranges)), orig(self, c))[1])
    _ws(1500)
    assert sum(calls) < 20000, sum(calls)   # прежний способ: ~ n²/2 = 1 000 000 сравнений
