"""NXLD: производные признаки и сводки для всех файлов отчёта — то, что раньше решалось при оформлении.

Оформление (report_*.py) только рисует: что актуально, что критично, сводки для Обзоров и тексты-выводы
приходят отсюда готовыми. Те же сводки берут выжимка для Redmine (brief) и снимок."""
import pandas as pd

WEEKDAY = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')


def _day(d):
    t = pd.Timestamp(d)
    return f"{WEEKDAY[t.weekday()]} {t.strftime('%d.%m')}"


def pct(x, d=1):
    return f'{x:.{d}f}'.replace('.', ',')


def overlap_text(H):
    """Вывод о пересечении нагрузок: часы, где много и людей, и роботов с ботами, и что при этом с обрывами 499."""
    if not H or H.get('_пересечение') is None or not len(H['_пересечение']): return ''
    X = H['_пересечение']
    top = ', '.join(f"{_day(r['d'])} {int(r['h']):02d}:00" for _, r in X.head(3).iterrows())
    b, o = H.get('_499_обычно') or 0, H.get('_499_в_пересечении')
    tail = ''
    if o is not None and b:
        k = o / b
        tail = (f' В эти часы люди уходили, не дождавшись ответа (499), в {pct(k)} раза чаще обычного — сервер не справляется с общей нагрузкой.' if k >= 1.3
                else ' Обрывов 499 у людей в эти часы не больше обычного — сервер справляется.')
    return f'часы, где много и людей, и роботов с ботами, — {top}.{tail}'


def slowness_text(T):
    """Вывод для «Признаков торможения»: худшие часы по обрывам и совет про время ответа в логе."""
    if not T: return []
    worst = ', '.join(f"{_day(d)} {h:02d}:00 — {pct(v)}%" for d, h, v in T.get('_худшие', []))
    out = [f"Куда смотреть: часы, где темнеют сразу несколько карт, — сервер не успевает. Больше всего обрывов у людей: {worst} (обычно {pct(T.get('_обычно', 0))}%)." if worst
           else 'Куда смотреть: часы, где темнеют сразу несколько карт, — сервер не успевает.']
    if 'время' not in T:
        out.append('В логе нет времени ответа сервера. Чтобы видеть скорость напрямую, попросите хостинг добавить $request_time в формат access-лога nginx (или %D в Apache).')
    return out


def build(res):
    """Признаки и сводки — в res (на месте), чтобы оформление брало готовое."""
    E = res.get('errors') or {}
    recent = E.get('с_дня', '') or ''
    S2 = (res.get('sheets') or {}).get('Ошибки', {})
    # 02: битые адреса из скриптов и рекламные ошибки — актуально ли (запрос был в последние дни), впустую ли клик (не 499)
    B = S2.get('Битые адреса из скриптов')
    if B is not None and len(B) and 'Последний' in B:
        B['актуально'] = [str(v) >= recent for v in B['Последний']]
    A = S2.get('Реклама: посадочные с ошибками')
    if A is not None and len(A):
        A['актуально'] = [str(v) >= recent for v in A['последний']]
        A['впустую'] = [int(c_) != 499 and a_ for c_, a_ in zip(A['entry_status'], A['актуально'])]   # 499 — человек не дождался: это скорость, не битая посадочная
    # 02: ошибки файлов — критично, если файл просят страницы сайта и ошибка встречается сейчас
    for f in res.get('files_errors') or []:
        f['актуально'] = str(f.get('последний_день') or '') >= recent
        f['критично'] = bool(f['актуально'] and int(f.get('со_страниц') or 0) > 0)
    sv = {}
    Fe = res.get('files_errors') or []
    if Fe:
        sv['ошибки_файлов_по_группам'] = pd.DataFrame(Fe).groupby('группа').agg(файлов=('файлов', 'sum'), запросов=('запросов', 'sum'),
                                                                                 примеры=('адрес', lambda s: list(s)[:2])).sort_values('запросов', ascending=False)
    SE = S2.get('Ошибки у поисковиков')
    if SE is not None and len(SE):
        sv['поиск_по_роботам'] = SE.groupby('робот').agg(типов=('шаблон', 'nunique'), запросов=('запросов', 'sum'), ошибок=('ошибок', 'sum')).sort_values('ошибок', ascending=False).reset_index()
    X = res.get('security') or {}
    Ad = X.get('админка')
    if Ad is not None and len(Ad):
        sv['админка_по_кто'] = Ad.groupby('кто').agg(IP=('ip', 'size'), запросов=('запросов', 'sum'), успешных=('успешных_200', 'sum')).sort_values('запросов', ascending=False).reset_index()
    H = X.get('часы')
    if H: H['вывод'] = overlap_text(H)
    T = E.get('торможение')
    if T: T['вывод'] = slowness_text(T)
    SB = (res.get('sheets') or {}).get('Боты', {})
    FK = SB.get('Подделки')
    if FK is not None and len(FK):
        sv['подделки_по_имени'] = FK.groupby('представлялся').agg(IP=('ip', 'nunique'), запросов=('запросов', 'sum')).sort_values('запросов', ascending=False).reset_index()
    AD = (res.get('bots_extra') or {}).get('реклама')
    if AD is not None and len(AD):
        sv['реклама_по_системам'] = AD.groupby('channel_sub').agg(визитов=('визитов', 'sum'), IP=('IP', 'sum')).sort_values('визитов', ascending=False).reset_index()
    SP = SB.get('Спам форм: визиты')
    sv['принято_от_ботов'] = int(SP['n_conv'].sum()) if SP is not None and len(SP) else 0
    MI = (res.get('profiles') or {}).get('меры_ip')
    if MI is not None and len(MI): sv['приговоры'] = MI['приговор'].value_counts().to_dict()
    res['сводки'] = sv
    return res
