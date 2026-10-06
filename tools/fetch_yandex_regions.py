#!/usr/bin/env python3
"""Обновить справочник регионов Яндекса (data/reference/regions_yandex.json) из API Директа.

Запуск — у себя, со своим OAuth-токеном приложения с доступом к API Директа (токен в файл не пишется):
    python3 tools/fetch_yandex_regions.py --token ТОКЕН [--client-login ЛОГИН]

Справочник Dictionaries.get → GeoRegions: GeoRegionId, GeoRegionName, GeoRegionType, ParentId.
Названия и родители из API заменяют прежние; коды, которых в API нет, остаются как были (из геобазы geo.c2n)."""
import argparse, datetime, json, os, sys
import requests

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'reference', 'regions_yandex.json')
LEVEL = {'World': 0, 'Continent': 0, 'Region': 1, 'Country': 1, 'Administrative area': 2, 'City': 3, 'Village': 4, 'District': 4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token', required=True)
    ap.add_argument('--client-login')
    a = ap.parse_args()
    h = {'Authorization': f'Bearer {a.token}', 'Accept-Language': 'ru', 'Content-Type': 'application/json; charset=utf-8'}
    if a.client_login: h['Client-Login'] = a.client_login
    r = requests.post('https://api.direct.yandex.com/json/v5/dictionaries', headers=h, timeout=120,
                      json={'method': 'get', 'params': {'DictionaryNames': ['GeoRegions']}})
    d = r.json()
    if 'error' in d: sys.exit(f"Ошибка API: {d['error']}")
    geo = d['result']['GeoRegions']
    ref = json.load(open(REF, encoding='utf-8')) if os.path.exists(REF) else {'регионы': {}}
    R = ref.setdefault('регионы', {})
    for g in geo:
        x = R.setdefault(str(g['GeoRegionId']), {})
        x['название'] = g['GeoRegionName']
        if g.get('ParentId'): x['родитель'] = int(g['ParentId'])
        lv = LEVEL.get(g.get('GeoRegionType'))
        if lv is not None: x['уровень'] = lv
    today = datetime.date.today().isoformat()
    ref['источники'] = [s for s in ref.get('источники', []) if 'API' not in s.get('файл', '')] + [{'что': 'названия и вложенность', 'файл': 'API Яндекс Директа v5, Dictionaries GeoRegions', 'получено': today}]
    ref['загружено'] = today; ref['регионов'] = len(R)
    json.dump(ref, open(REF, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'Регионов из API: {len(geo)}; всего в справочнике: {len(R)}')


if __name__ == '__main__':
    main()
