"""#19: «Меры по IP» (и STIX из них) — по окончательной важности дел: после пересчёта тревог и правок Детектива."""
import os
import pickle
import tempfile

import pandas as pd

import synth
from nxld import alarms, analyze, prepare, profiles


def _case(**kw):
    x = dict(дело='D1', кличка='k', важность='Тревога', важность_без_тревоги='К сведению', тревога_по=dict(файлы=['/.env'], сбой=False),
             обвинения=[dict(статья='Разведка')], сигнатура=dict(ложных=0), ips=['198.51.100.7'], вес=10, запросов=5)
    x.update(kw)
    return x


def _res(case, verdict):
    M = pd.DataFrame([dict(ip='198.51.100.7', дело=case['дело'], кличка='k', тип_сети='дата-центр', запросов=5, приговор=verdict, основание='Разведка; людей из этой сети нет'),
                      dict(ip='203.0.113.9', дело='', кличка='', тип_сети='', запросов=1, приговор='не трогать', основание='сотрудник')])
    return {'profiles': dict(дела=[case], меры_ip=M, меры_ip_люди=[]), 'security': {'утечки': pd.DataFrame([dict(файл='/.env', проверка='закрыт: 404', тревога=False, открыт_сейчас=True)])}}


def test_alarm_removed_changes_verdict():
    case = _case()
    res = _res(case, 'заблокировать')   # меры собраны, пока тревога стояла
    alarms.recheck_cases(res)   # тревога снята проверкой из сети: файл закрыт
    assert case['важность'] == 'К сведению'
    profiles.remeasure(res)
    M = res['profiles']['меры_ip'].set_index('ip')
    assert M.at['198.51.100.7', 'приговор'] == 'наблюдать' and 'к сведению' in M.at['198.51.100.7', 'основание']
    assert M.at['203.0.113.9', 'приговор'] == 'не трогать'   # свои — без изменений


def test_remeasure_keeps_table_when_nothing_changed():
    case = _case(важность='Важно', важность_без_тревоги='Важно')
    res = _res(case, 'заблокировать')
    before = res['profiles']['меры_ip']
    profiles.remeasure(res)
    assert res['profiles']['меры_ip'] is before


def test_detective_importance_edit_changes_verdict():
    case = _case(важность='Срочно', важность_правка='К сведению', тревога_по={})
    res = _res(case, 'заблокировать')
    alarms.recheck_cases(res)   # важность, поставленная Детективом (edits.json → «дела»), пересчёт тревог не перетирает
    profiles.remeasure(res)
    assert res['profiles']['меры_ip'].set_index('ip').at['198.51.100.7', 'приговор'] == 'наблюдать'


def test_analyze_builds_measures_after_alarm_recheck(monkeypatch):
    """В analyze пересчёт тревог идёт до «Мер по IP»: подменённый пересчёт, понизивший дела до «к сведению», виден в мерах."""
    monkeypatch.setenv('NXLD_STRICT_CATALOG', '1')
    called = []
    orig = alarms.recheck_cases

    def lowered(res):
        for x in (res.get('profiles') or {}).get('дела') or []: x['важность'] = 'К сведению'
        called.append(1)
        return orig(res) if False else None
    monkeypatch.setattr(alarms, 'recheck_cases', lowered)
    log = synth.Log()
    log.people()
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        log.write(path)
        prepare.run([path], work, log=lambda *a: None)
        res = analyze.run(work, log=lambda *a: None)
        M = res['profiles']['меры_ip']
        assert called, 'пересчёт тревог в analyze не вызывался'
        assert len(M[M['дело'] != '']) > 0 and set(M.loc[M['дело'] != '', 'приговор']) <= {'наблюдать', 'не трогать'}, M[['ip', 'приговор']]
