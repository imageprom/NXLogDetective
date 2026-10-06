#!/usr/bin/env python3
"""Обновить официальные списки сетей поисковых и ИИ-роботов (data/reference/robot_ranges.json).

Источник — github.com/lord-alfred/ipranges (CC0): ежедневно собирает официальные JSON-списки Google, Bing, OpenAI, Perplexity, DuckDuckGo.
Без ключей и регистрации (ТЗ 10.7). Запуск: python3 tools/update_robot_ranges.py [--src папка_клона]"""
import argparse, datetime, json, os, subprocess, tempfile

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'reference', 'robot_ranges.json')
FAM = {'googlebot': ['Googlebot', 'Googlebot-Image'], 'bing': ['Bingbot'],
       'openai': ['GPTBot (OpenAI)', 'OAI-SearchBot (OpenAI)', 'ChatGPT-User (OpenAI)'], 'perplexity': ['PerplexityBot'], 'duckduckbot': ['DuckDuckBot']}
OFFICIAL = {'googlebot': 'https://developers.google.com/search/apis/ipranges/googlebot.json', 'bing': 'https://www.bing.com/toolbox/bingbot.json',
            'openai': 'https://openai.com/gptbot.json, https://openai.com/searchbot.json, https://openai.com/chatgpt-user.json',
            'perplexity': 'https://www.perplexity.com/perplexitybot.json', 'duckduckbot': 'https://duckduckgo.com/duckduckbot.json'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', help='готовый клон lord-alfred/ipranges')
    a = ap.parse_args()
    src = a.src
    if not src:
        src = tempfile.mkdtemp()
        subprocess.run(['git', 'clone', '-q', '--depth', '1', 'https://github.com/lord-alfred/ipranges.git', src], check=True)
    when = subprocess.run(['git', '-C', src, 'log', '-1', '--format=%cs'], capture_output=True, text=True).stdout.strip() or datetime.date.today().isoformat()
    out = {'_о_файле': 'Официальные сети роботов: подлинный робот приходит только из них. Для семейств без списка подлинность — по ASN (engine/nxld/ipdb.py, VERIFIED).',
           'источник': 'github.com/lord-alfred/ipranges (CC0), официальные списки: ' + '; '.join(f'{k}: {v}' for k, v in OFFICIAL.items()),
           'получено': when, 'семейства': {}}
    for d, fams in FAM.items():
        p = os.path.join(src, d, 'ipv4_merged.txt')
        if not os.path.exists(p): continue
        nets = [x.strip() for x in open(p) if x.strip() and not x.startswith('#')]
        for f in fams: out['семейства'][f] = nets
    json.dump(out, open(REF, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('семейств:', len(out['семейства']), 'от', when)


if __name__ == '__main__':
    main()
