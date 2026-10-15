"""#20: спам форм определяется один раз — V.subgroup из visits.mark_form_spam; лист «Спам форм», «Принято» и операторы берут его."""
import os
import tempfile
from datetime import timedelta

import synth
from nxld import analyze, prepare


def _log():
    log = synth.Log()
    log.people(days=4)
    for d in range(4):   # человек отправляет форму: движок находит цель /contacts/send/
        t = synth.T0 + timedelta(days=d, hours=9)
        log.visit(synth.RU[0], t)
        log.line(synth.RU[0], t + timedelta(seconds=100), '/contacts/send/', 200, ref='https://site.ru/contacts/', method='POST')
    # визит А: прямой заход на битый адрес, 5 страниц, форма. Правило mark_form_spam (≤ 6 страниц) — спам; прежнее правило листа (≤ 4 страниц) — нет
    t = synth.T0 + timedelta(days=1, hours=15)
    ip = '185.100.0.1'
    log.line(ip, t, '/zz-dead/', 404, ref='-')
    for k in range(5): log.line(ip, t + timedelta(seconds=2 + k), f'/catalog/shary/?PAGEN_1={k + 2}', 200, ref='-')
    log.line(ip, t + timedelta(seconds=20), '/contacts/send/', 200, ref='https://site.ru/', method='POST')
    # визит Б: две отправки подряд за минуту (n_goal = 2): «пачка» прежнего листа — от трёх; здесь не спам ни по одному правилу
    t = synth.T0 + timedelta(days=2, hours=15)
    ip = '185.100.0.2'
    log.line(ip, t, '/', 200, ref='https://yandex.ru/')
    log.line(ip, t + timedelta(seconds=5), '/contacts/send/', 200, ref='https://site.ru/', method='POST')
    log.line(ip, t + timedelta(seconds=9), '/contacts/send/', 200, ref='https://site.ru/', method='POST')
    return log


def test_spam_sheet_follows_visit_subgroup(monkeypatch):
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        _log().write(path)
        prepare.run([path], work, log=lambda *a: None)
        res = analyze.run(work, log=lambda *a: None)
        ex = res['spam_examples']   # группы V.subgroup «спам форм…» (visits.mark_form_spam): класс → число визитов
        assert ex, 'mark_form_spam должен разметить визит А'
        SP = res['sheets']['Боты']['Спам форм: визиты']
        assert SP['класс'].value_counts().to_dict() == {e['класс']: e['визитов'] for e in ex}   # лист «Спам форм» — те же визиты и классы
        assert '185.100.0.1' in set(SP['ip'])   # визит А: 6 страниц — спам по правилу mark_form_spam (≤ 6), по прежнему правилу листа (≤ 4) не был бы
        K = res['sheets']['Боты']['Боты: классы']
        kk = K.set_index('класс') if 'класс' in K else K
        assert int(kk[kk.index.astype(str).str.startswith('спам')]['визитов'].sum()) == len(SP)
