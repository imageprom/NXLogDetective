"""NXLD: сборка результата — Excel по блокам, текст для Redmine (Textile), снимок, архив."""
import json, os, re, zipfile
from datetime import datetime
import numpy as np, pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from .findings import SEV_ORDER

FILES = {'Общий анализ': '01_Overview', 'Ошибки': '02_Errors', 'Нагрузка и безопасность': '03_Load_Security', 'Боты': '04_Bots', 'Маркетинг': '05_Marketing'}
SEV_FILL = {'Срочно': 'F8D7DA', 'Важно': 'FFF3CD', 'К сведению': 'E2EFDA', 'отмечено как норма': 'EDEDED'}
HDR = PatternFill('solid', fgColor='1F3864')
FONT = 'Arial'

SPAM_TEXT = {
    'спам форм: битый адрес → главная → форма': 'Бот открывает несуществующую страницу без реферера (получает 404), переходит на главную и через 20–40 секунд отправляет форму. Человек так не делает: люди приходят из поиска или рекламы и листают страницы.',
    'спам форм: отправка без просмотра страниц': 'Форма отправляется напрямую, без открытия единой страницы и без загрузки картинок и стилей.',
    'спам форм: быстрый обход и пачка отправок': 'За несколько секунд открывается много страниц и отправляется несколько форм подряд — быстрее, чем может человек.',
    'спам форм: смена IP посреди визита': 'Страницу открыл один IP, а форму с этой страницы отправил другой (видно по рефереру) — признак ротации прокси.',
    'спам форм: быстрая заявка с IP, уже пойманного за неделю': 'Заявка с прямого захода за считанные секунды с IP, который за неделю уже попадался на спаме.',
}


def site_slug(s):
    return re.sub(r'[^\w-]', '_', s)


def safe_sheet(name, used):
    n = re.sub(r'[\[\]*?/\\]', ' ', str(name)).replace(':', ' —')[:31].strip()
    base, k = n, 2
    while n in used:
        n = f'{base[:28]} {k}'; k += 1
    used.add(n)
    return n


def problems_df(items, with_block=False):
    rows = []
    for i, x in enumerate(sorted(items, key=lambda x: (x.get('статус') == 'отмечено как норма', SEV_ORDER[x['важность']])), 1):
        r = {'№': i}
        if with_block: r['Блок'] = x['блок']
        r.update({'Важность': x['статус'] if x.get('статус') == 'отмечено как норма' else x['важность'], 'Что происходит': x['что_происходит'], 'Факты': x['факты'],
                  'Где править': x['где_править'], 'Что сделать': x['что_сделать'], 'Главная цифра': x['главная_цифра'],
                  'Подробно на листе': x['лист'], 'Также в блоках': x['также_в'], 'Статус': x.get('статус', '')})
        rows.append(r)
    return pd.DataFrame(rows, columns=['№'] + (['Блок'] if with_block else []) + ['Важность', 'Что происходит', 'Факты', 'Где править', 'Что сделать', 'Главная цифра', 'Подробно на листе', 'Также в блоках', 'Статус'])


def kv_df(d, a='Показатель', b='Значение'):
    return pd.DataFrame([(k, v if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False, default=str)) for k, v in d.items()], columns=[a, b])


def about_df(res):
    inv, m = res['inventory'], res['site_map']
    eng = ', '.join(e['движок'] for e in m.get('engines', [])) or 'не определён (возможно, статический HTML или свой движок)'
    rows = [('Инструмент', f"NX Log Detective {inv.get('version', '')}"), ('Сайты в логах', ', '.join(m.get('site_hosts', []))),
            ('Период', f"{inv['period'][0]} — {inv['period'][1]}"), ('Часовой пояс лога', inv.get('tz', '')),
            ('Запросов (после удаления дублей)', inv['requests']), ('Уникальных IP', inv['ips']), ('Строк error-лога', inv.get('errors_lines', 0)),
            ('Пропуски по времени (часы без строк)', ', '.join(inv.get('hour_gaps', [])) or 'нет'),
            ('Пересечения файлов', f"{sum(d['lines_duplicate'] for d in inv.get('duplicates', []))} строк-дублей удалено" if inv.get('duplicates') else 'нет'),
            ('Веб-сервер', m.get('server', {}).get('веб-сервер', '')), ('PHP-FPM / upstream', json.dumps(m.get('server', {}).get('upstream', {}), ensure_ascii=False)),
            ('Пути на сервере (из error-лога)', json.dumps(m.get('server', {}).get('пути_на_сервере', {}), ensure_ascii=False)), ('Протоколы', json.dumps(m.get('server', {}).get('протокол', {}), ensure_ascii=False)),
            ('ОС', 'по логам определяется только косвенно (по путям); точнее — у администратора'), ('Движок', eng), ('Адрес админки', m.get('admin_regex', '')),
            ('Цели (формы)', len([f for f in m.get('forms', []) if str(f.get('вывод', '')).startswith('цель')])),
            ('Элементы каталога (шаблоны)', ', '.join(m.get('catalog_templates', [])[:8]) or 'не обнаружены'),
            ('Рекламные метки', ', '.join(m.get('ad_params', {}).keys()) or 'не обнаружены'),
            ('Проверки в интернете', res.get('internet', 'не выполнялись')), ('Сигнатуры', res.get('signatures_note', 'не загружались'))]
    rows += [(f'Очистка: {k}', v) for k, v in res['cleaning'].items()]
    rows += [('Не анализировалось', ', '.join(b for b in FILES if b not in res['selected']) or '—')]
    return pd.DataFrame(rows, columns=['Что', 'Значение'])


def files_df(res):
    return pd.DataFrame(res['inventory']['files'])


def site_map_sheets(m):
    out = {}
    out['Карта: формы и цели'] = pd.DataFrame(m.get('forms', []))
    out['Карта: подгружаемые блоки'] = pd.DataFrame(m.get('embedded_templates', []))
    out['Карта: служебные файлы'] = pd.DataFrame(m.get('service_files', []))
    rows = [('Сайты', ', '.join(m.get('site_hosts', []))), ('Движок', ', '.join(e['движок'] for e in m.get('engines', []))),
            ('Сервер', m.get('server', {}).get('веб-сервер', '')), ('Админка (шаблон адреса)', m.get('admin_regex', '')),
            ('Сотрудники (IP с успешным входом в админку)', ', '.join(m.get('staff_ips', []))),
            ('Мониторинги', '; '.join(f"{x['ip']} → {x['адрес']} каждые {x['интервал_с']} с" for x in m.get('monitors', []))),
            ('Элементы каталога', '\n'.join(m.get('catalog_templates', []))), ('Разделы (визиты людей)', '\n'.join(f'{k}: {v}' for k, v in list(m.get('top_sections', {}).items())[:20])),
            ('Рекламные метки на входах', json.dumps(m.get('ad_params', {}), ensure_ascii=False)), ('Прочие частые параметры входов', json.dumps(m.get('other_entry_params', {}), ensure_ascii=False)),
            ('Запросов с персональными данными в GET', m.get('get_pd_requests', 0))]
    out = {'Карта сайта': pd.DataFrame(rows, columns=['Что', 'Значение']), **out}
    return out


def write_xlsx(path, sheets, hidden=None):
    used = set()
    names = {}
    with pd.ExcelWriter(path, engine='openpyxl') as xw:
        for name, df in sheets.items():
            if df is None: continue
            sn = safe_sheet(name, used)
            names[name] = sn
            d = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
            if not len(d.columns): d = pd.DataFrame({'Нет данных': []})
            for col in d.columns:
                if d[col].dtype == object:
                    d[col] = d[col].map(lambda v: v if not isinstance(v, str) else v[:32000])
                if str(d[col].dtype).startswith('category'):
                    d[col] = d[col].astype(str)
            d.to_excel(xw, sheet_name=sn, index=False)
        if hidden:
            pd.DataFrame({'snapshot': [hidden[i:i + 30000] for i in range(0, len(hidden), 30000)]}).to_excel(xw, sheet_name='_snapshot', index=False)
    wb = load_workbook(path)
    for ws in wb.worksheets:
        if ws.title == '_snapshot':
            ws.sheet_state = 'hidden'; continue
        ws.freeze_panes = 'A2'
        for c in ws[1]:
            c.font = Font(name=FONT, bold=True, color='FFFFFF'); c.fill = HDR; c.alignment = Alignment(wrap_text=True, vertical='center')
        widths = {}
        sev_col = None
        for c in ws[1]:
            if c.value in ('Важность',): sev_col = c.column
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.font = Font(name=FONT, size=10)
                v = c.value
                L = len(str(v)) if v is not None else 0
                widths[c.column] = max(widths.get(c.column, 0), min(L, 70))
                if L > 70: c.alignment = Alignment(wrap_text=True, vertical='top')
                if isinstance(v, datetime): c.number_format = 'yyyy-mm-dd hh:mm'
            if sev_col:
                v = row[sev_col - 1].value
                if v in SEV_FILL:
                    row[sev_col - 1].fill = PatternFill('solid', fgColor=SEV_FILL[v])
        for c in ws[1]:
            widths[c.column] = max(widths.get(c.column, 0), min(len(str(c.value)), 30))
        for col, w in widths.items():
            ws.column_dimensions[get_column_letter(col)].width = max(8, min(w + 2, 72))
    wb.save(path)
    return names


def main_sheet(res, file_names):
    rows = []
    for b in FILES:
        items = [x for x in res['findings'] if x['блок'] == b and x.get('статус') != 'отмечено как норма']
        if b not in res['selected']:
            rows.append({'Блок': b, 'Срочно': 'не анализировалось'}); continue
        cnt = {s: sum(1 for x in items if x['важность'] == s) for s in SEV_ORDER}
        rows.append({'Блок': b, **cnt, 'Где подробно': file_names[b]})
    rows.append({})
    rows.append({'Блок': 'СРОЧНОЕ ПО БЛОКАМ'})
    urgent = [x for x in res['findings'] if x['важность'] == 'Срочно' and x.get('статус') != 'отмечено как норма' and x['блок'] in res['selected']]
    for x in sorted(urgent, key=lambda x: list(FILES).index(x['блок'])):
        rows.append({'Блок': x['блок'], 'Что происходит': x['что_происходит'], 'Главная цифра': x['главная_цифра'], 'Где подробно': f"{file_names[x['блок']]} → лист «{x['лист']}»"})
    return pd.DataFrame(rows, columns=['Блок', 'Срочно', 'Важно', 'К сведению', 'Что происходит', 'Главная цифра', 'Где подробно'])


def snapshot(res, site):
    return dict(tool='NX Log Detective', format='NXLD-snapshot/1', version=res['inventory'].get('version'), site=site, period=res['inventory']['period'],
                created=datetime.now().isoformat(timespec='seconds'), selected=res['selected'], summary=res['summary'], cleaning=res['cleaning'],
                daily=res['sheets'].get('Общий анализ', {}).get('По дням', pd.DataFrame()).to_dict('records'),
                findings=[{k: x.get(k) for k in ('key', 'блок', 'важность', 'что_происходит', 'главная_цифра', 'статус', 'отметка')} for x in res['findings']],
                ips=res['ips'].astype(str).to_dict('records'), marks={x['key']: x.get('отметка', '') for x in res['findings'] if x.get('статус') == 'отмечено как норма'},
                site_map={k: res['site_map'].get(k) for k in ('site_hosts', 'server', 'engines', 'admin_regex', 'forms', 'catalog_templates', 'embedded_templates', 'ad_params')})


def textile(res, site, file_names):
    inv = res['inventory']
    out = [f"h2. NX Log Detective: {site}, {inv['period'][0][:10]} — {inv['period'][1][:10]}", '',
           f"Проверены блоки: {', '.join(res['selected'])}. Запросов: " + f"{inv['requests']:,}".replace(',', ' ') + ". Подробности — в приложенных файлах NXLD_*.xlsx.", '']
    if res.get('compare') is not None:
        st = pd.Series([x.get('статус', '') for x in res['findings']])
        out += [f"h3. С прошлой проверки ({' — '.join(s_[:10] for s_ in res.get('prev_period') or [])})", '',
                f"Новых проблем: {int(st.str.startswith('новая').sum())}, сохраняются: {int(st.str.startswith('сохраняется').sum())}, не обнаружены в новом периоде: {int(st.str.startswith('не обнаружена').sum())}.", '']
    m = res['site_map']
    if not [f for f in m.get('forms', []) if str(f.get('вывод', '')).startswith('цель')]:
        out += ['Форм и целей на сайте не обнаружено — конверсии не считались.', '']
    if not m.get('ad_params'):
        out += ['Рекламных меток не обнаружено — реклама не анализировалась, только каналы по рефереру.', '']
    n = 0
    urgent = [x for x in res['findings'] if x['важность'] == 'Срочно' and x.get('статус') != 'отмечено как норма']
    if urgent:
        out += ['h3. Срочно', '']
        for x in sorted(urgent, key=lambda x: list(FILES).index(x['блок'])):
            n += 1
            out.append(f"*{n}.* [{x['блок']}] {x['что_происходит']}. {x['факты']} → _{file_names[x['блок']]}, лист «{x['лист']}»_")
            out.append('')
    for b in res['selected']:
        items = [x for x in res['findings'] if x['блок'] == b and x['важность'] != 'Срочно']
        out += [f'h3. {b}', '']
        s = res['summary'].get(b, {})
        if s:
            out.append(' · '.join(f'{k}: {v}' for k, v in list(s.items())[:8]))
            out.append('')
        for x in sorted(items, key=lambda x: SEV_ORDER[x['важность']]):
            n += 1
            mark = ' _(отмечено как норма)_' if x.get('статус') == 'отмечено как норма' else ''
            out.append(f"*{n}.* {x['важность']}: {x['что_происходит']}{mark}. {x['факты']}" + (f" Что сделать: {x['что_сделать']}." if x['что_сделать'] else ''))
            out.append('')
        if b == 'Боты':
            V = res.get('spam_examples', [])
            if V:
                out += ['h4. Какие боты у нас ходят', '']
                for ex in V:
                    out.append(f"*{ex['класс']}* — {SPAM_TEXT.get(ex['класс'], '')} Пример: {ex['ip']}, {ex['время']}, вход {ex['вход']}.")
                    out.append('')
            ips = res['ips']
            spam = ips[ips['категория'] == 'спам форм']
            if 0 < len(spam) <= 15:
                out.append('IP спама форм: ' + ', '.join(f"{r.ip} ({r.сеть})" for r in spam.itertuples()))
            elif len(spam):
                out.append(f'IP спама форм: {len(spam)} адресов, список на листе IP в {file_names["Общий анализ"]}.')
            out.append('')
    return '\n'.join(out)


def apply_edits(res, edits):
    """Правки ИИ после расследования: {"add": [находки], "remove": [ключи], "update": {ключ: {поле: значение}}}."""
    if not edits: return res
    rm = set(edits.get('remove', []))
    res['findings'] = [x for x in res['findings'] if x['key'] not in rm]
    for x in res['findings']:
        x.update(edits.get('update', {}).get(x['key'], {}))
    for a in edits.get('add', []):
        a = dict(a)
        a.setdefault('key', f"{a.get('блок')}:ии:{len(res['findings'])}")
        for k in ('факты', 'где_править', 'что_сделать', 'лист', 'также_в', 'статус'): a.setdefault(k, '')
        a.setdefault('главная_цифра', None)
        res['findings'].append(a)
    return res


def build(res, outdir, site=None, edits=None):
    os.makedirs(outdir, exist_ok=True)
    res = apply_edits(res, edits)
    site = site or (res['site_map'].get('site_hosts') or ['site'])[0]
    p0, p1 = res['inventory']['period']
    stem = f"NXLD_{site_slug(site)}_{p0[:10]}_{p1[5:10]}"
    file_names = {b: f'NXLD_{FILES[b]}.xlsx' for b in FILES}
    snap = snapshot(res, site)
    snap_json = json.dumps(snap, ensure_ascii=False, default=str, indent=1)
    about, files = about_df(res), files_df(res)
    written = []
    for b in res['selected']:
        S = res['sheets'].get(b, {})
        items = [x for x in res['findings'] if x['блок'] == b]
        summ = kv_df(res['summary'].get(b, {}))
        if b == 'Общий анализ':
            sheets = {'О данных': about, 'Файлы': files, 'Сводка': summ, 'Главное': main_sheet(res, file_names), 'Проблемы': problems_df(items), **site_map_sheets(res['site_map']), **S, 'IP': res['ips']}
            hidden = snap_json
        else:
            sheets = {'Проблемы': problems_df(items), 'Сводка': summ, 'О данных': about}
            if b == 'Маркетинг':
                O = res['sheets'].get('Общий анализ', {})
                sheets.update({f'Общее: {k}': O[k] for k in ('По дням', 'Каналы', 'Разделы', 'Спрос', 'Конверсии') if k in O})
            sheets.update(S)
            hidden = None
        if res.get('compare') is not None:
            cmp_ = res['compare']
            sheets['Было → стало'] = cmp_ if b == 'Общий анализ' else cmp_[cmp_['блок'] == b]
        path = os.path.join(outdir, file_names[b])
        write_xlsx(path, sheets, hidden)
        written.append(path)
    tx = os.path.join(outdir, 'NXLD_Redmine.textile')
    open(tx, 'w', encoding='utf-8').write(textile(res, site, file_names))
    sp = os.path.join(outdir, f'{stem}.snapshot.json')
    open(sp, 'w', encoding='utf-8').write(snap_json)
    written += [tx, sp]
    for extra in res.get('extra_files', []):
        written.append(extra)
    zp = os.path.join(outdir, f'{stem}.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in written:
            z.write(f, os.path.basename(f))
    return dict(files=written, zip=zp, stem=stem)
