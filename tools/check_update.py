#!/usr/bin/env python3
"""NXLD: есть ли версия новее на GitHub. Ничего не скачивает и не меняет — только сообщает.
Нет сети или GitHub недоступен — молча выходит (код 0)."""
import json, os, re, sys, urllib.request

REPO = 'imageprom/NXLogDetective'
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'engine'))


def _key(v):
    m = re.match(r'v?(\d+)\.(\d+)\.(\d+)(?:-(\w+))?', str(v))
    if not m: return None
    a, b, c, pre = m.groups()
    return (int(a), int(b), int(c), 0 if pre else 1, pre or '')


def main():
    from nxld.prepare import VERSION
    try:
        req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/releases?per_page=5', headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'nxld'})
        rel = json.load(urllib.request.urlopen(req, timeout=5))
    except Exception:
        print(f'NXLD {VERSION}: проверка обновлений пропущена (нет доступа к GitHub)')
        return
    tags = [(r.get('tag_name'), r.get('html_url')) for r in rel if not r.get('draft')]
    tags = [(t, u) for t, u in tags if _key(t)]
    if not tags:
        print(f'NXLD {VERSION}: релизов на GitHub нет'); return
    t, u = max(tags, key=lambda x: _key(x[0]))
    if _key(t) > _key(VERSION):
        print(f'NXLD {VERSION}: есть новая версия {t} — {u}. Скачайте архив скилла из релиза и загрузите его в настройках скиллов вместо текущего.')
    else:
        print(f'NXLD {VERSION}: версия актуальная')


if __name__ == '__main__':
    main()
