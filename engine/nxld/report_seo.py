"""NXLD: файл 06 «SEO» — как поисковики видят сайт, по тем же правилам, что 01–05.

Обзор → Проблемы → Статистика → Обход поисковиками → Файлы для роботов → Паразитные адреса → Поисковые ошибки →
Страницы без обхода → Переадресации у роботов → Органика → ИИ-видимость → Подлинность поисковиков.
Данные — seo.build; паразитные адреса — срез 03 (security), поисковые ошибки — блок 02, органика — блок 05,
ИИ-роботы — блок 04: в своих файлах эти листы при 06 не повторяются, там — ссылка «Связанное в других отчётах»."""
from . import sheets
import pandas as pd
from .report_index import Wide, brand_header, F_NOTE
from .report_tables import data_sheet, journal_sheet, extra_table, split_codes
from .report_bots import notes, ai_sheet
from .report_load import parasites_sheet
from .report_errors import search_errors_sheet
from .report_marketing import organic_sheet

ORDER = sheets.ORDER_06
LINK = sheets.LINK_06
p_ = lambda v: str(v).replace('.', ',')


def relink(findings):
    for x in findings:
        if x.get('блок') == 'SEO' and x.get('лист') in LINK: x['лист'] = LINK[x['лист']]


def _sheet(wb, nm, d, sub, widths, wrap, kpi, kpi_col, row_rule=None, links=()):
    if d is None or not len(d): return None
    if nm not in wb.sheetnames: wb.create_sheet(nm)
    data_sheet(wb, nm, d, nm, sub, widths, wrap=wrap, kpi=kpi, kpi_col=kpi_col, row_rule=row_rule, links=links, red=('Ошибки',))   # ошибки — красным
    return wb[nm]


def build_sheets(wb, res):
    D = res.get('seo') or {}
    S = res.get('sheets') or {}
    E = res.get('errors') or {}
    J = D.get('журнал')
    if J is not None and len(J):
        if 'Статистика' not in wb.sheetnames: wb.create_sheet('Статистика')
        def kpi(body):
            full = body[body['_полный'].astype(bool)] if body['_полный'].astype(bool).any() else body
            return [('Запросов Яндекса в день', int(round(full['Запросы поисковиков|Яндекс'].mean()))), ('Запросов Google в день', int(round(full['Запросы поисковиков|Google'].mean()))),
                    ('Людей из поиска', int(body['Люди из поиска|Визитов'].sum()))]
        journal_sheet(wb, 'Статистика', J, 'Подлинные поисковые роботы по дням: обход, ответы и люди из поиска', kpi, [('Сводка', 'Обзор'), ('Обход', 'Обход поисковиками')],
                      ['Только подлинные роботы: адрес проверен по сетям поисковика. Подделки — на листе «Подлинность поисковиков».',
                       'Ответы роботам: переадресации и ошибки, которые поисковики получили в этот день.'], kpi_col='Ответы роботам|Ошибок 5xx', outages=E.get('сбои'))
    C = D.get('обход')
    if C is not None and len(C):
        d = pd.DataFrame({'Робот': C['робот'], 'Поисковик': C['поисковик'], 'Запросов': C['запросов'], 'Страниц': C['страниц'], 'Разных страниц': C['адресов_страниц'],
                          'С параметрами, %': C['с_параметрами_%'], 'Ответ 2xx, %': C['ответ_2xx_%'], 'Переадресаций, %': C['переадресаций_%'], 'Ошибок 4xx, %': C['ошибок_4xx_%'],
                          'Ошибок 5xx, %': C['ошибок_5xx_%'], 'Трафик, МБ': C['МБ'], 'Последний день': pd.to_datetime(C['последний']).dt.strftime('%d.%m.%Y')})
        ws = _sheet(wb, 'Обход поисковиками', d, 'Как подлинные поисковые роботы обходят сайт: сколько, что и с каким ответом', {'Робот': 26, 'Поисковик': 14}, ('Робот',),
                    [('Роботов', len(d)), ('Запросов', int(d['Запросов'].sum()))], 'Ошибок 4xx, %',
                    row_rule=lambda r: F_NOTE if (r.get('Переадресаций, %') or 0) + (r.get('Ошибок 4xx, %') or 0) + (r.get('Ошибок 5xx, %') or 0) >= 20 else None)
        Sc = D.get('разделы')
        if ws is not None and Sc is not None and len(Sc):
            t = pd.DataFrame({'Раздел': Sc['раздел'], 'Запросов': Sc['запросов'], 'Яндекс': Sc['Яндекс'], 'Google': Sc['Google'], 'Bing': Sc['Bing'], 'Прочие': Sc['прочие'],
                              'Ошибок, %': Sc['ошибок_%'], 'Переадресаций, %': Sc['переадресаций_%']})
            extra_table(ws, t.head(60), 'Разделы глазами поисковиков', 'Страницы по первому сегменту адреса: кто обходит и сколько получает ошибок',
                        row_rule=lambda r: F_NOTE if (r.get('Ошибок, %') or 0) >= 10 else None, red=())
        notes(ws, ['Страниц — запросы страниц (без картинок, стилей и скриптов). С параметрами — доля страниц, открытых с параметрами в адресе: метками, фильтрами, сортировкой.'])
    Fl = D.get('файлы')
    if Fl is not None and len(Fl):
        sp_ = Fl['коды'].map(split_codes)   # ответы и ошибки — отдельно, ошибки красным
        d = pd.DataFrame({'Файл': Fl['файл'], 'Вывод': Fl['вывод'], 'Запросов': Fl['запросов'], 'От поисковиков': Fl['от_поисковиков'], 'Ответы': sp_.str[0], 'Ошибки': sp_.str[1],
                          'Последний ответ': Fl['последний_код'], 'Через переадресацию': Fl['через_переадресацию'], 'Ошибок': Fl['ошибок']})
        ws = _sheet(wb, 'Файлы для роботов', d, 'robots.txt, карты сайта, llms.txt и другие файлы, которые роботы ищут по стандартным адресам', {'Файл': 36, 'Вывод': 26, 'Ответы': 30, 'Ошибки': 30},
                    ('Файл', 'Ответы', 'Ошибки'), [('Файлов', len(d)), ('Не отвечают', int((d['Вывод'] == 'не отвечает').sum()))], 'Последний ответ',
                    row_rule=lambda r: F_NOTE if r.get('Вывод') != 'отвечает' else None)
        notes(ws, ['Здесь только файлы, которые просили поисковики или которые запрашивали не меньше 20 раз: перебор имён сканерами (sitemap-pt-post-1.xml и подобные) — не файлы для роботов.',
                   'Через переадресацию — робот сначала получил 301/302 и только потом файл: обычно так бывает на зеркалах (http, www).'])
    X = res.get('security') or {}
    parasites_sheet(wb, X.get('паразиты'))
    search_errors_sheet(wb, (S.get('Ошибки') or {}).get('Ошибки у поисковиков'))
    A, B = D.get('без_обхода'), D.get('без_людей')
    if (A is not None and len(A)) or (B is not None and len(B)):
        a = pd.DataFrame({'Страница': A['страница'], 'Визитов людей': A['визитов_людей']}) if A is not None and len(A) else pd.DataFrame({'Страница': ['—'], 'Визитов людей': [0]})
        ws = _sheet(wb, 'Страницы без обхода', a, 'Страницы, которые открывают люди, а поисковики за период не открывали', {'Страница': 70}, ('Страница',),
                    [('Без обхода', len(A) if A is not None else 0), ('Страниц людей', int(D.get('страниц_людей') or 0))], 'Визитов людей')
        if ws is not None and B is not None and len(B):
            sp_ = B['коды'].map(split_codes)
            extra_table(ws, pd.DataFrame({'Страница': B['страница'], 'Запросов роботов': B['запросов_роботов'], 'Ответы': sp_.str[0], 'Ошибки': sp_.str[1], 'Последний обход': B['последний_обход']}),
                        'Обходят, но люди не открывают', 'Адреса, на которые поисковики тратят обход, а люди не заходят: дубли, мусорные ссылки, удалённые страницы', wrap=('Страница', 'Ответы', 'Ошибки'), red=('Ошибки',))
        notes(ws, ['Страницы людей — настоящие страницы сайта с 3 и больше визитами людей, без служебных путей, фильтров и скриптов.'])
    R_ = D.get('переадресации')
    if R_ is not None and len(R_):
        d = pd.DataFrame({'Адрес': R_['адрес'], 'Переадресаций': R_['переадресаций'], 'Коды': R_['коды'], 'Роботы': R_['роботы']})
        kpi = [('Адресов', len(d)), ('Переадресаций', int(d['Переадресаций'].sum()))]   # по всем адресам; на лист — 1000 крупнейших
        _sheet(wb, 'Переадресации роботов', d.head(1000), 'Адреса, по которым поисковики получают переадресацию вместо страницы' + (' · на листе — 1000 крупнейших' if len(d) > 1000 else ''),
               {'Адрес': 60, 'Роботы': 44, 'Коды': 18}, ('Адрес', 'Роботы'), kpi, 'Коды')
    organic_sheet(wb, (S.get('Маркетинг') or {}).get('Органика'))
    SB = S.get('Боты') or {}
    ai_sheet(wb, SB.get('ИИ-роботы'), SB.get('ИИ: страницы по запросам людей'), nm='ИИ-видимость',
             title='Как сайт видят нейросети: какие ИИ-роботы читают сайт и что открывают по запросам людей')
    Au = D.get('подлинность')
    if Au is not None and len(Au):
        d = pd.DataFrame({'Робот': Au['робот'], 'Уникальных IP': Au['IP'], 'Подлинных IP': Au['подлинных_IP'], 'Поддельных IP': Au['поддельных_IP'], 'Запросов': Au['запросов'],
                          'Запросов подделок': Au['запросов_подделок'], 'Подделок, %': Au['подделок_%']})
        ws = _sheet(wb, 'Подлинность поисковиков', d, 'Сколько адресов называли себя поисковиком и сколько из них подлинные', {'Робот': 28}, ('Робот',),
                    [('Поддельных IP', int(d['Поддельных IP'].sum())), ('Их запросов', int(d['Запросов подделок'].sum()))], 'Подделок, %',
                    row_rule=lambda r: F_NOTE if (r.get('Подделок, %') or 0) >= 10 else None)
        notes(ws, ['Подлинный — адрес из сетей самого поисковика (проверка по справочнику сетей). Поддельные — боты под чужим именем; кто они и что делали — в файле 04, лист «Подделки».'])


def overview(wb, res, site):
    D = res.get('seo') or {}
    S = res.get('sheets') or {}
    if 'Обзор' in wb.sheetnames: del wb['Обзор']
    ws = wb.create_sheet('Обзор', 0)
    W = Wide(ws)
    brand_header(ws, W, res, f'NX LOG DETECTIVE — SEO {site.upper()}', 'Как поисковики и нейросети видят сайт: что обходят, что получают и что пропускают', last='I')
    names = set(wb.sheetnames)
    W.r += 1
    C = D.get('обход'); Fl = D.get('файлы'); Au = D.get('подлинность')
    eng = C.groupby('поисковик')['запросов'].sum() if C is not None and len(C) else pd.Series(dtype=int)
    org = (S.get('Маркетинг') or {}).get('Органика')
    W.kpis([('Запросов Яндекса', int(eng.get('Яндекс', 0))), ('Запросов Google', int(eng.get('Google', 0))), ('Запросов Bing', int(eng.get('Bing', 0))),
            ('Людей из поиска', int(org.drop(columns='day').values.sum()) if org is not None and len(org) else 0),
            ('Страниц без обхода', len(D.get('без_обхода')) if D.get('без_обхода') is not None else 0),
            ('Поддельных IP', int(Au['поддельных_IP'].sum()) if Au is not None and len(Au) else 0)])
    if C is not None and len(C):
        W.section('Обход', 'Подлинные поисковые роботы: сколько запросов и что получили в ответ.')
        W.table(['Робот', 'Запросов', 'С параметрами, %', 'Переадресаций, %', 'Ошибок 4xx, %', 'Ошибок 5xx, %'],
                [[r['робот'], int(r['запросов']), r['с_параметрами_%'], r['переадресаций_%'], r['ошибок_4xx_%'], r['ошибок_5xx_%']] for _, r in C.head(6).iterrows()],
                ['BC', 'D', 'E', 'F', 'G', 'H'], num=(1,))
        W.link('Обход и разделы', 'Обход поисковиками', names)
    if Fl is not None and len(Fl):
        W.section('Файлы для роботов', 'robots.txt, карта сайта и другие стандартные файлы: отвечают ли.')
        r0 = W.r + 1
        W.table(['Файл', 'Вывод', 'Запросов', 'Ответы', 'Ошибки'], [[r['файл'], r['вывод'], int(r['запросов'])] + list(split_codes(r['коды'])) for _, r in Fl.head(6).iterrows()],
                ['BC', 'D', 'E', 'FG', 'HI'], num=(2,), wrap=0.95)
        W.red(r0, 'H')
        W.link('Все файлы', 'Файлы для роботов', names)
    P = (res.get('security') or {}).get('паразиты')
    if P is not None and len(P):
        W.section('Паразитные адреса', 'Страницы, у которых поисковые роботы обходят тысячи вариантов адреса из-за меток и фильтров.')
        W.tsize = 9   # длинные списки роботов и параметров — шрифтом большой таблицы
        W.table(['Базовый адрес', 'Вариантов', 'Фигуранты', 'Виновники'], [[r['адрес'], int(r['вариантов']), r['фигуранты'], r['виновники']] for _, r in P.head(5).iterrows()], ['BC', 'D', 'EF', 'GHI'], num=(1,), wrap=0.95)
        W.tsize = 11
        W.link('Все страницы', 'Паразитные адреса', names)
    SE = (S.get('Ошибки') or {}).get('Ошибки у поисковиков')
    g = (res.get('сводки') or {}).get('поиск_по_роботам')
    if SE is not None and len(SE) and g is not None:
        W.section('Поисковые ошибки', 'Страницы, которые поисковые роботы получают с ошибкой, — они выпадают из поиска.')
        W.table(['Робот', 'Типов страниц', 'Запросов', 'Ошибок'], [[r['робот'], int(r['типов']), int(r['запросов']), int(r['ошибок'])] for _, r in g.iterrows()], ['B', 'C', 'D', 'E'], num=(1, 2, 3))
        W.link('Все ошибки', 'Поисковые ошибки', names)
    if Au is not None and len(Au):
        F_ = Au[Au['поддельных_IP'] > 0]
        if len(F_):
            W.section('Подлинность поисковиков', 'Под какими поисковиками прячутся боты.')
            W.table(['Робот', 'Подлинных IP', 'Поддельных IP', 'Подделок, %'], [[r['робот'], int(r['подлинных_IP']), int(r['поддельных_IP']), r['подделок_%']] for _, r in F_.head(6).iterrows()],
                    ['BC', 'D', 'E', 'F'], num=(1, 2))
            W.link('Подробно', 'Подлинность поисковиков', names)
    W.related(res, 'SEO')
    ws.page_setup.orientation = 'portrait'; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws


def build(wb, res, site):
    for k_ in list(wb.sheetnames):
        if k_ not in ('Проблемы',): del wb[k_]
    build_sheets(wb, res)
    overview(wb, res, site)
    byname = {w.title: w for w in wb._sheets}
    head_ = [byname[n_] for n_ in ORDER if n_ in byname]
    wb._sheets = head_ + [w for w in wb._sheets if w not in head_]
