"""Робот веб-архива (Internet Archive, Wayback Machine): подписи, сеть AS7941, сохранение страницы по сети и почерку, отказы, обход в минуты сбоя. Синтетика, example.com;
IP архива — из его префиксов (не личные данные)."""
import json
import os
import pickle
import tempfile
from datetime import timedelta

import synth
from nxld import analyze, prepare

T0 = synth.T0
UA_IA = 'Mozilla/5.0 (compatible; archive.org_bot +http://www.archive.org/details/archive.org_bot)'
UA_SA = 'Mozilla/5.0 (compatible; special_archiver/3.1.1 +http://www.archive.org/details/archive.org_bot)'
IA_IP, IA_IP2, SPN_IP, FAKE_IP = '207.241.224.5', '208.70.24.7', '207.241.225.10', '203.0.113.9'
SAVE_LABEL = 'Internet Archive: сохранение страницы (по сети и почерку)'


def _base():
    log = synth.Log()
    log.people()
    return log


def _crawl(log, ip, ua, n=12, day=1, hour=3, statuses=None, pace=2, robots=True):
    """Обход архива: robots.txt и n страниц, по статусам из списка (по кругу)."""
    t = T0 + timedelta(days=day, hours=hour)
    if robots: log.line(ip, t, '/robots.txt', 200, ua=ua)
    for k in range(n):
        log.line(ip, t + timedelta(seconds=pace * (k + 1)), f'/catalog/page{k}/', (statuses or [200])[k % len(statuses or [200])], ua=ua)


def _save_page(log, ip=SPN_IP, day=2, hour=5, resources=30):
    """Сохранение страницы: браузерная подпись, страница и её ресурсы за минуту."""
    t = T0 + timedelta(days=day, hours=hour)
    log.line(ip, t, '/about/', 200)
    for k in range(resources): log.line(ip, t + timedelta(seconds=1 + k * 2), f'/upload/iblock/{k}.jpg', 200, ref='https://site.ru/about/')


def _run(log):
    os.environ['NXLD_STRICT_CATALOG'] = '1'
    with tempfile.TemporaryDirectory() as d:
        path, work = os.path.join(d, 'access.log'), os.path.join(d, 'work')
        log.write(path)
        prepare.run([path], work, log=lambda *a: None)
        dump = os.path.join(d, 'ctx.pkl')
        os.environ['NXLD_DUMP_CTX'] = dump
        try: res = analyze.run(work, log=lambda *a: None)
        finally: os.environ.pop('NXLD_DUMP_CTX', None)
        c = pickle.load(open(dump, 'rb'))[0]
        brief = json.load(open(os.path.join(work, 'brief.json'), encoding='utf-8'))
    return res, c, brief


def _visits(c, ip):
    V = c.V
    return V[V['ip'].astype(str) == ip]


def _cards(res): return {x['key'].split(':')[1]: x for x in res['findings'] if x['key'].split(':')[1].startswith('web_archive')}


def test_signed_archive_from_its_network_is_robot_web_archive():
    log = _base()
    _crawl(log, IA_IP, UA_IA); _crawl(log, IA_IP2, UA_SA)
    res, c, _ = _run(log)
    for ip in (IA_IP, IA_IP2):
        v = _visits(c, ip)
        assert len(v) and set(v['group'].astype(str)) == {'Роботы'} and set(v['fam'].astype(str)) == {'Internet Archive'} and set(v['fam_cat'].astype(str)) == {'веб-архив'}, (ip, v[['group', 'fam']])
    t = res['actors']['роботы']
    r = t[t['робот'] == 'Internet Archive'].iloc[0]
    assert r['категория'] == 'веб-архив' and r['подлинных'] == 1 and r['запросов'] == 26


def test_signature_from_foreign_network_is_fake_robot():
    log = _base()
    _crawl(log, IA_IP, UA_IA); _crawl(log, FAKE_IP, UA_IA)
    res, c, _ = _run(log)
    v = _visits(c, FAKE_IP)
    assert set(v['group'].astype(str)) == {'Боты'} and set(v['subgroup'].astype(str)) == {'подделки роботов'}, v[['group', 'subgroup']]
    assert set(_visits(c, IA_IP)['group'].astype(str)) == {'Роботы'}
    assert res['web_archive']['fake']['requests'] == 13 and res['web_archive']['requests'] == 13   # подделка в счёт архива не идёт


def test_save_page_from_archive_network_without_signature():
    log = _base()
    _save_page(log)
    res, c, brief = _run(log)
    v = _visits(c, SPN_IP)
    assert len(v) == 1 and v['group'].iloc[0] == 'Роботы' and v['fam'].astype(str).iloc[0] == SAVE_LABEL and v['fam_cat'].astype(str).iloc[0] == 'веб-архив', v[['group', 'fam']]
    assert res['web_archive']['save_page']['visits'] == 1 and res['web_archive']['came']
    cand = [x for x in brief['signature_candidates'] if x['kind'] == 'web_archive_save']
    assert len(cand) == 1 and cand[0]['level'] == 'network_and_pattern' and cand[0]['to_verify'] is True and cand[0]['median_requests'] == 31 and cand[0]['asn'] == 7941, cand
    t = res['actors']['роботы']
    assert SAVE_LABEL in set(t['робот'])   # строка в существующей таблице роботов 04


def test_archive_network_visit_not_like_save_page_stays_as_is():
    log = _base()
    t = T0 + timedelta(days=2, hours=5)
    log.line(SPN_IP, t, '/about/', 200); log.line(SPN_IP, t + timedelta(minutes=30), '/contacts/', 200)   # две страницы без ресурсов — не пачка сохранения
    res, c, _ = _run(log)
    assert SAVE_LABEL not in set(_visits(c, SPN_IP)['fam'].astype(str)) and res['web_archive']['save_page']['visits'] == 0


def test_refused_card_on_403_and_none_without():
    log = _base()
    _crawl(log, IA_IP, UA_IA, n=24, statuses=[200, 200, 200, 403])
    res, _, _ = _run(log)
    x = _cards(res)['web_archive_refused']
    assert x['важность'] == 'Замечание' and '403' in x['факты'] and '/catalog/' in x['факты'] and 'archive.org_bot' in x['что_сделать'] and 'robots.txt' in x['что_сделать'], x
    assert res['web_archive']['refused']['requests'] == 6 and res['web_archive']['refused']['codes'] == {'403': 6}
    log = _base()
    _crawl(log, IA_IP, UA_IA, n=24)
    assert 'web_archive_refused' not in _cards(_run(log)[0])


def _human_503(log, minute_start, minutes=4, per_minute=40):
    """Люди в минуты сбоя: страница с ресурсами, потом страница с 503."""
    for m in range(minutes):
        t = T0 + timedelta(days=minute_start[0], hours=minute_start[1], minutes=m)
        for k in range(per_minute):
            ip, at = f'95.170.{m}.{k + 1}', t + timedelta(seconds=k % 40)
            log.line(ip, at, '/about/', 200, ref='https://yandex.ru/')
            for a in synth.ASSETS: log.line(ip, at + timedelta(seconds=1), a, 200, ref='https://site.ru/about/')
            log.line(ip, at + timedelta(seconds=10), f'/catalog/item{k % 12}/', 503, ref='https://site.ru/about/')


def _heavy_crawl(log, day, hour, minutes=4, per_minute=60):
    t = T0 + timedelta(days=day, hours=hour)
    for m in range(minutes):
        for k in range(per_minute): log.line(IA_IP, t + timedelta(minutes=m, seconds=k % 59), f'/catalog/deep{k % 12}/', 200, ua=UA_IA)


def test_outage_card_when_crawl_hits_failure_minutes_and_none_when_calm():
    log = _base()
    _heavy_crawl(log, 3, 14); _human_503(log, (3, 14))
    res, _, _ = _run(log)
    x = _cards(res)['web_archive_outage']
    assert x['важность'] == 'Важно' and 'Crawl-delay' in x['что_сделать'] and 'в минуту' in x['факты'], x
    wa = res['web_archive']
    assert wa['outage_coincide']['windows'] >= 1 and wa['outage'][0]['people_5xx'] >= 40 and wa['outage'][0]['archive_peak_per_minute'] >= 60
    log = _base()
    _heavy_crawl(log, 3, 14); _human_503(log, (4, 14))   # обход и сбой в разные часы
    res, _, _ = _run(log)
    assert 'web_archive_outage' not in _cards(res) and res['web_archive']['outage_coincide']['windows'] == 0


def test_no_archive_no_cards_but_brief_has_zero():
    res, _, brief = _run(_base())
    wa = brief['web_archive']
    assert wa['came'] is False and wa['requests'] == 0 and wa['first'] is None and wa['statuses'] == {} and not _cards(res)


def test_brief_numbers_and_comparison_with_previous():
    log = _base()
    _crawl(log, IA_IP, UA_IA, n=10, day=1); _crawl(log, IA_IP, UA_IA, n=10, day=3, statuses=[200, 200, 200, 429])
    res, _, brief = _run(log)
    wa = brief['web_archive']
    assert wa['came'] and wa['requests'] == 22 and wa['pages'] == 20 and wa['robots_txt'] == 2 and wa['days'] == 2 and wa['ips'] == 1
    assert wa['first'].startswith('2026-09-02 03:00') and wa['last'].startswith('2026-09-04 03:00') and wa['statuses'] == {'200': 20, '429': 2} and wa['peak_per_minute']['requests'] >= 1
    from nxld import webarchive
    cmp_ = webarchive.compare(dict(wa, requests=30), dict(wa, requests=22))
    assert cmp_['requests'] == {'was': 22, 'became': 30}
    assert webarchive.compare(wa, None) is None
    snap = res['web_archive']
    assert snap['requests'] == 22


def test_references_web_archive():
    ref = os.path.join(synth.ENGINE, '..', 'data')
    d = json.load(open(os.path.join(ref, 'reference', 'robot_ranges.json'), encoding='utf-8'))
    assert d['семейства']['Internet Archive'] == ['207.241.224.0/20', '208.70.24.0/21']
    from nxld import ipdb, uafam
    assert ipdb.VERIFIED['Internet Archive'] == {7941}
    assert uafam.family('Mozilla/5.0 (compatible; special_archiver/3.1.1)') == ('Internet Archive', 'веб-архив')
    assert uafam.family('CCBot/2.0')[0] == 'CCBot (Common Crawl, открытый архив)' and uafam.family('CCBot/2.0')[1] == 'ИИ: обучение'
    loc = json.load(open(os.path.join(ref, 'locale', 'ru', 'robots.json'), encoding='utf-8'))
    assert loc['types']['web_archive'] == 'веб-архив' and 'archive.today' in loc['notes']['archive_today']
    assert uafam.family('Mozilla/5.0 (compatible; archive.today)') is None or uafam.family('Mozilla/5.0 (compatible; archive.today)')[0] != 'Internet Archive'   # archive.today не опознаётся как Internet Archive


def test_comparison_with_previous_check_in_brief(tmp_path):
    import glob
    a, b = str(tmp_path / 'a'), str(tmp_path / 'b')
    os.makedirs(a); os.makedirs(b)
    log = _base(); _crawl(log, IA_IP, UA_IA, n=10)
    _, out, _ = synth.run(log, a)
    snap = glob.glob(os.path.join(out, '*.snapshot.json'))[0]
    assert json.load(open(snap, encoding='utf-8'))['web_archive']['requests'] == 11   # архив в снимке — всегда
    log = _base(); _crawl(log, IA_IP, UA_IA, n=10); _crawl(log, IA_IP, UA_IA, n=20, day=3)
    synth.run(log, b, '--prev', snap)
    wa = json.load(open(os.path.join(b, 'work', 'brief.json'), encoding='utf-8'))['web_archive']
    assert wa['requests'] == 32 and wa['compare']['requests'] == {'was': 11, 'became': 32} and wa['compare']['refused_requests'] == {'was': 0, 'became': 0}, wa['compare']
