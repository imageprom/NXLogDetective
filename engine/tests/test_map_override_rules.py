"""#18: поправка form_success_rules из map_override действует на цели (R.goal, goal_success, V.n_conv), а не только попадает в site_map.json."""
import os
import tempfile
from datetime import timedelta

import pandas as pd

import synth
from nxld import prepare


def _log():
    log = synth.Log()
    log.people(days=3)
    for k in range(7):   # 6 отправок с ответом 200 и одна с 302: движок не различает успех по коду (200)
        log.line(synth.RU[k % 5], synth.T0 + timedelta(days=k % 3, hours=10, minutes=k), '/contacts/send/', 302 if k == 6 else 200,
                 ref='https://site.ru/contacts/', method='POST')
    return log


def _prepare(override):
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        _log().write(path)
        prepare.run([path], work, log=lambda *a: None, map_override=override)
        R, V = pd.read_pickle(os.path.join(work, 'R.pkl')), pd.read_pickle(os.path.join(work, 'V.pkl'))
        return int((R['goal'].astype(str) != '').sum()), int(R['goal_success'].sum()), int(V['n_conv'].sum())


def test_form_success_rule_override_changes_goals():
    goals, ok, conv = _prepare(None)
    assert (goals, ok) == (7, 6) and conv == 6   # найдено движком: успех — ответ 200
    goals2, ok2, conv2 = _prepare({'form_success_rules': {'/contacts/send/': 'цель: успех = 3xx (редирект после отправки)'}})
    assert goals2 == 7 and ok2 == 1 and conv2 == 1   # по поправке успех — только 302/303
