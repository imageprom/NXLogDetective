"""NXLD: общие расчёты для всех файлов отчёта — чтобы один и тот же вопрос везде решался одинаково.

- кто это по IP (группа, подгруппа, подлинность, живой или программа);
- эпизоды — подряд идущие минуты с признаком (сбои, всплески нагрузки, натиск);
- история состояния по дням одной строкой («отдаётся 16.09–30.09 → закрыт с 01.10»);
- настоящий адрес сайта или ложный (по реестру адресов).
"""
import numpy as np
import pandas as pd

LIVE = ('Люди', 'Свои')   # живые — люди и сотрудники; остальное — программы


def _fmt_day(d): return pd.Timestamp(d).strftime('%d.%m')


def ip_profile(c):
    """Кто это по IP: главная группа и подгруппа (по числу запросов), имя робота, сеть, страна, организация, живой ли.
    Результат кэшируется в c._ip_profile; индекс — IP строкой."""
    if getattr(c, '_ip_profile', None) is not None: return c._ip_profile
    V = c.V
    W = V[['ip', 'group', 'subgroup', 'fam', 'n_req', 'nettype', 'cc']].copy()
    W['ip'] = W['ip'].astype(str)
    top = W.sort_values('n_req', ascending=False).drop_duplicates('ip').set_index('ip')
    groups = W.groupby(['ip', 'group'])['n_req'].sum().reset_index()
    T = c.T.drop_duplicates('ip').set_index('ip') if 'ip' in c.T else pd.DataFrame()
    P = pd.DataFrame({'группа': top['group'], 'подгруппа': top['subgroup'].astype(str), 'имя': top['fam'].astype(str),
                      'сеть': top['nettype'].astype(str), 'страна': top['cc'].astype(str)})
    P['организация'] = T['org'].reindex(P.index).astype(str).replace({'nan': '', 'None': ''}).values if 'org' in T else ''
    P['asn'] = pd.to_numeric(T['asn'].reindex(P.index), errors='coerce').fillna(0).astype(int).values if 'asn' in T else 0   # номер сети — для выгрузки STIX
    P['живой'] = P['группа'].isin(LIVE) & (P['подгруппа'] != 'сервер сайта')   # сервер сайта — «Свои», но не человек
    P['кто'] = [label(g, s, f) for g, s, f in zip(P['группа'], P['подгруппа'], P['имя'])]
    P['групп'] = groups.groupby('ip')['group'].nunique().reindex(P.index).fillna(1).astype(int)
    c._ip_profile = P
    return P


def label(group, sub, fam=''):
    """Подпись обращающегося одной строкой: «Боты — подделка Googlebot», «Роботы — YandexBot», «Люди»."""
    sub = str(sub or '')
    if group == 'Люди': return 'Люди'
    if group == 'Свои': return 'Свои — сервер сайта' if sub == 'сервер сайта' else 'Свои — сотрудник'
    if group == 'Роботы': return f'Роботы — {fam}' if fam else 'Роботы'
    if group == 'Боты':
        if sub == 'подделки роботов': return f'Боты — подделка {fam}' if fam else 'Боты — подделка робота'
        return f'Боты — {sub}' if sub else 'Боты'
    if group in ('Системы мониторинга', 'Утилиты'): return f'{group} — {sub}' if sub else group
    return str(group)


def who_text(groups, n=3):
    """Счётчик групп (Series: группа → запросов) → «Роботы (3 676), Боты (140), Люди (10)»."""
    s = pd.Series(groups).sort_values(ascending=False)
    s = s[s > 0].head(n)
    return ', '.join(f"{k} ({int(v):,})".replace(',', ' ') for k, v in s.items())


def episodes(minutes, gap=3):
    """Подряд идущие минуты (отсортированные номера минут) → список (первая, последняя, индексы), разрыв не больше gap минут."""
    minutes = np.asarray(minutes)
    if not len(minutes): return []
    cut = np.r_[0, np.where(np.diff(minutes) > gap)[0] + 1, len(minutes)]
    return [(int(minutes[a]), int(minutes[b - 1]), np.arange(a, b)) for a, b in zip(cut[:-1], cut[1:])]


def minute_norm(ts):
    """Запросов в минуту по каждой минуте лога и обычное число для этого часа суток (медиана по дням).
    Возвращает (номера минут, запросов, обычно)."""
    m = np.asarray(ts) // 60
    s = pd.Series(m).value_counts()
    idx = np.arange(int(m.min()), int(m.max()) + 1)
    full = np.zeros(len(idx), dtype=np.int64)
    full[s.index.values - idx[0]] = s.values
    hod = (idx // 60) % 24
    norm = pd.Series(full).groupby(hod).median().reindex(hod).values
    return idx, full, norm


def day_runs(days, states, days_all, names=None):
    """История по дням одной строкой: days и states — дни (YYYY-MM-DD) и состояние в каждый из них.
    «отдаётся 16.09–25.09 → закрыт с 26.09», «отдаётся весь период». names — подписи состояний."""
    names = names or {}
    runs = []
    for d, s in sorted(zip(days, states)):
        if runs and runs[-1][0] == s: runs[-1][2] = d
        else: runs.append([s, d, d])
    if not runs: return ''
    first_day = days_all[min(1, len(days_all) - 1)] if days_all else ''
    nm = lambda s: names.get(s, str(s))
    if len(runs) == 1:
        s, a, z = runs[0]
        return f'{nm(s)} весь период' if a <= first_day else f'{nm(s)} с {_fmt_day(a)}'
    out = []
    for i, (s, a, z) in enumerate(runs):
        if i == len(runs) - 1: out.append(f'{nm(s)} с {_fmt_day(a)}')
        elif a == z: out.append(f'{nm(s)} {_fmt_day(a)}')
        else: out.append(f'{nm(s)} {_fmt_day(a)}–{_fmt_day(z)}')
    return ' → '.join(out)


def real_addresses(c):
    """Настоящие адреса сайта: полный ответ получали люди или свои, и это не однозначный зонд (реестр адресов).
    Возвращает булев массив по категориям R['base']."""
    A = getattr(c, 'addr', None)
    if A is None: return np.zeros(len(c.R['base'].cat.categories), bool)
    return (A['людям'] & (A['зонд'] != 'однозначный')).values


def codes_text(st):
    """Коды ответа (массив) → «404 (33), 200 (2)» по убыванию."""
    s = pd.Series(np.asarray(st)).value_counts()
    return ', '.join(f"{int(k)} ({int(v):,})".replace(',', ' ') for k, v in s.items())


def split_codes_arr(st):
    """Коды ответа (массив) → («200 (15), 301 (3)», «404 (33)»): ответы и ошибки (4xx и 5xx, кроме 499 — посетитель ушёл сам)."""
    s = pd.Series(np.asarray(st)).value_counts()
    f = lambda k, v: f"{int(k)} ({int(v):,})".replace(',', '\u00a0')
    return ', '.join(f(k, v) for k, v in s.items() if not (k >= 400 and k != 499)), ', '.join(f(k, v) for k, v in s.items() if k >= 400 and k != 499)


def dmy(ts):
    """Секунды эпохи → «16.09.2026 14:08»."""
    return pd.to_datetime(int(ts), unit='s').strftime('%d.%m.%Y %H:%M')


def episode_id(ts):
    """Код эпизода по времени начала — как у сбоев: «27.09 22:25»."""
    return pd.to_datetime(int(ts), unit='s').strftime('%d.%m %H:%M')


def ua_text(values, width=120):
    """User-Agent для таблиц: самый частый (до width знаков) и «и ещё N» — сколько других вариантов."""
    v = pd.Series(list(values)).astype(str)
    v = v[(v != '') & (v != '-') & (v != 'nan')]
    if not len(v): return ''
    vc = v.value_counts()
    top = vc.index[0]
    top = top if len(top) <= width else top[:width - 1] + '…'
    return top + (f'\nи ещё {len(vc) - 1}' if len(vc) > 1 else '')


def ua_by_ip(V, ips):
    """IP → User-Agent (самый частый и «и ещё N») — для подделок, сканеров и других таблиц по IP."""
    X = V[V['ip'].astype(str).isin(set(map(str, ips)))]
    return {str(ip): ua_text(g['ua']) for ip, g in X.groupby(X['ip'].astype(str))} if len(X) else {}
