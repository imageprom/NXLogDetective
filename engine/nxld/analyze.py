"""NXLD: расчёт выбранных блоков по подготовленным таблицам. Результат — results.pkl (листы, сводки, проблемы)."""
import json, os, pickle, warnings
import numpy as np, pandas as pd
from . import visits, blocks, brief, recon
from .findings import Findings, calibrate

warnings.filterwarnings('ignore')
BLOCKS = ['Общий анализ', 'Ошибки', 'Нагрузка и безопасность', 'Боты', 'Маркетинг']


def cleaning_stats(R, V):
    H = V[V['group'] == 'Люди']
    return {
        'Просмотров у людей до очистки': int(H['n_pages_raw'].sum()), 'Просмотров у людей после очистки': int(H['n_pages'].sum()),
        'Склеено двойных загрузок (повтор адреса ≤ 5 с)': int(H['n_dup'].sum()), 'Склеено редиректов с их целью': int(H['n_redirect'].sum()),
        'Подгрузок форм и блоков (не считаются просмотрами)': int(H['n_embedded'].sum()),
        'Визитов людей во встроенных браузерах приложений': int(H['ua_webview'].sum()),
    }


def important_ips(c, S_bots):
    V, T = c.V, c.T.set_index('ip')
    rows = []
    def add(ips, cat, action):
        for ip in ips:
            vv = V[V['ip'] == ip]
            t = T.loc[ip] if ip in T.index else None
            rows.append(dict(ip=ip, категория=cat, сеть=t['org'] if t is not None else '', ASN=int(t['asn']) if t is not None else 0,
                             страна=t['cc'] if t is not None else '', тип_сети=t['nettype'] if t is not None else '',
                             визитов=len(vv), запросов=int(vv['n_req'].sum()), отправок=int(vv['n_goal'].sum()), принято=int(vv['n_conv'].sum()),
                             первый=blocks.dt(vv['start'].min()) if len(vv) else None, последний=blocks.dt(vv['end'].max()) if len(vv) else None,
                             действие=action if t is None or t['nettype'] in ('хостинг/облако',) else ('проверить/метка' if action.startswith('бан') else action)))
    spam = V[V['subgroup'].str.startswith('спам форм')]['ip'].unique()
    add(spam, 'спам форм', 'бан')
    if 'Подделки' in S_bots: add(S_bots['Подделки']['ip'].astype(str).unique(), 'поддельный робот', 'бан')
    if 'Операторы' in S_bots and len(S_bots['Операторы']):
        rc = set(x for x in ','.join(S_bots['Операторы'].get('адреса_разведки', pd.Series(dtype=str)).fillna('')).replace(' ', '').split(',') if x) - set(spam)
        add(sorted(rc), 'разведка оператора', 'наблюдение')
    add(c.m.get('staff_ips', []), 'свои: сотрудники', 'не трогать')
    add([m_['ip'] for m_ in c.m.get('monitors', [])], 'свои: мониторинг', 'не трогать')
    D = pd.DataFrame(rows, columns=['ip', 'категория', 'сеть', 'ASN', 'страна', 'тип_сети', 'визитов', 'запросов', 'отправок', 'принято', 'первый', 'последний', 'действие']).drop_duplicates('ip')
    return D


def run(workdir, selected=None, check_ips=(), marks=None, prev=None, log=print):
    selected = selected or BLOCKS
    selected = ['Общий анализ', 'Ошибки'] + [b for b in selected if b not in ('Общий анализ', 'Ошибки')]
    log('Загрузка подготовленных таблиц')
    R = pd.read_pickle(os.path.join(workdir, 'R.pkl'))
    V = pd.read_pickle(os.path.join(workdir, 'V.pkl'))
    T = pd.read_pickle(os.path.join(workdir, 'T.pkl'))
    G = pd.read_pickle(os.path.join(workdir, 'G.pkl'))
    E = pd.read_pickle(os.path.join(workdir, 'errors.pkl')) if os.path.exists(os.path.join(workdir, 'errors.pkl')) else pd.DataFrame()
    m = json.load(open(os.path.join(workdir, 'site_map.json')))
    inv = json.load(open(os.path.join(workdir, 'inventory.json')))
    V = visits.mark_form_spam(V, R)
    c = blocks.Ctx(R, V, E, T, m, inv, G)
    F = Findings()
    res = {'sheets': {}, 'summary': {}, 'selected': selected, 'site_map': m, 'inventory': inv, 'cleaning': cleaning_stats(R, V),
           'hosting': recon.detect_hosting(E), 'check_ips': list(check_ips or []),
           'mobile_share': round(float(V.loc[V['group'] == 'Люди', 'ua_mobile'].mean()) * 100, 1) if (V['group'] == 'Люди').any() else None}
    fn = {'Общий анализ': lambda: blocks.overview(c, F), 'Ошибки': lambda: blocks.errors(c, F),
          'Нагрузка и безопасность': lambda: blocks.load_security(c, F), 'Боты': lambda: blocks.bots(c, F, check_ips),
          'Маркетинг': lambda: blocks.marketing(c, F)}
    for b in BLOCKS:
        if b in selected or b == 'Боты':   # боты считаем всегда: нужны для листа IP и спама форм
            log(f'Блок: {b}')
            S, s = fn[b]()
            res['sheets'][b] = S
            res['summary'][b] = s
    res['ips'] = important_ips(c, res['sheets'].get('Боты', {}))
    sp = V[V['subgroup'].str.startswith('спам форм')].sort_values('start')
    res['spam_examples'] = [dict(класс=k, ip=g['ip'].iloc[-1], время=str(blocks.dt(g['start'].iloc[-1]))[:16], вход=g['entry'].iloc[-1], визитов=len(g)) for k, g in sp.groupby('subgroup')]
    if 'Боты' not in selected:
        res['sheets'].pop('Боты'); res['summary'].pop('Боты')
        F.items = [x for x in F.items if x['блок'] != 'Боты']
    # важность по вреду, однотипное — одной проблемой
    F.items = calibrate(F.items, int((V['group'] == 'Люди').sum()), int(R['ts'].max()))
    # отметки «это норма» из прошлого снимка или от человека
    marks = dict((prev or {}).get('marks', {}), **(marks or {}))
    for x in F.items:
        if x['key'] in marks:
            x['статус'] = 'отмечено как норма'
            x['отметка'] = marks[x['key']]
    if prev:
        old = {x['key']: x for x in prev.get('findings', [])}
        for x in F.items:
            if not x['статус']:
                x['статус'] = 'сохраняется' if x['key'] in old else 'новая'
                if x['key'] in old and isinstance(x['главная_цифра'], (int, float)) and isinstance(old[x['key']].get('главная_цифра'), (int, float)):
                    o = old[x['key']]['главная_цифра']
                    x['статус'] += f" (было {o}, стало {x['главная_цифра']})"
        cur = {x['key'] for x in F.items}
        for k, o in old.items():
            if k not in cur and o.get('блок') in selected:
                F.items.append(dict(key=k, блок=o['блок'], важность='К сведению', что_происходит=o['что_происходит'], факты='В новом периоде не обнаружено. Проверить: исправлено или просто нет запросов к этому адресу.',
                                    где_править='', что_сделать='Убедиться, что исправлено', главная_цифра=None, лист='', также_в='', статус='не обнаружена (исправлена или нет данных)'))
        rows = []
        for b, sm in res['summary'].items():
            for k, v in sm.items():
                ov = prev.get('summary', {}).get(b, {}).get(k)
                rows.append(dict(блок=b, показатель=k, было=ov, стало=v))
        res['compare'] = pd.DataFrame(rows)
        res['prev_period'] = prev.get('period')
    res['findings'] = F.items
    pickle.dump(res, open(os.path.join(workdir, 'results.pkl'), 'wb'))
    brief.save(brief.build(res, c, prev), workdir)
    log(f'Проблем найдено: {len(F.items)}')
    return res
