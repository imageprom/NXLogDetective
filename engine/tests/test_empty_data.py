"""Пустые данные не роняют сборку: реклама только от роботов (Обзор 05), лог без параметров запросов."""
import os
from datetime import timedelta

import synth


def test_ads_only_from_robots(tmp_path):
    log = synth.Log()
    log.people(pages=['/', '/catalog/', '/about/', '/contacts/'])   # люди — без рекламных меток
    for d in range(7):
        for k in range(10):   # рекламные клики — только робот проверки объявлений
            log.line('5.255.253.10', synth.T0 + timedelta(days=d, minutes=90 * k + 3), f'/catalog/shary/?utm_source=yandex&utm_medium=cpc&yclid={1000 + k}', ua=synth.UA_DIRECT)
    res, out, _ = synth.run(log, str(tmp_path))
    assert os.path.exists(os.path.join(out, 'NXLD_05_Marketing.xlsx'))
    ri = (res.get('marketing') or {}).get('реклама_итог') or {}
    assert ri.get('кликов') and not ri.get('людей')   # случай из задачи: клики есть, людей по рекламе нет


def test_log_without_query_params(tmp_path):
    log = synth.Log()
    log.people(pages=['/', '/catalog/', '/about/', '/contacts/', '/dostavka/'])
    res, _, text = synth.run(log, str(tmp_path))
    assert res['params'] == []
    assert "KeyError" not in text


def test_redmine_hint_without_edits(tmp_path):
    """Без --edits выжимка не пересобирается — в подсказке нет «пересобран с правками»."""
    log = synth.Log()
    log.people()
    _, _, text = synth.run(log, str(tmp_path))
    assert 'Напишите текст по work/brief.json и пересоберите' in text
    assert 'пересобран с правками' not in text


def test_log_without_errors(tmp_path):
    """Лог только с ответами 200: «Пострадавших страниц» нет — пустой результат, сборка не падает."""
    log = synth.Log()
    for d in range(7):
        for k in range(20):
            log.visit(synth.RU[k % len(synth.RU)], synth.T0 + timedelta(days=d, hours=8, minutes=25 * k))
    res, out, text = synth.run(log, str(tmp_path))
    assert ' 404 ' not in open(os.path.join(tmp_path, 'access.log')).read() and ' 500 ' not in open(os.path.join(tmp_path, 'access.log')).read()
    assert not len(res['errors']['нерабочие'])
    assert os.path.exists(os.path.join(out, 'NXLD_02_Errors.xlsx'))


def test_robots_sheet_without_verification(tmp_path):
    """Единственный представившийся робот — скрипт: «Подлинных, %» пусто у всех роботов, лист «Роботы» (04) строится."""
    log = synth.Log()
    log.people()
    for d in range(7):
        for k, u in enumerate(('/', '/catalog/', '/about/', '/contacts/')):
            log.line('203.0.113.7', synth.T0 + timedelta(days=d, hours=4, seconds=k), u, 200, ua='python-requests/2.31')
    res, out, _ = synth.run(log, str(tmp_path))
    RF = res['sheets']['Боты']['Роботы: семейства']
    assert len(RF) and RF['подлинных_%'].isna().all()
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(out, 'NXLD_04_Bots.xlsx'))
    assert 'Роботы' in wb.sheetnames
    hdr = [c.value for c in wb['Роботы'][4]]
    assert 'Подлинных, %' in hdr
