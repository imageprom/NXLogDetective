"""IP с обычными визитами людей (покупатели за IP мобильной сети, офиса) — не в STIX и не в «Мерах по IP» с блокировкой (задача #6)."""
import glob
import json
import os
from datetime import timedelta

import synth

UA_SCAN = 'Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0'
IPS = [f'81.2.69.{10 + i}' for i in range(20)]   # одна домашняя сеть: 20 IP перебирают зонды, у трёх — ещё и обычные визиты людей
PEOPLE = IPS[:3]


def _log():
    log = synth.Log()
    log.people()
    for i, ip in enumerate(IPS):
        for d in range(3):
            t = synth.T0 + timedelta(days=d + i % 4, hours=1, minutes=i)
            for j, u in enumerate(('/.env', '/.git/config', '/phpinfo.php', '/.env.bak', '/wp-login.php', '/backup.sql')):
                log.line(ip, t + timedelta(seconds=j), u, 404, ua=UA_SCAN)
    for ip in PEOPLE:   # страница + ресурсы, подгруженные страницей
        for d in range(3):
            log.visit(ip, synth.T0 + timedelta(days=d, hours=19))
    return log


def test_people_ips_not_blocked(tmp_path):
    res, out, _ = synth.run(_log(), str(tmp_path))
    Pf = res['profiles']
    MI = Pf['меры_ip']
    net = MI[MI['ip'].astype(str).isin(IPS)]
    act = net[net['приговор'].isin(['заблокировать', 'ограничить частоту'])]
    assert len(act) == 17 and not act['ip'].isin(PEOPLE).any(), net[['ip', 'приговор']]
    keep = net[net['ip'].isin(PEOPLE)]
    assert (keep['приговор'] == 'не трогать').all() and keep['основание'].str.contains('есть человеческие визиты').all(), keep
    st = json.load(open(glob.glob(os.path.join(out, '*.stix.json'))[0], encoding='utf-8'))
    in_stix = {ip for o in st['objects'] if o.get('type') == 'indicator' for ip in IPS if f"'{ip}'" in o.get('pattern', '')}
    assert len(in_stix) == 17 and not in_stix & set(PEOPLE), sorted(in_stix)
    C = Pf['состав']
    mark = C[C['ip'].isin(IPS)].set_index('ip')['пометка']
    assert set(mark[mark == 'есть человеческие визиты'].index) == set(PEOPLE), mark   # в деле остаются — как улика, с пометкой
