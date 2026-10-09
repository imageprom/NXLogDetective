"""Система мониторинга, которая сама получает отказы фильтра (403, 429, 444, 503) на заметной доле проверок, — карточка «К сведению»
в блоке «Боты»; мониторинг без отказов — без карточки."""
from datetime import timedelta

import synth

UA_BXMON = 'BitrixCloud Monitoring/1.0'


def _log(denied_every):
    log = synth.Log()
    log.people()
    for k in range(7 * 24 * 2):   # раз в 30 минут неделю
        code = 403 if denied_every and k % denied_every == 0 else 200
        log.line('198.51.100.10', synth.T0 + timedelta(minutes=30 * k), '/', code, ua=UA_BXMON, size=51234 if code == 200 else 150)
    return log


def _card(res):
    return [x for x in res['findings'] if x['key'].split(':')[1] == 'monitor_denied']


def test_monitor_half_denied(tmp_path):
    res, _, _ = synth.run(_log(2), str(tmp_path))
    c = _card(res)
    assert len(c) == 1, [x['key'] for x in res['findings']]
    c = c[0]
    assert c['блок'] == 'Боты' and c['важность'] == 'К сведению' and c['key'].endswith(':BitrixCloud Monitoring'), c
    assert '336 проверок' in c['факты'] and '50%' in c['факты'] and '403' in c['факты'], c['факты']
    assert 'исключения фильтра' in c['что_сделать']


def test_monitor_without_denials(tmp_path):
    res, _, _ = synth.run(_log(0), str(tmp_path))
    assert not _card(res)
