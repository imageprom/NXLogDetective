"""NXLD: расчёт блоков. Каждый блок возвращает (листы: {имя: DataFrame}, сводка: {метрика: значение}) и пишет черновые проблемы."""
import re
from collections import Counter, defaultdict
import numpy as np, pandas as pd
from . import recon
from .recon import mask_pd
from . import operators

KB, MB, GB = 1024, 1024 ** 2, 1024 ** 3
VULN = r'(^/\.env|/\.git/|/\.aws|/\.ssh|/\.svn|/\.DS_Store|phpinfo|/wp-login\.php|/wp-admin|/xmlrpc\.php|/wp-content/plugins|/phpmyadmin|/pma/|/adminer|/vendor/phpunit|/actuator|/cgi-bin/|/server-status|/config\.(json|yml|yaml|php)|/backup|\.(sql|bak|old|swp|tar|tar\.gz|tgz|zip|rar)$|/shell|/eval-stdin|/boaform|/HNAP1|/owa/|/autodiscover|/\.well-known/(?!acme)|/restore\.php|/bitrixsetup\.php|/install\.php|/setup\.php|/telescope|/_profiler|/debug|/console)'
from .visits import probe_rx as _probe_rx
VULN = '(?:' + VULN + ')|' + _probe_rx(('однозначный', 'неоднозначный'))   # плюс справочник зондов (data/reference/probes.json)


def dt(x):
    return pd.to_datetime(x, unit='s')


def topn(s, n=3):
    vc = s.astype(str).value_counts() if str(s.dtype) == 'category' else s.value_counts()
    return ', '.join(f'{k}: {v}' for k, v in vc[vc > 0].head(n).items())


class Ctx:
    """Общие данные для блоков."""

    def __init__(self, R, V, E, T, site_map, inv, G=None):
        R['day'] = R['day'].cat.reorder_categories(sorted(R['day'].cat.categories)).cat.as_ordered()
        self.R, self.V, self.E, self.T, self.m, self.inv, self.G = R, V, E, T, site_map, inv, G
        gc = pd.Categorical(V['group'].values)
        sc = pd.Categorical(V['subgroup'].values)
        vid = R['vid'].values
        self.rg = pd.Categorical.from_codes(gc.codes[vid], categories=gc.categories)
        self.rsub = pd.Categorical.from_codes(sc.codes[vid], categories=sc.categories)
        self.human = np.asarray(self.rg == 'Люди')
        self.H = V[V['group'] == 'Люди']
        self.search_ok = R['fam'].isin(['YandexBot', 'Googlebot', 'YandexRenderResourcesBot', 'Googlebot-Image', 'Bingbot']).values & (R['fam_verified'] == 'да').values
        self.declared = (R['fam'] != '').values
        self.days = sorted(map(str, R['day'].cat.categories))
        self.ndays = max(1, (R.ts.max() - R.ts.min()) / 86400)


# ======================= ОБЩИЙ АНАЛИЗ =======================
TOP_CHANNELS = [('Реклама', 'Реклама'), ('Поиск', 'Поиск'), ('Прямые заходы', 'Прямые заходы'), ('Карты', 'Карты'),
                ('Ссылки с сайтов', 'Ссылки с сайтов'), ('Внутренний переход', 'Внутренние переходы')]


def top_pages(c, n=500, by_section=False, by_template=False):
    """500 страниц по визитам людей: просмотры, визиты, IP, отправленные с них заявки, ошибки, каналы визитов."""
    R, V = c.R, c.V
    m = c.human & R['is_page'].values
    P = pd.DataFrame({'base': R['base'].values[m].astype(str), 'vid': R['vid'].values[m], 'ip': R['ip'].values[m].astype(str),
                      'st': R['status'].values[m], 'ts': R['ts'].values[m], 'tpl': R['tpl'].values[m].astype(str)})
    if not len(P): return pd.DataFrame()
    A = getattr(c, 'addr', None)
    if A is not None:   # срез реестра: страницы (is_page уже по форме), без зондов — они на листах безопасности
        code = R['base'].cat.codes.values[m]
        P = P[(A['зонд'].values[code] == '')]
    if by_section:   # «Разделы»: первый уровень адреса; несуществующие остаются, но помечаются
        P['addr'] = P['base']
        P['base'] = P['base'].str.extract(r'^(/[^/]*/?)')[0]
    alive = set(P.loc[(P['st'] >= 200) & (P['st'] < 300), 'base'])
    if not by_section: P = P[P['base'].isin(alive)]   # только существующие страницы
    if by_template:   # «Типы страниц»: шаблон адреса, под которым больше одной страницы
        P['addr'] = P['base']
        P['base'] = P['tpl']
        k_ = P.groupby('base')['addr'].nunique()
        P = P[P['base'].isin(k_[k_ >= 2].index)]
        if not len(P): return pd.DataFrame()
    ch = V['channel'].astype(str)
    P['ch'] = P['vid'].map(ch)
    g = P.groupby('base')
    D = pd.DataFrame({'просмотров': g.size(), 'визитов': g['vid'].nunique(), 'ip': g['ip'].nunique()})
    if by_section or by_template:
        D['страниц'] = g['addr'].nunique(); D['существует'] = D.index.isin(alive) if by_section else True
        if by_section:   # статус раздела: существует / переадресация / сломан / не существует
            r3_ = set(P.loc[(P['st'] >= 300) & (P['st'] < 400), 'base']); r5_ = set(P.loc[P['st'] >= 500, 'base'])
            D['статус'] = ['существует' if b_ in alive else 'переадресация' if b_ in r3_ else 'сломан' if b_ in r5_ else 'не существует' for b_ in D.index]
        D['ответы'] = g['st'].agg(lambda s: ', '.join(f'{k}:{v}' for k, v in s.value_counts().sort_index().items()))
    D = D.sort_values('визитов', ascending=False).head(n)
    T = P[P['base'].isin(D.index)]
    if by_template:
        D['ответы'] = T.groupby('base')['st'].agg(lambda s: ', '.join(f'{k}:{v}' for k, v in s.value_counts().sort_index().items()))
        D['пример'] = T.groupby(['base', 'addr'])['vid'].nunique().reset_index().sort_values('vid', ascending=False).drop_duplicates('base').set_index('base')['addr']
    D['ошибки'] = T[(T['st'] >= 400) & (T['st'] != 499)].groupby('base')['st'].agg(lambda s: ', '.join(f'{k}:{v}' for k, v in s.value_counts().sort_index().items()))
    # заявки, отправленные со страницы: отправки форм людьми, у которых страница — источник
    goal = R['goal'].astype(str).values if 'goal' in R else np.array([''] * len(R))
    gm = c.human & ~np.isin(goal, ['', 'nan']) & (R['method'].values == 'POST')
    rp = pd.Series(R['ref_path'].values[gm].astype(str))
    if by_section: rp = rp.str.extract(r'^(/[^/]*/?)')[0]
    D['заявок'] = rp.value_counts()
    U = T.drop_duplicates(['base', 'vid'])
    known = [k for k, _ in TOP_CHANNELS]
    for k, lab in TOP_CHANNELS: D[lab] = U[U['ch'] == k].groupby('base').size()
    D['Прочие'] = U[~U['ch'].isin(known)].groupby('base').size()
    D = D.fillna({'заявок': 0, 'ошибки': '', **{lab: 0 for _, lab in TOP_CHANNELS}, 'Прочие': 0})
    return D.reset_index().rename(columns={'base': 'страница'})



ACT_GROUPS = ('Люди', 'Роботы', 'Системы мониторинга', 'Утилиты', 'Боты', 'Свои')
SHORT = {'Системы мониторинга': 'Мониторинг'}   # подпись колонки во второй строке шапки


def day_span(R):
    """Какая часть суток каждого дня попала в лог: _с, _по (ЧЧ:ММ) и _полный — для журналов по дням."""
    t = pd.to_datetime(R['ts'], unit='s')
    span = t.groupby(t.dt.strftime('%Y-%m-%d')).agg(['min', 'max'])
    out = pd.DataFrame({'_с': span['min'].dt.strftime('%H:%M'), '_по': span['max'].dt.strftime('%H:%M')})
    out['_полный'] = (out['_с'] <= '00:05') & (out['_по'] >= '23:55')
    return out


def activity(c):
    """Активность по дням: визиты и уникальные IP по группам, отправленные заявки (роботы форм не шлют), какая часть суток в логе.
    Последняя строка — «Итого»: IP за весь период уникальные, а не сумма по дням."""
    R, V = c.R, c.V
    days = sorted(V['day'].unique())
    D = pd.DataFrame({'день': days}).set_index('день')
    for g in ACT_GROUPS:
        vg = V[V['group'] == g]
        D[f'Визиты|{SHORT.get(g, g)}'] = vg.groupby('day').size()
    for g in ACT_GROUPS:
        vg = V[V['group'] == g]
        D[f'IP|{SHORT.get(g, g)}'] = vg.groupby('day')['ip'].nunique()
    for g in ('Люди', 'Боты', 'Свои'):
        vg = V[V['group'] == g]
        D[f'Заявки|{g}'] = vg.groupby('day')['n_goal'].sum()
    D = D.fillna(0).astype(int)
    D = D.join(day_span(R)).reset_index()
    tot = {'день': 'Итого', '_полный': True, '_с': '', '_по': ''}
    for g in ACT_GROUPS:
        tot[f'Визиты|{SHORT.get(g, g)}'] = int(D[f'Визиты|{SHORT.get(g, g)}'].sum())
        tot[f'IP|{SHORT.get(g, g)}'] = int(V.loc[V['group'] == g, 'ip'].nunique())
    for g in ('Люди', 'Боты', 'Свои'):
        tot[f'Заявки|{g}'] = int(D[f'Заявки|{g}'].sum())
    return pd.concat([D, pd.DataFrame([tot])], ignore_index=True)


def overview(c, F):
    R, V, H = c.R, c.V, c.H
    S = {}
    grp = V.groupby(['group', 'subgroup']).agg(визитов=('n_req', 'size'), IP=('ip', 'nunique'), запросов=('n_req', 'sum'), ГБ=('bytes', lambda s: round(s.sum() / GB, 2))).reset_index()
    grp.columns = ['группа', 'подгруппа', 'визитов', 'IP', 'запросов', 'ГБ']
    S['Люди и боты'] = grp
    S['Журнал активности'] = activity(c)
    from .actors import channels   # каналы считаются в одном месте: сводка, этот лист, бриф
    ch = channels(c)
    S['Каналы'] = ch.assign(**{'доля_визитов_%': (ch['доля'] * 100).round(1), 'конверсия_%': (ch['конверсия'] * 100).round(2)}).drop(columns=['доля', 'конверсия'])
    hp = R.loc[c.human & R['is_page'].values, ['base', 'tpl', 'vid', 'ip']]
    S['Разделы'] = top_pages(c, n=100, by_section=True)
    S['Типы страниц'] = top_pages(c, n=200, by_template=True)
    # TOP500: самые посещаемые существующие страницы (людям отвечали 2xx) — интерес, заявки, ошибки, динамика, каналы
    S['Страницы'] = top_pages(c)
    # фильтры и поиск по сайту
    q = R.loc[c.human & R['is_page'].values, ['query', 'ip', 'base']]
    q = q[q['query'].astype(str) != '']
    if len(q):
        kv = q.assign(p=q['query'].astype(str).str.split('&')).explode('p')
        kv = kv[~kv['p'].str.match(r'(utm_|yclid|gclid|calltouch|etext|ybaip|y_ref|ysclid|erid|_openstat|from=|clear_cache|PAGEN)', na=False)]
        kv['ключ'] = kv['p'].str.split('=').str[0]
        fl = kv.groupby(['ключ', 'p']).agg(применений=('ip', 'size'), людей=('ip', 'nunique')).sort_values('людей', ascending=False).head(300).reset_index().rename(columns={'p': 'значение'})
        c.query_params = fl          # все пары «параметр=значение» у людей — для «Анатомии» (параметры), не отдельный лист
        S['Фасеты'] = facets(R, c)
    # конверсии — каждая отправка
    gp = (R['goal'] != '').values
    P = R.loc[gp, ['ts', 'ip', 'goal', 'status', 'goal_success', 'vid', 'base']].copy()
    P['группа'] = V['group'].values[P['vid'].values]
    P['подгруппа'] = V['subgroup'].values[P['vid'].values]
    P['канал'] = V['channel'].values[P['vid'].values]
    P['страниц_до'] = V['n_pages'].values[P['vid'].values]
    P['ресурсов_грузил'] = V['n_static'].values[P['vid'].values]
    P['сек_от_входа'] = P['ts'].values - V['start'].values[P['vid'].values]
    P['вход'] = V['entry'].values[P['vid'].values]
    P['вход_реферер'] = V['entry_ref'].values[P['vid'].values]
    P['сеть'] = V['nettype'].values[P['vid'].values]
    P['время'] = dt(P['ts'])
    P['принята'] = np.where(P['goal_success'], 'да', 'нет')
    P['статус'] = lead_status(P, R, c.m)
    S['Конверсии'] = P[['время', 'ip', 'goal', 'status', 'принята', 'статус', 'группа', 'подгруппа', 'канал', 'страниц_до', 'ресурсов_грузил', 'сек_от_входа', 'вход', 'вход_реферер', 'сеть']].rename(columns={'goal': 'цель', 'status': 'код'})
    # GET-отправки персональных данных
    G_ = c.G[c.G['query'].astype(str).map(recon.has_pd)] if c.G is not None and len(c.G) else None
    if G_ is not None and len(G_):
        g = G_.copy()
        g['запрос'] = g['query'].astype(str).map(mask_pd)
        g['время'] = dt(g['ts'])
        S['GET-отправки'] = g[['время', 'ip', 'base', 'запрос', 'status', 'fam']].head(2000).rename(columns={'base': 'адрес', 'status': 'код', 'fam': 'робот'})
        ppl = g[g['fam'].astype(str) == '']
        if len(ppl) >= 5:
            F.add('Нагрузка и безопасность', 'Важно', 'pd_in_get', 'forms', 'Персональные данные уходят в адресе страницы (GET)',
                  f"{len(ppl)} запросов с {ppl['ip'].nunique()} адресов; адреса: {', '.join(ppl['base'].astype(str).value_counts().index[:3])}",
                  'код форм сайта', 'Отправлять формы методом POST; убрать данные из адресов и из логов', len(ppl), 'GET-отправки')
    # сводка
    hv = len(H)
    acc = P[P['goal_success']]
    s = {'Период': f"{c.inv['period'][0]} — {c.inv['period'][1]}", 'Запросов': int(len(R)), 'Визитов всего': int(len(V)),
         'Визитов людей': hv, 'IP людей': int(H['ip'].nunique()), 'Просмотров страниц людьми': int(H['n_pages'].sum()),
         'Отправок целей всего': int(len(P)), 'Принято от людей': int((acc['группа'] == 'Люди').sum()),
         'Принято от ботов': int((acc['группа'] == 'Боты').sum()), 'Принято от своих (тесты)': int((acc['группа'] == 'Свои').sum()),
         'Конверсия людей (визит → принятая цель), %': round((acc['группа'] == 'Люди').sum() / max(1, hv) * 100, 3)}
    for gname in ['Роботы', 'Системы мониторинга', 'Утилиты', 'Боты', 'Свои']:
        s[f'Визитов: {gname}'] = int((V['group'] == gname).sum())
    # черновые проблемы
    bot_ok = acc[acc['группа'] == 'Боты']
    if len(bot_ok):
        F.add('Общий анализ', 'Срочно', 'bot_leads', 'all', f'Среди принятых заявок {len(bot_ok)} от ботов',
              f"{len(bot_ok)} принятых отправок с {bot_ok['ip'].nunique()} IP; последняя {bot_ok['время'].max()}. Примеры IP: {', '.join(bot_ok['ip'].astype(str).unique()[:8])}",
              'защита форм (код сайта), CRM', 'Отсеять эти заявки у менеджеров; поставить защиту форм', len(bot_ok), 'Конверсии', also=('Боты',))
    lost = P[(P['группа'] == 'Люди') & (P['status'] >= 400) & (P['status'] != 499)]
    if len(lost):
        F.add('Общий анализ', 'Срочно' if (lost['status'] >= 500).any() else 'Важно', 'lost_leads', 'all', f'{len(lost)} отправок людей получили ошибку сервера',
              f"Коды: {topn(lost['status'])}; цели: {topn(lost['goal'])}", 'код сайта', 'Проверить обработчики форм', len(lost), 'Конверсии', also=('Ошибки',))
    if c.inv.get('hour_gaps'):
        F.add('Общий анализ', 'Важно', 'gaps', 'log', f"В логе пропущено {len(c.inv['hour_gaps'])} часов",
              ', '.join(c.inv['hour_gaps'][:10]), 'сервер / ротация логов', 'Проверить, были ли сбои или потеря логов', len(c.inv['hour_gaps']), 'О данных')
    return S, s


# ======================= ОШИБКИ =======================
DB_RX = r'Too many connections|MySQL server has gone away|Lost connection|Can.t connect to|SQLSTATE|DB query error|Deadlock|marked as crashed|mysqli|Connection refused.*3306'
ERR_TYPES = [
    ('Бэкенд: таймаут', r'upstream timed out'), ('Бэкенд: не отвечает', r'connect\(\) failed|no live upstreams|recv\(\) failed|prematurely closed'),
    ('База данных', DB_RX), ('PHP Fatal', r'PHP Fatal|PHP Parse error'), ('PHP Warning', r'PHP Warning'), ('PHP Notice/Deprecated', r'PHP (Notice|Deprecated)'),
    ('Слишком большой запрос (413)', r'client intended to send too large body'), ('Ограничение частоты', r'limiting (requests|connections)'),
    ('Запрещено правилом', r'access forbidden by rule'), ('Файл не найден', r'No such file|is not found|open\(\).*failed \(2'),
    ('Права доступа', r'Permission denied|\(13:'), ('Нет места на диске', r'No space left'), ('Мало соединений', r'worker_connections'),
    ('SSL', r'SSL_|ssl'), ('Буферизация ответа (норма)', r'buffered to a temporary file'), ('Прочее', r'.'),
]


def outage_windows(R, st, E, gap=3):
    """Окна сбоев. Пик: в минуте ≥3 страниц с 5xx у ≥3 разных IP (не один робот на битых адресах) и ≥25% страниц с 5xx (разрыв ≤3 мин склеивается).
    Деградация: соседние минуты, где доля 5xx+499 у страниц ≥ max(3×обычной для этого часа, 20%) при ≥5 страницах,
    или запросов меньше 30% обычного для этого часа. Пик расширяется деградацией в обе стороны (разрыв ≤3 мин).
    Отдельные окна деградации без пика тоже возвращаются (пик_минут = 0)."""
    page = R['is_page'].values | (R['method'].values == 'POST')
    M = pd.DataFrame({'m': R['ts'].values // 60, 'p5': page & (st >= 500), 'p499': page & (st == 499), 'p': page,
                      'n': np.ones(len(st), dtype=np.int32), 's_ok': R['is_static'].values & (st < 400), 's': R['is_static'].values})
    mm = M.groupby('m').sum()
    m5 = page & (st >= 500)
    mm['ip5'] = pd.DataFrame({'m': M['m'].values[m5], 'ip': R['ip'].values[m5]}).groupby('m')['ip'].nunique()
    mm['ip5'] = mm['ip5'].fillna(0)
    full = np.arange(mm.index.min(), mm.index.max() + 1)
    mm = mm.reindex(full, fill_value=0)
    hour = (mm.index.values // 60) % 24
    share = (mm['p5'] + mm['p499']) / mm['p'].clip(lower=1)
    ok = mm['p'] >= 5
    base_share = pd.Series(np.where(ok, share, np.nan), index=mm.index).groupby(hour).transform('median').fillna(0).values
    base_n = mm['n'].groupby(hour).transform('median').values
    peak = ((mm['p5'] >= 3) & (mm['ip5'] >= 3) & (mm['p5'] / mm['p'].clip(lower=1) >= 0.25)).values
    dshare = (ok & (share >= np.maximum(3 * base_share, 0.2))).values
    drop = (mm['n'].values < 0.3 * base_n) & (base_n >= 20)
    idx = mm.index.values
    def runs(mask):
        pos = np.flatnonzero(mask); out = []
        if not len(pos): return out
        a = b = pos[0]
        for x in pos[1:]:
            if x - b > gap: out.append((a, b)); a = x
            b = x
        out.append((a, b)); return out
    # окна: пики, расширенные деградацией (доля ошибок или провал трафика); отдельно — деградация по доле ошибок без пика
    ext = dshare | drop | peak
    spans = []
    for a, b in runs(ext):
        if peak[a:b + 1].any():
            spans.append((a, b))
    for a, b in runs(dshare | peak):
        if not peak[a:b + 1].any() and b - a + 1 >= 10 and not any(x <= a and b <= y for x, y in spans):
            spans.append((a, b))
    rows = []
    for a, b in sorted(spans):
        pk = np.flatnonzero(peak[a:b + 1])
        seg = mm.iloc[a:b + 1]
        if len(pk):
            pa, pb = a + pk[0], a + pk[-1]
        else:
            if seg['p5'].sum() + seg['p499'].sum() < 20: continue
            pa, pb = a, b
        ps = mm.iloc[pa:pb + 1]
        t0, t1 = idx[a] * 60, idx[b] * 60 + 59
        dbmsg = up = 0
        if E is not None and len(E):
            em = E[(E['ts'] >= t0) & (E['ts'] <= t1)]
            dbmsg = int(em['msg'].str.contains(DB_RX, regex=True).sum())
            up = int(em['msg'].str.contains('upstream timed out|connect\\(\\) failed', regex=True).sum())
        static_ok = seg['s_ok'].sum() / max(1, seg['s'].sum())
        cause = []
        if dbmsg: cause.append(f'база данных ({dbmsg} сообщений)')
        if up: cause.append(f'бэкенд не отвечает/таймаут ({up})')
        if static_ok > 0.9 and seg['p5'].sum(): cause.append('статика отдавалась нормально — падала динамика')
        if (ps['n'].mean() < 0.3 * base_n[pa:pb + 1].mean()): cause.append('трафик провалился — сервер принимал мало запросов')
        if pb - pa + 1 < 2 and seg['p5'].sum() + seg['p499'].sum() < 20: continue   # одиночная минута без заметных потерь — шум
        rows.append(dict(деградация_с=dt(t0), начало=dt(idx[pa] * 60), конец=dt(idx[pb] * 60 + 59), деградация_по=dt(t1),
                         пик_минут=int(pb - pa + 1) if len(pk) else 0, минут_всего=int(b - a + 1),
                         страниц_с_5xx=int(seg['p5'].sum()), обрывов_499=int(seg['p499'].sum()),
                         доля_5xx_у_страниц_в_пик=round(ps['p5'].sum() / max(1, ps['p'].sum()), 2),
                         запросов_в_мин=int(ps['n'].mean()), обычно_запросов_в_мин=int(base_n[pa:pb + 1].mean()),
                         статика_в_норме=round(static_ok, 2), вероятная_причина='; '.join(cause) or 'не определена'))
    W = pd.DataFrame(rows)
    return W, rows


FACET_WORDS = {'rooms': 'Комнат', 'room': 'Комнат', 'komnat': 'Комнат', 'house_num': 'Дом', 'house': 'Дом', 'dom': 'Дом', 'total_area': 'Площадь',
               'area': 'Площадь', 'square': 'Площадь', 'complete_date': 'Срок сдачи', 'deadline': 'Срок сдачи', 'project': 'Проект', 'district': 'Район',
               'finishing': 'Отделка', 'price': 'Цена', 'cost': 'Цена', 'floor': 'Этаж', 'section': 'Секция', 'brand': 'Бренд', 'manufacturer': 'Производитель',
               'color': 'Цвет', 'colour': 'Цвет', 'size': 'Размер', 'material': 'Материал', 'category': 'Категория', 'type': 'Тип', 'city': 'Город', 'region': 'Регион'}
FACET_PATH = r'^([a-z][a-z0-9_]*)-(is|from|to)-(.+)$|^([a-z][a-z0-9_]*)[:=](.+)$'
FACET_KEY = r'(?i)(filter|^f$|^f\[|\[\]$|_(min|max|from|to)$|^pa_|^attr|^prop|^price|^brand|^color|^size)'
NOT_FACET = r'(?i)^(set_filter|del_filter|ajax\w*|sort\w*|order\w*|view|page|pagen_\d+|utm_\w+|yclid|gclid|fbclid|bxajaxid|clear_cache)$'


def facet_name(key):
    k = key.lower()
    for w in sorted(FACET_WORDS, key=len, reverse=True):
        if re.search(rf'(^|[_\[]){w}($|[_\]])', k): return FACET_WORDS[w]
    return key


def facets(R, c):
    """Фасеты — что люди выбирают в фильтре каталога. Только по логу и общим признакам, без привязки к движку:
    в пути (ключ-is-значение, ключ-from-…, ключ:значение) и в параметрах фильтра (filter…, …_min/_max, ключ[]= …)."""
    from urllib.parse import unquote
    pg = c.human & R['is_page'].values & (R['status'].values == 200)
    D = pd.DataFrame({'b': R['base'].values[pg].astype(str), 'q': R['query'].values[pg].astype(str), 'ip': R['ip'].values[pg].astype(str)})
    rows = []
    fp = D[D['b'].str.contains(r'/[a-z][a-z0-9_]*-(?:is|from|to)-|/[a-z][a-z0-9_]*[:=]', regex=True)]
    for b, ip in zip(fp['b'], fp['ip']):
        segs = b.strip('/').split('/')
        sec = '/' + segs[0] + '/'
        for sg in segs[1:]:
            m_ = re.match(FACET_PATH, unquote(sg), re.I)
            if not m_: continue
            if m_.group(1):
                k, op, v = m_.group(1), m_.group(2), m_.group(3)
                key = f'{k}-{op}'
            else:
                k, op, v = m_.group(4), 'is', m_.group(5)
                key = k
            name = facet_name(k) + {'from': ' от', 'to': ' до'}.get(op, '')
            for v1 in re.split(r'-or-|,', v):
                rows.append((sec, key, v1.strip(), name, ip, 'адрес фасетной страницы'))
    pq = D[D['q'] != '']
    for b, q, ip in zip(pq['b'], pq['q'], pq['ip']):
        sec = '/' + (b.strip('/').split('/')[0] or '') + '/'
        for part in q.split('&'):
            k, _, v = part.partition('=')
            k = unquote(k)
            if not v or re.match(NOT_FACET, k) or not re.search(FACET_KEY, k): continue
            base_ = re.sub(r'(?i)_(min|max|from|to)$', '', k)
            tail = ' от' if re.search(r'(?i)_(min|from)$', k) else ' до' if re.search(r'(?i)_(max|to)$', k) else ''
            nm = facet_name(base_)
            rows.append((sec, k, unquote(v), nm + tail if nm != base_ else k, ip, 'параметры фильтра'))   # неизвестный ключ — как есть
    if not rows: return pd.DataFrame()
    F = pd.DataFrame(rows, columns=['раздел', 'ключ', 'значение', 'условие', 'ip', 'откуда'])
    F['расшифровка'] = [('студия' if u == 'Комнат' and v == '0' else {'y': 'да', 'n': 'нет'}.get(str(v).lower(), v)) for u, v in zip(F['условие'], F['значение'])]
    F = decode_opaque(F)
    out = F.groupby(['раздел', 'ключ', 'значение', 'условие', 'расшифровка', 'откуда']).agg(запросов=('ip', 'size'), людей=('ip', 'nunique')).reset_index()
    return out.sort_values('людей', ascending=False).head(1000)[['раздел', 'ключ', 'значение', 'условие', 'расшифровка', 'запросов', 'людей', 'откуда']]


OPAQUE = r'^(\d{6,}|[0-9a-f]{32}|[0-9a-f]{40})$'


def decode_opaque(F):
    """Непонятные значения (длинные числа, hex) пробуем расшифровать, если они — контрольная сумма понятного:
    crc32, md5 или sha1 от значений фасетных страниц или небольших чисел. Не подобралось — оставляем как есть.
    Галочка вида «ключ_<код>=Y» — код и есть значение. Название поля берём у фасета с теми же значениями."""
    import zlib, hashlib
    F = F.copy()
    path = F[F['откуда'].str.startswith('адрес')]
    cands = {str(i) for i in range(0, 2001)}
    for v in path['значение'].astype(str):
        cands |= {v, v.capitalize(), v.title(), v.upper(), v.lower()}
    table = {}
    for c_ in cands:
        for enc in ('utf-8', 'cp1251'):
            try: b_ = c_.encode(enc)
            except Exception: continue
            h = zlib.crc32(b_)
            for k_ in (str(h), str(h - 2 ** 32 if h >= 2 ** 31 else h).lstrip('-'), hashlib.md5(b_).hexdigest(), hashlib.sha1(b_).hexdigest()):
                table.setdefault(k_, c_)
    def opaque(k, v):
        tail = str(k).rsplit('_', 1)[-1]
        if str(v).lower() in ('y', 'on', '1', 'true') and re.fullmatch(OPAQUE, tail.lower()): return tail.lower(), re.sub(r'_[^_]+$', '', str(k))
        if re.fullmatch(OPAQUE, str(v).lower()): return str(v).lower(), re.sub(r'(?i)_(min|max|from|to)$', '', str(k))
        return None, re.sub(r'(?i)_(min|max|from|to)$', '', str(k))
    keys = [opaque(k, v) for k, v in zip(F['ключ'], F['значение'])]
    F['_txt'] = [table.get(o) if o else None for o, _ in keys]
    F['_stem'] = [st for _, st in keys]
    cond_of = {}
    for _, r in path.iterrows(): cond_of.setdefault(str(r['значение']).lower(), Counter())[re.sub(r' (от|до)$', '', r['условие'])] += 1
    for i in F.index:   # условие у галочек — ключ без кода значения
        if F.at[i, 'условие'] == F.at[i, 'ключ'] and F.at[i, '_stem'] != F.at[i, 'ключ']: F.at[i, 'условие'] = F.at[i, '_stem']
    for stem, g in F[F['откуда'].str.startswith('параметры')].groupby('_stem'):
        vote = Counter()
        for t in g['_txt'].dropna():
            if not str(t).isdigit(): vote.update(cond_of.get(str(t).lower(), Counter()))   # совпадение чисел — слабая улика, поле по нему не называем
        if not vote: continue
        name = vote.most_common(1)[0][0]
        for i in g.index:
            k = str(F.at[i, 'ключ'])
            F.at[i, 'условие'] = name + (' от' if re.search(r'(?i)_(min|from)$', k) else ' до' if re.search(r'(?i)_(max|to)$', k) else '')
    for i in F.index[F['_txt'].notna()]:
        t = F.at[i, '_txt']
        F.at[i, 'расшифровка'] = 'студия' if F.at[i, 'условие'] == 'Комнат' and t == '0' else t
    return F.drop(columns=['_txt', '_stem'])


def lead_status(P, R, m):
    """Статус каждой заявки: принята / не принята и почему / что было дальше (повторил и отправил или ушёл)."""
    rules = m.get('form_success_rules') or {}
    if isinstance(rules, str):
        try: rules = eval(rules)
        except Exception: rules = {}
    chk = R['goal_check'].values[P.index] if 'goal_check' in R else np.array([''] * len(P), dtype=object)
    out = []
    ok_times = P[P['goal_success']].groupby('ip', observed=True)['ts'].apply(list).to_dict()
    for (i, r), how in zip(P.iterrows(), chk):
        st, rule = int(r['status']), str(rules.get(r['goal'], ''))
        if r['goal_success']:
            out.append('принята' + (' (подтверждена: ' + how + ')' if how else ' (успех по коду ответа не виден)' if 'не различим' in rule else '')); continue
        if st == 499: s_ = 'не дошла: посетитель не дождался ответа (499)'
        elif st >= 500: s_ = f'ошибка сервера ({st})'
        elif st >= 400: s_ = f'отклонена сервером ({st})'
        elif st in (302, 303): s_ = 'переадресация без подтверждения успеха'
        elif '3xx' in rule: s_ = 'отклонена формой: ошибка заполнения или проверки'
        else: s_ = 'успех не виден'
        later = [t for t in ok_times.get(r['ip'], []) if r['ts'] < t <= r['ts'] + 1800]
        s_ += ' → потом отправил успешно' if later else ' → больше не отправлял'
        out.append('не принята: ' + s_)
    return out


def errors(c, F):
    R, V = c.R, c.V
    S = {}
    st = R['status'].values
    WHO = np.array(['люди', 'поисковики', 'другие роботы', 'свои', 'боты'], dtype=object)
    KL = np.array(['5xx', '499', '404', '4xx прочие', 'норма'], dtype=object)
    rg = np.asarray(c.rg)
    who = np.select([c.human, c.search_ok, rg == 'Роботы', rg == 'Свои'], [0, 1, 2, 3], 4).astype(np.int8)
    kl = np.select([st >= 500, st == 499, st == 404, st >= 400], [0, 1, 2, 3], 4).astype(np.int8)
    X = pd.DataFrame({'d': R['day'].cat.codes.values, 'w': who, 'k': kl}).groupby(['d', 'w', 'k']).size().reset_index(name='n')
    X['день'] = R['day'].cat.categories[X['d']]; X['кто'] = WHO[X['w']]; X['класс'] = KL[X['k']]
    S['Ошибки по дням'] = X.pivot_table(index=['день', 'кто'], columns='класс', values='n', fill_value=0).reset_index()
    K = pd.DataFrame({'код': st, 'w': who}).groupby(['код', 'w']).size().reset_index(name='n')
    K['кто'] = WHO[K['w']]
    S['Коды ответа'] = K.pivot_table(index='код', columns='кто', values='n', fill_value=0).reset_index()
    # сбои: пик (страницы массово отдают 5xx) и деградация вокруг него (доля 5xx+499 в разы выше обычной для этого часа или провал трафика)
    S['Сбои'], outages = outage_windows(R, st, c.E)
    for w in outages:
        if w['пик_минут'] >= 2 and w['страниц_с_5xx'] >= 10:
            deg = f"деградация {str(w['деградация_с'])[:16]}–{str(w['деградация_по'])[11:16]}, " if w['деградация_с'] != w['начало'] or w['деградация_по'] != w['конец'] else ''
            F.add('Ошибки', 'Срочно', 'outage', str(w['начало'])[:16], f"Сбой {str(w['начало'])[:16]}–{str(w['конец'])[11:16]}: страницы отдавали 5xx",
                  f"{deg}пик {str(w['начало'])[11:16]}–{str(w['конец'])[11:16]} ({w['пик_минут']} мин): {w['страниц_с_5xx']} страниц с 5xx, {w['обрывов_499']} обрывов 499, "
                  f"запросов в минуту {w['запросов_в_мин']} при обычных {w['обычно_запросов_в_мин']} для этого часа; причина: {w['вероятная_причина']}",
                  'сервер / база данных', 'Найти причину по логам сервера и базы за окно деградации', int(w['минут_всего']), 'Сбои')
        elif w['минут_всего'] >= 10 and w['страниц_с_5xx'] + w['обрывов_499'] >= 20:
            F.add('Ошибки', 'Важно', 'degradation', str(w['деградация_с'])[:16], f"Деградация {str(w['деградация_с'])[:16]}–{str(w['деградация_по'])[11:16]}: рост 5xx/499 или провал трафика",
                  f"{w['минут_всего']} мин; {w['страниц_с_5xx']} страниц с 5xx, {w['обрывов_499']} обрывов 499; причина: {w['вероятная_причина']}",
                  'сервер', 'Проверить нагрузку и логи сервера за это окно', int(w['минут_всего']), 'Сбои')
    # данные окна для правил важности: когда кончилось, сколько длилось, задело ли рекламу и заявки
    for w in outages:
        for x in F.items:
            if x['key'] in (f"Ошибки:outage:{str(w['начало'])[:16]}", f"Ошибки:degradation:{str(w['деградация_с'])[:16]}"):
                a, b = pd.Timestamp(w['деградация_с']).timestamp(), pd.Timestamp(w['деградация_по']).timestamp()
                vw = V[(V['group'] == 'Люди') & (V['start'] <= b) & (V['end'] >= a)]
                x['окно'] = dict(с=a, по=b, минут=int(w['минут_всего']), час=pd.Timestamp(w['деградация_с']).hour,
                                 реклама=int((vw['channel'] == 'Реклама').sum()), заявки=int((vw['n_goal'] > 0).sum()))
    # 5xx по шаблонам
    page = R['is_page'].values | (R['method'].values == 'POST')
    m5 = (st >= 500) & page
    Q = R.loc[m5, ['tpl', 'base', 'day', 'vid', 'ts']].assign(чел=c.human[m5])
    if len(Q):
        g = Q.groupby('tpl', observed=True)
        T5 = pd.DataFrame({'ошибок': g.size(), 'у_людей': g['чел'].sum(), 'людей_задето': Q[Q['чел']].groupby('tpl', observed=True)['vid'].nunique(),
                           'адресов': g['base'].nunique(), 'пример': g['base'].first().astype(str), 'первый_день': g['day'].min().astype(str), 'последний_день': g['day'].max().astype(str),
                           'дней_с_ошибкой': g['day'].nunique()}).fillna(0).sort_values('у_людей', ascending=False)
        ok_tpl = R.loc[page & (st < 400), 'tpl'].value_counts()
        T5['успешных_ответов'] = ok_tpl.reindex(T5.index).fillna(0).astype(int).values
        S['5xx по шаблонам'] = T5.reset_index().rename(columns={'tpl': 'шаблон'})
        T5['раздел'] = [re.match(r'^(/[^/]*/?)', str(t)).group(1) for t in T5.index]
        big = T5[T5['у_людей'] >= 5]
        grouped = set()
        for sec, gsec in big.groupby('раздел'):
            if len(gsec) >= 3 and gsec['у_людей'].max() < 0.5 * gsec['у_людей'].sum():
                grouped |= set(gsec.index)
                F.add('Ошибки', 'Срочно' if gsec['у_людей'].sum() >= 20 else 'Важно', '5xx_section', sec, f"5xx на {len(gsec)} страницах раздела {sec}",
                      f"{int(gsec['у_людей'].sum())} ошибок у людей, задето визитов: {int(gsec['людей_задето'].sum())}; {gsec['первый_день'].min()} — {gsec['последний_день'].max()}; страницы: {', '.join(gsec.index[:6])}",
                      'код сайта', 'Исправить раздел или убрать ссылки на него', int(gsec['у_людей'].sum()), '5xx по шаблонам')
        for t, r in T5.head(15).iterrows():
            if r['у_людей'] >= 5 and t not in grouped:
                always = r['успешных_ответов'] == 0
                F.add('Ошибки', 'Срочно' if r['у_людей'] >= 20 else 'Важно', '5xx', t, f"{'Всегда' if always else 'Часто'} 5xx: {t}",
                      f"{int(r['у_людей'])} ошибок у людей, задето визитов: {int(r['людей_задето'])}; {r['первый_день']} — {r['последний_день']}; пример {r['пример']}",
                      'код сайта', 'Исправить страницу или убрать ссылки на неё', int(r['у_людей']), '5xx по шаблонам')
    # 404: входы извне у людей
    H = c.H
    e404 = H[H['entry_status'] == 404]
    if len(e404):
        X4 = e404.groupby(['entry', 'channel']).agg(визитов=('ip', 'size'), IP=('ip', 'nunique'), реферер=('entry_ref_host', lambda s: topn(s, 2))).sort_values('визитов', ascending=False).reset_index()
        X4 = X4.rename(columns={'entry': 'адрес', 'channel': 'канал'})
        S['404: входы извне'] = X4
        bych = e404.groupby('channel').size()
        for chn, n in bych.items():
            if chn in ('Реклама', 'Карты', 'Поиск', 'Соцсети и мессенджеры', 'ИИ-ассистенты', 'Площадки и агрегаторы') and n >= 3:
                ex = X4[X4['канал'] == chn].head(5)
                F.add('Ошибки', 'Срочно' if chn == 'Реклама' else 'Важно', '404_entry', chn, f'Люди приходят на несуществующие страницы: {chn}',
                      f"{n} визитов; адреса: {', '.join(ex['адрес'].astype(str))}", 'редиректы (nginx/.htaccess) или ссылки в источнике',
                      'Поставить 301 на живые адреса или исправить ссылки', int(n), '404: входы извне', also=('Маркетинг',) if chn == 'Реклама' else ())
    # битые ссылки на сайте
    vuln_b = R['base'].cat.categories.to_series().str.contains(VULN, regex=True, case=False).values[R['base'].cat.codes.values]
    bl = c.human & (st == 404) & R['ref_internal'].values & ~R['is_static'].values & ~vuln_b
    B = R.loc[bl, ['tpl', 'base', 'ref_path', 'vid']]
    if len(B):
        bt = B.groupby('tpl', observed=True).agg(переходов=('vid', 'size'), визитов=('vid', 'nunique'), пример=('base', 'first'), страниц_источников=('ref_path', 'nunique'),
                                                  главный_источник=('ref_path', lambda s: topn(s.astype(str), 2))).sort_values('визитов', ascending=False)
        S['Битые ссылки'] = bt.reset_index().rename(columns={'tpl': 'куда (шаблон)'})
        src = B.groupby('ref_path', observed=True).agg(битых_переходов=('vid', 'size'), разных_адресов=('base', 'nunique')).sort_values('битых_переходов', ascending=False)
        S['Битые ссылки: страницы-источники'] = src.head(200).reset_index().rename(columns={'ref_path': 'страница'})
        if bt['визитов'].sum() >= 10:
            F.add('Ошибки', 'Важно', 'broken_links', 'site', f"Битые ссылки на сайте: {int(bt['визитов'].sum())} визитов людей упёрлись в 404",
                  f"Главные: {', '.join(bt.head(5).index.astype(str))}", 'содержимое/шаблоны сайта', 'Исправить ссылки; начать со страниц-источников', int(bt['визитов'].sum()), 'Битые ссылки')
    # отсутствующие ресурсы
    mr = c.human & (st == 404) & R['is_static'].values & ~vuln_b & (R['ext'].astype(str).values != 'map')   # .map просит инструмент разработчика, не страница
    MR = R.loc[mr, ['base', 'ref_path', 'vid']]
    if len(MR):
        from .findings import load_rules
        invis = re.compile(load_rules().get('невидимые_файлы', 'placeholder|lazy|blank|spacer'), re.I)
        mt = MR.groupby('base', observed=True).agg(запросов=('vid', 'size'), визитов=('vid', 'nunique'), страниц=('ref_path', 'nunique')).sort_values('визитов', ascending=False)
        mt['группа'] = [b if invis.search(b) else '/apple-touch-icon*.png' if re.search(r'/apple-touch-icon[\w-]*\.png$', b) else re.sub(r'[^/]+$', '*', b)
                        for b in mt.index.astype(str)]   # заглушки — отдельной проблемой; иконки айфонов — отдельным пунктом
        S['Отсутствующие ресурсы'] = mt.head(500).reset_index().rename(columns={'base': 'файл'})
        mg = mt.groupby('группа').agg(файлов=('запросов', 'size'), запросов=('запросов', 'sum'), визитов=('визитов', 'max')).sort_values('запросов', ascending=False)
        for gname, r in mg.head(5).iterrows():
            if r['визитов'] >= 100:
                F.add('Ошибки', 'Важно', 'missing_static', gname, f'Отсутствующие файлы, которые запрашивают страницы: {gname}',
                      f"{int(r['файлов'])} файлов, {int(r['визитов'])} визитов людей, {int(r['запросов'])} запросов", 'код/вёрстка сайта', 'Вернуть файлы или убрать ссылки на них из шаблона', int(r['визитов']), 'Отсутствующие ресурсы')
                for x in F.items:
                    if x['key'] == f'Ошибки:missing_static:{gname}':
                        x['файлы'] = mt[mt['группа'] == gname].index.astype(str).tolist()[:20]
    # индексы для ИИ-поиска: спрашивают, а файла нет — замечание, не проблема
    ai = R['base'].cat.categories.to_series().str.fullmatch(r'/(llms(-full)?\.txt|ai\.txt)').fillna(False).values[R['base'].cat.codes.values]
    AI = R.loc[ai, ['base', 'status', 'fam']]
    if len(AI) and not (AI['status'].between(200, 299)).any():
        per = AI.groupby('base', observed=True).size().sort_values(ascending=False)
        per = per[per > 0]
        F.add('Ошибки', 'Замечание', 'ai_index', 'site', 'Нет файлов для ИИ-поиска: ' + ', '.join(per.index.astype(str)),
              '; '.join(f'{b} — {int(k)} запросов' for b, k in per.items()) + f"; запрашивают: {topn(AI['fam'].astype(str).replace('', 'браузеры'), 3)}",
              'сайт', 'Решить, нужен ли сайту llms.txt; если нужен — создать', int(len(AI)), '')
    # служебные файлы по дням
    sv = R['base'].cat.categories.to_series().str.contains(r'^/robots\.txt$|sitemap[\w-]*\.xml|\.yml$|/export/|feed|\.xml$', regex=True, case=False).values[R['base'].cat.codes.values]
    SV = R.loc[sv, ['base', 'day', 'status', 'bytes', 'fam']]
    if len(SV):
        sd = SV.groupby(['base', 'day'], observed=True).agg(запросов=('status', 'size'), коды=('status', lambda s: topn(s, 3)), КБ=('bytes', lambda s: round(s.mean() / KB, 1))).reset_index()
        S['Служебные файлы'] = sd.rename(columns={'base': 'адрес', 'day': 'день'})
        legit_cat = R['fam_cat'].isin(['Поисковик', 'Реклама/аналитика', 'Фиды/площадки', 'Сервисы Google']).values[sv]
        SV = SV.assign(legit=legit_cat)
        ever_ok = SV[SV['status'] == 200].groupby('base', observed=True).size()
        for b, g in SV.groupby('base', observed=True):
            gl = g[g['legit']]
            if not ((len(gl) >= 10 and (gl['status'] >= 400).mean() > 0.8) or (ever_ok.get(b, 0) >= 5 and (g['status'].iloc[-max(1, len(g) // 5):] >= 400).mean() > 0.8)):
                other_map = 'sitemap' in str(b) and SV[SV['base'].astype(str).str.contains('sitemap') & (SV['base'].astype(str) != str(b)) & (SV['status'] == 200)].shape[0] >= 5   # карта есть под другим именем
                if not other_map and re.fullmatch(r'/(robots\.txt|sitemap\.xml)', str(b)) and len(g[(g['status'] < 300) | (g['status'] >= 400)]) and (g.loc[(g['status'] < 300) | (g['status'] >= 400), 'status'] == 404).mean() > 0.9:
                    F.add('Ошибки', 'Важно' if 'sitemap' in str(b) else 'К сведению', 'no_service', str(b), f'На сайте нет {b}', f"{int((g['status'] == 404).sum())} запросов получили 404; запрашивают: {topn(g['fam'].astype(str).replace('', 'браузеры'), 3)}", 'сайт', f'Создать {b}', len(g), 'Служебные файлы')
                continue
            if True:
                feed = not re.search(r'robots|sitemap', str(b))
                F.add('Ошибки', 'Срочно' if feed else 'Важно', 'service_err', str(b), f"{'Фид' if feed else 'Служебный файл'} {b} отдаёт ошибку",
                      f"{len(g)} запросов, коды {topn(g['status'])}; кто запрашивает: {topn(g['fam'].astype(str).replace('', 'браузеры'), 3)}",
                      'фид/генерация файла на сайте', 'Восстановить файл или поправить адрес в кабинетах', len(g), 'Служебные файлы', also=('Маркетинг',) if feed else ())
    # поисковики
    so = c.search_ok
    if so.any():
        SE = R.loc[so, ['fam', 'tpl', 'status']]
        se = SE.assign(ошибка=SE['status'] >= 400).groupby(['fam', 'tpl'], observed=True).agg(запросов=('status', 'size'), ошибок=('ошибка', 'sum'),
                                                                                       коды=('status', lambda x: topn(x[x >= 400], 3))).reset_index()
        se = se[se['ошибок'] > 0].sort_values('ошибок', ascending=False)
        S['Ошибки у поисковиков'] = se.head(300).rename(columns={'fam': 'робот', 'tpl': 'шаблон'})
        share = (SE['status'] >= 400).mean()
        conc = se[(se['запросов'] >= 30) & (se['ошибок'] >= 20) & (se['ошибок'] / se['запросов'] >= 0.3)]
        if share <= 0.05 and len(conc):
            F.add('Ошибки', 'Важно', 'search_errors', 'templates', f'Поисковые роботы получают ошибки в {len(conc)} шаблонах',
                  '; '.join(f"{r['fam']} {r['tpl']} — {int(r['ошибок'])} из {int(r['запросов'])} ({r['коды']})" for _, r in conc.head(5).iterrows()),
                  'код сайта / редиректы', 'Исправить страницы или убрать их из индекса', int(conc['ошибок'].sum()), 'Ошибки у поисковиков')
        if share > 0.05:
            F.add('Ошибки', 'Важно', 'search_errors', 'all', f'Поисковые роботы получают ошибки: {share*100:.1f}% запросов',
                  f"Главные шаблоны: {', '.join(se.head(5)['шаблон'].astype(str))}", 'код сайта / редиректы', 'Убрать из индекса или исправить', round(share * 100, 1), 'Ошибки у поисковиков')
    # реклама: посадочные с ошибками
    ad = H[(H['channel'] == 'Реклама') & (H['entry_status'] >= 400)]
    if len(ad):
        S['Реклама: посадочные с ошибками'] = ad.groupby(['entry', 'entry_status']).agg(кликов=('ip', 'size'), первый=('day', 'min'), последний=('day', 'max')).sort_values('кликов', ascending=False).reset_index()
    # мягкие ошибки: одинаковый размер ответа на множестве разных адресов
    pg = R.loc[R['is_page'].values & (st == 200) & (R['method'].values != 'HEAD'), ['base', 'bytes']]
    sz = pg.groupby('bytes')['base'].nunique()
    soft = sz[(sz >= 200) & (sz.index < 20000)].sort_values(ascending=False)
    if len(soft):
        S['Одинаковые ответы'] = soft.head(20).reset_index().rename(columns={'bytes': 'размер_байт', 'base': 'разных_адресов'})
    tiny = pg[pg['bytes'] < 300]
    if len(tiny) > 100:
        S['Пустые страницы'] = tiny.groupby('base', observed=True).size().sort_values(ascending=False).head(100).reset_index(name='ответов_меньше_300_байт')
    # изменения статусов по шаблонам (детектор выкладок)
    pp = R.loc[page & c.human, ['tpl', 'day', 'status']]
    dom = pp.assign(cls=np.where(pp['status'] >= 500, '5xx', np.where(pp['status'] == 404, '404', np.where(pp['status'] < 400, 'OK', '4xx')))).groupby(['tpl', 'day', 'cls'], observed=True).size().unstack('cls', fill_value=0)
    ch = []
    for t, g in dom.groupby(level=0):
        if g.values.sum() < 50: continue
        lab = g.idxmax(axis=1).values
        days = [d for _, d in g.index]
        for i in range(1, len(lab)):
            if lab[i] != lab[i - 1]:
                ch.append(dict(шаблон=t, день=days[i], было=lab[i - 1], стало=lab[i]))
    S['Изменения статусов'] = pd.DataFrame(ch)
    # защита: кого блокирует
    blk = np.isin(st, [403, 429, 444, 503])
    # «люди» — только визиты, которые смотрели сайт (есть страница с ответом 200); сканер служебных файлов — не человек
    browsing = np.isin(R['vid'].values, np.unique(R['vid'].values[c.human & R['is_page'].values & (st == 200)]))
    probe = R['base'].cat.categories.to_series().str.contains(r'\.log$|/logs?/|^/(upload|uploads|images|files|bitrix|local)/$', regex=True, case=False).values[R['base'].cat.codes.values]   # логи и листинги папок ищут сканеры
    PB = R.loc[blk & ~vuln_b & ~probe & ((c.human & browsing) | c.search_ok | (R['fam'] == 'YaDirectFetcher').values), ['day', 'status', 'nettype', 'cc', 'ua_webview', 'base', 'fam']]
    if len(PB):
        PB = PB.assign(кто=np.where(PB['fam'].astype(str) == '', 'люди', PB['fam'].astype(str)))
        S['Защита: кого блокирует'] = PB.groupby(['кто', 'status', 'nettype', 'cc'], observed=True).agg(ответов=('day', 'size'), дней=('day', 'nunique'), пример=('base', 'first')).sort_values('ответов', ascending=False).reset_index().head(300)
        nh = int((PB['кто'] == 'люди').sum())
        if nh >= 30:
            F.add('Ошибки', 'Важно', 'blocked_people', 'all', f'Люди получают блокировки (403/429/444/503): {nh} ответов',
                  topn(PB.loc[PB['кто'] == 'люди', 'status']), 'защита (nginx, CMS, хостинг)', 'Проверить правила защиты', nh, 'Защита: кого блокирует')
    # error-лог
    if c.E is not None and len(c.E):
        E = c.E
        kind = pd.Series('Прочее', index=E.index)
        for name, rx in reversed(ERR_TYPES):
            kind[E['msg'].str.contains(rx, regex=True)] = name
        E2 = E.assign(тип=kind, день=dt(E['ts']).dt.strftime('%Y-%m-%d'))
        et = E2.groupby('тип').agg(сообщений=('ts', 'size'), первый=('день', 'min'), последний=('день', 'max'), пример=('msg', 'first'), запрос=('request', lambda s: topn(s, 2))).sort_values('сообщений', ascending=False)
        S['Error-лог'] = et.reset_index()
        for t, r in et.iterrows():
            if t in ('База данных', 'Нет места на диске', 'PHP Fatal') and r['сообщений'] > 0:
                F.add('Ошибки', 'Срочно' if t != 'PHP Fatal' else 'Важно', 'errlog', t, f'В error-логе: {t}', f"{r['сообщений']} сообщений, {r['первый']} — {r['последний']}; {str(r['пример'])[:200]}",
                      'сервер / код', 'Разобрать по error-логу', int(r['сообщений']), 'Error-лог')
    # битый код страниц: скрипты сайта собирают адреса из шаблонов (${marker.image}, ' + href +) — люди получают 404
    kg = constructs(c)
    bad = kg[kg['со_страниц_сайта'] > 0] if len(kg) else kg
    if len(bad):
        S['Битые адреса из скриптов'] = bad[['адрес', 'со_страниц_сайта', 'IP', 'коды', 'страница']].rename(columns={'адрес': 'Адрес', 'со_страниц_сайта': 'Запросов со страниц сайта', 'коды': 'Коды', 'страница': 'Страница-источник'})
        F.add('Ошибки', 'Важно', 'broken_js', 'constructs', f'Скрипты сайта собирают битые адреса ({len(bad)})',
              '; '.join(f"{r['адрес']} — со страницы {r['страница'] or '?'}, {int(r['со_страниц_сайта'])} раз" for _, r in bad.head(5).iterrows()),
              'шаблоны и скрипты сайта', 'Найти на этих страницах код, который подставляет переменную в адрес, и исправить', int(bad['со_страниц_сайта'].sum()), 'Битые адреса из скриптов')
    s = {'Доля ошибок у людей, %': round(((st >= 400) & c.human & page).sum() / max(1, (c.human & page).sum()) * 100, 2),
         '5xx у людей': int(((st >= 500) & c.human).sum()), 'Окон сбоев': int((S['Сбои']['пик_минут'] > 0).sum()) if len(S['Сбои']) else 0,
         'Визитов людей со входом на 404': int(len(e404)), 'Битых переходов внутри сайта': int(bl.sum())}
    return S, s


# ======================= НАГРУЗКА И БЕЗОПАСНОСТЬ =======================
ATTACK = r"(?i)(union(\s|%20|\+)+select|'(\s|%20|\+)*or(\s|%20|\+)*'?1'?=|sleep\(|benchmark\(|<script|%3Cscript|javascript:|\.\./|%2e%2e%2f|\$\{jndi:|/etc/passwd|cmd=|exec\(|base64_decode|wget(\s|%20)http|curl(\s|%20)http)"
TARGETS = [('WordPress', r'wp-|xmlrpc'), ('Утечки конфигов (.env, .git, ключи)', r'\.env|\.git|\.aws|\.ssh|\.svn|config\.|credentials'), ('Бэкапы и дампы', r'backup|\.(sql|sqlite|sqlitedb|db|dump|bak|old|tar|tgz|zip|rar|bz2|xz|lz)(\.|$)'),
           ('Панели БД и админки', r'phpmyadmin|pma|adminer|/admin'), ('Отладка и фреймворки', r'phpinfo|actuator|telescope|_profiler|debug|console|phpunit'),
           ('Установщики Битрикс', r'restore\.php|bitrixsetup|install\.php|setup\.php'), ('Роутеры/IoT/почта', r'boaform|HNAP|owa|autodiscover|cgi-bin'), ('Прочее', r'.')]


def constructs(c):
    """Конструкты из реестра адресов: это не адрес — шаблон JavaScript, склейка строк, кавычки, параметры без «?».
    Со страниц сайта у людей — битый код сайта (ошибка); у роботов — битая ссылка в сети; у посторонних — инъекции и зонды."""
    if getattr(c, '_constructs', None) is not None: return c._constructs
    R = c.R
    kg = pd.DataFrame()
    A_ = getattr(c, 'addr', None)
    if A_ is not None and (A_['форма'] == 'конструкт').any():
        cc_ = R['base'].cat.codes.values
        km = (A_['форма'] == 'конструкт').reindex(range(len(R['base'].cat.categories))).fillna(False).values[cc_]
        K = R.loc[km, ['base', 'status', 'ip', 'ref_internal', 'ref_path']].assign(люди=c.human[km] | np.asarray(c.rg == 'Свои')[km], роботы=np.asarray(c.rg == 'Роботы')[km])
        if len(K):
            self_ = K['ref_path'].astype(str).values == K['base'].astype(str).values   # реферер «сам на себя» — не страница-источник
            K = K.assign(со_страниц=K['ref_internal'].astype(bool) & K['люди'] & ~self_, ref_path=K['ref_path'].astype(str).where(~self_, ''))
            kg = K.groupby('base', observed=True).agg(запросов=('ip', 'size'), IP=('ip', 'nunique'), люди=('люди', 'sum'), роботы=('роботы', 'sum'), со_страниц_сайта=('со_страниц', 'sum'),
                                                       коды=('status', lambda s: topn(s, 4)),
                                                       страница=('ref_path', lambda s: (s.astype(str)[s.astype(str).str.startswith('/')].mode().tolist() or [''])[0])).reset_index().rename(columns={'base': 'адрес'})
            kg['вывод'] = np.select([kg['со_страниц_сайта'] > 0, kg['люди'] > 0, kg['роботы'] > 0],
                                    ['битый код страницы: адрес собран скриптом сайта', 'у людей, без страницы сайта: битая ссылка снаружи', 'роботы: битая ссылка где-то в сети'],
                                    'посторонние: инъекция или зонд')
            kg = kg.sort_values(['со_страниц_сайта', 'запросов'], ascending=False)
    c._constructs = kg
    return kg


def load_security(c, F):
    R, V = c.R, c.V
    S = {}
    st = R['status'].values
    by = R['bytes'].values
    hr = pd.DataFrame({'h': R['ts'].values // 3600, 'g': c.rg.codes, 'b': by}).groupby(['h', 'g']).agg(n=('b', 'size'), mb=('b', 'sum')).reset_index()
    hr['час'] = dt(hr['h'] * 3600); hr['группа'] = c.rg.categories[hr['g']]
    S['Нагрузка по часам'] = hr.pivot_table(index='час', columns='группа', values='n', fill_value=0).reset_index()
    mn = pd.DataFrame({'m': R['ts'].values // 60, 'ip': R['ip'].cat.codes.values, 'e': st >= 500, 'c': st == 499})
    pm = mn.groupby('m').agg(запросов=('ip', 'size'), ошибок_5xx=('e', 'sum'), не_дождались_499=('c', 'sum')).sort_values('запросов', ascending=False).head(30)
    sub = R.loc[np.isin(mn['m'].values, pm.index.values), ['ts', 'ip', 'fam']]
    sub = sub.assign(m=sub['ts'] // 60)
    tops = sub.groupby('m').agg(главный_IP=('ip', lambda s: topn(s.astype(str), 1)), главный_робот=('fam', lambda s: topn(s.astype(str)[s.astype(str) != ''], 1)))
    pm = pm.join(tops)
    pm.index = dt(pm.index * 60)
    S['Пики'] = pm.reset_index().rename(columns={'m': 'минута', 'index': 'минута'})
    w = pd.DataFrame({'гр': c.rg, 'под': c.rsub, 'fam': R['fam'].values, 'page': ~R['is_static'].values, 'b': by})
    who = w.groupby(['гр', 'под', 'fam'], observed=True).agg(запросов=('b', 'size'), страниц=('page', 'sum'), ГБ=('b', lambda s: round(s.sum() / GB, 2))).sort_values('запросов', ascending=False).reset_index()
    S['Кто нагружает'] = who.rename(columns={'гр': 'группа', 'под': 'подгруппа', 'fam': 'семейство'})
    # ловушки: шаблоны с огромным числом вариантов параметров у роботов и ботов
    nb = ~c.human & R['is_page'].values
    tr = R.loc[nb, ['tpl', 'query']]
    trap = tr.groupby('tpl', observed=True)['query'].nunique().sort_values(ascending=False)
    trap = trap[trap >= 500]
    S['Ловушки для роботов'] = trap.reset_index().rename(columns={'tpl': 'шаблон', 'query': 'разных_параметров'})
    for t, n in trap.head(3).items():
        F.add('Нагрузка и безопасность', 'Важно', 'trap', str(t), f'Ловушка для роботов: {t} — {n} вариантов параметров',
              'Роботы обходят комбинации фильтров/сортировок', 'robots.txt / canonical / noindex', 'Закрыть параметры от обхода', int(n), 'Ловушки для роботов')
    ft = pd.DataFrame({'ext': R['ext'].values, 'b': by}).groupby('ext', observed=True).agg(запросов=('b', 'size'), ГБ=('b', lambda s: round(s.sum() / GB, 2))).sort_values('ГБ', ascending=False)
    S['Типы файлов'] = ft.reset_index().rename(columns={'ext': 'расширение'})
    hv = R.loc[R['is_static'].values & (st == 200), ['base', 'bytes']]
    heavy = hv.groupby('base', observed=True)['bytes'].agg(['size', 'sum', 'mean']).sort_values('sum', ascending=False).head(200)
    heavy.columns = ['запросов', 'байт', 'средний']
    heavy['ГБ'] = (heavy['байт'] / GB).round(2); heavy['средний_КБ'] = (heavy['средний'] / KB).round(0)
    S['Тяжёлые файлы'] = heavy[['запросов', 'ГБ', 'средний_КБ']].reset_index().rename(columns={'base': 'файл'})
    big_img = heavy[(heavy['средний'] > 500 * KB) & heavy.index.astype(str).str.contains(r'\.(jpe?g|png|gif|webp)$', case=False)]
    if len(big_img):
        F.add('Нагрузка и безопасность', 'Важно', 'heavy_images', 'site', f'Тяжёлые картинки: {len(big_img)} файлов больше 500 КБ',
              f"Вместе {big_img['ГБ'].sum():.1f} ГБ трафика; пример {big_img.index[0]} ({int(big_img['средний_КБ'].iloc[0])} КБ)", 'контент/вёрстка', 'Сжать, перевести в WebP/AVIF, отдавать по размеру экрана', round(big_img['ГБ'].sum(), 1), 'Тяжёлые файлы')
    sm = R['is_static'].values & c.human
    share304 = (st[sm] == 304).mean() if sm.any() else 0
    hot = R.loc[R['is_static'].values & ~R['ref_internal'].values & (R['ref_host'] != '').values & R['ext'].isin(['jpg', 'jpeg', 'png', 'webp', 'gif']).values, ['ref_host', 'bytes']]
    hot = hot[~hot['ref_host'].astype(str).str.contains(r'yandex|google|bing|ya\.ru|mail\.ru|webvisor|metrika', regex=True)]
    if len(hot):
        S['Хотлинк'] = hot.groupby('ref_host', observed=True)['bytes'].agg(['size', 'sum']).rename(columns={'size': 'запросов', 'sum': 'байт'}).sort_values('байт', ascending=False).head(50).reset_index()
        hk = S['Хотлинк']; big = hk[hk['байт'] >= 50 * 1024 ** 2]
        if len(big):
            dev = big[big['ref_host'].astype(str).str.contains(r'dev|test|stage|staging|demo|local', regex=True)]
            F.add('Нагрузка и безопасность', 'К сведению', 'hotlink', 'site', f'Чужие сайты показывают картинки сайта: {len(big)}',
                  '; '.join(f"{r['ref_host']} — {r['байт'] / 1024 ** 2:.0f} МБ" for _, r in big.head(5).iterrows()) + (f"; тестовые копии: {', '.join(dev['ref_host'].astype(str))}" if len(dev) else ''),
                  'nginx (защита от хотлинка)', 'Запретить отдачу картинок чужим сайтам; тестовой копии — брать картинки со своего сервера', int(big['байт'].sum() / 1024 ** 2), 'Хотлинк')
    # админка
    A = R.loc[R['is_admin'].values, ['ip', 'status', 'method', 'base', 'day', 'nettype', 'cc', 'fam']]
    if len(A):
        ad = A.groupby('ip', observed=True).agg(запросов=('status', 'size'), успешных_200=('status', lambda s: int((s == 200).sum())), POST=('method', lambda s: int((s == 'POST').sum())),
                                               дней=('day', 'nunique'), сеть=('nettype', 'first'), страна=('cc', 'first'), робот=('fam', 'first')).sort_values('запросов', ascending=False).reset_index()
        ad['org'] = c.T.set_index('ip').reindex(ad['ip'].astype(str))['org'].values
        ad['сотрудник'] = ad['ip'].astype(str).isin(c.m.get('staff_ips', []))
        S['Админка'] = ad
        outsiders = ad[~ad['сотрудник'] & (ad['успешных_200'] > 0) & (ad['робот'].astype(str) == '')]
        susp = ad[ad['сотрудник'] & ~ad['страна'].astype(str).isin(['RU', ''])]
        if len(susp):
            F.add('Нагрузка и безопасность', 'Срочно', 'admin_foreign', 'all', 'Успешные входы в админку из-за рубежа', ', '.join(f"{r.ip} ({r.страна}, {r.org})" for r in susp.head(5).itertuples()),
                  'доступ к админке', 'Проверить, свои ли это входы', len(susp), 'Админка')
    # служебные разделы (не админка движка): /manager/, /admin/ и т.п. — форму входа узнаём по поведению (ТЗ, «Служебные разделы и формы входа»)
    gen = R['base'].cat.categories.to_series().str.contains(r'^/(manager|admin|administrator|panel|cp|backend|dashboard|crm|lk-admin)/', regex=True).values[R['base'].cat.codes.values] & ~R['is_admin'].values
    GA = R.loc[gen & ~R['is_static'].values, ['ip', 'base', 'fam', 'day', 'method', 'status', 'bytes']]
    if len(GA):
        staff = set(c.m.get('staff_ips', []))
        GA = GA[~GA['ip'].astype(str).isin(staff)].assign(ip=lambda d: d['ip'].astype(str), base=lambda d: d['base'].astype(str))
        GA['раздел'] = GA['base'].str.extract(r'^(/[^/]+/)')[0]
        SE = {'YandexBot', 'Googlebot', 'Bingbot'}
        rows = []
        for sec_, g in GA.groupby('раздел'):
            root = g[g['base'] == sec_]
            posters = set(root.loc[root['method'] == 'POST', 'ip'])
            fp_src = root[(root['method'] == 'GET') & (root['status'] == 200) & (root['bytes'] > 0) & ~root['ip'].isin(posters)]['bytes']
            fp = float(fp_src.median()) if len(fp_src) else 0.0
            tol = max(300.0, 0.05 * fp)
            r200 = root[(root['status'] == 200) & (root['bytes'] > 0)]
            logged = set(r200.loc[(r200['bytes'] - fp).abs() > tol, 'ip']) if fp else set()
            pr = root[root['method'] == 'POST']
            fail = pr[(pr['status'] == 200) & ((pr['bytes'] - fp).abs() <= tol)] if fp else pr.iloc[0:0]
            inner = g[(g['base'] != sec_) & (g['status'] == 200)]
            inner_open = inner[~inner['ip'].isin(logged)]
            if fp:   # движок показывает форму входа прямо на закрытой странице (Битрикс: ?login=yes) — это не «открыто»
                inner_open = inner_open[(inner_open['bytes'] - fp).abs() > tol]
            rows.append(dict(раздел=sec_, ответов_200=int((g['status'] == 200).sum()), IP=g['ip'].nunique(), IP_с_200=g.loc[g['status'] == 200, 'ip'].nunique(),
                             поисковики=int(g.loc[g['status'] == 200, 'fam'].astype(str).isin(SE).sum()),
                             отпечаток_формы_байт=round(fp), POST_входов=len(pr), неудачных=len(fail), адресов_вошло=len(logged),
                             форма_входа='да' if len(pr) else 'не видно', внутренних_без_входа=len(inner_open), адресов_без_входа=inner_open['ip'].nunique(),
                             страницы_без_входа=', '.join(sorted(inner_open['base'].unique())[:5]),
                             кто_без_входа=', '.join(f"{k} — {v}" for k, v in inner_open['fam'].astype(str).replace('', 'не робот').value_counts().head(4).items()), подбор_IP=fail['ip'].nunique(), последний=g['day'].max()))
        sec = pd.DataFrame(rows)
        S['Открытые служебные разделы'] = sec
        for _, r in sec[sec['IP'] >= 5].iterrows():
            nm = r['раздел']
            if r['адресов_без_входа'] >= 3:
                F.add('Нагрузка и безопасность', 'Важно', 'open_section', nm, f"Страницы раздела {nm} отдаются без входа",
                      f"{int(r['внутренних_без_входа'])} ответов 200 для {int(r['адресов_без_входа'])} адресов, которые не входили; кто: {r['кто_без_входа']}; страницы: {r['страницы_без_входа']}",
                      'nginx / настройки доступа', 'Проверить, должны ли эти страницы быть доступны без входа; если нет — закрыть', int(r['адресов_без_входа']), 'Открытые служебные разделы')
            if r['подбор_IP'] >= 10:
                F.add('Нагрузка и безопасность', 'Важно', 'login_bruteforce', nm, f"Подбор пароля к форме входа {nm}",
                      f"{int(r['неудачных'])} неудачных входов с {int(r['подбор_IP'])} адресов", 'настройки защиты', 'Ограничить число попыток входа, закрыть форму по IP', int(r['неудачных']), 'Открытые служебные разделы')
            if r['форма_входа'] == 'да' and r['поисковики']:
                F.add('Нагрузка и безопасность', 'К сведению', 'login_indexed', nm, f"Страница входа {nm} видна поисковикам",
                      f"поисковые роботы открывали её {int(r['поисковики'])} раз; к форме обращались {int(r['IP_с_200'])} адресов", 'robots.txt',
                      f'Закрыть от индексации: Disallow: {nm} в robots.txt', int(r['поисковики']), 'Открытые служебные разделы')
            elif r['форма_входа'] != 'да' and r['адресов_без_входа'] < 3 and r['IP_с_200'] >= 5:
                F.add('Нагрузка и безопасность', 'К сведению', 'open_section_unknown', nm, f"Служебный раздел {nm} отвечает посторонним — проверить, что там",
                      f"{int(r['ответов_200'])} ответов 200 для {int(r['IP_с_200'])} адресов; формы входа по логу не видно", 'настройки доступа', 'Открыть адрес и проверить, что он показывает', int(r['IP']), 'Открытые служебные разделы')
    # служебные файлы и сканеры
    bs = R['base'].cat.categories.to_series()
    vm = bs.str.contains(VULN, regex=True, case=False).values[R['base'].cat.codes.values]
    VQ = R.loc[vm, ['ip', 'base', 'status', 'bytes', 'nettype', 'cc', 'day', 'fam']]
    if len(VQ):
        tgt = pd.Series('Прочее', index=VQ.index)
        for name, rx in reversed(TARGETS):
            tgt[VQ['base'].astype(str).str.contains(rx, regex=True, case=False)] = name
        VQ = VQ.assign(цель=tgt)
        S['Сканеры: что искали'] = VQ.groupby('цель').agg(запросов=('ip', 'size'), IP=('ip', 'nunique'), ответов_200=('status', lambda s: int((s == 200).sum())), коды=('status', lambda s: topn(s, 4))).sort_values('запросов', ascending=False).reset_index()
        got = VQ[(VQ['status'] == 200) & (VQ['bytes'] > 0)]
        if len(got):
            # общий критерий реестра: неоднозначный зонд, который люди или свои получают как обычный адрес, — страница сайта, не утечка
            A_ = getattr(c, 'addr', None)
            if A_ is not None:
                own_ = A_.loc[(A_['зонд'] != 'однозначный') & A_['людям'], 'адрес']
                got = got[~got['base'].astype(str).isin(set(own_))]
            gg = got.groupby('base', observed=True).agg(ответов_200=('ip', 'size'), IP=('ip', 'nunique'), размер=('bytes', 'median'), первый=('day', 'min'), последний=('day', 'max')).sort_values('ответов_200', ascending=False).reset_index()
            # кому отдано: свои (сотрудники) или чужие; у чужих размер сравнивается с частыми ответами соседних адресов
            # (страница входа, заглушка, soft 404). Полный ответ, полученный только своими, — не утечка.
            staff = set(c.m.get('staff_ips', []))
            cats = R['base'].cat.categories
            is_staff = R['ip'].astype(str).isin(staff).values if staff else np.zeros(len(R), bool)
            def verdict(path):
                pc = np.where(cats == path)[0]
                own = np.isin(R['base'].cat.codes.values, pc) & (st == 200) & (R['bytes'].values > 0)
                n_staff, out_sz = int((own & is_staff).sum()), R['bytes'].values[own & ~is_staff]
                d = re.sub(r'[^/]*$', '', str(path))
                idx = np.setdiff1d(np.where(cats.str.startswith(d))[0], pc)
                nb = np.isin(R['base'].cat.codes.values, idx) & (st == 200) & ~is_staff
                freq = pd.Series(R['bytes'].values[nb] // 100 * 100).value_counts()
                freq = [v for v, k in freq.items() if k >= 3 and v > 0][:5]
                if not len(out_sz):
                    return n_staff, 0, None, 'полный ответ получили только свои (сотрудники) — утечки нет'
                med = float(np.median(out_sz))
                if any(abs(med - f) <= max(200, 0.1 * f) for f in freq):
                    return n_staff, len(out_sz), med, 'чужим отдана страница входа/заглушка (как у соседних адресов)'
                return n_staff, len(out_sz), med, 'ПРОВЕРИТЬ: чужим отдан ответ, не похожий на соседние'
            vv = [verdict(b_) for b_ in gg['base']]
            gg['получили_свои'] = [v[0] for v in vv]; gg['получили_чужие'] = [v[1] for v in vv]
            gg['размер_у_чужих'] = [v[2] for v in vv]; gg['вывод'] = [v[3] for v in vv]
            real = gg[gg['вывод'].str.startswith('ПРОВЕРИТЬ')]
            c.leaks = real   # утечки — для «Файлов» и «Анатомии» в Overview
            if len(real):
                # только утечки: служебные файлы, которые сервер отдал посторонним; заглушки и ответы своим сюда не входят
                S['Утечки служебных файлов'] = real.drop(columns=['вывод']).rename(columns={'base': 'файл'})
                F.add('Нагрузка и безопасность', 'Срочно', 'exposed', 'files', f'Сервер отдал служебные файлы по запросам сканеров ({len(real)} адресов)',
                      ', '.join(real['base'].astype(str).head(8)), 'nginx / права на файлы', 'Проверить каждый адрес и закрыть доступ', len(real), 'Утечки служебных файлов')
        nets = VQ.groupby(['ip'], observed=True).agg(запросов=('base', 'size'), сеть=('nettype', 'first'), страна=('cc', 'first'), дней=('day', 'nunique')).sort_values('запросов', ascending=False).reset_index()
        nets['org'] = c.T.set_index('ip').reindex(nets['ip'].astype(str))['org'].values
        S['Сканеры: IP'] = nets.head(300)
    # атаки в параметрах
    qc = R['query'].cat.categories.to_series()
    am = qc.str.contains(ATTACK, regex=True).values[R['query'].cat.codes.values] | vm & bs.str.contains(ATTACK, regex=True).values[R['base'].cat.codes.values]
    AQ = R.loc[am, ['ip', 'base', 'query', 'status', 'bytes', 'day']]
    if len(AQ):
        S['Атаки в параметрах'] = AQ.assign(запрос=AQ['query'].astype(str).str.slice(0, 200)).groupby(['base', 'status'], observed=True).agg(запросов=('ip', 'size'), IP=('ip', 'nunique'), адрес=('ip', 'first'), пример=('запрос', 'first')).sort_values('запросов', ascending=False).reset_index().head(300)
        a5 = AQ[AQ['status'] >= 500]
        if len(a5):
            F.add('Нагрузка и безопасность', 'Срочно', 'attack_500', 'params', f'Атаки через параметры вызвали 500 ({len(a5)} раз)',
                  ', '.join(a5['base'].astype(str).unique()[:5]), 'код сайта', 'Проверить обработку параметров на этих адресах', len(a5), 'Атаки в параметрах')
    # подозрительные исполняемые файлы в папках загрузок
    sx = bs.str.contains(r'^/(upload|uploads|wp-content/uploads|files|images|media)/.*\.(php\d?|phtml|asp|aspx|jsp|cgi|pl)$', regex=True, case=False).values[R['base'].cat.codes.values]
    SX = R.loc[sx & (st == 200), ['ip', 'base', 'method', 'day']]
    if len(SX):
        S['Подозрительные файлы'] = SX.groupby('base', observed=True).agg(ответов_200=('ip', 'size'), IP=('ip', 'nunique'), POST=('method', lambda s: int((s == 'POST').sum())), первый=('day', 'min')).reset_index()
        F.add('Нагрузка и безопасность', 'Срочно', 'webshell', 'files', 'Исполняемые файлы в папке загрузок отвечают 200 — признак веб-шелла',
              ', '.join(SX['base'].astype(str).unique()[:5]), 'сервер / файлы сайта', 'Срочно проверить файлы на сервере', int(SX['base'].nunique()), 'Подозрительные файлы')
    kg = constructs(c)   # конструкты — все, со всеми выводами (битый код сайта — ещё и в «Ошибках»)
    if len(kg): S['Конструкты в адресах'] = kg.head(500).rename(columns={'адрес': 'Адрес', 'запросов': 'Запросов', 'люди': 'Люди', 'роботы': 'Роботы', 'со_страниц_сайта': 'Со страниц сайта',
                                                                       'коды': 'Коды', 'страница': 'Страница-источник', 'вывод': 'Вывод'})
    # живой человек, который систематически исследует сайт (actors.json): разовый — просто не человек-посетитель, регулярный — отдельное предупреждение
    hv = c.V[c.V['subgroup'].astype(str).str.startswith('человек-исследователь, регулярно')]
    if len(hv):
        hr = hv.groupby(['ip', 'ua'], observed=True).agg(визитов=('n_req', 'size'), дней=('day', 'nunique'), первый=('day', 'min'), последний=('day', 'max'),
                                                       сеть=('nettype', 'first'), страна=('cc', 'first'), признак=('subgroup', 'first')).reset_index()
        hr['признак'] = hr['признак'].str.split(': ', n=1).str[1]
        tried = R.loc[R['vid'].isin(hv.index) & vm, ['ip', 'base']].astype(str).groupby('ip')['base'].agg(lambda s: ', '.join(pd.unique(s)[:6]))
        hr['что_пробовал'] = hr['ip'].astype(str).map(tried).fillna('')
        S['Исследователи сайта'] = hr.drop(columns='ua').sort_values('дней', ascending=False)
        F.add('Нагрузка и безопасность', 'Важно', 'human_prober', 'actors', f'Человек систематически исследует сайт ({hr["ip"].nunique()} адресов)',
              '; '.join(f"{r['ip']} — {r['дней']} дн., {r['первый']}…{r['последний']}: {r['что_пробовал'] or r['признак']}" for _, r in hr.head(5).iterrows()),
              'сервер / настройки защиты', 'Проверить, кто это (свой разработчик или посторонний); постороннего ограничить по IP', int(hr['ip'].nunique()), 'Исследователи сайта')
    tok = qc.str.contains(r'(?i)(?:^|&)(sessid|phpsessid|token|access_token|api_key|apikey|key|password|passwd)=', regex=True).values[R['query'].cat.codes.values]
    if tok.sum():
        S['Токены в адресах'] = R.loc[tok, ['base', 'query']].assign(параметр=lambda d: d['query'].astype(str).str.extract(r'(?i)((?:sessid|phpsessid|token|access_token|api_key|apikey|key|password|passwd))=')[0]).groupby(['base', 'параметр'], observed=True).size().sort_values(ascending=False).head(100).reset_index(name='запросов')
    # флуд и работа защиты
    fl = mn.groupby(['m', 'ip']).size().sort_values(ascending=False).head(30).reset_index(name='запросов_в_минуту')
    fl['минута'] = dt(fl['m'] * 60); fl['ip'] = R['ip'].cat.categories[fl['ip']]
    S['Флуд'] = fl[['минута', 'ip', 'запросов_в_минуту']]
    s = {'Трафик, ГБ': round(by.sum() / GB, 1), 'Пик запросов в минуту': int(pm['запросов'].max()) if len(pm) else 0,
         'Доля 304 у статики (кэш), %': round(share304 * 100, 1), 'Запросов сканеров': int(vm.sum()),
         'Доля вредных запросов, получивших 200, %': round((st[vm] == 200).mean() * 100, 1) if vm.any() else 0}
    return S, s


# ======================= БОТЫ =======================
def bots(c, F, check_ips=()):
    R, V = c.R, c.V
    S = {}
    T = c.T.set_index('ip')
    rb = V[V['fam'] != '']
    # объявленные роботы по семействам
    rr = R.loc[c.declared, ['fam', 'fam_cat', 'ip', 'day', 'bytes', 'status', 'asn', 'fam_verified', 'base', 'is_static']]
    if len(rr):
        g = rr.groupby('fam', observed=True)
        fam = pd.DataFrame({'категория': g['fam_cat'].first().astype(str), 'запросов': g.size(), 'IP': g['ip'].nunique(), 'дней': g['day'].nunique(),
                            'МБ': (g['bytes'].sum() / MB).round(1), 'доля_200_%': g['status'].agg(lambda s: round((s == 200).mean() * 100, 1)),
                            '404': g['status'].agg(lambda s: int((s == 404).sum())), '5xx': g['status'].agg(lambda s: int((s >= 500).sum())),
                            'подлинных_%': g['fam_verified'].agg(lambda s: round((s.astype(str) == 'да').mean() * 100, 1) if (s.astype(str) != '').any() else None),
                            'что_смотрел': g['base'].agg(lambda s: topn(s.astype(str).str.extract(r'^(/[^/]*/?)')[0], 3))}).sort_values('запросов', ascending=False)
        S['Роботы: семейства'] = fam.reset_index().rename(columns={'fam': 'семейство'})
        rn = rr.groupby(['fam', 'asn'], observed=True).size().reset_index(name='запросов').sort_values('запросов', ascending=False)
        orgs = c.T.drop_duplicates('asn').set_index('asn')['org']
        rn['сеть'] = rn['asn'].map(orgs)
        S['Роботы: сети'] = rn.head(500).rename(columns={'fam': 'семейство'})
        unk = fam[(fam['категория'].isin(['Мониторинг', 'Прочие боты'])) & (fam['МБ'] >= 100)]
        for f, r in unk.iterrows():
            F.add('Боты', 'Важно', 'unknown_robot', f, f'Неопознанный робот или мониторинг: {f} — на усмотрение оптимизатора',
                  f"{int(r['запросов'])} запросов, {r['МБ']} МБ, {int(r['IP'])} IP; смотрит: {r['что_смотрел']}", 'robots.txt / ограничение частоты', 'Выяснить, чей; если не нужен — ограничить', r['МБ'], 'Роботы: семейства')
        heavy = fam[fam['категория'].isin(['SEO-сервис']) & (fam['запросов'] >= 20000)]
        for f, r in heavy.iterrows():
            F.add('Нагрузка и безопасность', 'Важно', 'heavy_robot', f, f'SEO-робот {f} создаёт заметную нагрузку', f"{int(r['запросов'])} запросов, {r['МБ']} МБ", 'robots.txt (Crawl-delay/Disallow) или nginx', 'Ограничить или запретить', int(r['запросов']), 'Кто нагружает', also=('Боты',))
    # подделки
    fk = V[V['subgroup'] == 'подделки роботов']
    if len(fk):
        fq = fk.groupby('ip').agg(представлялся=('fam', 'first'), запросов=('n_req', 'sum'), визитов=('n_req', 'size'), страна=('cc', 'first'), сеть=('nettype', 'first'), первый=('day', 'min'), последний=('day', 'max')).sort_values('запросов', ascending=False).reset_index()
        fq['org'] = T.reindex(fq['ip'])['org'].values
        S['Подделки'] = fq
        F.add('Боты', 'Важно', 'fake_crawlers', 'all', f"Поддельные поисковые роботы: {fq['ip'].nunique()} IP", f"Представлялись: {topn(fq['представлялся'])}; сети: {topn(fq['org'].astype(str))}",
              'nginx (бан по IP/подсети хостингов)', 'Заблокировать', int(fq['ip'].nunique()), 'Подделки')
    ex = V[V['subgroup'] == 'явные (не браузер)']
    if len(ex):
        S['Явные боты'] = ex.groupby('ua').agg(визитов=('ip', 'size'), IP=('ip', 'nunique'), запросов=('n_req', 'sum'), сети=('nettype', lambda s: topn(s, 2))).sort_values('запросов', ascending=False).head(300).reset_index()
    # маскирующиеся: классы по визиту
    B = V[(V['group'] == 'Боты') | ((V['group'] == 'Люди') & (V['n_goal'] > 0))].copy()
    cls = np.full(len(B), '', dtype=object)
    e404 = (B['entry_status'] == 404) & (B['entry_ref'] == '-')
    cls = np.where((B['n_goal'] > 0) & (B['n_pages'] == 0), 'спам форм: отправка без просмотра страниц', cls)
    cls = np.where((B['n_goal'] > 0) & e404 & (B['n_pages'] <= 4) & (cls == ''), 'спам форм: битый адрес → главная → форма', cls)
    cls = np.where((B['n_goal'] >= 3) & (B['dur'] < 120) & (cls == ''), 'спам форм: пачка отправок', cls)
    cls = np.where((B['n_pages'] >= 10) & (B['n_static'] == 0) & (cls == ''), 'парсер', cls)
    cls = np.where(B['ua'].str.contains('HeadlessChrome|Puppeteer|Playwright|PhantomJS|Lightpanda', regex=True) & (cls == ''), 'headless', cls)
    cls = np.where((B['subgroup'] == 'маскирующиеся: без загрузки ресурсов') & (cls == ''), 'без загрузки ресурсов', cls)
    B['класс'] = cls
    B = B[B['класс'] != '']
    if len(B):
        S['Боты: классы'] = B.groupby('класс').agg(визитов=('ip', 'size'), IP=('ip', 'nunique'), отправок=('n_goal', 'sum'), принято=('n_conv', 'sum'), сети=('nettype', lambda s: topn(s, 3))).reset_index()
        spam = B[B['класс'].str.startswith('спам')]
        if len(spam):
            sv = spam[['ip', 'класс', 'start', 'entry', 'entry_status', 'n_pages', 'n_static', 'n_goal', 'n_conv', 'nettype', 'cc', 'ua']].copy()
            sv['org'] = T.reindex(sv['ip'])['org'].values
            sv['начало'] = dt(sv['start'])
            S['Спам форм: визиты'] = sv.drop(columns='start').sort_values('начало')
    # операторы: связываем IP спама форм по уликам (см. operators.py); таблица улик — отдельным листом
    spam_ips = set(V.loc[V['subgroup'].str.startswith('спам форм'), 'ip'])
    comp, recon, EV = operators.link(V, spam_ips)
    S['Операторы: улики'] = EV
    ops = []
    k = 0
    for grp in sorted(comp, key=lambda g_: len(g_ & spam_ips), reverse=True):
        gv = V[V['ip'].isin(grp)]
        core = sorted(grp & spam_ips); rc = sorted(grp & recon)
        k += 1
        label = f'Оператор {k}' if len(grp) >= 2 else f'Одиночный спамер {k}'
        ev = EV[(EV['IP_A'].isin(grp) | EV['IP_B'].isin(grp))]
        used = ev[ev['учтена'].str.startswith('да')]
        kinds = Counter(k for x in used['улика'] for k in x.split('; '))
        sp404 = gv[gv['ip'].isin(core) & (gv['entry_status'] == 404)]['entry']
        okey = sp404.value_counts().index[0] if len(sp404) else (core[0] if core else label)
        ops.append(dict(_key=okey, оператор=label, улики=', '.join(f'{t} ({n})' for t, n in kinds.most_common()) or '—',
                        слабые_связи_с_другими=int((~ev['учтена'].str.startswith('да')).sum()), IP_спама=len(core), IP_разведки=len(rc), сети=topn(T.reindex(sorted(grp))['org'].astype(str), 3),
                        дни=', '.join(sorted(gv['day'].unique())[:20]), отправок=int(gv['n_goal'].sum()), принято=int(gv['n_conv'].sum()),
                        битые_входы=', '.join(sorted(set(gv.loc[gv['entry_status'] == 404, 'entry']))[:6]), адреса_спама=', '.join(core), адреса_разведки=', '.join(rc)))
    S['Операторы'] = pd.DataFrame(ops).drop(columns='_key', errors='ignore')
    for o in ops:
        if o['оператор'].startswith('Оператор') and o['отправок'] > 0:
            F.add('Боты', 'Срочно' if o['принято'] else 'Важно', 'operator', o['_key'], f"{o['оператор']}: {o['IP_спама']} IP спама форм" + (f" и {o['IP_разведки']} IP разведки" if o['IP_разведки'] else '') + ', связанных между собой',
                  f"Отправок {o['отправок']}, принято {o['принято']}; дни: {o['дни']}; сети: {o['сети']}; улики: {o['улики']}; общие битые входы: {o['битые_входы']}", 'защита форм + бан хостинговых подсетей', 'Защитить формы, отсеять заявки', o['принято'], 'Операторы')
    # сети ботов
    bv = V[V['group'] == 'Боты']
    bn = bv.groupby(['asn', 'nettype']).agg(визитов=('ip', 'size'), IP=('ip', 'nunique'), подгруппы=('subgroup', lambda s: topn(s, 2))).sort_values('IP', ascending=False).reset_index()
    bn['сеть'] = bn['asn'].map(c.T.drop_duplicates('asn').set_index('asn')['org'])
    bn['что_делать_с_адресами'] = bn['nettype'].map({'хостинг/облако': 'можно банить подсетью', 'VPN/прокси-релей': 'только по поведению', 'мобильный оператор': 'не банить',
                                                    'RU провайдер доступа': 'только по поведению', 'зарубежный провайдер доступа': 'по аудитории сайта'}).fillna('по ситуации')
    S['Бот-сети'] = bn.head(300)
    # проверка присланных IP
    if check_ips:
        rows = []
        for ip in check_ips:
            vv = V[V['ip'] == ip]
            t = T.reindex([ip]).iloc[0]
            if not len(vv):
                rows.append(dict(ip=ip, в_логе='нет', сеть=t['org'], страна=t['cc']))
                continue
            rows.append(dict(ip=ip, в_логе='да', сеть=t['org'], страна=t['cc'], тип_сети=t['nettype'], визитов=len(vv), запросов=int(vv['n_req'].sum()), группа=topn(vv['group'] + ' ' + vv['subgroup'], 2),
                             отправок=int(vv['n_goal'].sum()), принято=int(vv['n_conv'].sum()), первый=dt(vv['start'].min()), последний=dt(vv['end'].max()), входы=topn(vv['entry'], 3), UA=topn(vv['ua'].str.slice(0, 60), 2)))
        S['Проверка IP'] = pd.DataFrame(rows)
    # ИИ-роботы
    ai = R['fam_cat'].isin([x for x in R['fam_cat'].cat.categories if str(x).startswith('ИИ')]).values
    if ai.any():
        A = R.loc[ai, ['fam', 'fam_cat', 'ip', 'base', 'status', 'bytes', 'fam_verified', 'day']]
        g = A.groupby(['fam_cat', 'fam'], observed=True)
        S['ИИ-роботы'] = pd.DataFrame({'запросов': g.size(), 'IP': g['ip'].nunique(), 'дней': g['day'].nunique(), 'МБ': (g['bytes'].sum() / MB).round(1),
                                       'ошибок': g['status'].agg(lambda s: int((s >= 400).sum())), 'подлинных_%': g['fam_verified'].agg(lambda s: round((s.astype(str) == 'да').mean() * 100) if (s.astype(str) != '').any() else None),
                                       'что_читал': g['base'].agg(lambda s: topn(s.astype(str), 3))}).reset_index().rename(columns={'fam_cat': 'назначение', 'fam': 'робот'})
        uf = A[A['fam_cat'].astype(str) == 'ИИ: запрос пользователя']
        if len(uf):
            S['ИИ: страницы по запросам людей'] = uf.groupby(['base', 'fam'], observed=True).agg(запросов=('ip', 'size'), дней=('day', 'nunique')).sort_values('запросов', ascending=False).reset_index().head(200)
    aich = c.H[c.H['channel'] == 'ИИ-ассистенты']
    s = {'Визитов ботов': int(len(bv)), 'IP ботов': int(bv['ip'].nunique()), 'Семейств объявленных роботов': int(rb['fam'].nunique()),
         'Подделок роботов (IP)': int(fk['ip'].nunique()) if len(fk) else 0, 'Операторов (связанных групп IP)': len(ops),
         'Запросов ИИ-роботов': int(ai.sum()), 'Визитов людей из ИИ-ассистентов': int(len(aich))}
    return S, s


# ======================= МАРКЕТИНГ =======================
def parse_ad(q):
    d = {}
    for kv in q.split('&'):
        if '=' in kv:
            k, v = kv.split('=', 1)
            d[k.lower()] = v
    out = {'utm_source': d.get('utm_source', ''), 'utm_medium': d.get('utm_medium', ''), 'кампания': d.get('utm_campaign', ''), 'фраза': d.get('utm_term', '')}
    uc = d.get('utm_content', '')
    for part in re.split(r'\||%7C', uc):
        if '.' in part:
            k, v = part.split('.', 1)
            out[k] = v
    ct = d.get('calltouch_tm', '')
    for part in ct.split('_'):
        if ':' in part:
            k, v = part.split(':', 1)
            out.setdefault({'c': 'cid', 'gb': 'gid', 'ad': 'aid', 'ph': 'pid', 'st': 'source_type', 'pt': 'position_type', 's': 'source', 'dt': 'device', 'reg': 'region'}.get(k, 'ct_' + k), v)
    if 'cid' in out and not out['кампания']:
        out['кампания'] = out['cid']
    out['макрос_не_подставлен'] = '{' in q or '%7B' in q
    return out


def placement_type(src, system_source):
    s = (src or '').lower()
    if system_source == 'search' or s in ('none', ''):
        return 'Поиск' if system_source in ('search', '') else 'не указано'
    parts = s.split('.')
    tlds = {'ru', 'com', 'net', 'org', 'su', 'рф', 'info', 'io', 'tv', 'me', 'pro', 'online', 'site', 'xyz', 'by', 'kz', 'ua', 'app', 'media', 'top', 'ai', 'cc', 'de'}
    if len(parts) >= 2 and parts[-1] in tlds and parts[0] not in tlds:
        return 'РСЯ: сайты'
    if re.match(r'^(ru|com)\.yandex|^ru\.kinopoisk|edadeal|^ru\.beru', s):
        return 'РСЯ: приложения Яндекса'
    return 'РСЯ: сторонние приложения'


def marketing(c, F):
    R, V, H = c.R, c.V, c.H
    S = {}
    # каналы подробно (люди)
    def stats(df):
        return pd.Series({'визитов': len(df), 'IP': df['ip'].nunique(), 'страниц_на_визит': round(df['n_pages'].mean(), 2),
                          'мгновенный_уход_%': round(((df['n_pages'] <= 1) & (df['dur'] < 10)).mean() * 100, 1), 'смотрели_каталог_%': round((df['n_catalog'] > 0).mean() * 100, 1),
                          'отправок': int(df['n_goal'].sum()), 'принято': int(df['n_conv'].sum()), 'конверсия_%': round(df['n_conv'].sum() / max(1, len(df)) * 100, 3)})
    S['Каналы подробно'] = H.groupby(['channel', 'channel_sub']).apply(stats).reset_index().sort_values('визитов', ascending=False).rename(columns={'channel': 'канал', 'channel_sub': 'источник'})
    # воронки по целям
    gp = (R['goal'] != '').values
    P = R.loc[gp & c.human, ['goal', 'goal_success', 'vid']]
    emb = set(e['шаблон'] for e in c.m.get('embedded_templates', []))
    fun = []
    for gname, g in P.groupby('goal', observed=True):
        tplname = str(gname).split('?')[0]
        preloaded = tplname in emb
        fun.append(dict(цель=gname, визитов_людей=len(H), открыли_форму='не считается: форма грузится с каждой страницей' if preloaded else '', отправили_визитов=g['vid'].nunique(),
                        отправок=len(g), принято=int(g['goal_success'].sum())))
    S['Воронки'] = pd.DataFrame(fun).sort_values('принято', ascending=False) if fun else pd.DataFrame()
    # разрезы конверсии
    cut = {}
    bt = R[['base', 'tpl']].drop_duplicates('base')
    tplmap = dict(zip(bt['base'].astype(str), bt['tpl'].astype(str)))
    H2 = H.assign(вход_шаблон=H['entry'].map(tplmap).fillna(H['entry']),
                  устройство=np.where(H['ua_mobile'], 'мобильные', 'десктоп'), браузер_приложения=np.where(H['ua_webview'], 'встроенный браузер приложения', 'обычный браузер'))
    first_seen = H.groupby('ip')['start'].transform('min')
    H2['визит'] = np.where(H2['start'] > first_seen, 'повторный', 'первый')
    for col, name in [('устройство', 'Устройства'), ('браузер_приложения', 'Встроенные браузеры'), ('hour', 'Часы'), ('weekday', 'Дни недели'), ('визит', 'Новые и повторные')]:
        cut[name] = H2.groupby(col).apply(stats).reset_index()
    ent = H2.groupby('вход_шаблон').apply(stats).reset_index().sort_values('визитов', ascending=False).head(200)
    cut['Страницы входа'] = ent
    S.update({f'Конверсии: {k}': v for k, v in cut.items()})
    # очистка по каналам
    allv = V[V['channel'].notna()]
    cl = allv.groupby('channel').agg(визитов_всех=('ip', 'size'), из_них_людей=('group', lambda s: int((s == 'Люди').sum())), ботов=('group', lambda s: int((s == 'Боты').sum())),
                                     просмотров_до_очистки=('n_pages_raw', 'sum'), просмотров_после=('n_pages', 'sum'), двойных_загрузок=('n_dup', 'sum'), редиректов=('n_redirect', 'sum'))
    cl['доля_ботов_%'] = (cl['ботов'] / cl['визитов_всех'] * 100).round(1)
    S['Качество и очистка по каналам'] = cl.reset_index().rename(columns={'channel': 'канал'})
    # органика
    org = H[H['channel'] == 'Поиск']
    if len(org):
        S['Органика'] = org.groupby(['channel_sub', 'day']).size().unstack('channel_sub', fill_value=0).reset_index()
    # реклама
    AD = H[H['channel'] == 'Реклама'].copy()
    Vall_ad = V[V['channel'] == 'Реклама']
    s = {'Визитов людей': int(len(H)), 'Из рекламы': int(len(AD)), 'Из поиска': int((H['channel'] == 'Поиск').sum()),
         'Конверсия рекламы, %': round(AD['n_conv'].sum() / max(1, len(AD)) * 100, 3), 'Конверсия поиска, %': round(org['n_conv'].sum() / max(1, len(org)) * 100, 3) if len(org) else 0}
    if len(AD):
        pa = pd.DataFrame([parse_ad(q) for q in AD['entry_query']], index=AD.index)
        AD = AD.join(pa)
        AD['тип_площадки'] = [placement_type(src, st_) for src, st_ in zip(AD.get('source', pd.Series('', index=AD.index)).fillna(''), AD.get('source_type', pd.Series('', index=AD.index)).fillna(''))]
        AD.loc[AD['channel_sub'] != 'Яндекс Директ', 'тип_площадки'] = AD['channel_sub']
        S['Реклама: системы и типы площадок'] = AD.groupby(['channel_sub', 'тип_площадки']).apply(stats).reset_index().rename(columns={'channel_sub': 'система'})
        for col, name in [('кампания', 'Кампании'), ('aid', 'Объявления'), ('фраза', 'Фразы'), ('source', 'Площадки'), ('region', 'Регионы'), ('device', 'Устройства (метка)')]:
            if col in AD:
                t = AD.groupby(col).apply(stats).reset_index().sort_values('визитов', ascending=False)
                if col == 'source':
                    t['тип'] = [placement_type(x, '') for x in t[col]]
                S[f'Реклама: {name}'] = t.head(1000)
        AD['час'] = AD['hour']
        S['Реклама: часы'] = AD.groupby('час').apply(stats).reset_index()
        if 'source' in AD:
            pl = AD.groupby('source').apply(stats)
            off = pl[(pl['визитов'] >= 30) & (pl['принято'] == 0)].copy()
            off['почему'] = [f"{int(r['визитов'])} визитов, 0 заявок, уход сразу {r['мгновенный_уход_%']}%, каталог смотрели {r['смотрели_каталог_%']}%" for _, r in off.iterrows()]
            off = off.sort_values('визитов', ascending=False).reset_index()
            off['тип'] = [placement_type(x, '') for x in off['source']]
            S['Площадки к отключению'] = off[off['source'].astype(str).str.lower() != 'none'][['source', 'тип', 'визитов', 'почему']]
            if len(S['Площадки к отключению']):
                F.add('Маркетинг', 'Важно', 'placements_off', 'list', f"{len(S['Площадки к отключению'])} площадок с заметным трафиком и без заявок",
                      f"Вместе {int(S['Площадки к отключению']['визитов'].sum())} визитов; крупнейшие: {', '.join(S['Площадки к отключению']['source'].astype(str).head(5))}",
                      'рекламный кабинет', 'Проверить и отключить площадки по списку', int(S['Площадки к отключению']['визитов'].sum()), 'Площадки к отключению')
        tp = S['Реклама: системы и типы площадок']
        base_cr = org['n_conv'].sum() / max(1, len(org)) if len(org) else 0
        for _, r in tp.iterrows():
            cr = r['принято'] / max(1, r['визитов'])
            if r['визитов'] >= 1000 and r['принято'] > 0 and base_cr > 0 and cr < base_cr / 10:
                F.add('Маркетинг', 'Важно', 'placement_type_low', f"{r['система']}:{r['тип_площадки']}", f"{r['система']} / {r['тип_площадки']}: конверсия в {base_cr / max(cr, 1e-9):.0f} раз ниже, чем у поиска",
                      f"{int(r['визитов'])} визитов, {int(r['принято'])} заявок ({r['конверсия_%']}%); уход сразу {r['мгновенный_уход_%']}%", 'рекламный кабинет', 'Сократить бюджет или исключить площадки этого типа', int(r['визитов']), 'Реклама: системы и типы площадок')
        for _, r in tp.iterrows():
            if r['визитов'] >= 1000 and r['принято'] == 0:
                F.add('Маркетинг', 'Важно', 'placement_type_zero', f"{r['система']}:{r['тип_площадки']}", f"{r['система']} / {r['тип_площадки']}: {int(r['визитов'])} визитов и 0 заявок",
                      f"Уход сразу {r['мгновенный_уход_%']}%, каталог смотрели {r['смотрели_каталог_%']}%", 'рекламный кабинет', 'Сократить или отключить этот тип площадок', int(r['визитов']), 'Реклама: системы и типы площадок')
        if 'кампания' in AD:
            kc = S['Реклама: Кампании']
            for _, r in kc[(kc['визитов'] >= 2000) & (kc['принято'] == 0)].head(5).iterrows():
                F.add('Маркетинг', 'Важно', 'campaign_zero', str(r['кампания']), f"Кампания {r['кампания']}: {int(r['визитов'])} визитов и 0 заявок",
                      f"Уход сразу {r['мгновенный_уход_%']}%", 'рекламный кабинет', 'Разобрать площадки и настройки кампании', int(r['визитов']), 'Реклама: Кампании')
        # посадочные
        lp = AD.assign(посадочная=AD['entry']).groupby(['посадочная', 'entry_status']).apply(stats).reset_index().sort_values('визитов', ascending=False)
        S['Реклама: посадочные'] = lp.head(500)
        lerr = AD[AD['entry_status'] >= 400]
        if len(lerr):
            F.add('Маркетинг', 'Срочно', 'ad_landing_errors', 'all', f'Реклама ведёт на страницы с ошибкой: {len(lerr)} кликов',
                  f"Коды {topn(lerr['entry_status'])}; адреса: {', '.join(lerr['entry'].value_counts().index[:5])}", 'рекламный кабинет / сайт', 'Исправить ссылки в объявлениях или страницы', len(lerr), 'Реклама: посадочные', also=('Ошибки',))
        mac = AD[AD['макрос_не_подставлен']] if 'макрос_не_подставлен' in AD else []
        lab = []
        if len(mac): lab.append(dict(проблема='Макрос не подставился ({...} в адресе)', кликов=len(mac), пример=mac['entry_query'].iloc[0][:200]))
        noutm = AD[(AD['entry_query'].str.contains('yclid=')) & ~AD['entry_query'].str.contains('utm_')]
        if len(noutm): lab.append(dict(проблема='yclid без UTM-меток', кликов=len(noutm), пример=noutm['entry_query'].iloc[0][:200]))
        S['Метки: проблемы'] = pd.DataFrame(lab)
        if (len(mac) >= 10) or (len(noutm) >= 50):
            F.add('Маркетинг', 'Важно', 'broken_labels', 'all', 'Рекламные метки сломаны',
                  '; '.join(f"{x['проблема']} — {x['кликов']} кликов" for x in lab), 'рекламный кабинет', 'Проверить шаблон отслеживания в кампаниях', int(len(mac) + len(noutm)), 'Метки: проблемы')
        # боты в оплачиваемом трафике
        bad = Vall_ad[Vall_ad['group'] == 'Боты']
        s['Доля ботов в рекламном трафике, %'] = round(len(bad) / max(1, len(Vall_ad)) * 100, 1)
    return S, s
