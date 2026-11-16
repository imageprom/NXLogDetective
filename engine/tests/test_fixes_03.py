"""Исправления по ходу 0.3: #28 (конец окна сбоя), #29 (журналы 05 и 06 теряли день), код страны «NA». Данные вымышленные."""
import os, sys
from types import SimpleNamespace
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import numpy as np, pandas as pd
from nxld import errors, ipdb, marketing, seo

T0 = int(pd.Timestamp('2026-09-01 10:00:00').timestamp())


def test_outage_request_count_stops_at_window_end():
    """#28: окно сбоя 10:00–10:02 кончается в 10:02:59; запрос в 10:03:30 в «запросов за время сбоя» не входит."""
    ts = np.array([T0 - 1, T0, T0 + 60, T0 + 179, T0 + 180, T0 + 210, T0 + 238])
    X = pd.DataFrame([dict(начало='2026-09-01 10:00:00', конец='2026-09-01 10:02:59', деградация_с='2026-09-01 10:00:00', деградация_по='2026-09-01 10:02:59')])
    D = errors.outages(SimpleNamespace(R=pd.DataFrame({'ts': ts})), X)
    assert int(D['запросов'].iloc[0]) == 3


def _j0(days):
    return pd.DataFrame([dict(день=d, _с='00:00', _по='23:59', _полный=True) for d in days] + [dict(день='Итого')])


def test_marketing_journal_keeps_day_without_people():
    """#29: в день без визитов людей рекламные клики ботов и их заявки остаются в журнале 05."""
    V = pd.DataFrame([dict(day='2026-09-01', group='Люди', channel='Реклама', n_goal=1, n_conv=1, entry_status=200),
                      dict(day='2026-09-02', group='Боты', channel='Реклама', n_goal=2, n_conv=2, entry_status=200),
                      dict(day='2026-09-02', group='Боты', channel='Прямые заходы', n_goal=0, n_conv=1, entry_status=200)])
    J = marketing.journal(V, _j0(['2026-09-01', '2026-09-02'])).set_index('день')
    assert J.loc['2026-09-02', 'Рекламные клики|Ботов'] == 1 and J.loc['2026-09-02', 'Рекламные клики|Впустую'] == 1 and J.loc['2026-09-02', 'Заявки|От ботов'] == 3
    assert J.loc['2026-09-01', 'Визиты людей|Реклама'] == 1 and J.loc['2026-09-02', 'Визиты людей|Все'] == 0
    assert J.loc['Итого', 'Рекламные клики|Ботов'] == 1 and J.loc['Итого', 'Заявки|От ботов'] == 3


def test_seo_journal_keeps_day_without_search_robots():
    """#29: в день без поисковых роботов визиты людей из поиска остаются в журнале 06."""
    R = pd.DataFrame({'day': pd.Categorical(['2026-09-01', '2026-09-01', '2026-09-02']), 'fam': pd.Categorical(['YandexBot', 'YandexBot', '']), 'status': [200, 404, 200]})
    V = pd.DataFrame([dict(day='2026-09-01', group='Люди', channel='Поиск', n_conv=0), dict(day='2026-09-02', group='Люди', channel='Поиск', n_conv=1),
                      dict(day='2026-09-02', group='Люди', channel='Поиск', n_conv=0)])
    J = seo.journal(SimpleNamespace(R=R, V=V), np.array([True, True, False]), _j0(['2026-09-01', '2026-09-02'])).set_index('день')
    assert J.loc['2026-09-02', 'Люди из поиска|Визитов'] == 2 and J.loc['2026-09-02', 'Люди из поиска|Заявок'] == 1
    assert J.loc['2026-09-01', 'Запросы поисковиков|Яндекс'] == 2 and J.loc['2026-09-01', 'Ответы роботам|Ошибок 4xx'] == 1 and J.loc['2026-09-02', 'Запросы поисковиков|Яндекс'] == 0
    assert J.loc['Итого', 'Люди из поиска|Визитов'] == 3


def test_country_code_na_is_namibia_not_missing():
    """Код страны «NA» в базе стран — Намибия; раньше при чтении он превращался в «пусто»."""
    s, e, cc = ipdb._load()['c']
    assert not pd.isna(pd.Series(cc)).any()
    i = int(np.where(cc == 'NA')[0][0])
    n = int(s[i])
    ip = '.'.join(str((n >> k) & 255) for k in (24, 16, 8, 0))
    assert ipdb.lookup([ip])['cc'].iloc[0] == 'NA'


def test_paren_values_keep_decimal_comma():
    """«…ошибки: 16,6% запросов» — число с запятой остаётся как есть (было «(16),6%»); «Googlebot: 28, YandexBot: 15» по-прежнему в скобках."""
    import openpyxl
    from nxld.report_tables import paren_values
    wb = openpyxl.Workbook(); ws = wb.active
    ws['A1'] = 'Поисковые роботы получают ошибки: 16,6% запросов'
    ws['A2'] = 'Googlebot: 28, YandexBot: 15'
    ws['A3'] = 'Трафик: 1,5 МБ; запросов: 1 234, людей: 7'
    paren_values(wb)
    assert ws['A1'].value == 'Поисковые роботы получают ошибки: 16,6% запросов'
    assert ws['A2'].value == 'Googlebot (28), YandexBot (15)'
    assert ws['A3'].value == 'Трафик: 1,5 МБ; запросов (1 234), людей (7)'


def test_severity_set_by_edit_is_not_overridden_by_alarm():
    """Важность, заданную правкой Детектива, пересчёт тревог не трогает; причина, по которой движок поднял бы тревогу, остаётся на карточке."""
    from nxld import alarms, edits

    def res():
        return dict(findings=[dict(key='Безопасность:pd_in_get:all', блок='Безопасность', важность='Важно', что_происходит='x', главная_цифра=40),
                              dict(key='Безопасность:webshell:all', блок='Безопасность', важность='Важно', что_происходит='y', главная_цифра=1)], security={})
    r = res(); alarms.apply(r)
    assert [x['важность'] for x in r['findings']] == ['Тревога', 'Тревога']
    r = edits.apply(res(), {'update': {'Безопасность:pd_in_get:all': {'важность': 'Замечание'}}}); alarms.apply(r); alarms.apply(r)   # тревоги пересчитываются не один раз
    a, b = r['findings']
    assert a['важность'] == 'Замечание' and 'почему_тревога' not in a and 'персональные данные' in a['тревога_снята_правкой']
    assert b['важность'] == 'Тревога' and b.get('почему_тревога') and 'тревога_снята_правкой' not in b   # карточку без правки тревога поднимает как раньше
    r = edits.apply(res(), {'update': {'Безопасность:pd_in_get:all': {'что_сделать': 'z'}}}); alarms.apply(r)
    assert r['findings'][0]['важность'] == 'Тревога'   # правка другого поля важность не закрепляет


def test_no_search_errors_block_in_errors_overview_catalog():
    """#21: «Поисковые ошибки» живут в 06; на Обзоре 02 такого блока нет ни в каталоге, ни в коде — остаётся ссылка в «Связанном»."""
    import json
    J = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'locale', 'ru', 'report_structure.json'), encoding='utf-8'))
    by = {f['code']: f for f in J['files']}
    assert 'search_errors' not in [b['code'] for b in by['errors']['sheets'][0]['blocks']]
    assert 'search_errors' in [b['code'] for b in by['seo']['sheets'][0]['blocks']]
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nxld', 'report_errors.py'), encoding='utf-8').read()
    assert "W.block('search_errors')" not in src
