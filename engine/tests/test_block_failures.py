"""#25: «Файлы» пропадали молча на логе, где в одной папке три и больше файлов одного вида. Сбой расчёта блока — не молчит."""
import json
import os
import tempfile
from datetime import timedelta

import pytest

import synth
from nxld import analyze, prepare, recon


def _log(fold=True):
    log = synth.Log()
    log.people()
    if not fold: return log
    for k in range(8):   # файлы одной папки второго уровня и одного вида — свёртка «/upload/iblock/…/*.jpg»
        for d in range(3):
            log.line(synth.RU[k % 5], synth.T0 + timedelta(days=d, hours=10, minutes=k), f'/upload/iblock/photo{k}.jpg', 200)
    return log


def _run(tmp, log, monkeypatch=None, boom=None):
    path, work = os.path.join(tmp, 'access.log'), os.path.join(tmp, 'work')
    log.write(path)
    prepare.run([path], work, log=lambda *a: None)
    lines = []
    if boom: monkeypatch.setattr(recon, 'files_inventory', boom)
    res = analyze.run(work, log=lines.append)
    return res, lines, work


def test_files_inventory_builds_without_folding(monkeypatch):
    """Свёртка пустая (в папках меньше трёх файлов одного вида): строковая колонка pandas + пустой массив numpy раньше давали TypeError."""
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        res, lines, work = _run(d, _log(fold=False))
        assert res['files'], lines
        assert not res.get('сбои_блоков'), res.get('сбои_блоков')


def test_files_inventory_builds_with_folded_files(monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        res, lines, work = _run(d, _log())
        assert res['files'], lines   # блок «Файлы» построен
        assert not res.get('сбои_блоков'), res.get('сбои_блоков')
        assert any('…/*.' in str(r['адрес']) for r in res['files'])   # свёртка работает


def test_block_failure_is_in_run_log_and_brief(monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    def boom(*a, **k): raise ValueError('сломан расчёт')
    with tempfile.TemporaryDirectory() as d:
        res, lines, work = _run(d, _log(), monkeypatch, boom)
        assert res['files'] is None
        assert res['сбои_блоков'] == [{'блок': 'Файлы', 'причина': 'ValueError: сломан расчёт'}]
        assert any('Блок не построен: «Файлы» — ValueError: сломан расчёт' in x for x in lines), lines   # журнал запуска
        brief = json.load(open(os.path.join(work, 'brief.json'), encoding='utf-8'))
        assert brief['проверка']['сбои_блоков'] == [{'блок': 'Файлы', 'причина': 'ValueError: сломан расчёт'}]   # выжимка
        assert any('«Файлы»' in x and 'не построен' in x for x in brief['проверка']['оговорки'])
