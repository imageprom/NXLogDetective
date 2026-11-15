#!/usr/bin/env python3
"""Отпечаток отчёта и сравнение двух отчётов по ячейкам.

  python3 tools/report_digest.py digest <папка_отчёта> > отпечаток.json
  python3 tools/report_digest.py diff <папка_A> <папка_B>      # какие листы отличаются и сколько ячеек

Нужен при переделках «под капотом»: отчёт до и после должен совпасть."""
import hashlib, json, os, sys
import openpyxl


def sheets(folder):
    """{файл: {лист: [строки значений]}} по всем xlsx папки."""
    out = {}
    for f in sorted(os.listdir(folder)):
        if not f.endswith('.xlsx'): continue
        wb = openpyxl.load_workbook(os.path.join(folder, f), read_only=True)
        out[f] = {s: [tuple(r) for r in wb[s].iter_rows(values_only=True)] for s in wb.sheetnames}
        wb.close()
    return out


def digest(folder):
    return {f: {s: hashlib.sha1(json.dumps(rows, ensure_ascii=False, default=str).encode()).hexdigest()[:16] for s, rows in ss.items()} for f, ss in sheets(folder).items()}


def diff(a, b, limit=5):
    """Список расхождений: (файл, лист, что, примеры)."""
    A, B, out = sheets(a), sheets(b), []
    for f in sorted(set(A) | set(B)):
        if f not in A or f not in B:
            out.append((f, '', 'файл только в одном отчёте', [])); continue
        for s in list(A[f]) + [s for s in B[f] if s not in A[f]]:
            if s not in A[f] or s not in B[f]:
                out.append((f, s, 'лист только в одном отчёте', [])); continue
            ra, rb = A[f][s], B[f][s]
            cells = []
            for i in range(max(len(ra), len(rb))):
                x, y = (ra[i] if i < len(ra) else ()), (rb[i] if i < len(rb) else ())
                for j in range(max(len(x), len(y))):
                    u, v = (x[j] if j < len(x) else None), (y[j] if j < len(y) else None)
                    if u != v: cells.append((i + 1, j + 1, u, v))
            if cells: out.append((f, s, f'ячеек {len(cells)}, строк {len(ra)} → {len(rb)}', cells[:limit]))
    return out


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'digest':
        print(json.dumps(digest(sys.argv[2]), ensure_ascii=False, indent=1))
    elif len(sys.argv) >= 4 and sys.argv[1] == 'diff':
        d = diff(sys.argv[2], sys.argv[3])
        for f, s, what, cells in d:
            print(f'{f} · {s}: {what}')
            for i, j, u, v in cells: print(f'    R{i}C{j}: {str(u)[:70]!r} → {str(v)[:70]!r}')
        print('Отчёты совпадают' if not d else f'Листов с расхождениями: {len(d)}')
        sys.exit(1 if d else 0)
    else:
        print(__doc__)
