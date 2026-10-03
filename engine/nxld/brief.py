"""NXLD: выжимка для ИИ — brief.json (ТЗ, раздел 12 «Текст для Redmine», и 15.1).

Всё, что нужно, чтобы написать связный отчёт, не читая логи и Excel: цифры уже с контекстом, сравнения,
хронологии, точные названия объектов и ссылки «файл + лист». Ориентир — 20–40 КБ.
"""
import json, os, re
import numpy as np, pandas as pd

FILES = {'Общий анализ': 'NXLD_01_Overview.xlsx', 'Ошибки': 'NXLD_02_Errors.xlsx', 'Нагрузка и безопасность': 'NXLD_03_Load_Security.xlsx',
         'Боты': 'NXLD_04_Bots.xlsx', 'Маркетинг': 'NXLD_05_Marketing.xlsx'}
# частые обработчики форм → человеческое имя (если имени нет — ИИ называет форму сам по адресу и странице)
FORM_NAMES = [(r'callback_newproject|newproject', 'заявка по новому проекту'), (r'modal_callback|callback', 'обратный звонок'),
              (r'excursion', 'запись на экскурсию'), (r'getprice|get_price|price', 'запрос цены'), (r'mortgage_consultation', 'консультация по ипотеке'),
              (r'mortgage|ipoteka', 'ипотека'), (r'finishing|otdelka', 'отделка'), (r'order|zakaz', 'заказ'), (r'feedback|contact', 'обратная связь'),
              (r'subscribe', 'подписка'), (r'question|vopros', 'вопрос')]


def sheet_name(n):
    """Имя листа так, как его пишет Excel-сборка (двоеточие недопустимо)."""
    return re.sub(r'[\[\]*?/\\]', ' ', str(n)).replace(':', ' —')[:31].strip()


def ref(block, sheet):
    return f'{FILES[block]}, лист «{sheet_name(sheet)}»'


def rnd(x, nd=1):
    if x is None or (isinstance(x, float) and np.isnan(x)): return None
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating, float)): return round(float(x), nd)
    return x


def recs(df, cols=None, n=8, nd=1, width=160):
    if df is None or not len(df): return []
    d = df[cols] if cols else df
    return [{k: rnd(v, nd) if not isinstance(v, str) else v[:width] for k, v in r.items()} for r in d.head(n).astype(object).to_dict('records')]


def form_name(path):
    p = str(path).lower()
    for rx, name in FORM_NAMES:
        if re.search(rx, p): return name
    return None


def ts(x):
    return pd.Timestamp(int(x), unit='s').strftime('%Y-%m-%d %H:%M')


def slash_check(rows, R):
    """Для битых входов: отвечает ли тот же адрес с косой чертой в конце (или без неё) нормально."""
    if not rows: return rows
    cats = R['base'].cat.categories
    ok = set(cats[np.unique(R['base'].cat.codes.values[(R['status'].values == 200) & R['is_page'].values])])
    for r in rows:
        a = str(r.get('адрес', ''))
        alt = a[:-1] if a.endswith('/') else a + '/'
        r['рабочий_вариант'] = alt if alt in ok else None
    return rows


def build(res, c, prev=None):
    S, sm, inv, m = res['sheets'], res['summary'], res['inventory'], res['site_map']
    V, R = c.V, c.R
    p0, p1 = inv['period']
    last = pd.Timestamp(p1)
    days = (pd.Timestamp(p1[:10]) - pd.Timestamp(p0[:10])).days + 1
    caveats = []
    if last.hour < 23: caveats.append(f'лог заканчивается {last:%d.%m в %H:%M}, последний день неполный')
    if inv.get('hour_gaps'): caveats.append(f"пропуски в логе: {', '.join(inv['hour_gaps'][:5])}")
    if not inv.get('errors_lines'): caveats.append('error-лога нет: причины 5xx по нему не проверялись')
    B = {'проверка': dict(сайт=(m.get('site_hosts') or ['?'])[0], другие_хосты=(m.get('site_hosts') or [])[1:], период=[p0, p1], дней=days,
                          строк_access=inv.get('requests'), строк_error=inv.get('errors_lines'), блоки=res['selected'],
                          тип='повторная' if prev else 'первичная', прошлая_проверка=(prev or {}).get('period'), оговорки=caveats)}
    # --- портрет сайта
    H = V[V['group'] == 'Люди']
    O = S.get('Общий анализ', {})
    ch = O.get('Каналы')
    eng = [e['движок'] for e in m.get('engines', [])] or ['не определён']
    C = O.get('Конверсии', pd.DataFrame())
    acc = lambda g: int(((C['группа'] == g) & (C['принята'] == 'да')).sum()) if len(C) else 0
    snt = lambda g: int((C['группа'] == g).sum()) if len(C) else 0
    goals = [f for f in m.get('forms', []) if str(f.get('вывод', '')).startswith('цель')]
    fun = S.get('Маркетинг', {}).get('Воронки', pd.DataFrame())
    forms = []
    if len(C):
        HC = C[C['группа'] == 'Люди'].copy()
        HC['форма'] = HC['цель'].astype(str)
        for f_, g in HC.groupby('форма'):
            rule = next((str(f.get('вывод')) for f in goals if str(f.get('адрес', '')) == f_), '')
            forms.append(dict(обработчик=f_, название=form_name(f_), отправок_людей=len(g), принято=int((g['принята'] == 'да').sum()), как_понять_что_принята=rule))
        forms.sort(key=lambda x: -x['принято'])
    rules = sorted({str(f.get('вывод')) for f in goals})
    wv = H['ua_webview'] if 'ua_webview' in H else pd.Series(False, index=H.index)
    def cr(d): return round(d['n_conv'].sum() / max(1, len(d)) * 100, 3)
    B['сайт'] = dict(
        движок=eng, сервер=m.get('server', {}).get('веб-сервер'), протокол=list((m.get('server', {}).get('протокол') or {}).keys())[:1],
        визитов_людей=int(len(H)), IP_людей=int(H['ip'].nunique()), визитов_роботов=int((V['group'] == 'Роботы').sum()),
        визитов_ботов=int((V['group'] == 'Боты').sum()), визитов_своих=int((V['group'] == 'Свои').sum()),
        доля_мобильных_у_людей_проц=round(H['ua_mobile'].mean() * 100, 1) if len(H) else None,
        каналы=recs(ch, ['канал', 'визитов', 'доля_визитов_%', 'конверсий'], n=10) if ch is not None else [],
        встроенные_браузеры=dict(визитов=int(wv.sum()), конверсия_проц=cr(H[wv]), у_обычных_браузеров_проц=cr(H[~wv])),
        как_считается_заявка=rules, формы=forms[:15],
        заявки=dict(люди_принято=acc('Люди'), люди_отправок=snt('Люди'), боты_принято=acc('Боты'), боты_отправок=snt('Боты'),
                    свои_тесты_принято=acc('Свои'), свои_адреса=len(m.get('staff_ips', []))),
        где=ref('Общий анализ', 'Конверсии'))
    if len(C):
        hc = C[(C['группа'] == 'Люди') & (C['принята'] == 'да')]
        B['сайт']['заявки_людей_по_дням'] = hc.groupby(hc['время'].astype(str).str[:10]).size().to_dict()
    # --- проблемы (уже откалиброванные)
    B['проблемы'] = [dict(ключ=x['key'], блок=x['блок'], важность=x['важность'], что=x['что_происходит'], факты=str(x.get('факты', ''))[:700 if x['важность'] == 'Срочно' else 350],
                          что_сделать=x.get('что_сделать', ''), цифра=rnd(x.get('главная_цифра')), где=ref(x['блок'], x['лист']) if x.get('лист') else FILES[x['блок']],
                          статус=x.get('статус', ''), калибровка=x.get('калибровка', '')) for x in res['findings']]
    n_urg = sum(1 for x in res['findings'] if x['важность'] == 'Срочно')
    B['проверка']['срочных'] = n_urg
    if n_urg > 5: B['проверка']['внимание'] = f'«Срочно» — {n_urg}: пересмотреть важность (норма — до 5)'
    # --- боты
    if 'Боты' in S:
        SB = S['Боты']
        ops = SB.get('Операторы', pd.DataFrame())
        bc = C[C['группа'] == 'Боты'] if len(C) else C
        waves = bc.groupby(bc['время'].astype(str).str[:10]).agg(отправок=('ip', 'size'), принято=('принята', lambda s: int((s == 'да').sum()))).reset_index().rename(columns={'время': 'день'}) if len(bc) else pd.DataFrame()
        sv = SB.get('Спам форм: визиты', pd.DataFrame())
        opr = recs(ops, n=6, nd=0, width=1200)
        for o in opr:   # «дни» — все дни визитов группы, включая разведку; отдельно — когда группа отправляла формы
            ips = [x.strip() for x in str(o.get('адреса_спама', '')).split(',') if x.strip()]
            cc = bc[bc['ip'].astype(str).isin(ips)] if len(bc) else bc
            o['дни_отправок_форм'] = sorted(cc['время'].astype(str).str[:10].unique().tolist()) if len(cc) else []
            o['последняя_отправка'] = str(cc['время'].max())[:16] if len(cc) else None
            o['дни'] = 'все дни визитов группы, включая разведку без отправок: ' + str(o.get('дни', ''))
        B['боты'] = dict(
            операторы=opr, волны_бот_заявок=recs(waves, n=31),
            последняя_принятая_бот_заявка=str(bc.loc[bc['принята'] == 'да', 'время'].max())[:16] if len(bc) else None,
            сценарии_спама=recs(SB.get('Боты: классы'), n=8), формы_спама=(bc['цель'].astype(str).map(lambda p: form_name(p) or p).value_counts().head(5).to_dict() if len(bc) else {}),
            сети_спама=(sv['org'].astype(str).value_counts().head(8).to_dict() if len(sv) and 'org' in sv else {}),
            подделки=dict(IP=len(SB.get('Подделки', [])), главные=recs(SB.get('Подделки'), ['ip', 'представлялся', 'запросов', 'страна', 'org', 'первый', 'последний'], n=6)),
            роботы_главные=recs(SB.get('Роботы: семейства'), ['семейство', 'категория', 'запросов', 'IP', 'МБ', 'доля_200_%', 'что_смотрел'], n=8),
            ИИ_роботы=recs(SB.get('ИИ-роботы'), ['назначение', 'робот', 'запросов', 'IP'], n=8),
            людей_из_ИИ_ассистентов=sm.get('Боты', {}).get('Визитов людей из ИИ-ассистентов'),
            проверка_IP=recs(SB.get('Проверка IP'), n=20),
            где=dict(операторы=ref('Боты', 'Операторы'), улики=ref('Боты', 'Операторы: улики'), визиты=ref('Боты', 'Спам форм: визиты'), подделки=ref('Боты', 'Подделки')))
    # --- маркетинг
    if 'Маркетинг' in S:
        SM = S['Маркетинг']
        tp = SM.get('Реклама: системы и типы площадок', pd.DataFrame()).copy()
        if len(tp):
            tp['визитов_на_заявку'] = [round(v / p) if p else None for v, p in zip(tp['визитов'], tp['принято'])]
        org = H[H['channel'] == 'Поиск']
        kc = SM.get('Реклама: Кампании', pd.DataFrame())
        pl = SM.get('Площадки к отключению', pd.DataFrame())
        B['маркетинг'] = dict(
            органический_поиск=dict(визитов=int(len(org)), заявок=int(org['n_conv'].sum()), визитов_на_заявку=round(len(org) / org['n_conv'].sum()) if org['n_conv'].sum() else None),
            типы_площадок=recs(tp, ['система', 'тип_площадки', 'визитов', 'принято', 'визитов_на_заявку', 'мгновенный_уход_%', 'смотрели_каталог_%'], n=10),
            кампании_без_заявок=recs(kc[(kc['принято'] == 0)].sort_values('визитов', ascending=False), ['кампания', 'визитов', 'мгновенный_уход_%', 'смотрели_каталог_%'], n=6) if len(kc) else [],
            кампании_с_заявками=recs(kc[kc['принято'] > 0].sort_values('принято', ascending=False), ['кампания', 'визитов', 'принято'], n=6) if len(kc) else [],
            площадки_к_отключению=dict(всего=len(pl), визитов=int(pl['визитов'].sum()) if len(pl) else 0, крупнейшие=recs(pl, ['source', 'тип', 'визитов'], n=6)),
            метки=recs(SM.get('Метки: проблемы'), n=4),
            где=dict(типы=ref('Маркетинг', 'Реклама: системы и типы площадок'), кампании=ref('Маркетинг', 'Реклама: Кампании'),
                     площадки=ref('Маркетинг', 'Площадки к отключению')))
    # --- ошибки
    SE = S.get('Ошибки', {})
    st = SE.get('Изменения статусов', pd.DataFrame())
    t5 = SE.get('5xx по шаблонам', pd.DataFrame())
    chg = {}
    if len(st):
        for t, g in st.groupby('шаблон'):
            chg[str(t)] = '; '.join(f"{r['день']}: {r['было']} → {r['стало']}" for _, r in g.iterrows())
    t5r = recs(t5, ['шаблон', 'ошибок', 'у_людей', 'людей_задето', 'первый_день', 'последний_день', 'дней_с_ошибкой', 'успешных_ответов'], n=10)
    for r in t5r: r['смена_статуса'] = chg.get(r['шаблон'], '')
    land = SE.get('Реклама: посадочные с ошибками', pd.DataFrame())
    ad_last = {}
    if 'Маркетинг' in S:
        AD = V[(V['channel'] == 'Реклама')]
        for e in land['entry'].head(10) if len(land) else []:
            a = AD[AD['entry'] == e]
            if len(a): ad_last[e] = ts(a['start'].max())
    B['ошибки'] = dict(
        сбои=recs(SE.get('Сбои'), n=5), ошибки_сервера_по_страницам=t5r,
        реклама_на_ошибках=[dict(r, последний_клик=ad_last.get(r['entry'])) for r in recs(land, n=10)],
        входы_на_404=slash_check(recs(SE.get('404: входы извне'), n=10), R), служебные_и_фиды=[dict(ключ=x['key'], что=x['что_происходит'], факты=x['факты'][:300]) for x in res['findings'] if ':service_err:' in x['key']],
        отсутствующие_файлы=recs(SE.get('Отсутствующие ресурсы'), ['файл', 'запросов', 'визитов', 'страниц'], n=8),
        ошибки_у_поисковиков=recs(SE.get('Ошибки у поисковиков'), n=5), error_лог=recs(SE.get('Error-лог'), ['тип', 'сообщений', 'первый', 'последний'], n=8),
        где=dict(сбои=ref('Ошибки', 'Сбои'), шаблоны=ref('Ошибки', '5xx по шаблонам'), реклама=ref('Ошибки', 'Реклама: посадочные с ошибками'),
                 входы=ref('Ошибки', '404: входы извне'), файлы=ref('Ошибки', 'Отсутствующие ресурсы'), проблемы=ref('Ошибки', 'Проблемы')))
    # --- безопасность и нагрузка
    if 'Нагрузка и безопасность' in S:
        SL = S['Нагрузка и безопасность']
        ad = SL.get('Админка', pd.DataFrame())
        tf = SL.get('Типы файлов', pd.DataFrame())
        hv = SL.get('Тяжёлые файлы', pd.DataFrame())
        rb = S.get('Боты', {}).get('Роботы: семейства', pd.DataFrame())
        secs = max(1, (pd.Timestamp(p1) - pd.Timestamp(p0)).total_seconds())
        mon = []
        if len(rb):
            for _, r in rb[rb['категория'].astype(str).str.contains('Мониторинг')].head(5).iterrows():
                mon.append(dict(робот=r['семейство'], запросов=int(r['запросов']), МБ=rnd(r['МБ']), примерно_раз_в_секунд=round(secs / max(1, r['запросов'])), что=r['что_смотрел']))
        B['безопасность'] = dict(
            сканеры=recs(SL.get('Сканеры: что искали'), n=8), всего_запросов_сканеров=sm.get('Нагрузка и безопасность', {}).get('Запросов сканеров'),
            отданные_служебные_файлы=recs(SL.get('Служебные файлы: что отдано'), n=6),
            открытые_разделы=recs(SL.get('Открытые служебные разделы'), n=5),
            админка=dict(адресов=len(ad), своих=int(ad['сотрудник'].sum()) if len(ad) else 0,
                         чужих_с_успехом=int((~ad['сотрудник'] & (ad['успешных_200'] > 0) & (ad['робот'].astype(str) == '')).sum()) if len(ad) else 0),
            атаки_в_параметрах=recs(SL.get('Атаки в параметрах'), n=4),
            где=dict(сканеры=ref('Нагрузка и безопасность', 'Сканеры: что искали'), разделы=ref('Нагрузка и безопасность', 'Открытые служебные разделы'),
                     файлы=ref('Нагрузка и безопасность', 'Служебные файлы: что отдано')))
        B['нагрузка'] = dict(
            трафик_ГБ=sm.get('Нагрузка и безопасность', {}).get('Трафик, ГБ'), по_типам=recs(tf, n=6),
            тяжёлые_файлы=dict(главные=recs(hv, n=6), ГБ_у_шести=round(float(hv['ГБ'].head(6).sum()), 1) if len(hv) else 0),
            доля_304_у_статики_проц=sm.get('Нагрузка и безопасность', {}).get('Доля 304 у статики (кэш), %'),
            пики=recs(SL.get('Пики'), n=3), кто_нагружает=recs(SL.get('Кто нагружает'), n=8), мониторинги=mon,
            ловушки=recs(SL.get('Ловушки для роботов'), n=4),
            где=dict(тяжёлые=ref('Нагрузка и безопасность', 'Тяжёлые файлы'), кто=ref('Нагрузка и безопасность', 'Кто нагружает'), ловушки=ref('Нагрузка и безопасность', 'Ловушки для роботов')))
    # --- сравнение
    if prev and res.get('compare') is not None:
        stt = pd.Series([x.get('статус', '') for x in res['findings']])
        B['сравнение'] = dict(новых=int(stt.str.startswith('новая').sum()), сохраняются=int(stt.str.startswith('сохраняется').sum()),
                             не_обнаружены=int(stt.str.startswith('не обнаружена').sum()), показатели=recs(res['compare'], n=40))
    # --- файлы и вопросы
    B['файлы'] = {FILES[b]: [sheet_name(k) for k in (['Проблемы'] + list(S.get(b, {}).keys()))][:25] for b in res['selected']}
    q = [x['что_происходит'] for x in res['findings'] if ':unknown_robot:' in x['key']]
    if len(C):
        nh = int(((C['группа'] == 'Люди') & (C['принята'] != 'да')).sum())
        if nh: q.append(f'{nh} отправок людей не приняты сервером — сверить (часть может быть повторными нажатиями)')
    q.append('звонки и мессенджеры в логах не видны')
    B['открытые_вопросы'] = q
    B['что_за_сайт'] = res.get('site_profile')   # Детектив может поправить через edits.json → «site_profile»
    an = res.get('anatomy') or {}
    B['тематика_подсказки'] = an.get('подсказки')   # по ним Детектив называет тематику и уровни каталогов (edits.json → «anatomy_names», «site_profile.тематика»)
    B['сигналы_без_проблемы'] = res.get('loose_signals', [])   # признак на листе есть, карточки нет: завести проблему или объяснить, почему норма
    if res.get('unknown_params'):   # Детектив ищет в сети и пишет в edits.json → «справочник» (SKILL.md, шаг «Незнакомые параметры»)
        B['незнакомые_параметры'] = res['unknown_params']
    cv = res.get('coverage')
    if cv is not None and len(cv):
        B['покрытие'] = {st_: cv.loc[cv['состояние'] == st_, 'проверка'].tolist() for st_ in ('проверено, не найдено', 'не применимо', 'детектора пока нет')}
    return B


def save(B, workdir):
    p = os.path.join(workdir, 'brief.json')
    txt = json.dumps(B, ensure_ascii=False, default=str, separators=(',', ':'))
    txt = txt.replace('},{', '},\n{').replace('],"', '],\n"')   # строки покороче — удобнее читать по частям
    open(p, 'w', encoding='utf-8').write(txt)
    return p
