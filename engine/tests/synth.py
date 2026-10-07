"""Синтетические логи nginx combined для тестов и полный прогон движка во временной папке.

Прогон дописывает справочник data/reference/learned — run() возвращает его как было."""
import os
import pickle
import random
import subprocess
import sys
from datetime import datetime, timedelta

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
LEARNED = os.path.join(ENGINE, '..', 'data', 'reference', 'learned')
UA_CHROME = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
UA_DIRECT = 'Mozilla/5.0 (compatible; YaDirectFetcher/1.0; Dyatel; +http://yandex.com/bots)'
PAGES = ['/', '/catalog/', '/catalog/?PAGEN_1=2', '/catalog/shary/', '/about/', '/contacts/', '/dostavka/', '/akcii/']
ASSETS = ['/local/templates/main/style.css', '/local/templates/main/script.js', '/upload/iblock/1.jpg']
RU = ['95.165.10.20', '95.165.11.30', '176.59.40.10', '94.25.170.10', '46.138.1.1']
T0 = datetime(2026, 9, 1)


class Log:
    def __init__(self, seed=1):
        self.L = []
        random.seed(seed)

    def line(self, ip, t, url, code=200, ua=UA_CHROME, ref='-', size=None, method='GET'):
        self.L.append((t, f'{ip} - - [{t:%d/%b/%Y:%H:%M:%S} +0300] "{method} {url} HTTP/1.1" {code} {size if size is not None else random.randint(2000, 60000)} "{ref}" "{ua}"'))

    def visit(self, ip, t, pages=None, ref='https://yandex.ru/', entry=None):
        """Человек: страница входа, оформление, ещё несколько страниц."""
        pages = pages or PAGES
        p = entry or random.choice(pages)
        self.line(ip, t, p, 200, ref=ref)
        for a in ASSETS: self.line(ip, t + timedelta(seconds=1), a, 200, ref=f'https://site.ru{p}')
        for k in range(3):
            self.line(ip, t + timedelta(seconds=30 * (k + 1)), random.choice(pages), 200, ref=f'https://site.ru{p}')

    def people(self, days=7, per_day=20, pages=None):
        """Люди из России по дням; в каждом дне — пара битых адресов и сканер, как в живом логе."""
        for d in range(days):
            for k in range(per_day):
                self.visit(RU[k % len(RU)], T0 + timedelta(days=d, hours=8, minutes=25 * k), pages)
            self.line(RU[d % len(RU)], T0 + timedelta(days=d, hours=12), '/old-page/', 404, ref='https://site.ru/')
            for k, u in enumerate(('/.env', '/wp-login.php', '/phpinfo.php', '/.git/config')):
                self.line('185.220.101.5', T0 + timedelta(days=d, hours=3, seconds=k), u, 404, ua='Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0')

    def write(self, path):
        self.L.sort(key=lambda x: x[0])
        with open(path, 'w') as f: f.write('\n'.join(s for _, s in self.L) + '\n')
        return len(self.L)


def run(log, d, *extra):
    """Полный прогон nxld_run.py: возвращает (res, out, вывод). Справочник learned — как был."""
    path, work, out = os.path.join(d, 'access.log'), os.path.join(d, 'work'), os.path.join(d, 'out')
    log.write(path)
    keep = {os.path.join(r, f): open(os.path.join(r, f), 'rb').read() for r, _, fs in os.walk(LEARNED) for f in fs}
    try:
        p = subprocess.run([sys.executable, os.path.join(ENGINE, 'nxld_run.py'), '--logs', path, '--work', work, '--out', out, *extra],
                           capture_output=True, text=True, timeout=900, env=dict(os.environ, NXLD_STRICT_CATALOG='1'))   # лист вне каталога — ошибка
    finally:
        for r, _, fs in os.walk(LEARNED):
            for f in fs:
                if os.path.join(r, f) not in keep: os.remove(os.path.join(r, f))
        for f, b in keep.items(): open(f, 'wb').write(b)
    text = p.stdout + p.stderr
    assert p.returncode == 0, text[-4000:]
    assert 'Traceback' not in text, text[-4000:]
    return pickle.load(open(os.path.join(work, 'results.pkl'), 'rb')), out, text
