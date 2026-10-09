"""#13: мобильное приложение Битрикс24 (встроенный браузер) — «Люди», не «Боты · явные (не браузер)», не «Свои»;
в дела, «Меры по IP» и STIX не попадает."""
from datetime import timedelta

import synth
from test_bitrix_agents import _outside

UA_APP = ['bitrix24app/5.6.700 (iPhone; iOS 26.6; Scale/3.00)', 'Phone/Android/BitrixMobile/Version=61']


def test_bitrix24_app_is_people(tmp_path):
    log = synth.Log()
    log.people()
    ips = ['203.0.113.5', '203.0.113.6']
    for d in range(7):
        for j, (ip, ua) in enumerate(zip(ips, UA_APP)):
            for k, p in enumerate(('/catalog/', '/catalog/shary/', '/contacts/')):
                log.line(ip, synth.T0 + timedelta(days=d, hours=10 + j, minutes=5 * k), p, 200, ua=ua, size=40000)
    res, out, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Общий анализ']['Люди и боты']
    assert not len(G[(G['группа'] == 'Боты') & (G['подгруппа'].astype(str) == 'явные (не браузер)')]), G
    assert int(G.loc[G['группа'] == 'Люди', 'IP'].sum()) == len(set(synth.RU)) + 2, G
    assert int(G.loc[G['группа'] == 'Свои', 'визитов'].sum()) == 0, G
    _outside(res, out, ips)
