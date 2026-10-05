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
    """Системы мониторинга: названные (семейство робота с категорией «Мониторинг») и опознанные по ритму (один адрес через равные промежутки)."""
    R = c.R
    rows = []
    fc = R['fam_cat'].astype(str).values
    m = fc == 'Мониторинг'
    if m.any():
        X = R.loc[m, ['fam', 'ip', 'ts', 'base', 'status', 'bytes']]
        for f, g in X.groupby('fam', observed=True):
            per_ip = [_interval(gi['ts'].values) for _, gi in g.groupby('ip', observed=True)]
            per_ip = [x for x in per_ip if x]
            rows.append(dict(система=str(f).replace(' (мониторинг)', ''), как='по имени', проверяет=', '.join(g['base'].astype(str).value_counts().head(2).index), IP=int(g['ip'].nunique()),
                             интервал=int(np.median(per_ip)) if per_ip else None, запросов=len(g), коды=topn(g['status'], 4), байт=int(g['bytes'].sum())))
    for x in c.m.get('monitors') or []:
        g = R[(R['ip'].astype(str) == str(x.get('ip'))) & (R['ua'].astype(str) == str(x.get('ua')))]
        if not len(g): continue
        rows.append(dict(система=f"Без имени ({x.get('ip')})", как='по ритму', проверяет=str(x.get('адрес')), IP=1, интервал=x.get('интервал_с'),
                         запросов=len(g), коды=topn(g['status'], 4), байт=int(g['bytes'].sum())))
    d = pd.DataFrame(rows)
    return d.sort_values('запросов', ascending=False).head(top) if len(d) else d


def robots(c, top=10):
    """Роботы по семействам (кроме систем мониторинга), по запросам."""
    R = c.R
    m = np.asarray(c.declared) & (R['fam_cat'].astype(str).values != 'Мониторинг')
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
                роботы=robots(c), сигнатуры=signatures(c))
