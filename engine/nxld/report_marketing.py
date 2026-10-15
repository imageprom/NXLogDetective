"""NXLD: файл 05 «Маркетинг» — по тем же правилам, что 01–04.

Обзор → Проблемы → Статистика → Каналы → Воронки → Конверсии по времени → Аудитория → Страницы входа →
Реклама → Кампании → Фразы → Площадки → Органика (до файла 06) → подробные списки: Объявления, Регионы.
Данные — блок «Маркетинг» (blocks.marketing) и marketing.build (журнал, карты, качество, боты в рекламе);
оформление только рисует."""
from . import sheets
from .catalog import order as catalog_order
import pandas as pd
from .report_index import Wide, brand_header, ORANGE, F_NOTE
from .report_tables import data_sheet, journal_sheet, heat_sheet, extra_table, notes, notes_of, legend_of
from .report_bots import notes

LINK = sheets.LINK_05
F_GREY = 'EFEFEF'
MCOLS = {'визитов': 'Визитов', 'IP': 'Уникальных IP', 'страниц_на_визит': 'Страниц на визит', 'мгновенный_уход_%': 'Ушли сразу, %',
         'смотрели_каталог_%': 'Смотрели каталог, %', 'отправок': 'Отправок', 'принято': 'Принято', 'конверсия_%': 'Конверсия, %'}
INTS = ('визитов', 'IP', 'отправок', 'принято')


def relink(findings):
    for x in findings:
        if x.get('блок') == 'Маркетинг' and x.get('лист') in LINK: x['лист'] = LINK[x['лист']]


def sheets_for(S, res):
    return {'Обзор': pd.DataFrame()}


def _m(df, keys, empty='(без метки)'):
    """Срез с метрикой визитов (marketing.metrics) → колонки отчёта: keys — {колонка данных: подпись}."""
    d = pd.DataFrame({lab: df[k].astype(str).replace({'': empty, 'nan': empty}) for k, lab in keys.items()})
    for k, lab in MCOLS.items():
        if k in df: d[lab] = df[k].fillna(0).astype(int) if k in INTS else df[k].fillna(0)
    return d


def _ad(S, B, col, name, label, extra=None):
    """Рекламный срез: метрика людей + клики всех, боты, роботы, ошибки посадочной, впустую."""
    P = S.get(f'Реклама: {name}')
    Bt = (B or {}).get(name)
    if P is None and Bt is None: return None
    P = P if P is not None else pd.DataFrame({col: []})
    if Bt is not None: P = P.drop(columns=[c for c in ('регион', 'область') if c in P and c in Bt])
    M = Bt.merge(P, on=col, how='outer') if Bt is not None else P.copy()
    for k in ('визитов_всех', 'ботов', 'роботов', 'ошибок_посадочной', 'впустую', *INTS):
        if k in M: M[k] = M[k].fillna(0).astype(int)
    M = M.sort_values('визитов_всех' if 'визитов_всех' in M else 'визитов', ascending=False).reset_index(drop=True)   # весь срез — для цифр сводки; на лист — первые 1000
    d = pd.DataFrame({label: M[col].astype(str).replace({'': '(без метки)', 'nan': '(без метки)'})})
    if extra: d = pd.concat([d, extra(M)], axis=1)
    if 'визитов_всех' in M:
        d['Кликов всего'] = M['визитов_всех'].values; d['Людей'] = M.get('визитов', 0); d['Ботов'] = M['ботов'].values
        d['Доля ботов, %'] = M['доля_ботов_%'].fillna(0).values; d['Роботов'] = M['роботов'].values
        d['Ошибок посадочной'] = M['ошибок_посадочной'].values; d['Впустую'] = M['впустую'].values
    for k, lab in list(MCOLS.items())[1:]:
        if k in M: d[lab] = M[k].fillna(0).astype(int).values if k in INTS else M[k].fillna(0).values
    return d.reset_index(drop=True), M


def _sheet(wb, nm, d, sub, widths, wrap, kpi, kpi_col, links=(), row_rule=None, red=('Ошибок посадочной',), auto=None):
    if d is None or not len(d): return None
    if nm not in wb.sheetnames: wb.create_sheet(nm)
    data_sheet(wb, nm, d, widths, note=sub, wrap=wrap, kpi=kpi, kpi_col=kpi_col, links=links, row_rule=row_rule, red=red, auto=auto)
    return wb[nm]


def _bots_rule(r):
    try: return F_NOTE if float(r.get('Доля ботов, %') or 0) >= 30 else None
    except Exception: return None


def build_sheets(wb, res, S):
    MK = res.get('marketing') or {}
    E = res.get('errors') or {}
    B = MK.get('реклама_боты') or {}
    # Статистика
    J = MK.get('журнал')
    if J is not None and len(J):
        if 'Статистика' not in wb.sheetnames: wb.create_sheet('Статистика')
        def kpi(body):
            full = body[body['_полный'].astype(bool)] if body['_полный'].astype(bool).any() else body
            return [('Визитов людей в день', int(round(full['Визиты людей|Все'].mean()))), ('Из рекламы в день', int(round(full['Визиты людей|Реклама'].mean()))),
                    ('Принято заявок', int(body['Заявки|Принято'].sum())), ('Кликов впустую', int(body['Рекламные клики|Впустую'].sum()))]
        journal_sheet(wb, 'Статистика', J, kpi, kpi_col='Визиты людей|Прочие', outages=E.get('сбои'))
    # Каналы
    C = S.get('Каналы подробно')
    if C is not None and len(C):
        d = _m(C, {'канал': 'Канал', 'источник': 'Источник'}, empty='—')
        ws = _sheet(wb, 'Каналы', d, None, {'Канал': 24, 'Источник': 30}, ('Канал', 'Источник'),
                    [('Каналов', int(d['Канал'].nunique())), ('Визитов людей', int(d['Визитов'].sum())), ('Принято', int(d['Принято'].sum()))], 'Отправок', red=())
        Q, CL = MK.get('качество'), S.get('Качество и очистка по каналам')
        if ws is not None and Q is not None and len(Q):
            q = Q.merge(CL[['канал'] + [k for k in ('просмотров_до_очистки', 'просмотров_после', 'двойных_загрузок') if k in CL]], on='канал', how='left') if CL is not None and len(CL) else Q
            t = pd.DataFrame({'Канал': q['канал'], 'Людей': q['людей'], 'Ботов': q['ботов'], 'Доля ботов, %': q['доля_ботов_%'], 'Заявок людей': q['заявок_людей'],
                              'Заявок ботов': q['заявок_ботов'], 'Фальшивых заявок, %': q['фальшивых_заявок_%'], 'Конверсия людей, %': q['конверсия_людей_%']})
            if 'просмотров_до_очистки' in q:
                t['Просмотров до очистки'] = q['просмотров_до_очистки'].fillna(0).astype(int); t['После очистки'] = q['просмотров_после'].fillna(0).astype(int)
                t['Двойных загрузок'] = q['двойных_загрузок'].fillna(0).astype(int)
            extra_table(ws, t, 'channel_quality',
                        row_rule=lambda r: F_NOTE if (r.get('Фальшивых заявок, %') or 0) >= 30 else None, red=())
    # Воронки
    Fn = S.get('Воронки')
    if Fn is not None and len(Fn):
        from .blocks import form_name
        d = pd.DataFrame({'Форма': form_name(Fn['цель']).values, 'Обработчик': Fn['цель'].astype(str).values, 'Открыли форму': Fn['открыли_форму'].astype(str).replace({'': '—'}).values,
                          'Отправили (визитов)': Fn['отправили_визитов'].astype(int).values, 'Отправок': Fn['отправок'].astype(int).values, 'Принято': Fn['принято'].astype(int).values})
        d['Принято, %'] = (d['Принято'] / d['Отправок'].clip(lower=1) * 100).round(1)
        _sheet(wb, 'Воронки', d, None, {'Форма': 26, 'Обработчик': 46, 'Открыли форму': 34}, ('Обработчик', 'Открыли форму'),
               [('Форм', len(d)), ('Отправок', int(d['Отправок'].sum())), ('Принято', int(d['Принято'].sum()))], 'Отправок', red=())
    OF = S.get('Воронка заказа')   # магазин: воронка заказа по визитам людей (B2, #22); подписи — data/locale/<язык>/funnel.json, блок order_funnel каталога
    if OF and OF.get('шаги'):
        from . import texts
        from .catalog import K
        tx = texts.file('funnel')
        st = OF['шаги']; hv = max(1, st[0][1])
        f = pd.DataFrame({tx['columns']['step']: [tx['steps'][k] for k, _ in st], tx['columns']['visits']: [v for _, v in st]})
        prev = [None] + [v for _, v in st[:-1]]
        f[tx['columns']['of_prev']] = [None if p_ is None else round(v / max(1, p_) * 100, 1) for (_, v), p_ in zip(st, prev)]
        f[tx['columns']['of_people']] = [round(v / hv * 100, 1) for _, v in st]
        if 'Воронки' in wb.sheetnames:
            ws = wb['Воронки']
            shown = extra_table(ws, f, 'order_funnel', widths=None, red=()) is not False
        else:
            ws = _sheet(wb, 'Воронки', f, None, {tx['columns']['step']: 26}, (), [(tx['steps']['order'], st[-1][1])], tx['columns']['visits'], red=())
            shown = ws is not None and K(ws).h('order_funnel') is not None
        if shown and OF.get('заказ_через_корзину') is not None and ws is not None:
            from openpyxl.styles import Font
            ws.cell(ws.max_row + 2, 2, tx['note'].format(orders=st[-1][1], in_cart=OF['заказ_через_корзину'])).font = Font(name='Arial', size=9, italic=True, color='808080')
    # Конверсии по времени
    T = [b for b in MK.get('время') or [] if b[2] is not None and len(b[2])]
    if T:
        heat_sheet(wb, 'Конверсии по времени', T, unit='Сумма за период по дню недели и часу')   # карты — из движка (marketing)
    # Аудитория
    cuts = [(k, lab) for k, lab in (('Конверсии: Устройства', 'Устройство'), ('Конверсии: Встроенные браузеры', 'Браузер'), ('Конверсии: Новые и повторные', 'Визит'))
            if S.get(k) is not None and len(S[k])]
    if cuts:
        k0, l0 = cuts[0]
        D0 = S[k0]; d = _m(D0, {D0.columns[0]: l0})
        ws = _sheet(wb, 'Аудитория', d, None, {l0: 30}, (l0,),
                    [('Визитов людей', int(d['Визитов'].sum()))], 'Отправок', red=())
        code_ = {'Браузер': 'browsers', 'Визит': 'new_returning'}
        from .catalog import K
        for k, lab in sorted(cuts[1:], key=lambda x: K(ws).order(list(code_.values())).index(code_[x[1]])) if ws is not None else []:   # порядок доп. таблиц — из каталога
            Dk = S[k]
            extra_table(ws, _m(Dk, {Dk.columns[0]: lab}), code_[lab], red=())
    # Страницы входа
    EP = S.get('Конверсии: Страницы входа')
    if EP is not None and len(EP):
        d = _m(EP, {'вход_шаблон': 'Страница входа'})
        ws = _sheet(wb, 'Страницы входа', d, None, {'Страница входа': 60}, ('Страница входа',),
                    [('Страниц', len(d)), ('Визитов', int(d['Визитов'].sum()))], 'Отправок', red=())
        LP = S.get('Реклама: посадочные')
        if ws is not None and LP is not None and len(LP):
            t = _m(LP, {'посадочная': 'Рекламная посадочная'}); t.insert(1, 'Код', LP['entry_status'].astype(int).values)
            extra_table(ws, t.head(300), 'ad_landings', wrap=('Рекламная посадочная',),
                        row_rule=lambda r: F_NOTE if int(r.get('Код') or 0) >= 400 and int(r.get('Код') or 0) != 499 else None, red=())
    # Реклама
    TP = S.get('Реклама: системы и типы площадок')
    if TP is not None and len(TP):
        d = _m(TP, {'система': 'Система', 'тип_площадки': 'Тип площадки'})
        RI = MK.get('реклама_итог') or {}
        ws = _sheet(wb, 'Реклама', d, None, {'Система': 22, 'Тип площадки': 30}, ('Тип площадки',),
                    [('Кликов всего', int(RI.get('кликов', 0))), ('Людей', int(RI.get('людей', 0))), ('Впустую', int(RI.get('впустую', 0)))], 'Отправок', red=())
        r_ = _ad(S, B, 'device', 'Устройства (метка)', 'Устройство (по метке)')
        if ws is not None and r_ is not None:
            extra_table(ws, r_[0], 'ad_devices', red=('Ошибок посадочной',))
        notes_of(ws)
    # Кампании, Фразы, Площадки, Объявления, Регионы
    kp = [('кампания', 'Кампании', 'Кампания', {'Кампания': 50}),   # подзаголовки листов — из каталога
          ('фраза', 'Фразы', 'Фраза', {'Фраза': 50}),
          ('source', 'Площадки', 'Площадка', {'Площадка': 36, 'Тип': 20, 'Вердикт': 28}),
          ('aid', 'Объявления', 'Объявление', {'Объявление': 24}),
          ('region', 'Регионы', 'Код', {'Код': 10, 'Регион': 26, 'Область': 28})]
    from .blocks import placement_type
    from .marketing import verdict
    for col, nm, lab, wd in kp:
        ex = None
        if col == 'source':
            ex = lambda M: pd.DataFrame({'Тип': [placement_type(x, '') for x in M['source'].astype(str)],
                                         'Вердикт': [verdict(r) for _, r in M.iterrows()]})
        if col == 'region':   # название и область — из движка (marketing.label_ads); неизвестный код остаётся кодом
            ex = lambda M: pd.DataFrame({'Регион': M['регион'].fillna('') if 'регион' in M else '', 'Область': M['область'].fillna('') if 'область' in M else ''}, index=M.index)
        r_ = _ad(S, B, col, nm, lab, ex)
        if r_ is None: continue
        d = r_[0]
        kpi = [(f'{nm}', len(d)), ('Кликов', int(d['Кликов всего'].sum()) if 'Кликов всего' in d else int(d['Визитов'].sum())),
               ('Впустую', int(d['Впустую'].sum()) if 'Впустую' in d else 0)]   # цифры — по всему срезу
        if col == 'source': kpi.append(('К отключению', int(d['Вердикт'].astype(str).str.startswith('отключить').sum())))
        cut = '· на листе — 1000 крупнейших' if len(d) > 1000 else ''   # динамическая часть подзаголовка (каталог: auto «cut»)
        if cut: d = d.head(1000)
        rule = (lambda r: F_NOTE if str(r.get('Вердикт', '')).startswith('отключить') else None) if col == 'source' else _bots_rule
        ws = _sheet(wb, nm, d, None, wd, tuple(wd), kpi, 'Роботов', row_rule=rule, auto={'cut': cut})
        if ws is not None and col == 'фраза':
            notes_of(ws)
        if ws is not None and col == 'source':
            notes_of(ws)
    # «Органика» — только в 06 «SEO» (каталог #8: запасных мест SEO-листов в 02–05 нет)


def organic_sheet(wb, O):
    """Органика — визиты людей из поиска по дням и поисковикам (06 «SEO», или 05, если 06 не строится)."""
    if O is None or not len(O): return None
    d = O.copy(); dt_ = pd.to_datetime(d['day'])
    d = pd.concat([pd.DataFrame({'Дата': dt_.dt.strftime('%d.%m.%Y')}), d.drop(columns='day').astype(int)], axis=1)
    ws = _sheet(wb, 'Органика', d, None, {'Дата': 12}, (),
                [('Визитов из поиска', int(d.drop(columns='Дата').values.sum()))], None, red=())
    if ws is not None:
        notes_of(ws)
    return ws


def overview(wb, res, site):
    num_ = lambda v: int(v) if pd.notna(v) and v else 0   # NaN or 0 — это NaN, int(NaN) падает (у кампаний VK нет «принято»)
    MK = res.get('marketing') or {}
    S = (res.get('sheets') or {}).get('Маркетинг', {})
    if 'Обзор' in wb.sheetnames: del wb['Обзор']
    ws = wb.create_sheet('Обзор', 0)
    W = Wide(ws)
    brand_header(ws, W, res, last='I', site=site.upper())
    names = set(wb.sheetnames)
    W.r += 1
    Q = MK.get('качество'); RI = MK.get('реклама_итог') or {}
    ppl = int(Q['людей'].sum()) if Q is not None else 0
    acc = int(Q['заявок_людей'].sum()) if Q is not None else 0
    W.kpis([('Визитов людей', ppl), ('Принято заявок', acc), ('Конверсия, %', round(acc / max(1, ppl) * 100, 3)), ('Рекламных кликов', int(RI.get('кликов', 0))),
            ('Из них людей', int(RI.get('людей', 0))), ('Впустую', int(RI.get('впустую', 0))), ('Фальшивых заявок', int(Q['заявок_ботов'].sum()) if Q is not None else 0)])
    if Q is not None and len(Q):
        W.block('channels')
        W.table(['Канал', 'Людей', 'Доля ботов, %', 'Заявок людей', 'Конверсия, %', 'Фальшивых, %'],
                [[r['канал'], int(r['людей']), r['доля_ботов_%'], int(r['заявок_людей']), r['конверсия_людей_%'], r['фальшивых_заявок_%']] for _, r in Q.head(8).iterrows()],
                ['BC', 'D', 'E', 'F', 'G', 'H'], num=(1, 3))
        W.links_of('channels', names)
    G = MK.get('реклама_по_системам')
    if G is not None and len(G) and {'визитов', 'мгновенный_уход_%', 'принято', 'конверсия_%'} <= set(G.columns):   # людей по рекламе нет — метрик нет, блока нет
        W.block('ads')
        G = G.sort_values('кликов', ascending=False)
        W.table(['Система', 'Кликов', 'Людей', 'Ушли сразу, %', 'Принято', 'Конверсия, %'],
                [[r['channel_sub'], int(r['кликов']), int(r['визитов']), r['мгновенный_уход_%'], int(r['принято']), r['конверсия_%']] for _, r in G.head(6).iterrows()],
                ['BC', 'D', 'E', 'F', 'G', 'H'], num=(1, 2, 4))
        W.links_of('ads', names)
    K = (MK.get('реклама_боты') or {}).get('Кампании')
    KP = S.get('Реклама: Кампании')
    if K is not None and len(K):
        M = K.merge(KP, on='кампания', how='left') if KP is not None else K
        M = M.sort_values('визитов_всех', ascending=False)
        W.block('campaigns')
        W.table(['Кампания', 'Кликов', 'Впустую', 'Ботов, %', 'Принято'],
                [[str(r['кампания']) or '(без метки)', int(r['визитов_всех']), int(r['впустую']), r['доля_ботов_%'], num_(r.get('принято', 0))] for _, r in M.head(6).iterrows()],
                ['BCDE', 'F', 'G', 'H', 'I'], num=(1, 2, 4), wrap=0.95)
        W.links_of('campaigns', names)
    for key, code, n_ in (('фразы_топ', 'phrases', 10), ('фразы_с_заявками', 'phrases_leads', 5)):
        T = MK.get(key)
        if T is None or not len(T): continue
        W.block(code)
        W.table(['Фраза', 'Кликов', 'Людей', 'Впустую', 'Принято', 'Конверсия, %'],
                [[str(r['фраза']), num_(r['визитов_всех']), num_(r['визитов']), num_(r['впустую']), num_(r['принято']), r['конверсия_%']] for _, r in T.head(n_).iterrows()],
                ['BCD', 'E', 'F', 'G', 'H', 'I'], num=(1, 2, 3, 4), wrap=0.95)
        W.links_of(code, names)
    T = MK.get('регионы_топ')
    if T is not None and len(T):
        W.block('regions')
        W.table(['Регион', 'Область', 'Кликов', 'Людей', 'Впустую', 'Принято'],
                [[r['регион'] or str(r['region']), r['область'], num_(r['визитов_всех']), num_(r['визитов']), num_(r['впустую']), num_(r['принято'])] for _, r in T.iterrows()],
                ['BC', 'DE', 'F', 'G', 'H', 'I'], num=(2, 3, 4, 5), wrap=0.95)
        W.links_of('regions', names)
    OFF = S.get('Площадки к отключению')
    if OFF is not None and len(OFF):
        W.block('placements_off')
        W.table(['Площадка', 'Тип', 'Визитов', 'Почему'], [[r['source'], r['тип'], int(r['визитов']), r['почему']] for _, r in OFF.head(6).iterrows()],
                ['BC', 'D', 'E', 'FGHI'], num=(2,), wrap=0.95)
        W.links_of('placements_off', names, count=len(OFF))
    LB = S.get('Метки: проблемы')
    if LB is not None and len(LB):
        W.block('tags')
        W.table(['Проблема', 'Кликов', 'Пример'], [[r['проблема'], int(r['кликов']), str(r['пример'])[:120]] for _, r in LB.iterrows()], ['BC', 'D', 'EFGHI'], num=(1,), wrap=0.95)
    W.related(res, 'Маркетинг')
    W.finish()   # блоки — в порядке каталога (#11)
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws


def build(wb, res, S, site):
    for k_ in list(wb.sheetnames):
        if k_ not in ('Проблемы',): del wb[k_]
    build_sheets(wb, res, S)
    from .catalog import prune
    prune(wb, 'Маркетинг')   # до Обзора: строки на невыведенные листы не появляются (#8)
    overview(wb, res, site)
    byname = {w.title: w for w in wb._sheets}
    head_ = [byname[n_] for n_ in catalog_order('Маркетинг') if n_ in byname]   # порядок — из каталога (#8)
    wb._sheets = head_ + [w for w in wb._sheets if w not in head_]
