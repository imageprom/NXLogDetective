"""Версия одна: движок (prepare.VERSION), заголовки README и SKILL.md; архив скилла берёт её из движка (tools/build_skill.py)."""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'engine'))
from nxld.prepare import VERSION  # noqa: E402


def test_version_022():
    assert VERSION == '0.2.2'


def test_headers_match_engine():
    for f, rx in (('README.md', r'^# NX Log Detective \(NXLD\) (\S+)$'), (os.path.join('skill', 'SKILL.md'), r'^# NX Log Detective (\S+)$')):
        m = re.search(rx, open(os.path.join(ROOT, f), encoding='utf-8').read(), re.M)
        assert m and m.group(1) == VERSION, (f, m and m.group(1))
