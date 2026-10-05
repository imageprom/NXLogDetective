"""NXLD: реестр обращающихся — второй срез той же классификации, что и реестр адресов (classify.py).

Цепочка: адрес → запрос → обращающийся → сигнатура. Здесь собирается то, что уже найдено при анализе
(группы визитов, семейства роботов, сигнатуры сканеров и спама, свои), в компактные таблицы.
Построчно — только значащие обращающиеся: сотрудники (один IP — одна строка), системы мониторинга, роботы по семействам,
боты по сигнатурам. Люди — итогами по группам и каналам, без списка IP.
Сводка «Активность» и полные листы берут эти таблицы, а не считают заново."""
import numpy as np
import pandas as pd

from .blocks import topn, TOP_CHANNELS

MB = 1024 ** 2

# как подгруппа визита называется в отчёте; сигнатура — подробность после «: »
SUB_LABEL = {'': '', 'сотрудники': 'Сотрудники', 'мониторинги': 'Системы мониторинга', 'известные': 'Известные', 'неизвестные': 'Неизвестные',
             'подделки роботов': 'Подделки роботов', 'явные (не браузер)': 'Явные (не браузер)',
             'маскирующиеся: без загрузки ресурсов': 'Маскирующиеся под браузер'}
SIG_KIND = [('сканер под браузер', 'Зонды и перебор'), ('человек-исследователь', 'Зонды и перебор'), ('спам форм', 'Спам форм'),
            ('маскирующиеся', 'Маскировка'), ('подделки роботов', 'Подделка робота'), ('явные', 'Явный бот')]
CHANNEL_LABEL = dict(TOP_CHANNELS)


def sub_label(s):
    s = str(s)
    if s in SUB_LABEL: return SUB_LABEL[s]
    if s == 'неопознанный мониторинг': return 'Неопознанный мониторинг'
    if s and ':' not in s and s[:1].islower() and s not in ('известные', 'неизвестные'): return s   # имя утилиты (curl, wget) — как есть
    head = s.split(': ', 1)[0]
    return {'сканер под браузер': 'Сканеры под браузер', 'спам форм': 'Спам форм', 'человек-исследователь, разово': 'Люди-исследователи',
            'человек-исследователь, регулярно': 'Люди-исследователи'}.get(head, head[:1].upper() + head[1:])


def sig_kind(s):
    s = str(s)
    for k, v in SIG_KIND:
        if s.startswith(k): return v
    return 'Прочее'


def sig_label(s):
    """«сканер под браузер: однозначный зонд» → «Однозначный зонд»; «маскирующиеся: без загрузки ресурсов» → «Без загрузки ресурсов»."""
    s = str(s)
    tail = s.split(': ', 1)[1] if ': ' in s else s
    return tail[:1].upper() + tail[1:]


def channels(c):
    """Каналы визитов людей — один расчёт для сводки, листа «Каналы» и брифа. Заявки — отправки форм."""
    H = c.H
    g = H.groupby('channel').agg(визитов=('n_req', 'size'), IP=('ip', 'nunique'), заявок=('n_goal', 'sum')).sort_values('визитов', ascending=False)
    g = g[g['визитов'] > 0]
    g['доля'] = g['визитов'] / max(1, g['визитов'].sum())
    g['конверсия'] = g['заявок'] / g['визитов'].clip(lower=1)
    g = g.reset_index().rename(columns={'channel': 'канал'})
    g['канал'] = g['канал'].map(lambda x: CHANNEL_LABEL.get(x, x))
    return g


def groups(c):
    """Посетители по группам и подгруппам (сигнатуры свёрнуты в подгруппу), по визитам."""
    V = c.V
    d = V.assign(под=V['subgroup'].map(sub_label))
    g = d.groupby(['group', 'под']).agg(визитов=('n_req', 'size'), IP=('ip', 'nunique'), запросов=('n_req', 'sum'), байт=('bytes', 'sum')).reset_index()
    g = g.rename(columns={'group': 'группа', 'под': 'подгруппа'}).sort_values('визитов', ascending=False)
    return g


def staff(c):
    """Сотрудники: один IP — одна строка. Опознаны по успешной работе в админке движка."""
    R, V = c.R, c.V
    ips = [str(x) for x in (c.m.get('staff_ips') or [])]
    if not ips: return pd.DataFrame()
    sv = V[(V['group'] == 'Свои') & (V['subgroup'] == 'сотрудники') & V['ip'].astype(str).isin(ips)]
    ipr = R['ip'].astype(str)
    rm = ipr.isin(ips).values
    adm = pd.Series(R['is_admin'].values[rm], index=ipr.values[rm]).groupby(level=0).sum() if 'is_admin' in R else pd.Series(dtype=int)
    T = c.T.set_index('ip')
    rows = []
    for ip in ips:
        v = sv[sv['ip'].astype(str) == ip]
        if not len(v): continue
        rows.append(dict(IP=ip, сеть=str(T['org'].get(ip, '') or '').replace('"', ''), визитов=len(v), запросов=int(v['n_req'].sum()), дней=int(v['day'].nunique()),
                         первый=v['day'].min(), последний=v['day'].max(), в_админке=int(adm.get(ip, 0)), заявок=int(v['n_goal'].sum())))
    return pd.DataFrame(rows).sort_values('запросов', ascending=False) if rows else pd.DataFrame()


def _interval(ts):
    """Типичный интервал между запросами, секунды (медиана), — ритм системы мониторинга."""
    t = np.sort(np.asarray(ts))
    return int(np.median(np.diff(t))) if len(t) > 2 else None


def monitoring(c, top=10):
    """Системы мониторинга — группа реестра обращающихся: название сервиса (справочник или User-Agent) или «неопознанный мониторинг» (по ритму).
    Что проверяет, с какого интервала, ошибки, трафик; у неопознанного — с IP сотрудника ли он ходит."""
    R, V = c.R, c.V
    m = np.asarray(c.rg) == 'Системы мониторинга'
    if not m.any(): return pd.DataFrame()
    sub = V['subgroup'].reindex(R['vid'].values[m]).astype(str).values
    X = pd.DataFrame({'s': sub, 'ip': R['ip'].astype(str).values[m], 'ts': R['ts'].values[m], 'base': R['base'].astype(str).values[m],
                      'st': R['status'].values[m], 'b': R['bytes'].values[m]})
    staff = set(str(x) for x in (c.m.get('staff_ips') or []))
    rows = []
    for nm, g in X.groupby('s'):
        unk = nm == 'неопознанный мониторинг'
        for key, gg in (g.groupby('ip') if unk else [(None, g)]):   # неопознанные — по одному IP: это разные системы
            per_ip = [_interval(gi['ts'].values) for _, gi in gg.groupby('ip')]
            per_ip = [x for x in per_ip if x]
            rows.append(dict(система=(f"Неопознанный ({key})" + (' — IP сотрудника' if key in staff else '')) if unk else nm, как='по ритму' if unk else 'по имени и поведению',
                             проверяет=', '.join(gg['base'].value_counts().head(2).index), IP=int(gg['ip'].nunique()),
                             интервал=int(np.median(per_ip)) if per_ip else None, запросов=len(gg), коды=topn(gg['st'], 4), байт=int(gg['b'].sum())))
    d = pd.DataFrame(rows)
    return d.sort_values('запросов', ascending=False).head(top) if len(d) else d


def product_name(ua):
    """Название программы из User-Agent без номеров и ссылок: «Uptime monitoring by Overseer (…rid: …)» → «Overseer»,
    «Mozilla/5.0 (DomainCheckService)» → «DomainCheckService», «curl/8.4.0» → «curl»."""
    import re
    u = str(ua)
    m = re.match(r'^Mozilla/[\d.]+ \(([A-Za-z][\w.-]+)\)\s*$', u)
    if m: return m.group(1)
    m = re.search(r'\b(?:by|from)\s+([A-Z][\w.-]+)', u)
    if m: return m.group(1)
    u = re.sub(r'\(.*?\)|https?://\S+|\brid:\s*\S+|[0-9a-f]{8}-[0-9a-f-]{20,}', ' ', u)
    m = re.search(r'([A-Za-z][\w.-]*[A-Za-z])(?=/|\s|$)', u)
    return m.group(1) if m else 'без названия'


UTIL_NAME = {'Headless-браузер': 'Headless-браузер', 'Скрипты: прочие': 'Прочие программы'}


def utilities(c):
    """Утилиты: curl, wget, Python, PHP, Go, headless-браузеры, запросы без User-Agent. Что запрашивали и на что похоже —
    по уликам: зонды → сканер; IP сотрудника → свой; один адрес по расписанию → интеграция; немного запросов к живым страницам → разработчик или проверка."""
    R, V = c.R, c.V
    m = (np.asarray(c.rg) == 'Утилиты')
    if not m.any(): return pd.DataFrame()
    A = c.addr
    cc = R['base'].cat.codes.values
    fam_ = R['fam'].astype(str).values[m]; ua_ = R['ua'].astype(str).values[m]
    X = pd.DataFrame({'u': [product_name(u) if f == 'Скрипты: прочие' else f for f, u in zip(fam_, ua_)], 'ip': R['ip'].astype(str).values[m], 'asn': R['asn'].values[m], 'day': R['day'].astype(str).values[m],
                      'b': cc[m], 'st': R['status'].values[m]})
    X['зонд'] = A['зонд'].values[X['b']] != ''
    X['живой'] = A['существование'].values[X['b']] == 'живой'
    X['адрес'] = A['адрес'].values[X['b']]
    staff = set(str(x) for x in (c.m.get('staff_ips') or []))
    rows = []
    def verdict(g):   # вывод — по каждому IP отдельно: под одной утилитой бывают и сканеры, и интеграции
        n = len(g); probes = int(g['зонд'].sum()); top = g['адрес'].value_counts()
        if g['ip'].iloc[0] in staff: return 'свой'
        if probes >= 3 or probes / n >= 0.2: return 'сканер'
        if top.iloc[0] / n >= 0.8 and g['day'].nunique() >= 3: return 'интеграция'
        if n <= 300 and g['живой'].mean() >= 0.8: return 'разработчик или проверка'
        return 'не ясно'
    for u, g in X.groupby('u'):
        n = len(g)
        top = g['адрес'].value_counts()
        per_ip = pd.Series({ip: verdict(gi) for ip, gi in g.groupby('ip')}).value_counts()
        like = ', '.join(f"{k} — {v} IP" for k, v in per_ip.items())
        rows.append(dict(утилита=UTIL_NAME.get(u, u), запросов=n, IP=g['ip'].nunique(), сетей=g['asn'].nunique(), дней=g['day'].nunique(),
                         что=', '.join(f"{a or '(пусто)'} ({k})" for a, k in top.head(3).items()), зондов=int(g['зонд'].sum()), коды=topn(pd.Series(g['st']), 4), похоже=like))
    return pd.DataFrame(rows).sort_values('запросов', ascending=False)


def robots(c, top=10):
    """Роботы по семействам (кроме систем мониторинга), по запросам."""
    R = c.R
    m = np.asarray(c.rg) == 'Роботы'   # без систем мониторинга и утилит — у них свои группы
    X = R.loc[m, ['fam', 'fam_cat', 'ip', 'day', 'bytes', 'status', 'fam_verified']]
    if not len(X): return pd.DataFrame()
    g = X.groupby('fam', observed=True)
    ver = g['fam_verified'].agg(lambda s: (s.astype(str) == 'да').mean() if (s.astype(str) != '').any() else None)
    d = pd.DataFrame({'категория': g['fam_cat'].first().astype(str), 'подлинных': ver, 'запросов': g.size(), 'IP': g['ip'].nunique(),
                      'дней': g['day'].nunique(), 'байт': g['bytes'].sum(), 'коды': g['status'].agg(lambda s: topn(s, 5))})
    return d.sort_values('запросов', ascending=False).head(top).reset_index().rename(columns={'fam': 'робот'})


def signatures(c, top=None):
    """Боты по сигнатурам: какой признак их выдал. Строка — сигнатура (подгруппа визита), не IP."""
    V = c.V
    B = V[V['group'] == 'Боты']
    if not len(B): return pd.DataFrame()
    g = B.groupby('subgroup').agg(визитов=('n_req', 'size'), IP=('ip', 'nunique'), сетей=('asn', 'nunique'), дней=('day', 'nunique'),
                                  заявок=('n_goal', 'sum'), сеть=('nettype', lambda s: topn(s.astype(str), 1).split(': ')[0]),
                                  вход=('entry', lambda s: topn(s.astype(str), 1).split(': ')[0])).reset_index()
    g['вид'] = g['subgroup'].map(sig_kind)
    g['сигнатура'] = g['subgroup'].map(sig_label)
    g = g.sort_values('визитов', ascending=False)
    return g.head(top) if top else g


def build(c):
    """Реестр обращающихся — в результаты анализа (res['actors'])."""
    return dict(каналы=channels(c), группы=groups(c), сотрудники=staff(c), мониторинг=monitoring(c),
                роботы=robots(c), утилиты=utilities(c), сигнатуры=signatures(c))
