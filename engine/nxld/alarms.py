"""NXLD: уровень «Тревога» — выше «Срочно».

Тревога — подтверждённый вред, который идёт сейчас, или угроза данным: служебный файл отдаётся посторонним до конца лога
(или по проверке из сети), сбой не закончился, веб-шелл, загрузка файлов посторонними, персональные данные в адресах,
закрытый раздел отдаёт данные без входа, атака получила необычный ответ и проверка подтвердила. Правила и пороги —
data/severity_rules.json → «тревога». Вызов идемпотентный: после правок Детектива (edits.json) применяется снова."""
import json, os
import pandas as pd

PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'severity_rules.json'))


def rules():
    try: return json.load(open(PATH, encoding='utf-8')).get('тревога', {})
    except Exception: return {}


def _type(x):
    k = str(x.get('key', ''))
    return k.split(':')[1] if k.count(':') >= 2 else ''


def leaks_open(res):
    """Служебные файлы, которые отдаются посторонним сейчас: по проверке из сети, а без неё — по последнему ответу в логе в последние дни."""
    L = (res.get('security') or {}).get('утечки')
    if L is None or not len(L): return []
    out = []
    for _, r in L.iterrows():
        chk = str(r.get('проверка', '') or '')
        if chk.startswith('закрыт'): continue
        if chk.startswith('открыт') or bool(r.get('открыт_сейчас')): out.append(str(r['файл']))
    return out


def apply(res, items=None):
    R_ = rules()
    items = res.get('findings') if items is None else items
    if not items: return items
    sec = res.get('security') or {}
    for x in items:
        if x.get('_до_тревоги'): x['важность'] = x.pop('_до_тревоги')   # повторный вызов — от исходной важности
        t, why = _type(x), None
        if t == 'exposed' and R_.get('утечка_открыта_сейчас'):
            op = leaks_open(res)
            if op: why = 'отдаётся посторонним сейчас: ' + ', '.join(op)
        elif t == 'outage' and R_.get('сбой_продолжается') and 'продолжается на конец лога' in str(x.get('почему', '')) + str(x.get('факты', '')):
            why = 'сбой продолжается на конец лога'
        elif t == 'webshell' and R_.get('веб_шелл'): why = 'исполняемый файл в папке загрузок отвечает'
        elif t == 'upload_outsiders' and R_.get('загрузка_посторонними'): why = 'посторонние загружают файлы на сервер'
        elif t == 'pd_in_get' and (x.get('главная_цифра') or 0) >= R_.get('персональные_данные_в_адресе_от', 5): why = 'персональные данные уходят в адресах'
        elif t == 'open_section':
            Z = sec.get('разделы')
            mb = float(Z.loc[Z['раздел'] == x['key'].split(':', 2)[2], 'без_входа_байт'].sum()) / 1024 ** 2 if Z is not None and len(Z) and 'без_входа_байт' in Z else 0
            if mb >= R_.get('раздел_без_входа_скачано_МБ', 1): why = f'без входа отдано {mb:.1f} МБ'.replace('.', ',')
        elif t == 'attack_odd_200' and R_.get('атака_необычный_200_подтверждена') and x.get('подтверждено'):
            why = 'проверка из сети подтвердила необычный ответ'
        if why:
            x['_до_тревоги'] = x['важность']; x['важность'] = 'Тревога'
            x['почему_тревога'] = why
    return items


def count(res, block=None):
    return sum(1 for x in res.get('findings') or [] if x.get('важность') == 'Тревога' and (block is None or x.get('блок') == block))
