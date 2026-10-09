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


# ---- #9, второй круг: улики, а не догадка ----
UA_GOOGLE = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'


def test_robot_pool_followup(tmp_path):
    """Подтверждённый робот берёт продолжение с другого адреса своего пула — переадресация не проблема."""
    log = synth.Log()
    log.people()
    for i in range(300):
        t = synth.T0 + timedelta(days=i % 7, hours=i % 24, minutes=i % 60)
        log.line(f'66.249.66.{i % 20 + 1}', t, '/robots.txt', 301, ua=UA_GOOGLE, size=0)
        log.line(f'66.249.66.{i % 20 + 101}', t + timedelta(seconds=2), '/robots.txt', 200, ua=UA_GOOGLE, size=300)
    res, _, _ = synth.run(log, str(tmp_path))
    assert not _card(res), _card(res)
    r = res['seo']['файлы'].set_index('файл').loc['/robots.txt']
    assert r['переадресаций_с_проблемой'] == 0, r


def test_redirect_then_403(tmp_path):
    """Переадресация, затем 403 на тот же путь — отказ фильтра, не проблема переадресации: карточки про robots.txt нет."""
    log = synth.Log()
    log.people()
    for i in range(300):
        ip = f'198.51.100.{i % 30 + 1}'
        t = synth.T0 + timedelta(days=i % 7, hours=i % 24, minutes=i % 60)
        log.line(ip, t, '/robots.txt', 301, ua=UA_BOT, size=0)
        log.line(ip, t + timedelta(seconds=1), '/robots.txt', 403, ua=UA_BOT, size=150)
    res, _, _ = synth.run(log, str(tmp_path))
    assert not _card(res), _card(res)
    r = res['seo']['файлы'].set_index('файл').loc['/robots.txt']
    assert r['переадресаций_с_отказом'] == 300 and r['переадресаций_с_проблемой'] == 0, r


def test_card_text_and_network_check(tmp_path):
    """Без продолжения: в карточке — что видно по логу, без «другой путь, другой хост»; проверка из сети «тот же путь по https» снимает её."""
    res, _, _ = synth.run(_log('away'), str(tmp_path))
    c = _card(res)[0]
    assert 'по логу не видно' in c['факты'] and 'другой хост' not in c['факты'], c['факты']
    import sys
    sys.path.insert(0, synth.ENGINE)
    from nxld import edits
    res = edits.apply(res, {'проверка_сайта': {'/robots.txt': {'итог': 'отвечает', 'когда': '01.10.2026', 'redirect': 'same_path_https'}}})
    assert not _card(res)
