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
