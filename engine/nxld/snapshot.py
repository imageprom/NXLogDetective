"""NXLD: снимок проверки NXLD-snapshot/2 — всё, что нужно повторной проверке для сравнения «было → стало».

Совместим с /1: ключи summary, cleaning, daily, findings, ips, marks, site_map сохранены (их читает analyze.run).
Новое: паспорт с отпечатками логов и правил, знаменатели, дела и сигнатуры, проблемные адреса, сбои и всплески,
служебные данные, точки приёма, параметры, состояния страниц людей, журналы всех файлов, реклама, SEO, правки.
IP людей в снимок не попадают никогда: только боты серьёзных дел, свои, сервер и мониторинги. Секреты — нет."""
import glob, hashlib, json, os
from datetime import datetime
import numpy as np, pandas as pd

FORMAT = 'NXLD-snapshot/2'
DATA = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
SERIOUS = ('Тревога', 'Срочно')


def _rec(df, cols=None, n=None):
    """DataFrame → записи (только нужные колонки, без пустых)."""
    if df is None or not hasattr(df, 'columns') or not len(df): return []
    d = df[[c for c in (cols or df.columns) if c in df.columns]]
    if n: d = d.head(n)
    d = d.astype(object).where(d.notna(), None)
    out = []
    for r in d.to_dict('records'):
        out.append({k: (v.item() if isinstance(v, np.generic) else (str(v) if isinstance(v, (pd.Timestamp, datetime)) else v)) for k, v in r.items() if v not in (None, '')})
    return out


def rule_hashes():
    """Хеши справочников и правил: при сравнении видно, что изменились правила, а не сайт."""
    out = {}
    for p in sorted(glob.glob(os.path.join(DATA, '**', '*.json'), recursive=True)):
        rel = os.path.relpath(p, DATA)
        if rel.startswith('reference/learned'): continue   # обученное на сайтах — не правило
        out[rel] = hashlib.sha256(open(p, 'rb').read()).hexdigest()[:12]
    return out


def fingerprints(inv):
    """Отпечатки логов: имя, тип, строк, период; хеш набора — та же ли это выгрузка."""
    F = [{k: f.get(k) for k in ('файл', 'тип', 'формат', 'строк', 'с', 'по')} for f in inv.get('files') or []]
    h = hashlib.sha256(json.dumps(F, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {'набор': h, 'файлы': F}


def denominators(res):
    """Знаменатели: на что делились проценты в этой проверке."""
    S = res.get('summary') or {}
    MK = res.get('marketing') or {}
    Q = MK.get('качество')
    RI = MK.get('реклама_итог') or {}
    cl = res.get('cleaning') or {}
    return {'запросов': (res.get('inventory') or {}).get('requests'), 'визитов_людей': int(Q['людей'].sum()) if Q is not None and len(Q) else None,
            'просмотров_людей': cl.get('Просмотров у людей после очистки'), 'рекламных_кликов': RI.get('кликов'),
            'визитов_ботов': (S.get('Боты') or {}).get('Визитов ботов'), 'IP_ботов': (S.get('Боты') or {}).get('IP ботов')}


def cases(res):
    """Дела: всё без IP, кроме серьёзных (Тревога и Срочно) — по ним IP нужны, чтобы узнать фигуранта снова."""
    out = []
    for x in (res.get('profiles') or {}).get('дела') or []:
        c = {'дело': x['дело'], 'кличка': x['кличка'], 'важность': x['важность'], 'обвинения': [o.get('id') or o['статья'] for o in x['обвинения']],
             'IP': (x.get('состав') or {}).get('IP'), 'запросов': x.get('запросов')}
        if x['важность'] not in ('К сведению', 'Замечание'): c.update(сигнатура=x.get('сигнатура'), с=x.get('t0'), по=x.get('t1'))
        if x['важность'] in SERIOUS: c['ips'] = sorted(x.get('ips') or [])
        out.append(c)
    return out


def journals(res):
    """Журналы по дням всех файлов (без служебных колонок)."""
    J = {'01': (res.get('sheets') or {}).get('Общий анализ', {}).get('Журнал активности'), '02': (res.get('errors') or {}).get('журнал'),
         '03': (res.get('security') or {}).get('журнал'), '04': (res.get('bots_extra') or {}).get('журнал'),
         '05': (res.get('marketing') or {}).get('журнал'), '06': (res.get('seo') or {}).get('журнал')}
    return {k: _rec(v.drop(columns=[c for c in ('_с', '_по', '_полный') if c in v.columns])) for k, v in J.items() if v is not None and hasattr(v, 'columns') and len(v)}


def build(res, site, edits=None):
    from .report import snapshot as v1   # поля /1 — как были
    s = v1(res, site)
    s['format'] = FORMAT
    s['совместим_с'] = ['NXLD-snapshot/1']
    inv = res.get('inventory') or {}
    m = res.get('site_map') or {}
    X = res.get('security') or {}
    E = res.get('errors') or {}
    Pf = res.get('profiles') or {}
    MK = res.get('marketing') or {}
    D = res.get('seo') or {}
    SM = (res.get('sheets') or {}).get('Маркетинг', {})
    s['паспорт'] = {'логи': fingerprints(inv), 'правила': rule_hashes(), 'знаменатели': denominators(res)}
    s['findings'] = [{k: x.get(k) for k in ('key', 'блок', 'важность', 'заголовок', 'что_происходит', 'главная_цифра', 'статус', 'отметка', 'тема', 'лист', 'почему_тревога') if x.get(k) not in (None, '')}
                     for x in res['findings']]
    s['дела'] = cases(res)
    s['сигнатуры'] = _rec(Pf.get('сигнатуры'), ['id', 'дело', 'IP', 'запросов', 'ложных'])   # текст правила — в learned/signatures.json по id
    s['проблемные_адреса'] = _rec(E.get('нерабочие'), ['адрес', 'тип', 'статус', 'сейчас', 'критично', 'запросов', 'последний'], 300)
    s['сбои'] = _rec(E.get('сбои'), ['сбой', 'начало', 'конец', 'минут_всего', 'пик_минут', 'страниц_с_5xx', 'обрывов_499', 'вероятная_причина'])
    s['всплески'] = _rec(X.get('всплески'), ['всплеск', 'начало', 'конец', 'минут', 'запросов', 'пик_в_минуту', 'в_норме', 'IP', 'картина', 'кто_главный'])
    s['служебные_данные'] = {'утечки': _rec(X.get('утечки'), ['файл', 'открыт_сейчас', 'отдан_раз', 'IP', 'размер', 'первый', 'последний', 'последний_ответ', 'проверка', 'проверено']),
                             'разделы': _rec(X.get('разделы'), ['раздел', 'настоящий', 'запросов', 'ответов_200', 'IP_с_200', 'адресов_без_входа', 'без_входа_байт', 'форма_входа', 'первый', 'последний'])}
    s['точки_приёма'] = [{k: x.get(k) for k in ('Адрес точки', 'Метод', 'Опознано как', 'Запросов', 'Уникальных IP') if x.get(k) not in (None, '')}
                         for x in sorted(res.get('intake') or [], key=lambda x: -int(x.get('Запросов') or 0))[:200]]
    s['параметры'] = [{k: p.get(k) for k in ('ключ', 'группа', 'запросов', 'людей')} for p in sorted(res.get('params') or [], key=lambda p: -int(p.get('запросов') or 0))[:300]]
    s['показатели'] = {'сводки': {k: (_rec(v) if hasattr(v, 'columns') else v) for k, v in (res.get('сводки') or {}).items()}}
    s['страницы_людей'] = _rec((res.get('sheets') or {}).get('Общий анализ', {}).get('Страницы'), ['страница', 'просмотров', 'визитов', 'ошибки', 'заявок'], 500)
    s['журналы'] = journals(res)
    RB = MK.get('реклама_боты') or {}
    def ad(name, col):   # срез рекламы: люди (визитов, принято) и все клики (боты, впустую) — одной записью, 200 крупнейших
        P, B = SM.get(f'Реклама: {name}'), RB.get(name)
        if B is None: return _rec(P, [col, 'визитов', 'принято'], 200)
        M = B.merge(P[[col, 'визитов', 'принято']], on=col, how='left') if P is not None else B
        return _rec(M.sort_values('визитов_всех', ascending=False), [col, 'визитов_всех', 'визитов', 'ботов', 'впустую', 'принято'], 200)
    s['реклама'] = {'итог': MK.get('реклама_итог'), 'качество': _rec(MK.get('качество')), 'кампании': ad('Кампании', 'кампания'), 'площадки': ad('Площадки', 'source')}
    s['seo'] = {'обход': _rec(D.get('обход')), 'файлы': _rec(D.get('файлы')), 'подлинность': _rec(D.get('подлинность')), 'разделы': _rec(D.get('разделы'), None, 60),
                'без_обхода': len(D.get('без_обхода')) if D.get('без_обхода') is not None else None}
    s['свои'] = {'сотрудники': m.get('staff_ips') or [], 'сервер': m.get('server_ips') or [],
                 'мониторинги': [{k: x.get(k) for k in ('ip', 'адрес', 'интервал_с')} for x in m.get('monitors') or []]}
    s['правки'] = edits or {}
    return s


def check_keys(prev, res):
    """Стабильность ключей проблем: что пропало и что появилось относительно прошлого снимка (для «Было → стало» и проверки движка)."""
    a = {x['key'] for x in (prev or {}).get('findings', [])}
    b = {x['key'] for x in res['findings']}
    return {'пропали': sorted(a - b), 'появились': sorted(b - a), 'общих': len(a & b)}
