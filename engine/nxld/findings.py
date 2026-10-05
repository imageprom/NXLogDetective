"""NXLD: единая структура проблемы (находки)."""
SEV_ORDER = {'Срочно': 0, 'Важно': 1, 'К сведению': 2, 'Замечание': 3}   # замечание — не проблема: аналитик решает сам


class Findings:
    def __init__(self):
        self.items = []

    def add(self, block, severity, ftype, obj, title, facts, where='', action='', metric=None, sheet='', also=()):
        key = f'{block}:{ftype}:{obj}'
        if any(x['key'] == key for x in self.items):
            return
        self.items.append(dict(key=key, блок=block, важность=severity, что_происходит=title, факты=facts,
                               где_править=where, что_сделать=action, главная_цифра=metric, лист=sheet,
                               также_в=', '.join(also), статус=''))

    def block(self, name):
        return sorted([x for x in self.items if x['блок'] == name], key=lambda x: SEV_ORDER[x['важность']])


# ---- калибровка важности (ТЗ, раздел 12 «Текст для Redmine»: важность по вреду, однотипное — одной проблемой) ----
PEOPLE_METRIC = {'5xx', '404_entry'}          # у этих типов главная цифра — число задетых людей/визитов
GROUP_TITLES = {
    '5xx': 'Ошибки сервера на отдельных страницах', '404_entry': 'Люди приходят на несуществующие страницы',
    'missing_static': 'Отсутствующие файлы, которые запрашивают страницы', 'trap': 'Паразитные адреса: ловушки для роботов',
    'campaign_zero': 'Кампании с заметным трафиком и без заявок', 'unknown_robot': 'Неопознанные роботы и мониторинги',
    'placement_type_low': 'Типы рекламных площадок с конверсией в разы ниже поиска',
}
GEN = {'Реклама': 'рекламы', 'Карты': 'Карт', 'Поиск': 'поиска'}
LOWER = {'Срочно': 'Важно', 'Важно': 'К сведению', 'К сведению': 'К сведению', 'Замечание': 'Замечание'}


def load_rules(path=None):
    import json, os
    path = path or os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'severity_rules.json')
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return {}


def set_sev(x, sev, why):
    x['важность'] = sev; x['почему'] = why; x['калибровка'] = why


def calibrate(items, human_visits, period_end_ts, rules=None):
    """Важность — взвешивание факторов (ТЗ, «Важность проблем»): кого задело, намерение канала, видимость,
    длится ли сейчас, деньги. Пороги — data/severity_rules.json. Однотипное сводится в одну проблему."""
    import re
    import pandas as pd
    R_ = rules if rules is not None else load_rules()
    small = max(R_.get('мелкое_минимум', 20), R_.get('мелкое_доля_визитов', 0.001) * human_visits)
    hot = set(R_.get('горячие_каналы', ['Карты', 'Поиск', 'Реклама']))
    stale = R_.get('давнее_дней', 7) * 86400
    O = R_.get('сбои', {})
    invisible = re.compile(R_.get('невидимые_файлы', 'placeholder|lazy|blank|spacer'), re.I)
    outs = [x for x in items if x['key'].split(':')[1] in ('outage', 'degradation') and x.get('окно')]
    for x in items:
        t = x['key'].split(':')[1]
        obj = x['key'].split(':', 2)[2] if x['key'].count(':') >= 2 else ''
        if t == '404_entry' and obj in hot:
            why = f"вход из {GEN.get(obj, obj)} — горячий канал: человек ищет конкретную страницу"
            if x['важность'] == 'К сведению': set_sev(x, 'Важно', why)
            elif not x.get('почему'): x['почему'] = why
        elif t in PEOPLE_METRIC and isinstance(x.get('главная_цифра'), (int, float)) and x['главная_цифра'] < small and x['важность'] not in ('К сведению', 'Замечание'):
            set_sev(x, 'К сведению', f'задело меньше {small:.0f} визитов людей')
        if t == 'missing_static' and x.get('файлы') and all(invisible.search(f) for f in x['файлы']):
            set_sev(x, 'К сведению', 'файл-заглушка: человек его, скорее всего, не видит')
        if t in ('outage', 'degradation') and x.get('окно'):
            w = x['окно']
            same_hour = sum(1 for y in outs if y['окно']['час'] == w['час'])
            if period_end_ts - w['по'] <= O.get('продолжается_если_конец_ближе_мин', 30) * 60:
                set_sev(x, 'Срочно', 'сбой продолжается на конец лога — сайт, возможно, лежит прямо сейчас')
            elif len(outs) >= O.get('повторяется_от_раз', 3):
                set_sev(x, 'Важно', f'сбои повторяются: {len(outs)} за период')
            elif same_hour >= O.get('по_расписанию_час_совпадает_дней', 2):
                set_sev(x, 'Важно', 'сбои в одно и то же время — похоже на расписание (бэкап, крон)')
            elif w['минут'] >= O.get('долгий_от_мин', 60):
                set_sev(x, 'Важно', f"долгий сбой: {w['минут']} мин")
            elif w['реклама'] or w['заявки']:
                set_sev(x, 'Важно', 'сбой пришёлся на рекламные визиты' + (' и заявки' if w['заявки'] else ''))
            else:
                set_sev(x, 'К сведению', 'короткий единичный сбой, после него сайт работает')
            if x['важность'] != 'Срочно' and period_end_ts - w['по'] > stale and x['важность'] == 'Важно' and len(outs) < O.get('повторяется_от_раз', 3):
                set_sev(x, 'К сведению', x['почему'] + '; давно и не повторялся')
    out, groups = [], {}
    for x in items:
        b, t = x['блок'], x['key'].split(':')[1]
        if t in GROUP_TITLES and x['важность'] != 'Срочно':
            groups.setdefault((b, t, x['важность']), []).append(x)
        else:
            out.append(x)
    top = {}
    for (b, t, sev) in groups:
        if len(groups[(b, t, sev)]) > 1: top.setdefault((b, t), []).append(sev)
    for (b, t, sev), xs in groups.items():
        if len(xs) == 1:
            out.append(xs[0]); continue
        suffix = 'группа' if SEV_ORDER[sev] == min(SEV_ORDER[s_] for s_ in top[(b, t)]) else 'мелочи'
        xs = sorted(xs, key=lambda x: (SEV_ORDER[x['важность']], -(x.get('главная_цифра') or 0)))
        nums = [x.get('главная_цифра') for x in xs if isinstance(x.get('главная_цифра'), (int, float))]
        out.append(dict(key=f'{b}:{t}:{suffix}', блок=b, важность=sev, что_происходит=f'{GROUP_TITLES[t]}: {len(xs)}',
                        факты='; '.join(f"{x['что_происходит']} — {x['факты']}" for x in xs), где_править=xs[0]['где_править'],
                        что_сделать=xs[0]['что_сделать'], главная_цифра=sum(nums) if nums else None, лист=xs[0]['лист'],
                        также_в=xs[0].get('также_в', ''), статус='', состав=[x['key'] for x in xs], калибровка=f'сведено {len(xs)} однотипных',
                        почему=group_why(xs), файлы=sum((x.get('файлы', []) for x in xs), [])))
    return sorted(out, key=lambda x: SEV_ORDER[x['важность']])


def group_why(xs):
    import re
    ch = [m.group(1) for x in xs for m in [re.match(r'вход из (\S+) — горячий канал', str(x.get('почему', '')))] if m]
    if len(ch) > 1:
        return f"входы из {' и '.join(dict.fromkeys(ch))} — горячие каналы: человек ищет конкретную страницу"
    return xs[0].get('почему', '')
