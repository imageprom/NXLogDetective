"""Лог без сессий с каналами (#16): пустые данные не роняют сборку «Каналы подробно» и остальной маркетинг."""
import os
import tempfile
from datetime import timedelta

import synth

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


def _log():
    log = synth.Log()
    for i in range(300):   # 20 IP из TEST-NET, без реферера, коды 200/404
        log.line(f'203.0.113.{i % 20 + 1}', synth.T0 + timedelta(minutes=i), f'/page{i % 7}', 200 if i % 9 else 404, ua=UA)
    return log


def test_log_without_channel_sessions_builds():
    with tempfile.TemporaryDirectory() as d:
        res, out, text = synth.run(_log(), d)
        assert os.path.exists(os.path.join(out, 'NXLD_05_Marketing.xlsx'))
        assert 'KeyError' not in text
