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
        if chk.startswith('открыт'):   # проверено из сети: тревога — только если внутри существенное (пароли, ключи, доступ к базе)
            if bool(r.get('тревога')): out.append(str(r['файл']))
            continue
        if bool(r.get('открыт_сейчас')): out.append(str(r['файл']))   # не проверено: по логу открыт — тревога, пока не проверят
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
            if op:
                L = sec.get('утечки')
                chk = {str(r['файл']): (str(r.get('проверка') or ''), str(r.get('проверено') or '')) for _, r in L.iterrows()} if L is not None else {}
                net = [f for f in op if chk.get(f, ('', ''))[0].startswith('открыт')]
                if net: why = 'проверено из сети' + (f" {chk[net[0]][1]}" if chk[net[0]][1] else '') + ': отдаётся посторонним, и внутри существенное (пароли, ключи, доступы) — ' + ', '.join(net)
                else: why = 'по логу отдаётся посторонним на конец лога (из сети не проверено): ' + ', '.join(op)
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


def recheck_cases(res):
    """Дела в 04 после проверок из сети: «Тревога» по утечке остаётся, только если файл всё ещё тревожный (leaks_open)."""
    D = (res.get('profiles') or {}).get('дела') or []
    if not D: return
    op_ = set(leaks_open(res))
    for x in D:
        why = x.get('тревога_по') or {}
        if not why or 'важность_без_тревоги' not in x: continue
        alarm = why.get('сбой') or any(f_ in op_ for f_ in why.get('файлы') or [])
        x['важность'] = 'Тревога' if alarm else x['важность_без_тревоги']
    D.sort(key=lambda x: (x['важность'] != 'Тревога', -x.get('вес', 0), -x.get('запросов', 0)))
