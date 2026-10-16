"""#26: лог почти без POST — форм нет, prepare не падает, целей нет."""
import os
import tempfile
from datetime import timedelta

import pandas as pd

import synth
from nxld import prepare


def test_prepare_on_log_without_posts():
    log = synth.Log()
    for k in range(30): log.visit(f'198.51.100.{k + 1}', synth.T0 + timedelta(hours=8, minutes=5 * k), ref='https://yandex.ru/')
    for k in range(2):   # один-два POST — форм-кандидатов не набирается
        log.line(f'198.51.100.{k + 1}', synth.T0 + timedelta(hours=9, minutes=k), '/contacts/send/', 200, ref='https://site.ru/contacts/', method='POST')
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        log.write(path)
        prepare.run([path], work, log=lambda *a: None)
        assert os.path.exists(os.path.join(work, 'site_map.json'))
