"""NXLD: связывание IP спама форм в операторов по уликам.

Улики делятся на три силы:
- сильная — достаточно одной: смена IP посреди визита (визит пришёл со страницы, которую за ≤ 2 ч до этого открыл
  другой IP и получил 404); общий битый вход, на который люди напрямую почти не заходят (≤ 5 IP);
- средняя — нужна ещё хотя бы одна улика: общий битый вход, на который заходят и люди; реферер — битый адрес,
  через который входил другой спамер; тот же приём входа (прямой заход на битый адрес в том же разделе, затем форма);
- слабая — сама по себе ничего не связывает: тот же браузер (UA целиком), та же сеть (ASN), одна волна (отправки в
  один день с разницей ≤ 2 ч).
Группы склеиваются, если между ними есть сильная улика или средняя плюс любая другая (сумма баллов ≥ 3:
сильная 3, средняя 2, слабая 1; средняя обязательна).
"""
import re
from collections import defaultdict
from itertools import combinations
import pandas as pd

W = {'сильная': 3, 'средняя': 2, 'слабая': 1}
WAVE = 7200


def _path(ref):
    return re.sub(r'^https?://[^/]+', '', str(ref)).split('?')[0]


def _ts(x):
    return pd.Timestamp(int(x), unit='s').strftime('%d.%m %H:%M')


def link(V, spam_ips, human_direct_max=5):
    spam_ips = set(spam_ips)
    sv = V[V['ip'].isin(spam_ips)]
    spam_v = sv[sv['subgroup'].str.startswith('спам форм')]
    ev = []   # (a, b, тип, сила, доказательство)

    def add(a, b, typ, force, proof):
        if a != b:
            a, b = sorted((a, b))
            ev.append(dict(IP_A=a, IP_B=b, улика=typ, сила=force, доказательство=proof))

    e404 = V[(V['entry_status'] == 404) & (V['fam_verified'] != 'да')]
    direct = e404['entry_ref'].isin(['-', ''])
    hum_direct = e404[(e404['group'] == 'Люди') & direct].groupby('entry')['ip'].nunique()
    # 1. общий битый вход
    s404 = sv[sv['entry_status'] == 404]
    for ent, g in s404.groupby('entry'):
        ips = sorted(set(g['ip']))
        if len(ips) < 2: continue
        nh = int(hum_direct.get(ent, 0))
        force = 'сильная' if nh <= human_direct_max else 'средняя'
        first = g.groupby('ip')['start'].min()
        for a, b in combinations(ips, 2):
            add(a, b, 'общий битый вход', force, f'оба входили на {ent} (404): {a} — {_ts(first[a])}, {b} — {_ts(first[b])}; людей с прямым заходом туда {nh}')
    # 2. смена IP посреди визита (сильная) и реферер — битый вход другого спамера (средняя)
    recon = set()
    spam404_by_entry = s404.groupby('entry')['ip'].agg(set)
    for _, r in spam_v[spam_v['entry_ref_internal']].iterrows():
        pth = _path(r['entry_ref'])
        mm = e404[(e404['entry'] == pth) & (e404['ip'] != r['ip']) & (r['start'] - e404['start']).between(0, 7200)]
        for _, o in mm.drop_duplicates('ip').iterrows():
            add(r['ip'], o['ip'], 'смена IP посреди визита', 'сильная',
                f"{o['ip']} открыл {pth} (404) в {_ts(o['start'])}, через {int((r['start'] - o['start']) // 60)} мин {r['ip']} пришёл с этой страницы и отправил форму")
            if o['ip'] not in spam_ips: recon.add(o['ip'])
        for o in spam404_by_entry.get(pth, set()) - {r['ip']}:
            add(r['ip'], o, 'реферер — битый вход другого спамера', 'средняя',
                f"{r['ip']} пришёл со страницы {pth}, которой нет на сайте; через неё же входил спамер {o}")
    # разведка, вошедшая через те же редкие битые адреса, что и спам
    for _, r in e404[e404['ip'].isin(recon)].drop_duplicates(['ip', 'entry']).iterrows():
        for o in spam404_by_entry.get(r['entry'], set()):
            nh = int(hum_direct.get(r['entry'], 0))
            add(r['ip'], o, 'общий битый вход', 'сильная' if nh <= human_direct_max else 'средняя',
                f"разведка {r['ip']} и спамер {o} входили на {r['entry']} (404); людей с прямым заходом туда {nh}")
    # 3. тот же приём входа: прямой заход на битый адрес в одном разделе, затем форма
    trick = spam_v[spam_v['subgroup'] == 'спам форм: битый адрес → главная → форма'].copy()
    if len(trick):
        trick['раздел'] = trick['entry'].str.extract(r'^(/[^/]+/)', expand=False).fillna('/') + trick['entry'].str.endswith('/').map({True: ' (со слэшем)', False: ' (без слэша)'})
        for sec, g in trick.groupby('раздел'):
            ips = sorted(set(g['ip']))
            ex = g.groupby('ip')['entry'].first()
            for a, b in combinations(ips, 2):
                if ex[a] != ex[b]:
                    add(a, b, 'тот же приём входа', 'средняя', f'прямой заход на несуществующий адрес раздела {sec}, затем форма: {a} — {ex[a]}, {b} — {ex[b]}')
    # 4. слабые: UA, сеть, волна (только между спамерами)
    info = spam_v.groupby('ip').agg(ua=('ua', 'first'), asn=('asn', 'first'), t=('start', list))
    for a, b in combinations(sorted(info.index), 2):
        A, B = info.loc[a], info.loc[b]
        if A['ua'] == B['ua']:
            add(a, b, 'тот же браузер', 'слабая', f"одинаковый UA: {A['ua'][:90]}")
        if A['asn'] and A['asn'] == B['asn']:
            add(a, b, 'та же сеть', 'слабая', f"ASN {A['asn']}")
        near = [(x, y) for x in A['t'] for y in B['t'] if abs(x - y) <= WAVE]
        if near:
            x, y = near[0]
            add(a, b, 'одна волна', 'слабая', f'отправки {_ts(x)} и {_ts(y)}')
    E = pd.DataFrame(ev, columns=['IP_A', 'IP_B', 'улика', 'сила', 'доказательство']).drop_duplicates(['IP_A', 'IP_B', 'улика'])
    # склейка: сначала по сильным, затем группы со средней + ещё одной уликой
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for ip in spam_ips | recon: find(ip)
    for _, e in E[E['сила'] == 'сильная'].iterrows():
        parent[find(e['IP_A'])] = find(e['IP_B'])
    changed = True
    while changed:
        changed = False
        score = defaultdict(lambda: defaultdict(int))
        for _, e in E[E['сила'] != 'сильная'].iterrows():
            a, b = find(e['IP_A']), find(e['IP_B'])
            if a == b: continue
            k = tuple(sorted((a, b)))
            score[k][(e['улика'], e['сила'])] = W[e['сила']]
        for (a, b), types in score.items():
            if any(f == 'средняя' for _, f in types) and sum(types.values()) >= 3 and find(a) != find(b):
                parent[find(a)] = find(b); changed = True
    comps = defaultdict(set)
    for ip in spam_ips | recon: comps[find(ip)].add(ip)
    # компактная таблица улик: по одной строке на присоединение IP к группе (самая сильная улика пары,
    # остальные улики этой пары — через «;»), плюс связи между разными группами, которых не хватило для склейки
    E['_s'] = E['сила'].map({'сильная': 0, 'средняя': 1, 'слабая': 2})
    P = (E.sort_values('_s').groupby(['IP_A', 'IP_B'], sort=False)
         .agg(сила=('сила', 'first'), _s=('_s', 'first'), улика=('улика', lambda x: '; '.join(dict.fromkeys(x))),
              доказательство=('доказательство', 'first')).reset_index())
    P['_same'] = [find(a) == find(b) for a, b in zip(P['IP_A'], P['IP_B'])]
    tree, par = [], {}
    def f2(x):
        par.setdefault(x, x)
        while par[x] != x: x = par[x]
        return x
    for _, r in P[P['_same']].sort_values(['_s', 'IP_A']).iterrows():
        a, b = f2(r['IP_A']), f2(r['IP_B'])
        if a != b:
            par[a] = b; tree.append(r)
    out = pd.DataFrame(tree)
    if len(out): out['учтена'] = 'да — связывает в группу'
    rest = P[~P['_same']].copy()
    rest['учтена'] = 'нет — улик не хватает (нужна средняя или сильная)'
    cols = ['IP_A', 'IP_B', 'сила', 'улика', 'доказательство', 'учтена']
    out = pd.concat([out, rest], ignore_index=True)
    out = out[cols] if len(out) else pd.DataFrame(columns=cols)
    return list(comps.values()), recon, out
