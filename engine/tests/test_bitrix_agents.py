"""#12: BitrixCloud Monitoring — «Системы мониторинга» с названием сервиса в любой сети; в дела, «Меры по IP» (кроме строки
«не трогать») и STIX не попадает."""
import glob
import os
from datetime import timedelta

import synth

UA_BXMON = 'BitrixCloud Monitoring/1.0'


def _outside(res, out, ips):
    Pf = res['profiles'] or {}
    in_cases = {ip for d in Pf.get('дела', []) for ip in d.get('ips', [])}
    MI = Pf.get('меры_ip')
    # «Меры по IP»: строка «не трогать» (белый список систем мониторинга) — не мера; иначе адреса там быть не должно
    in_mi = set(MI.loc[MI['приговор'].astype(str) != 'не трогать', 'ip'].astype(str)) if MI is not None and len(MI) else set()
    assert not (in_cases | in_mi) & set(ips), (in_cases, in_mi)
    for f in glob.glob(os.path.join(out, '*.stix.json')):
        text = open(f, encoding='utf-8').read()
        assert not any(f'"{ip}' in text or f"'{ip}" in text for ip in ips)


def test_bitrixcloud_monitoring(tmp_path):
    log = synth.Log()
    log.people()
    ips = ['198.51.100.10', '203.0.113.10']
    for j, ip in enumerate(ips):
        for k in range(7 * 24 * 2):   # раз в 30 минут неделю; у второго адреса — с перерывами (ритм нарушен)
            if j == 1 and k % 5 == 0: continue
            log.line(ip, synth.T0 + timedelta(minutes=30 * k + j * 7), '/', 200, ua=UA_BXMON, size=51234)
    res, out, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Общий анализ']['Люди и боты']
    mon = G[(G['группа'] == 'Системы мониторинга') & (G['подгруппа'].astype(str) == 'BitrixCloud Monitoring')]
    assert int(mon['IP'].sum()) == 2, G
    assert not len(G[(G['группа'] == 'Боты') & (G['подгруппа'].astype(str) == 'явные (не браузер)')]), G
    assert 'неопознанный мониторинг' not in set(G['подгруппа'].astype(str)), G
    _outside(res, out, ips)

