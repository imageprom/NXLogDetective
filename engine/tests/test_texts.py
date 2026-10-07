"""Тексты карточек: число согласовано со словом, десятичная запятая; справочник сигнатур хранит сайт отпечатком."""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'engine'))
from nxld.findings_text import tidy  # noqa: E402


def test_agreement():
    assert tidy('Адреса без косой черты (1501 адресов)') == 'Адреса без косой черты (1501 адрес)'
    assert tidy('2 дней, 1 визитов, 11 запросов, 22 файлов') == '2 дня, 1 визит, 11 запросов, 22 файла'
    assert tidy('с 21 адресов') == 'с 21 адреса'
    assert tidy('1 533 запросов') == '1 533 запроса'


def test_decimal_comma():
    assert tidy('людям 0.7%, трафик 3.1 ГБ') == 'людям 0,7%, трафик 3,1 ГБ'
    assert tidy('IP 1.2.3.4, версия 0.2.2') == 'IP 1.2.3.4, версия 0.2.2'


def test_signatures_store_fingerprints():
    J = json.load(open(os.path.join(ROOT, 'data', 'reference', 'learned', 'signatures.json'), encoding='utf-8'))
    sites = {k for e in J.get('сигнатуры', {}).values() for k in e.get('сайты', {})}
    assert all(s.startswith('сайт-') for s in sites), sorted(s for s in sites if not s.startswith('сайт-'))
