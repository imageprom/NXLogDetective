#!/usr/bin/env python3
"""NXLD: архив скилла для загрузки в Claude (настройки → скиллы).
Внутри одна папка nx-log-detective/: SKILL.md и references/ (из skill/), engine/, data/, tools/, README.md, LICENSE.
Пример: python3 tools/build_skill.py --out dist"""
import argparse, os, subprocess, sys, zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(ROOT, 'engine'))
SKIP_DIRS = {'__pycache__', '.git', '.pytest_cache'}


def files():
    """Только то, что в git (без рабочих прогонов и кэша)."""
    out = subprocess.run(['git', '-C', ROOT, 'ls-files'], capture_output=True, text=True, check=True).stdout.split('\n')
    return [f for f in out if f and not set(f.split('/')) & SKIP_DIRS]


def main():
    from nxld.prepare import VERSION
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=os.path.join(ROOT, 'dist')); a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    zp = os.path.join(a.out, f'nx-log-detective-{VERSION}.zip')
    n = 0
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in files():
            top = f.split('/')[0]
            if top == 'skill': arc = f[len('skill/'):]
            elif top in ('engine', 'data', 'tools') or f in ('README.md', 'LICENSE'): arc = f
            else: continue   # signatures/legacy — только в репозитории
            z.write(os.path.join(ROOT, f), 'nx-log-detective/' + arc); n += 1
        z.writestr('nx-log-detective/VERSION', VERSION + '\n'); n += 1
    print(f'{zp}: {n} файлов, {os.path.getsize(zp) / 1024 ** 2:.1f} МБ')


if __name__ == '__main__':
    main()
