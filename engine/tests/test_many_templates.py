"""#27: «5xx по шаблонам» не зависит от числа разных шаблонов (больше 127 — коды категорий int16)."""
import os
import tempfile
from datetime import timedelta

import synth
from nxld import analyze, prepare


def _name(k):   # разделы буквами: цифры шаблон сворачивает в одно
    a = 'abcdefghijklmnopqrstuvwxyz'
    return a[k // 26 % 26] + a[k % 26] + 'razdel'


def test_5xx_by_template_with_many_templates(monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    log = synth.Log()
    log.people(days=3, per_day=10)
    for k in range(240):   # обход по 240 разным разделам — больше 127 шаблонов
        log.line(f'198.51.100.{k % 200 + 1}', synth.T0 + timedelta(days=1, hours=9, seconds=k), f'/{_name(k)}/', 200, ref='https://site.ru/')
    for k in range(40):    # страницы с ответом 503 по 40 разделам, у людей
        log.line(f'198.51.100.{k + 1}', synth.T0 + timedelta(days=2, hours=10, seconds=k), f'/{_name(k)}/', 503, ref='https://site.ru/')
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        log.write(path)
        prepare.run([path], work, log=lambda *a: None)
        res = analyze.run(work, log=lambda *a: None)
    assert not res.get('сбои_блоков'), res.get('сбои_блоков')
    T5 = res['sheets']['Ошибки']['5xx по шаблонам']
    assert len(T5) >= 40 and (T5['успешных_ответов'] >= 1).all(), T5[['шаблон', 'успешных_ответов']].head()
