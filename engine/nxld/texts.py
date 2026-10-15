"""NXLD: тексты карточек — обычными строками в data/locale/<язык>/cards.json (язык — NXLD_LOCALE, по умолчанию ru).
Ключ — тип карточки (латиницей); в тексте подстановки {имя} вида str.format."""
import json
import os

LOCALE = os.environ.get('NXLD_LOCALE', 'ru')
_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'locale', LOCALE, 'cards.json'))
_CACHE = {}


def file(name):
    """Тексты листа или блока отчёта — data/locale/<язык>/<name>.json целиком."""
    if name not in _CACHE:
        try: _CACHE[name] = json.load(open(os.path.join(os.path.dirname(_PATH), name + '.json'), encoding='utf-8'))
        except Exception: _CACHE[name] = {}
    return _CACHE[name]


def card(key):
    """Тексты карточки: found, check (для справочника проблем), title, facts, where, action."""
    if 'all' not in _CACHE:
        try: _CACHE['all'] = json.load(open(_PATH, encoding='utf-8'))
        except Exception: _CACHE['all'] = {}
    return _CACHE['all'].get(key, {})


def fmt(key, field, **kw):
    """Текст поля карточки с подстановками."""
    return str(card(key).get(field, '')).format(**kw)
