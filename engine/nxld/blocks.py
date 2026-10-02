"""NXLD: расчёт блоков. Каждый блок возвращает (листы: {имя: DataFrame}, сводка: {метрика: значение}) и пишет черновые проблемы."""
import re
from collections import Counter, defaultdict
import numpy as np, pandas as pd
from .recon import mask_pd

KB, MB, GB = 1024, 1024 ** 2, 1024 ** 3
VULN = r'(^/\.env|/\.git/|/\.aws|/\.ssh|/\.svn|/\.DS_Store|phpinfo|/wp-login\.php|/wp-admin|/xmlrpc\.php|/wp-content/plugins|/phpmyadmin|/pma/|/adminer|/vendor/phpunit|/actuator|/cgi-bin/|/server-status|/config\.(json|yml|yaml|php)|/backup|\.(sql|bak|old|swp|tar|tar\.gz|tgz|zip|rar)$|/shell|/eval-stdin|/boaform|/HNAP1|/owa/|/autodiscover|/\.well-known/(?!acme)|/restore\.php|/bitrixsetup\.php|/install\.php|/setup\.php|/telescope|/_profiler|/debug|/console)'


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
def overview(c, F):
    R, V, H = c.R, c.V, c.H
    S = {}
    grp = V.groupby(['group', 'subgroup']).agg(визитов=('n_req', 'size'), IP=('ip', 'nunique'), запросов=('n_req', 'sum'), ГБ=('bytes', lambda s: round(s.sum() / GB, 2))).reset_index()
    grp.columns = ['группа', 'подгруппа', 'визитов', 'IP', 'запросов', 'ГБ']
    S['Люди и боты'] = grp
    D = V.pivot_table(index='day', columns='group', values='n_req', aggfunc='size', fill_value=0)
    D['конверсий людей'] = H.groupby('day')['n_conv'].sum()
    D['конверсий ботов'] = V[V['group'] == 'Боты'].groupby('day')['n_conv'].sum()
    D['конверсий своих'] = V[V['group'] == 'Свои'].groupby('day')['n_conv'].sum()
    D = D.fillna(0).astype(int).reset_index().rename(columns={'day': 'день'})
    S['По дням'] = D
    ch = H.groupby('channel').agg(визитов=('n_req', 'size'), IP=('ip', 'nunique'), конверсий=('n_conv', 'sum')).sort_values('визитов', ascending=False)
    ch['доля_визитов_%'] = (ch['визитов'] / ch['визитов'].sum() * 100).round(1)
    ch['конверсия_%'] = (ch['конверсий'] / ch['визитов'] * 100).round(2)
    S['Каналы'] = ch.reset_index().rename(columns={'channel': 'канал'})
    hp = R.loc[c.human & R['is_page'].values, ['base', 'tpl', 'vid', 'ip']]
    sec = hp.assign(раздел=hp['base'].astype(str).str.extract(r'^(/[^/]*/?)')[0]).groupby('раздел').agg(просмотров=('vid', 'size'), визитов=('vid', 'nunique'), IP=('ip', 'nunique')).sort_values('визитов', ascending=False)
    S['Разделы'] = sec.head(100).reset_index()
    tp = hp.groupby('tpl', observed=True).agg(просмотров=('vid', 'size'), визитов=('vid', 'nunique'), IP=('ip', 'nunique'), адресов=('base', 'nunique')).sort_values('визитов', ascending=False)
    S['Шаблоны страниц'] = tp.head(200).reset_index().rename(columns={'tpl': 'шаблон'})
    # спрос: элементы каталога
    cat = c.m.get('catalog_templates', [])
    if cat:
        ci = R.loc[c.human & R['is_catalog'].values, ['base', 'tpl', 'ip']]
        dem = ci.groupby(['tpl', 'base'], observed=True)['ip'].nunique().sort_values(ascending=False).head(500).reset_index()
        dem.columns = ['шаблон', 'элемент', 'людей']
        S['Спрос'] = dem
    # фильтры и поиск по сайту
    q = R.loc[c.human & R['is_page'].values, ['query', 'ip', 'base']]
    q = q[q['query'].astype(str) != '']
    if len(q):
        kv = q.assign(p=q['query'].astype(str).str.split('&')).explode('p')
        kv = kv[~kv['p'].str.match(r'(utm_|yclid|gclid|calltouch|etext|ybaip|y_ref|ysclid|erid|_openstat|from=|clear_cache|PAGEN)', na=False)]
        kv['ключ'] = kv['p'].str.split('=').str[0]
        fl = kv.groupby(['ключ', 'p']).agg(применений=('ip', 'size'), людей=('ip', 'nunique')).sort_values('людей', ascending=False).head(300).reset_index().rename(columns={'p': 'значение'})
        S['Фильтры и поиск'] = fl
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
    S['Конверсии'] = P[['время', 'ip', 'goal', 'status', 'принята', 'группа', 'подгруппа', 'канал', 'страниц_до', 'ресурсов_грузил', 'сек_от_входа', 'вход', 'вход_реферер', 'сеть']].rename(columns={'goal': 'цель', 'status': 'код'})
    # GET-отправки персональных данных
    if c.G is not None and len(c.G):
        g = c.G.copy()
        g['запрос'] = g['query'].astype(str).map(mask_pd)
        g['время'] = dt(g['ts'])
        S['GET-отправки'] = g[['время', 'ip', 'base', 'запрос', 'status', 'fam']].head(2000).rename(columns={'base': 'адрес', 'status': 'код', 'fam': 'робот'})
    # сводка
    hv = len(H)
    acc = P[P['goal_success']]
    s = {'Период': f"{c.inv['period'][0]} — {c.inv['period'][1]}", 'Запросов': int(len(R)), 'Визитов всего': int(len(V)),
         'Визитов людей': hv, 'IP людей': int(H['ip'].nunique()), 'Просмотров страниц людьми': int(H['n_pages'].sum()),
         'Отправок целей всего': int(len(P)), 'Принято от людей': int((acc['группа'] == 'Люди').sum()),
         'Принято от ботов': int((acc['группа'] == 'Боты').sum()), 'Принято от своих (тесты)': int((acc['группа'] == 'Свои').sum()),
         'Конверсия людей (визит → принятая цель), %': round((acc['группа'] == 'Люди').sum() / max(1, hv) * 100, 3)}
    for gname in ['Роботы', 'Боты', 'Свои']:
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
    # сбои: минуты с массовыми 5xx у страниц
    page = R['is_page'].values | (R['method'].values == 'POST')
    minute = R['ts'].values // 60
    M = pd.DataFrame({'m': minute, 'p5': page & (st >= 500), 'p': page, 's_ok': R['is_static'].values & (st < 400), 's': R['is_static'].values,
                      'size': R['bytes'].values * page})
    mm = M.groupby('m').agg(p5=('p5', 'sum'), p=('p', 'sum'), s_ok=('s_ok', 'sum'), s=('s', 'sum'))
    bad = mm[(mm['p5'] >= 5) & (mm['p5'] / mm['p'].clip(lower=1) >= 0.5)]
    win = []
    if len(bad):
        idx = bad.index.values
        start = idx[0]; prev = idx[0]
        for x in list(idx[1:]) + [None]:
            if x is None or x - prev > 3:
                seg = mm.loc[start:prev]
                e = c.E
                dbmsg = 0
                if e is not None and len(e):
                    em = e[(e['ts'] >= start * 60) & (e['ts'] <= prev * 60 + 59)]
                    dbmsg = int(em['msg'].str.contains(DB_RX, regex=True).sum())
                    up = int(em['msg'].str.contains('upstream timed out|connect\\(\\) failed', regex=True).sum())
                else:
                    up = 0
                static_ok = seg['s_ok'].sum() / max(1, seg['s'].sum())
                cause = []
                if dbmsg: cause.append(f'база данных ({dbmsg} сообщений)')
                if up: cause.append(f'бэкенд не отвечает/таймаут ({up})')
                if static_ok > 0.9: cause.append('статика отдавалась нормально — падала динамика')
                win.append(dict(начало=dt(start * 60), конец=dt(prev * 60 + 59), минут=int(prev - start + 1), страниц_с_5xx=int(seg['p5'].sum()),
                                доля_5xx_у_страниц=round(seg['p5'].sum() / max(1, seg['p'].sum()), 2), статика_в_норме=round(static_ok, 2), вероятная_причина='; '.join(cause) or 'не определена'))
                if x is not None: start = x
            if x is not None: prev = x
    W = pd.DataFrame(win)
    S['Сбои'] = W
    for _, w in W.iterrows():
        if w['минут'] >= 2:
            F.add('Ошибки', 'Срочно', 'outage', str(w['начало'])[:16], f"Сбой {str(w['начало'])[:16]}–{str(w['конец'])[11:16]}: страницы отдавали 5xx",
                  f"{w['минут']} мин, {w['страниц_с_5xx']} страниц с ошибкой; {w['вероятная_причина']}", 'сервер / база данных', 'Найти причину по логам сервера и базы', int(w['минут']), 'Сбои')
    # 5xx по шаблонам
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
    mr = c.human & (st == 404) & R['is_static'].values
    MR = R.loc[mr, ['base', 'ref_path', 'vid']]
    if len(MR):
        mt = MR.groupby('base', observed=True).agg(запросов=('vid', 'size'), визитов=('vid', 'nunique'), страниц=('ref_path', 'nunique')).sort_values('визитов', ascending=False)
        mt['группа'] = [re.sub(r'[^/]+$', '*', b) if n >= 1 else b for b, n in zip(mt.index.astype(str), mt['запросов'])]
        S['Отсутствующие ресурсы'] = mt.head(500).reset_index().rename(columns={'base': 'файл'})
        mg = mt.groupby('группа').agg(файлов=('запросов', 'size'), запросов=('запросов', 'sum'), визитов=('визитов', 'max')).sort_values('запросов', ascending=False)
        for gname, r in mg.head(5).iterrows():
            if r['визитов'] >= 100:
                F.add('Ошибки', 'Важно', 'missing_static', gname, f'Отсутствующие файлы, которые запрашивают страницы: {gname}',
                      f"{int(r['файлов'])} файлов, {int(r['запросов'])} запросов людей", 'код/вёрстка сайта', 'Вернуть файлы или убрать ссылки на них из шаблона', int(r['запросов']), 'Отсутствующие ресурсы')
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
                if re.fullmatch(r'/(robots\.txt|sitemap\.xml)', str(b)) and (g['status'] == 404).mean() > 0.9:
                    F.add('Ошибки', 'К сведению', 'no_service', str(b), f'На сайте нет {b}', f"{len(g)} запросов, все получили 404", 'сайт', f'Создать {b}', len(g), 'Служебные файлы')
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
        se = SE.assign(ошибка=SE['status'] >= 400).groupby(['fam', 'tpl'], observed=True).agg(запросов=('status', 'size'), ошибок=('ошибка', 'sum')).reset_index()
        se = se[se['ошибок'] > 0].sort_values('ошибок', ascending=False)
        S['Ошибки у поисковиков'] = se.head(300).rename(columns={'fam': 'робот', 'tpl': 'шаблон'})
        share = (SE['status'] >= 400).mean()
        if share > 0.05:
            F.add('Ошибки', 'Важно', 'search_errors', 'all', f'Поисковые роботы получают ошибки: {share*100:.1f}% запросов',
                  f"Главные шаблоны: {', '.join(se.head(5)['шаблон'].astype(str))}", 'код сайта / редиректы', 'Убрать из индекса или исправить', round(share * 100, 1), 'Ошибки у поисковиков')
    # реклама: посадочные с ошибками
    ad = H[(H['channel'] == 'Реклама') & (H['entry_status'] >= 400)]
    if len(ad):
        S['Реклама: посадочные с ошибками'] = ad.groupby(['entry', 'entry_status']).agg(кликов=('ip', 'size'), первый=('day', 'min'), последний=('day', 'max')).sort_values('кликов', ascending=False).reset_index()
    # мягкие ошибки: одинаковый размер ответа на множестве разных адресов
    pg = R.loc[R['is_page'].values & (st == 200), ['base', 'bytes']]
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
    PB = R.loc[blk & (c.human | c.search_ok | (R['fam'] == 'YaDirectFetcher').values), ['day', 'status', 'nettype', 'cc', 'ua_webview', 'base', 'fam']]
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
    s = {'Доля ошибок у людей, %': round(((st >= 400) & c.human & page).sum() / max(1, (c.human & page).sum()) * 100, 2),
         '5xx у людей': int(((st >= 500) & c.human).sum()), 'Окон сбоев': int(len(W)),
         'Визитов людей со входом на 404': int(len(e404)), 'Битых переходов внутри сайта': int(bl.sum())}
    return S, s


# ======================= НАГРУЗКА И БЕЗОПАСНОСТЬ =======================
ATTACK = r"(?i)(union(\s|%20|\+)+select|'(\s|%20|\+)*or(\s|%20|\+)*'?1'?=|sleep\(|benchmark\(|<script|%3Cscript|javascript:|\.\./|%2e%2e%2f|\$\{jndi:|/etc/passwd|cmd=|exec\(|base64_decode|wget(\s|%20)http|curl(\s|%20)http)"
TARGETS = [('WordPress', r'wp-|xmlrpc'), ('Утечки конфигов (.env, .git, ключи)', r'\.env|\.git|\.aws|\.ssh|\.svn|config\.'), ('Бэкапы и архивы', r'backup|\.(sql|bak|old|tar|tgz|zip|rar)$'),
           ('Панели БД и админки', r'phpmyadmin|pma|adminer|/admin'), ('Отладка и фреймворки', r'phpinfo|actuator|telescope|_profiler|debug|console|phpunit'),
           ('Установщики Битрикс', r'restore\.php|bitrixsetup|install\.php|setup\.php'), ('Роутеры/IoT/почта', r'boaform|HNAP|owa|autodiscover|cgi-bin'), ('Прочее', r'.')]


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
    # служебные разделы, открытые всем (не админка движка): /manager/, /admin/ и т.п.
    gen = R['base'].cat.categories.to_series().str.contains(r'^/(manager|admin|administrator|panel|cp|backend|dashboard|crm|lk-admin)/', regex=True).values[R['base'].cat.codes.values] & ~R['is_admin'].values
    GA = R.loc[gen & (st == 200) & ~R['is_static'].values, ['ip', 'base', 'fam', 'day']]
    if len(GA):
        staff = set(c.m.get('staff_ips', []))
        GA = GA[~GA['ip'].astype(str).isin(staff)]
        sec = GA.assign(раздел=GA['base'].astype(str).str.extract(r'^(/[^/]+/)')[0]).groupby('раздел').agg(ответов_200=('ip', 'size'), IP=('ip', 'nunique'),
              поисковики=('fam', lambda s: int(s.astype(str).isin(['YandexBot', 'Googlebot', 'Bingbot']).sum())), страниц=('base', 'nunique'), последний=('day', 'max')).reset_index()
        S['Открытые служебные разделы'] = sec
        for _, r in sec[(sec['IP'] >= 5)].iterrows():
            F.add('Нагрузка и безопасность', 'Важно', 'open_section', r['раздел'], f"Служебный раздел {r['раздел']} открыт всем" + (' и индексируется поисковиками' if r['поисковики'] else ''),
                  f"{int(r['ответов_200'])} ответов 200 для {int(r['IP'])} IP, страниц {int(r['страниц'])}; поисковики: {int(r['поисковики'])}", 'nginx / настройки доступа', 'Закрыть паролем или по IP, запретить индексацию', int(r['IP']), 'Открытые служебные разделы')
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
            gg = got.groupby('base', observed=True).agg(ответов_200=('ip', 'size'), IP=('ip', 'nunique'), размер=('bytes', 'median'), первый=('day', 'min'), последний=('day', 'max')).sort_values('ответов_200', ascending=False).reset_index()
            S['Служебные файлы: что отдано'] = gg
            # отбрасываем «200», размер которых совпадает с типичным ответом соседних адресов (страница входа, заглушка, soft 404)
            def typical(path):
                d = re.sub(r'[^/]*$', '', str(path))
                cats = R['base'].cat.categories
                idx = np.where(cats.str.startswith(d))[0]
                mm = np.isin(R['base'].cat.codes.values, idx) & (st == 200) & ~c.human
                return np.median(R['bytes'].values[mm]) if mm.any() else -1
            gg['типичный_размер_рядом'] = [typical(b) for b in gg['base']]
            gg['вывод'] = np.where((gg['типичный_размер_рядом'] > 0) & ((gg['размер'] - gg['типичный_размер_рядом']).abs() <= 0.1 * gg['типичный_размер_рядом']),
                                   'отдана заглушка/страница входа (как у соседних адресов)', 'ПРОВЕРИТЬ: ответ отличается от соседних')
            S['Служебные файлы: что отдано'] = gg
            real = gg[gg['вывод'].str.startswith('ПРОВЕРИТЬ')]
            if len(real):
                F.add('Нагрузка и безопасность', 'Срочно', 'exposed', 'files', f'Сервер отдал служебные файлы по запросам сканеров ({len(real)} адресов)',
                      ', '.join(real['base'].astype(str).head(8)), 'nginx / права на файлы', 'Проверить каждый адрес и закрыть доступ', len(real), 'Служебные файлы: что отдано')
        nets = VQ.groupby(['ip'], observed=True).agg(запросов=('base', 'size'), сеть=('nettype', 'first'), страна=('cc', 'first'), дней=('day', 'nunique')).sort_values('запросов', ascending=False).reset_index()
        nets['org'] = c.T.set_index('ip').reindex(nets['ip'].astype(str))['org'].values
        S['Сканеры: IP'] = nets.head(300)
    # атаки в параметрах
    qc = R['query'].cat.categories.to_series()
    am = qc.str.contains(ATTACK, regex=True).values[R['query'].cat.codes.values] | vm & bs.str.contains(ATTACK, regex=True).values[R['base'].cat.codes.values]
    AQ = R.loc[am, ['ip', 'base', 'query', 'status', 'bytes', 'day']]
    if len(AQ):
        S['Атаки в параметрах'] = AQ.assign(запрос=AQ['query'].astype(str).str.slice(0, 200)).groupby(['base', 'status'], observed=True).agg(запросов=('ip', 'size'), IP=('ip', 'nunique'), пример=('запрос', 'first')).sort_values('запросов', ascending=False).reset_index().head(300)
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
    # операторы: связываем IP спама форм (1) общими битыми входами и (2) сменой IP посреди визита:
    # визит начался со страницы, которую за <= 2 ч до этого открыл другой IP и получил 404 (этот IP — разведка оператора)
    spam_ips = set(V.loc[V['subgroup'].str.startswith('спам форм'), 'ip'])
    sv = V[V['ip'].isin(spam_ips)]
    links = defaultdict(set)
    why = defaultdict(set)
    for ent, g in sv[sv['entry_status'] == 404].groupby('entry'):
        ips = set(g['ip'])
        for i in ips:
            links[i] |= ips - {i}
        if len(ips) > 1: why[frozenset(ips)].add(f'общий битый вход {ent}')
    e404 = V[(V['entry_status'] == 404) & (V['fam_verified'] != 'да')][['ip', 'start', 'entry', 'group']]
    recon = set()
    for _, r in sv[sv['entry_ref_internal']].iterrows():
        pth = re.sub(r'^https?://[^/]+', '', r['entry_ref']).split('?')[0]
        mm = e404[(e404['entry'] == pth) & (e404['ip'] != r['ip']) & (r['start'] - e404['start']).between(0, 7200)]
        for o in mm['ip'].unique():
            links[r['ip']].add(o); links[o].add(r['ip'])
            if o not in spam_ips: recon.add(o)
    # разведка, вошедшая через те же битые адреса, что и спам (если люди на них почти не попадают) — связывает группы
    hum404 = V[(V['group'] == 'Люди') & (V['entry_status'] == 404)].groupby('entry')['ip'].nunique()
    spam_ent = defaultdict(set)
    for _, r in sv[sv['entry_status'] == 404].iterrows():
        spam_ent[r['entry']].add(r['ip'])
    for _, r in e404[e404['ip'].isin(recon)].iterrows():
        if r['entry'] in spam_ent and hum404.get(r['entry'], 0) <= 5:
            for o in spam_ent[r['entry']]:
                links[r['ip']].add(o); links[o].add(r['ip'])
    comp, seen = [], set()
    for i in spam_ips:
        if i in seen: continue
        st_, grp = [i], set()
        while st_:
            x = st_.pop()
            if x in grp: continue
            grp.add(x); st_ += list(links[x] - grp)
        seen |= grp
        comp.append(grp)
    ops = []
    k = 0
    for grp in sorted(comp, key=lambda g_: len(g_ & spam_ips), reverse=True):
        gv = V[V['ip'].isin(grp)]
        core = sorted(grp & spam_ips); rc = sorted(grp & recon)
        k += 1
        label = f'Оператор {k}' if len(grp) >= 2 else f'Одиночный спамер {k}'
        ops.append(dict(оператор=label, IP_спама=len(core), IP_разведки=len(rc), сети=topn(T.reindex(sorted(grp))['org'].astype(str), 3),
                        дни=', '.join(sorted(gv['day'].unique())[:20]), отправок=int(gv['n_goal'].sum()), принято=int(gv['n_conv'].sum()),
                        битые_входы=', '.join(sorted(set(gv.loc[gv['entry_status'] == 404, 'entry']))[:6]), адреса_спама=', '.join(core), адреса_разведки=', '.join(rc)))
    S['Операторы'] = pd.DataFrame(ops)
    for o in ops:
        if o['оператор'].startswith('Оператор') and o['отправок'] > 0:
            F.add('Боты', 'Срочно' if o['принято'] else 'Важно', 'operator', o['битые_входы'][:60], f"{o['оператор']}: {o['IP_спама']} IP спама форм" + (f" и {o['IP_разведки']} IP разведки" if o['IP_разведки'] else '') + ', связанных между собой',
                  f"Отправок {o['отправок']}, принято {o['принято']}; дни: {o['дни']}; сети: {o['сети']}; общие битые входы: {o['битые_входы']}", 'защита форм + бан хостинговых подсетей', 'Защитить формы, отсеять заявки', o['принято'], 'Операторы')
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


def marketing(c, F, control_point=None):
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
        # боты в оплачиваемом трафике
        bad = Vall_ad[Vall_ad['group'] == 'Боты']
        s['Доля ботов в рекламном трафике, %'] = round(len(bad) / max(1, len(Vall_ad)) * 100, 1)
        # до и после контрольной точки
        if control_point:
            cp = pd.Timestamp(control_point).timestamp()
            AD['период'] = np.where(AD['start'] >= cp, 'после', 'до')
            hours = AD.groupby('период')['start'].agg(lambda s: max(1, (s.max() - s.min()) / 3600))
            ba = AD.groupby(['период', 'тип_площадки']).size().unstack('период', fill_value=0)
            for p in ba.columns: ba[f'{p}: кликов в час'] = (ba[p] / hours[p]).round(1)
            S['До и после'] = ba.reset_index()
    return S, s
