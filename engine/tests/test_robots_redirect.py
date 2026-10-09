"""#9: robots.txt через переадресацию http → https того же пути — норма, карточки нет; на другой путь или без продолжения — карточка."""
from datetime import timedelta

import synth

UA_BOT = 'Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)'


def _log(kind):
    log = synth.Log()
    log.people()
    for i in range(300):
        ip = f'198.51.100.{i % 30 + 1}'
        t = synth.T0 + timedelta(days=i % 7, hours=i % 24, minutes=i % 60)
        log.line(ip, t, '/robots.txt', 301, ua=UA_BOT, size=0)
        if kind == 'https':   # тот же путь уже по https — ответ 200
            log.line(ip, t + timedelta(seconds=1), '/robots.txt', 200, ua=UA_BOT, size=300)
        elif kind == 'path':   # переадресация на другой путь
            log.line(ip, t + timedelta(seconds=1), '/robots/', 200, ua=UA_BOT, size=300)
        # kind == 'away': на другой хост — продолжения в логе нет
    return log


def _card(res):
    return [x for x in res['findings'] if x['key'].split(':')[1] == 'robots_redirect']


def test_https_redirect_is_normal(tmp_path):
    res, _, _ = synth.run(_log('https'), str(tmp_path))
    assert not _card(res), _card(res)
    Fl = res['seo']['файлы']
    r = Fl[Fl['файл'] == '/robots.txt'].iloc[0]
    assert r['через_переадресацию'] == 300 and r['переадресаций_с_проблемой'] == 0 and r['вывод'] == 'отвечает', r


def test_redirect_to_other_path_is_card(tmp_path):
    res, _, _ = synth.run(_log('path'), str(tmp_path))
    assert _card(res)


def test_redirect_away_is_card(tmp_path):
    res, _, _ = synth.run(_log('away'), str(tmp_path))
    assert _card(res)
