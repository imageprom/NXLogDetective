#!/usr/bin/env python3
"""NX Log Detective — запуск из командной строки.

Пример:
  python3 nxld_run.py --logs ./logs --work ./work --out ./out
  python3 nxld_run.py --logs ./logs --work ./work --out ./out --blocks errors,bots --check-ips 1.2.3.4,5.6.7.8
  python3 nxld_run.py --work ./work --out ./out --stage analyze      # пересчитать блоки без повторного разбора логов

Этапы: prepare (разбор логов, ~1–3 мин на 10 млн строк), analyze (блоки), report (Excel, Redmine, снимок, архив).
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nxld import prepare, analyze, report

BLK = {'overview': 'Общий анализ', 'errors': 'Ошибки', 'load': 'Нагрузка и безопасность', 'security': 'Нагрузка и безопасность', 'bots': 'Боты', 'marketing': 'Маркетинг', 'seo': 'SEO'}


def main():
    ap = argparse.ArgumentParser(description='NX Log Detective')
    ap.add_argument('--logs', nargs='*', default=[], help='файлы или папки с логами (.log, .gz, .zip)')
    ap.add_argument('--work', required=True, help='рабочая папка (промежуточные таблицы)')
    ap.add_argument('--out', help='папка для результата')
    ap.add_argument('--blocks', default='all', help='overview,errors,load,bots,marketing,seo или all (overview и errors — всегда)')
    ap.add_argument('--check-ips', default='', help='IP через запятую для проверки')
    ap.add_argument('--marks', default=None, help='JSON {ключ_проблемы: комментарий} — отметки «это норма» или прошлый снимок .snapshot.json')
    ap.add_argument('--map-override', default=None, help='JSON с поправками карты сайта (site_hosts, staff_ips, catalog_templates ...)')
    ap.add_argument('--prev', default=None, help='снимок прошлой проверки (.snapshot.json) — для сравнения')
    ap.add_argument('--edits', default=None, help='JSON с правками находок после расследования (add/remove/update)')
    ap.add_argument('--redmine', default=None, help='текст для Redmine, написанный ИИ (по умолчанию work/NXLD_Redmine.textile, если есть)')
    ap.add_argument('--only', default=None, help='собрать только эти файлы: overview,errors,load,bots,marketing (для отладки отчётов; без текста, снимка и архива)')
    ap.add_argument('--stage', default='all', choices=['all', 'prepare', 'analyze', 'report'])
    ap.add_argument('--site', default=None)
    a = ap.parse_args()
    sel = None if a.blocks == 'all' else sorted({BLK[x.strip()] for x in a.blocks.split(',') if x.strip()}, key=list(BLK.values()).index)
    marks = None
    if a.marks:
        j = json.load(open(a.marks, encoding='utf-8'))
        marks = j.get('marks', j) if isinstance(j, dict) else None
    ovr = json.load(open(a.map_override, encoding='utf-8')) if a.map_override else None
    if a.stage in ('all', 'prepare'):
        prepare.run(a.logs, a.work, map_override=ovr)
    if a.stage in ('all', 'analyze'):
        prev = json.load(open(a.prev, encoding='utf-8')) if a.prev else None
        analyze.run(a.work, sel, [x.strip() for x in a.check_ips.split(',') if x.strip()], marks, prev)
    if a.stage in ('all', 'analyze', 'report') and a.out:
        import pickle
        res = pickle.load(open(os.path.join(a.work, 'results.pkl'), 'rb'))
        edits = json.load(open(a.edits, encoding='utf-8')) if a.edits else None
        rm = a.redmine or os.path.join(a.work, 'NXLD_Redmine.textile')
        only = {BLK[x.strip()] for x in a.only.split(',') if x.strip()} if a.only else None
        out = report.build(res, a.out, a.site, edits, rm, only, a.work)
        if not os.path.exists(rm) and not only:
            print('Текста для Redmine от ИИ нет — в архив положен черновик движка (NXLD_Redmine_черновик.textile). Напишите текст по work/brief.json (он пересобран с правками) и пересоберите --stage report.')
        print('Готово:', out['zip'] or ', '.join(out['files']))


if __name__ == '__main__':
    main()
