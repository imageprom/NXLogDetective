"""NXLD: ведомственные роботы — проверяющие системы Роскомнадзора (сети ФГУП «ГРЧЦ») и сканер СайберОК (СКИПА).

Справочник — data/reference/gov_robots.json (сети, ASN, источник и to_verify у каждой записи), подписи — data/locale/<язык>/gov_robots.json.
Принадлежность по ASN берётся из базы сетей (asn визита), если она есть, иначе по префиксам; из двух префиксов — более узкий. Сеть — не приговор: тип визита решает поведение (visits.mark_gov_robots)."""
import ipaddress
import json
import os

import numpy as np
import pandas as pd

from . import texts

_REF = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference', 'gov_robots.json'))
_C = {}


def ref():
    if 'ref' not in _C:
        try: _C['ref'] = json.load(open(_REF, encoding='utf-8'))
        except Exception: _C['ref'] = {}
    return _C['ref']


def tx(): return texts.file('gov_robots')


def nets():
    """[(сеть, оператор)] по справочнику, узкие сети раньше широких."""
    if 'nets' not in _C:
        out = []
        for op, rec in (ref().get('operators') or {}).items():
            for p in rec.get('prefixes', []):
                try: out.append((ipaddress.ip_network(p['net']), op))
                except ValueError: pass
        _C['nets'] = sorted(out, key=lambda x: -x[0].prefixlen)
    return _C['nets']


def asn_ops():
    if 'asn' not in _C:
        _C['asn'] = {int(a): op for op, rec in (ref().get('operators') or {}).items() for a in rec.get('asn', [])}
    return _C['asn']


def operator_of(ip, asn=0):
    """Оператор сети IP: префикс справочника (более узкий), иначе ASN. '' — не из сетей справочника."""
    try: a = ipaddress.ip_address(str(ip))
    except ValueError: a = None
    if a is not None:
        for n, op in nets():
            if a.version == n.version and a in n: return op
    try: return asn_ops().get(int(asn), '')
    except (TypeError, ValueError): return ''


def operators(ips, asns=None):
    """Оператор для списка IP (по уникальным): массив строк. asns — ASN из базы сетей, если известны."""
    ips = pd.Series(list(ips), dtype=str)
    asns = pd.Series(asns if asns is not None else [0] * len(ips)).fillna(0).values
    cache = {}
    out = np.empty(len(ips), dtype=object)
    for i, (ip, a) in enumerate(zip(ips.values, asns)):
        k = (ip, a)
        if k not in cache: cache[k] = operator_of(ip, a)
        out[i] = cache[k]
    return out


def user_agents():
    return [u for rec in (ref().get('operators') or {}).values() for u in rec.get('user_agents', [])]
