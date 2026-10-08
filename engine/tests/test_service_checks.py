"""Запросы к стандартным файлам /.well-known/ из сетей самих сервисов (Google, Apple…) — «Роботы · проверка сервиса»:
без дел, обвинений, сигнатур и STIX (задача #10, дополнение). Akamai — не сеть сервиса: через неё идёт iCloud Private Relay (люди),
но и оттуда стандартное имя — не зонд, дел нет (раунд 3)."""
import glob
import json
import os
from datetime import timedelta

import synth

GOOGLE = ['66.249.66.5', '74.125.210.5', '108.177.8.5']
AKAMAI = ['23.32.0.5', '23.192.0.5']
UA_LINKS = 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'
UA_PASS = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15'


def _log():
    log = synth.Log()
    log.people()
    for d in range(7):
        for j, ip in enumerate(GOOGLE):   # проверка связи приложения Android с сайтом
            for k in range(4):
                log.line(ip, synth.T0 + timedelta(days=d, hours=1 + k, minutes=j), '/.well-known/assetlinks.json', 404, ua=UA_LINKS)
        for j, ip in enumerate(AKAMAI):   # менеджеры паролей
            for k in range(3):
                log.line(ip, synth.T0 + timedelta(days=d, hours=5 + k, minutes=j), '/.well-known/passkey-endpoints', 404, ua=UA_PASS)
    return log


def test_service_checks_are_robots_without_cases(tmp_path):
    res, out, _ = synth.run(_log(), str(tmp_path))
    G = res['sheets']['Общий анализ']['Люди и боты']
    svc = G[(G['группа'] == 'Роботы') & (G['подгруппа'].astype(str) == 'проверка сервиса')]
    assert int(svc['IP'].sum()) == len(GOOGLE), G   # Akamai убрана из service_checks.json
    ips = set(GOOGLE + AKAMAI)
    Pf = res['profiles'] or {}
    cases = [d for d in Pf.get('дела', []) if set(d.get('ips', [])) & ips]
    assert not cases, [(d['кличка'], [o['статья'] for o in d['обвинения']]) for d in cases]
    MI = Pf.get('меры_ip')
    assert MI is None or not len(MI) or not set(MI['ip'].astype(str)) & ips
    st = glob.glob(os.path.join(out, '*.stix.json'))
    if st:
        text = open(st[0], encoding='utf-8').read()
        assert not any(f"'{ip}'" in text for ip in ips)
