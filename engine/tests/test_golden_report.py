"""Эталонный отчёт: один и тот же вымышленный лог даёт тот же отчёт, лист в лист.

Переделки «под капотом» (слой данных 0.3) не должны менять отчёт. Если отчёт изменён намеренно —
пересоздать эталон: NXLD_GOLDEN_UPDATE=1 python3 -m pytest -q tests/test_golden_report.py
и перечислить изменившиеся листы в описании правки."""
import json, os, sys, tempfile
from datetime import timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import synth, report_digest

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden', 'synth_report.json')
UA_GOOGLE = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
UA_CURL = 'curl/8.4.0'


def golden_log():
    L = synth.Log(seed=7)
    L.people(days=7, per_day=20)
    T0 = synth.T0
    for d in range(7):
        t = T0 + timedelta(days=d)
        for k in range(30):   # поисковый робот из своей сети
            L.line('66.249.66.1', t + timedelta(hours=2, minutes=k), synth.PAGES[k % len(synth.PAGES)], 200, ua=UA_GOOGLE)
        L.line('66.249.66.1', t + timedelta(hours=2, minutes=40), '/robots.txt', 200, ua=UA_GOOGLE, size=120)
        for k in range(12):   # утилита из дата-центра
            L.line('203.0.113.7', t + timedelta(hours=4, seconds=5 * k), f'/catalog/shary/item{k}/', 200, ua=UA_CURL)
        for k in range(3):   # заявки: форма со страницы сайта
            ip = synth.RU[(d + k) % len(synth.RU)]
            L.line(ip, t + timedelta(hours=10 + k, minutes=3), '/contacts/', 200, ref='https://yandex.ru/')
            L.line(ip, t + timedelta(hours=10 + k, minutes=4), '/ajax/form.php?form_id=callback', 200, ref='https://site.ru/contacts/', method='POST', size=60)
        L.line(synth.RU[d % len(synth.RU)], t + timedelta(hours=15), '/catalog/broken/', 500, ref='https://site.ru/catalog/')
        L.line('198.51.100.9', t + timedelta(hours=16), '/akcii/', 200, ref='https://example.com/links/', host='site.ru')
    return L


def test_report_matches_golden():
    with tempfile.TemporaryDirectory() as d:
        _, out, _ = synth.run(golden_log(), d)
        got = {f: {s: h for s, h in ss.items() if not s.startswith('_')} for f, ss in report_digest.digest(out, mask=r'Отчёт от \d+ \S+ \d{4} · NX Log Detective [\w.\-]+').items()}   # служебный лист со снимком хранит время сборки; дата отчёта и версия в шапке «Обзора» — под маской
    if os.environ.get('NXLD_GOLDEN_UPDATE'):
        json.dump(got, open(GOLDEN, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    want = json.load(open(GOLDEN, encoding='utf-8'))
    changed = sorted(f'{f} · {s}' for f in set(got) | set(want) for s in set(got.get(f, {})) | set(want.get(f, {})) if got.get(f, {}).get(s) != want.get(f, {}).get(s))
    assert not changed, 'Отчёт изменился на листах: ' + '; '.join(changed)
