"""NXLD: выгрузка STIX 2.1 — полный пакет проверки по ТЗ, раздел 10.5–10.6.

Один JSON-пакет (bundle): сигнатуры поведения (indicator: правило Sigma целиком и шаблон STIX), дела (intrusion-set),
IP и сети (ipv4-addr, autonomous-system), связи с описанием улики (relationship), что и сколько раз видели (sighting),
статус и уверенность, автор (identity) и метки распространения TLP.
Коды объектов — UUID v5 от наших постоянных кодов (SIG-…, номер дела, IP): повторная выгрузка не задваивает объекты у получателя.
В пакет не попадают: белый список (сотрудники, сервер сайта, мониторинги, подлинные роботы), IP людей, содержимое файлов.
Документация: https://docs.oasis-open.org/cti/stix/v2.1/stix-v2.1.html"""
import json, uuid
from datetime import datetime, timezone, timedelta
import pandas as pd

NS = uuid.UUID('6f1d2c3a-6e0b-5d3e-9a51-4e584c440001')   # пространство имён NX Log Detective для UUID v5
TLP_AMBER = 'marking-definition--f88d31f6-486f-44da-b317-01333bde0b82'   # стандартные метки STIX 2.1 (спецификация, 7.2.1.4)
TLP_GREEN = 'marking-definition--34098fce-860f-48ae-8e50-ebd3cc5e41da'
TLP_DEFS = {TLP_AMBER: 'amber', TLP_GREEN: 'green'}
CASES = ('Тревога', 'Срочно', 'Важно')   # дела с IP; «К сведению» — только сигнатуры
CONF = {'доказано': 85, 'вероятно': 60, 'совпадение': 30}
LEVEL = {'Тревога': 'critical', 'Срочно': 'high', 'Важно': 'medium', 'К сведению': 'low', 'Замечание': 'informational'}
MAX_IP_PATTERN = 100   # IP в одном шаблоне STIX и в одном правиле Sigma; остальные — объектами ipv4-addr со связями


def sid(kind, key):
    return f"{kind}--{uuid.uuid5(NS, f'{kind}:{key}')}"


def ts(x=None):
    """Время STIX: UTC, «2026-10-01T18:36:00.000Z»."""
    if x is None: t = datetime.now(timezone.utc)
    else:
        t = pd.Timestamp(x)
        t = (t.tz_localize('UTC') if t.tzinfo is None else t.tz_convert('UTC')).to_pydatetime()
    return t.strftime('%Y-%m-%dT%H:%M:%S.') + f'{t.microsecond // 1000:03d}Z'


def _dmy(v):
    try: return ts(pd.to_datetime(v, dayfirst=True))
    except Exception: return None


def status(verdict, nettype):
    """Статус адреса по ТЗ 10.6: blocklist, watchlist, anonymization; белый список в пакет не идёт."""
    if verdict == 'не трогать': return None
    if 'VPN' in str(nettype) or 'прокси' in str(nettype): return 'anonymization'
    return 'malicious-activity' if verdict == 'заблокировать' else 'anomalous-activity'


def valid_until(start, nettype):
    """Домашние и мобильные адреса меняются быстро — короткий срок; хостинги — дольше."""
    days = 90 if str(nettype).startswith('дата-центр') else 30
    return ts(pd.Timestamp(start) + timedelta(days=days))


def sigma_rule(sig, case, ips, learned):
    """Правило Sigma 2.1.0 (YAML) для сигнатуры: только то, что формат умеет; остальное — словами в description и falsepositives."""
    import yaml
    rule = (learned.get(sig['id']) or {}).get('rule') or {}
    det, fp = {}, []
    if rule.get('user_agent'):
        det['selection'] = {'cs-user-agent|contains': rule['user_agent']}
        if rule.get('сеть_не'):
            fp.append(f"Подлинный {rule['user_agent']} — запросы из сетей AS{', AS'.join(map(str, rule['сеть_не']))}: "
                      'в таксономии webserver поля сети нет, проверять по сети или обратному DNS')
    if not det and not ips: return None   # поведение без адресов (дела «К сведению») в Sigma не выражается — правило не выгружается
    if not det:
        det['selection'] = {'c-ip': sorted(ips)[:MAX_IP_PATTERN]}
        fp.append('Правило по адресам этого дела: поведение (' + '; '.join(rule.get('признаки') or [sig.get('правило', '')]) +
                  ') в Sigma не выражается, описано в description')
    if sig.get('ложных'): fp.append(f"Из тех же сетей приходят люди ({sig['ложных']} визитов): сеть целиком не закрывать")
    det['condition'] = 'selection'
    doc = {'title': f"{sig['id']}: {case['кличка']}", 'id': str(uuid.uuid5(NS, f"sigma:{sig['id']}")), 'status': 'experimental',
           'description': f"{sig['правило']}. Проверка на логе: {sig.get('проверка', '')}. Дело {case['дело']}: " +
                          '; '.join(f"{o['статья']} ({o['сила']})" for o in case['обвинения'][:4]),
           'author': 'NX Log Detective', 'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
           'logsource': {'category': 'webserver'}, 'detection': det, 'falsepositives': fp or ['Неизвестны'],
           'level': LEVEL.get(case['важность'], 'medium')}
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def stix_pattern(sig, ips, learned):
    """Шаблон STIX: User-Agent подделки или адреса дела (до MAX_IP_PATTERN)."""
    rule = (learned.get(sig['id']) or {}).get('rule') or {}
    if rule.get('user_agent'):
        ua = str(rule['user_agent']).replace("'", "\\'")
        return f"[network-traffic:extensions.'http-request-ext'.request_header.'User-Agent' LIKE '%{ua}%']"
    ips = sorted(ips)[:MAX_IP_PATTERN]
    return ' OR '.join(f"[ipv4-addr:value = '{ip}']" for ip in ips) if ips else None


def build(res, site, version='0.2.0'):
    """STIX-пакет проверки: dict bundle и сводка (сколько чего) для Обзоров."""
    Pf = res.get('profiles') or {}
    D = Pf.get('дела') or []
    MI = Pf.get('меры_ip')
    Sg = Pf.get('сигнатуры')
    S = (res.get('sheets') or {}).get('Боты', {})
    ev = S.get('Операторы: улики')
    try:
        from .profiles import REF
        import os
        learned = json.load(open(os.path.join(REF, 'learned', 'signatures.json'), encoding='utf-8'))
        learned = next(iter(learned.values())) if len(learned) == 1 and not str(next(iter(learned))).startswith('SIG-') else learned
    except Exception:
        learned = {}
    p0, p1 = (res.get('inventory') or {}).get('period') or [None, None]
    now = ts()
    me = {'type': 'identity', 'spec_version': '2.1', 'id': sid('identity', 'nxld'), 'created': now, 'modified': now,
          'name': f'NX Log Detective {version}', 'identity_class': 'system'}
    where = {'type': 'identity', 'spec_version': '2.1', 'id': sid('identity', f'site:{site}'), 'created': now, 'modified': now,
             'name': site, 'identity_class': 'organization', 'created_by_ref': me['id'], 'object_marking_refs': [TLP_AMBER]}
    objs = [me, where]
    marks = [{'type': 'marking-definition', 'spec_version': '2.1', 'id': m, 'created': '2017-01-20T00:00:00.000Z',
              'definition_type': 'tlp', 'name': f'TLP:{c.upper()}', 'definition': {'tlp': c}} for m, c in TLP_DEFS.items()]
    objs += marks
    base = lambda t, key, **kw: {'type': t, 'spec_version': '2.1', 'id': sid(t, key), 'created': now, 'modified': now,
                                 'created_by_ref': me['id'], **kw}
    ips_of = {}
    if MI is not None and len(MI):
        for _, r in MI.iterrows(): ips_of.setdefault(r['дело'], []).append(r)
    seen_ip, seen_as = {}, {}
    n_ind = n_ip = 0
    sig_by_case = {r['дело']: r for _, r in Sg.iterrows()} if Sg is not None and len(Sg) else {}
    for x in D:
        serious = x['важность'] in CASES
        sig = sig_by_case.get(x['дело'])
        conf = max([CONF.get(o['сила'], 50) for o in x['обвинения']] or [50])
        rows = [r for r in ips_of.get(x['дело'], []) if status(r['приговор'], r['тип_сети'])] if serious else []
        ips = [str(r['ip']) for r in rows]
        iset = None
        if serious:
            iset = base('intrusion-set', f"case:{x['дело']}", name=f"Дело {x['дело']} · {x['кличка']}", object_marking_refs=[TLP_AMBER],
                        description='Обвинения: ' + '; '.join(f"{o['статья']} ({o['сила']}): {o['что']}" for o in x['обвинения']) +
                                    (f". Ущерб: {x['ущерб']}" if x.get('ущерб') else ''),
                        first_seen=ts(pd.to_datetime(x['t0'], unit='s')) if x.get('t0') else None,
                        last_seen=ts(pd.to_datetime(x['t1'], unit='s')) if x.get('t1') else None,
                        confidence=conf, labels=[x['важность']])
            iset = {k: v for k, v in iset.items() if v is not None}
            objs.append(iset)
        if sig is not None:
            vt = 'malicious-activity' if x['важность'] in ('Тревога', 'Срочно') else 'anomalous-activity'
            vfrom = ts(p0) if p0 else now
            for kind, pat in (('sigma', sigma_rule(sig, x, ips, learned)), ('stix', stix_pattern(sig, ips, learned))):
                if not pat: continue
                ind = base('indicator', f"{kind}:{sig['id']}", name=f"{sig['id']}: {x['кличка']}", pattern_type=kind, pattern=pat,
                           valid_from=vfrom, indicator_types=[vt], confidence=conf,
                           description=f"{sig['правило']}. {sig.get('проверка', '')}",
                           object_marking_refs=[TLP_AMBER if (serious and not ((learned.get(sig['id']) or {}).get('rule') or {}).get('user_agent')) else TLP_GREEN],
                           external_references=[{'source_name': 'NX Log Detective', 'external_id': sig['id']}])
                objs.append(ind); n_ind += 1
                if iset: objs.append(base('relationship', f"ind-set:{kind}:{sig['id']}", relationship_type='indicates', source_ref=ind['id'], target_ref=iset['id'],
                                          object_marking_refs=[TLP_AMBER]))
                objs.append(base('sighting', f"sight:{kind}:{sig['id']}:{site}", sighting_of_ref=ind['id'], where_sighted_refs=[where['id']],
                                 count=int(min(sig.get('запросов') or 1, 999999999)), first_seen=ts(p0) if p0 else now, last_seen=ts(p1) if p1 else now,
                                 object_marking_refs=[TLP_AMBER]))
        groups = {}
        for r in rows:   # адреса дела: объект адреса и сети; индикатор — один на группу адресов с одним статусом и сроком (до MAX_IP_PATTERN)
            ip = str(r['ip'])
            if ip not in seen_ip:
                a = {'type': 'ipv4-addr', 'spec_version': '2.1', 'id': sid('ipv4-addr', ip), 'value': ip, 'object_marking_refs': [TLP_AMBER]}
                asn = int(r.get('asn') or 0) if 'asn' in r else 0
                if asn:
                    if asn not in seen_as:
                        seen_as[asn] = {'type': 'autonomous-system', 'spec_version': '2.1', 'id': sid('autonomous-system', str(asn)), 'number': asn,
                                        'name': str(r.get('сеть') or '')}
                        if not seen_as[asn]['name']: del seen_as[asn]['name']
                        objs.append(seen_as[asn])
                    a['belongs_to_refs'] = [seen_as[asn]['id']]
                seen_ip[ip] = a; objs.append(a); n_ip += 1
            st_ = status(r['приговор'], r['тип_сети'])
            groups.setdefault((st_, 90 if str(r['тип_сети']).startswith('дата-центр') else 30), []).append(r)
        for (st_, days), rs in groups.items():
            for k0 in range(0, len(rs), MAX_IP_PATTERN):
                part = rs[k0:k0 + MAX_IP_PATTERN]
                key = f"ips:{x['дело']}:{st_}:{days}:{k0 // MAX_IP_PATTERN}"
                why = pd.Series([str(r['основание']) for r in part]).value_counts().index[0]
                vf = min((v for v in (_dmy(r.get('первый')) for r in part) if v), default=ts(p0) if p0 else now)
                vu = ts(pd.Timestamp(p1 or now) + timedelta(days=days))
                ind = base('indicator', key, name=f"Дело {x['дело']}: {len(part)} IP — {part[0]['приговор']}", pattern_type='stix',
                           pattern=' OR '.join(f"[ipv4-addr:value = '{r['ip']}']" for r in part), valid_from=vf, indicator_types=[st_],
                           confidence=conf if st_ == 'malicious-activity' else min(conf, 50), description=f"{x['кличка']}. Основание: {why}",
                           object_marking_refs=[TLP_AMBER], external_references=[{'source_name': 'NX Log Detective', 'external_id': x['дело']}])
                if pd.Timestamp(vu) > pd.Timestamp(vf): ind['valid_until'] = vu   # домашние и мобильные — короткий срок, хостинги — дольше
                objs.append(ind); n_ind += 1
                if iset: objs.append(base('relationship', f"ind-set:{key}", relationship_type='indicates', source_ref=ind['id'], target_ref=iset['id'],
                                          object_marking_refs=[TLP_AMBER]))
                objs.append(base('opinion', f"op:{key}", explanation=why, opinion='agree' if st_ == 'malicious-activity' else 'neutral',
                                 object_refs=[ind['id']], object_marking_refs=[TLP_AMBER]))
    if ev is not None and len(ev):   # улики между IP операторов: связь «адрес — адрес» с описанием
        for _, e in ev.iterrows():
            a, b = str(e['IP_A']), str(e['IP_B'])
            if a in seen_ip and b in seen_ip and str(e.get('учтена', '')).startswith('да'):
                objs.append(base('relationship', f'ev:{a}:{b}', relationship_type='related-to', source_ref=seen_ip[a]['id'], target_ref=seen_ip[b]['id'],
                                 description=f"{e['улика']} ({e['сила']}): {e['доказательство']}", object_marking_refs=[TLP_AMBER]))
    uniq, seen_ = [], set()   # одна сигнатура у нескольких дел — объект один
    for o in objs:
        if o['id'] in seen_: continue
        seen_.add(o['id']); uniq.append(o)
    objs = uniq
    bundle = {'type': 'bundle', 'id': sid('bundle', f"{site}:{p0}:{p1}"), 'objects': objs}
    sig_ids = sorted({o['external_references'][0]['external_id'] for o in objs if o['type'] == 'indicator' and o.get('pattern_type') == 'sigma'})
    n_rules = len(sig_ids)
    summary = {'объектов': len(objs), 'сигнатур': n_rules, 'сигнатур_всего': int(len(Sg)) if Sg is not None else 0, 'индикаторов': n_ind, 'IP': n_ip,
               'дел': sum(1 for x in D if x['важность'] in CASES), 'сигнатуры_в_пакете': sig_ids}
    return bundle, summary


def validate(bundle):
    """Проверка официальным валидатором STIX (stix2-validator), если он установлен: (успех, сообщения)."""
    try:
        from stix2validator import validate_string, ValidationOptions
    except Exception:
        return None, ['валидатор STIX не установлен — проверка пропущена']
    r = validate_string(json.dumps(bundle, ensure_ascii=False), ValidationOptions(version='2.1', strict=False))
    rs = getattr(r, 'object_results', None) or [r]
    msgs = []
    for o in rs:
        msgs += [str(e) for e in (getattr(o, 'errors', None) or [])][:30]
        msgs += ['предупреждение: ' + str(w) for w in (getattr(o, 'warnings', None) or [])][:10]
    return bool(r.is_valid), msgs
