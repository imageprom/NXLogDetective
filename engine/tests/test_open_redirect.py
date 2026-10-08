"""Открытый редирект: один обработчик — одна карточка, только известные обработчики движков; ссылка в параметре
у произвольного адреса — зонд (SSRF) в «Атаках в параметрах»; переадресация на https — не в счёт (задача #4)."""
from datetime import timedelta

import synth

UA_BOT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
HTTPS_301 = 162   # размер ответа nginx «301 Moved Permanently» при переадресации http → https
VARIANTS = ['/bitrix/redirect.php', '//bitrix/redirect.php', '///bitrix/redirect.php', '/bitrix//redirect.php', '//bitrix//redirect.php',
            '/bitrix///redirect.php', '////bitrix/redirect.php', 'http://site.ru/bitrix/redirect.php', 'http://site.ru//bitrix//redirect.php',
            'https://www.site.ru///bitrix/redirect.php']


def _log():
    log = synth.Log()
    log.people()
    k = 0
    for rep in range(4):   # десятки вариантов одного обработчика: повторные «/», схема и хост своего сайта
        for v in VARIANTS:
            ip = f'51.15.{rep}.{k % 200 + 1}'; k += 1
            log.line(ip, synth.T0 + timedelta(days=k % 7, hours=6, seconds=k), f'{v}?goto=https://spam.example.org/p{k}', 302, ua=UA_BOT, size=0)
    for j in range(30):   # переадресация сайта на https — обычные страницы, тот же размер ответа
        log.line(f'95.165.7.{j + 1}', synth.T0 + timedelta(days=j % 7, hours=7, seconds=j), '/catalog/', 301, size=HTTPS_301)
    for j in range(5):   # тот же обработчик, но ответ — переадресация на https (размер как у обычных страниц): не в счёт
        log.line(f'51.15.9.{j + 1}', synth.T0 + timedelta(days=j, hours=8), f'/bitrix/rk.php?goto=https://spam.example.org/x{j}', 301, ua=UA_BOT, size=HTTPS_301)
    for j in range(6):   # произвольный адрес с параметром-ссылкой — зонд SSRF, не открытый редирект
        log.line(f'51.15.8.{j + 1}', synth.T0 + timedelta(days=j, hours=9), '/api/fetch?url=http://169.254.169.254/latest/meta-data/', 301, ua=UA_BOT, size=0)
    return log


def test_open_redirect_one_card_per_handler(tmp_path):
    res, _, _ = synth.run(_log(), str(tmp_path))
    od = [x for x in res['findings'] if x['key'].split(':')[1] == 'open_redirect']
    assert [x['key'] for x in od] == ['Нагрузка и безопасность:open_redirect:/bitrix/redirect.php'], [x['key'] for x in od]
    assert 'вероятно' in (od[0]['что_происходит'] + od[0]['факты']).lower() and 'https' in od[0]['факты']
    assert od[0]['главная_цифра'] == len(VARIANTS) * 4
    A = res['security']['атаки']
    ssrf = A[A['адрес'].astype(str).str.startswith('/api/fetch')]
    assert len(ssrf) and ssrf['вид'].astype(str).str.contains('SSRF').all(), A[['адрес', 'вид']]
