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
