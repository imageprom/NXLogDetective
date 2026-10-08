"""NXLD: пороги — доли от размера лога (data/thresholds.json). Порог = max(минимум, доля × база)."""
import json, math, os

_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'thresholds.json'))
try:
    _T = json.load(open(_PATH, encoding='utf-8'))
except Exception:
    _T = {}


def value(name, default=None):
    """Порог-значение, не зависящее от размера лога: {"значение": …} в data/thresholds.json."""
    return (_T.get(name) or {}).get('значение', default)


class Sizes:
    """Размер лога: визиты людей, запросы, IP — то, от чего считаются доли."""
    def __init__(self, визиты=0, запросы=0, ip=0):
        self.b = {'визиты': визиты, 'запросы': запросы, 'ip': ip}

    def __call__(self, name, default_min=3):
        t = _T.get(name) or {}
        base = self.b.get(t.get('база', 'запросы'), 0)
        return max(int(t.get('минимум', default_min)), int(math.ceil(float(t.get('доля', 0)) * base)))
