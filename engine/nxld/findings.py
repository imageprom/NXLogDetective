"""NXLD: единая структура проблемы (находки)."""
SEV_ORDER = {'Срочно': 0, 'Важно': 1, 'К сведению': 2}


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
    'missing_static': 'Отсутствующие файлы, которые запрашивают страницы', 'trap': 'Ловушки для роботов в фильтрах и параметрах',
    'campaign_zero': 'Кампании с заметным трафиком и без заявок', 'unknown_robot': 'Неопознанные роботы и мониторинги',
    'placement_type_low': 'Типы рекламных площадок с конверсией в разы ниже поиска',
}
LOWER = {'Срочно': 'Важно', 'Важно': 'К сведению', 'К сведению': 'К сведению'}


def calibrate(items, human_visits, period_end_ts, small_share=0.001, stale_days=7):
    """1) мелкое (< 0,1% визитов людей) — «К сведению»; 2) закончившиеся сбои старше недели — на ступень ниже;
    3) однотипные проблемы одного блока (кроме «Срочно») сводятся в одну со списком внутри."""
    import pandas as pd
    small = max(20, small_share * human_visits)
    for x in items:
        t = x['key'].split(':')[1]
        if t in PEOPLE_METRIC and isinstance(x.get('главная_цифра'), (int, float)) and x['главная_цифра'] < small and x['важность'] != 'К сведению':
            x['важность'] = 'К сведению'; x['калибровка'] = f'мелкое: меньше {small:.0f} задетых'
        if t in ('outage', 'degradation'):
            try:
                end = pd.Timestamp(x['key'].split(':', 2)[2]).timestamp()
                if period_end_ts - end > stale_days * 86400:
                    x['важность'] = LOWER[x['важность']]; x['калибровка'] = f'закончилось больше {stale_days} дней назад и не повторялось'
            except Exception:
                pass
    out, groups = [], {}
    for x in items:
        b, t = x['блок'], x['key'].split(':')[1]
        if t in GROUP_TITLES and x['важность'] != 'Срочно':
            groups.setdefault((b, t), []).append(x)
        else:
            out.append(x)
    for (b, t), xs in groups.items():
        if len(xs) == 1:
            out.append(xs[0]); continue
        xs = sorted(xs, key=lambda x: (SEV_ORDER[x['важность']], -(x.get('главная_цифра') or 0)))
        nums = [x.get('главная_цифра') for x in xs if isinstance(x.get('главная_цифра'), (int, float))]
        out.append(dict(key=f'{b}:{t}:группа', блок=b, важность=xs[0]['важность'], что_происходит=f'{GROUP_TITLES[t]}: {len(xs)}',
                        факты='; '.join(f"{x['что_происходит']} — {x['факты']}" for x in xs), где_править=xs[0]['где_править'],
                        что_сделать=xs[0]['что_сделать'], главная_цифра=sum(nums) if nums else None, лист=xs[0]['лист'],
                        также_в=xs[0].get('также_в', ''), статус='', состав=[x['key'] for x in xs], калибровка=f'сведено {len(xs)} однотипных'))
    return sorted(out, key=lambda x: SEV_ORDER[x['важность']])
