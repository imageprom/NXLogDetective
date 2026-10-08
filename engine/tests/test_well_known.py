"""/.well-known: стандартное имя без других улик — не зонд в любой сети; нестандартное имя — зонд (задача #10, раунд 3)."""
from datetime import timedelta

import synth

UA_PASS = 'com.apple.AuthenticationServicesCore.AuthenticationServicesAgent/20618.2.12.11.6 CFNetwork/1568.200.51 Darwin/24.1.0'
UA_SCAN = 'Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0'
# Cloudflare (iCloud Private Relay), Akamai (Private Relay), Fastly, домашняя сеть
PASS = ['104.28.10.5', '172.224.226.5', '23.32.0.5', '151.101.0.5', '146.75.0.5', synth.RU[1]]
STD = ['/.well-known/passkey-endpoints', '/.well-known/apple-app-site-association', '/.well-known/assetlinks.json',
       '/.well-known/security.txt', '/.well-known/traffic-advice', '/.well-known/openid-configuration', '/.well-known/mta-sts.txt']
ODD = ['/.well-known/shell.php', '/.well-known/.env', '/.well-known/x/index.php']


def _log():
    log = synth.Log()
    log.people()
    for d in range(7):
        for j, ip in enumerate(PASS):
            for k, u in enumerate(STD):
                log.line(ip, synth.T0 + timedelta(days=d, hours=2 + k, minutes=j), u, 404, ua=UA_PASS)
        for k, u in enumerate(ODD * 4):   # нестандартные имена из той же сети — зонд
            log.line('104.28.99.7', synth.T0 + timedelta(days=d, hours=3, seconds=k), u, 404, ua=UA_SCAN)
    return log


def _recon(res):
    return {ip: [o['что'] for o in d['обвинения'] if o['id'] == 'recon'] for d in res['profiles']['дела'] for ip in d.get('ips', [])}


def test_standard_well_known_not_probe_in_any_net(tmp_path):
    res, _, _ = synth.run(_log(), str(tmp_path))
    rc = _recon(res)
    assert not any(rc.get(ip) for ip in PASS), {ip: rc.get(ip) for ip in PASS}
    assert not any(set(d.get('ips', [])) & set(PASS) for d in res['profiles']['дела'])
    assert rc.get('104.28.99.7'), rc   # нестандартное имя — по-прежнему «Разведка»


def test_apple_autofill_agent_is_people(tmp_path):
    """#14: агент автозаполнения паролей Apple только со стандартными /.well-known/ — «Люди»; тот же UA с посторонним
    адресом — обычные правила (не «Люди»)."""
    log = synth.Log()
    log.people()
    ONLY, ODD_IP = ['95.165.160.1', '104.28.10.6', '172.224.226.6'], '95.165.160.2'
    for d in range(7):
        for j, ip in enumerate(ONLY):
            log.line(ip, synth.T0 + timedelta(days=d, hours=20, minutes=j), '/.well-known/passkey-endpoints', 404, ua=UA_PASS)
            log.line(ip, synth.T0 + timedelta(days=d, hours=20, minutes=j, seconds=2), '/.well-known/apple-app-site-association', 404, ua=UA_PASS)
        log.line(ODD_IP, synth.T0 + timedelta(days=d, hours=21), '/.well-known/passkey-endpoints', 404, ua=UA_PASS)
        log.line(ODD_IP, synth.T0 + timedelta(days=d, hours=21, seconds=3), '/catalog/', 200, ua=UA_PASS)
    res, _, _ = synth.run(log, str(tmp_path))
    G = res['sheets']['Общий анализ']['Люди и боты']
    assert 'явные (не браузер)' in set(G.loc[G['группа'] == 'Боты', 'подгруппа'].astype(str)), G   # ODD_IP — обычные правила
    assert int(G.loc[G['группа'] == 'Люди', 'IP'].sum()) == len(set(synth.RU)) + len(ONLY), G
    import sys
    sys.path.insert(0, synth.ENGINE)
    import json, os
    A = json.load(open(os.path.join(synth.ENGINE, '..', 'data', 'reference', 'system_agents.json'), encoding='utf-8'))
    assert A.get('to_verify') == 'проверить заново на новых данных'
