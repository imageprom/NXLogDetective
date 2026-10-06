"""NXLD: сборка результата — Excel по блокам, текст для Redmine (Textile), снимок, архив."""
import json, numbers, os, re, zipfile
from datetime import datetime
import numpy as np, pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from .findings import SEV_ORDER
from . import report_index, report_problems, report_anatomy, report_files, report_tables
from . import sheets as sheet_catalog

FILES = {'Общий анализ': '01_Overview', 'Ошибки': '02_Errors', 'Нагрузка и безопасность': '03_Load_Security', 'Боты': '04_Bots', 'Маркетинг': '05_Marketing', 'SEO': '06_SEO'}
SEV_FILL = {'Срочно': 'F8D7DA', 'Важно': 'FFF3CD', 'К сведению': 'E2EFDA', 'Замечание': 'F3F3F3', 'отмечено как норма': 'EDEDED'}
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


def own_people(wb, m):
    """Сотрудники и мониторинги — на листе «Люди и боты», под таблицей."""
    if 'Люди и боты' not in wb.sheetnames: return
    ws = wb['Люди и боты']
    r = ws.max_row + 2
    staff = m.get('staff_ips') or []
    mons = m.get('monitors') or []
    from openpyxl.styles import Font
    ws.cell(r, 1, 'Свои: сотрудники').font = Font(bold=True)
    ws.cell(r, 2, 'IP с успешным входом в админку; их визиты не считаются людьми и заявками').font = Font(italic=True)
    for ip in staff:
        r += 1; ws.cell(r, 1, ip)
    r += 2
    ws.cell(r, 1, 'Мониторинги').font = Font(bold=True)
    ws.cell(r, 2, 'запрашивают одну страницу через равные промежутки; не люди и не нагрузка').font = Font(italic=True)
    for x in mons:
        r += 1; ws.cell(r, 1, str(x.get('ip'))); ws.cell(r, 2, f"{x.get('адрес')} каждые {x.get('интервал_с')} с; запросов {x.get('запросов')}")


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
                elif isinstance(v, numbers.Integral) and not isinstance(v, bool) and abs(v) >= 1000: c.number_format = report_index.NUM_FMT
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
    return pd.DataFrame(rows, columns=['Блок', 'Срочно', 'Важно', 'К сведению', 'Замечание', 'Что происходит', 'Главная цифра', 'Где подробно'])


def snapshot(res, site):
    return dict(tool='NX Log Detective', format='NXLD-snapshot/1', version=res['inventory'].get('version'), site=site, period=res['inventory']['period'],
                created=datetime.now().isoformat(timespec='seconds'), selected=res['selected'], summary=res['summary'], cleaning=res['cleaning'],
                daily=res['sheets'].get('Общий анализ', {}).get('Журнал активности', pd.DataFrame()).to_dict('records'),
                findings=[{k: x.get(k) for k in ('key', 'блок', 'важность', 'что_происходит', 'главная_цифра', 'статус', 'отметка')} for x in res['findings']],
                ips=res['ips'].astype(str).to_dict('records'), marks={x['key']: x.get('отметка', '') for x in res['findings'] if x.get('статус') == 'отмечено как норма'},
                site_map={k: res['site_map'].get(k) for k in ('site_hosts', 'server', 'engines', 'admin_regex', 'forms', 'catalog_templates', 'embedded_templates', 'ad_params')})


LABEL = {'Тревога': 'Тревога', 'Срочно': 'Приоритетная', 'Важно': 'Важная', 'К сведению': 'Остальное', 'Замечание': 'Замечание'}


def textile(res, site, file_names):
    """Запасной черновик движка — если Детектив не написал текст по brief.json. Порядок разделов — как в skill/references/redmine.md."""
    from .sheets import resolve
    inv = res['inventory']
    where = lambda x: f"{file_names[x['блок']]}, лист «{resolve(x['блок'], x['лист'])}»" if x.get('лист') else file_names[x['блок']]
    live = [x for x in res['findings'] if x.get('статус') != 'отмечено как норма']
    out = [f"h2. NX Log Detective: {site}, {inv['period'][0][:10]} — {inv['period'][1][:10]}", '',
           f"Проверены блоки: {', '.join(res['selected'])}. Запросов: " + f"{inv['requests']:,}".replace(',', ' ') + ". Подробности — в приложенных файлах NXLD_*.xlsx.", '']
    m = res['site_map']
    if not [f for f in m.get('forms', []) if str(f.get('вывод', '')).startswith('цель')]:
        out += ['Форм и целей на сайте не обнаружено — конверсии не считались.', '']
    if not m.get('ad_params'):
        out += ['Рекламных меток не обнаружено — реклама не анализировалась, только каналы по рефереру.', '']
    al = [x for x in live if x['важность'] == 'Тревога']
    if al:   # «Тревога» — перед «Главным»: подтверждённый вред, который идёт сейчас
        out += ['h3. Тревога', '']
        for x in al:
            out += [f"*{x.get('заголовок') or x['что_происходит']}.* {x.get('почему_тревога', '')}. {x.get('что_сделать', '')}. Подробно — {where(x)}.", '']
    top = [x for x in live if x['важность'] == 'Срочно']
    if top:
        out += ['h3. Главное', '']
        out += [f"* {x.get('заголовок') or x['что_происходит']} — {where(x)}" for x in top[:5]] + ['']
    if res.get('compare') is not None:
        st = pd.Series([x.get('статус', '') for x in res['findings']])
        out += [f"h3. Что изменилось с прошлой проверки ({' — '.join(s_[:10] for s_ in res.get('prev_period') or [])})", '',
                f"Новых проблем: {int(st.str.startswith('новая').sum())}, сохраняются: {int(st.str.startswith('сохраняется').sum())}, исправлены или не обнаружены: {int(st.str.startswith('исправлена').sum())}.", '']
    n = 0
    for b in res['selected']:
        items = [x for x in live if x['блок'] == b and x['важность'] not in ('Тревога',)]
        if not items: continue
        out += [f'h3. {b}', '']
        for x in sorted(items, key=lambda x: SEV_ORDER[x['важность']]):
            n += 1
            out.append(f"*{n}.* {LABEL.get(x['важность'], x['важность'])}: {x.get('заголовок') or x['что_происходит']}. {x.get('факты', '')}" + (f" Что сделать: {x['что_сделать']}." if x.get('что_сделать') else '') + f" ({where(x)})")
            out.append('')
        if b == 'Боты':
            D = (res.get('profiles') or {}).get('дела') or []
            if D:
                out += ['h4. Главные дела', '']
                for x in D[:3]:
                    ch = '; '.join(f"{o['статья']} ({o['сила']})" for o in x['обвинения'][:3])
                    out += [f"*Дело {x['дело']}* · {x['кличка']}: {ch}. Подробно — {file_names['Боты']}, лист «Разыскиваются».", '']
    out += ['h3. Файлы', ''] + [f"* {file_names[b]}" for b in res['selected']] + ['']
    return '\n'.join(out)


from .edits import apply as apply_edits   # правки Детектива — в engine/nxld/edits.py


def build(res, outdir, site=None, edits=None, redmine=None, only=None, workdir=None, skip_existing=False):
    """redmine — путь к тексту, который написал ИИ по brief.json (work/NXLD_Redmine.textile).
    Если его нет, кладётся запасной черновик движка с пометкой «черновик»."""
    os.makedirs(outdir, exist_ok=True)
    res = apply_edits(res, edits)
    from . import alarms, derive
    alarms.apply(res)   # после правок Детектива (проверки из сети) — тревоги заново
    alarms.recheck_cases(res)   # и у дел в 04
    derive.build(res)   # признаки и сводки для оформления — готовыми
    from . import report_errors
    report_errors.relink(res['findings'])   # карточки ссылаются на новые листы 02
    from . import report_load
    report_load.relink(res['findings'])   # и 03
    from . import report_bots
    report_bots.relink(res['findings'])   # и 04
    from . import report_marketing
    report_marketing.relink(res['findings'])   # и 05
    from . import report_seo
    report_seo.relink(res['findings'])   # и 06
    site = site or (res['site_map'].get('site_hosts') or ['site'])[0]
    p0, p1 = res['inventory']['period']
    stem = f"NXLD_{site_slug(site)}_{p0[:10]}_{p1[5:10]}"
    stix_bundle = None
    if res.get('profiles'):   # STIX 2.1: сигнатуры, дела, адреса и связи — один пакет в архиве (ТЗ 10.5); сводка — для Обзоров 01 и 04
        try:
            from . import stix
            from .prepare import VERSION
            stix_bundle, sm_ = stix.build(res, site, VERSION)
            res['stix'] = dict(sm_, файл=f'{stem}.stix.json')
        except Exception:
            import traceback; traceback.print_exc(); res['stix'] = None
    if workdir and edits and not only:   # выжимка — заново, с правками и проверками из сети: текст пишется по ней (SKILL.md, шаг 5); STIX в ней — уже построенный
        try:
            from . import brief as brief_
            brief_.refresh(res, workdir)
        except Exception:
            import traceback; traceback.print_exc()
    file_names = {b: f'NXLD_{FILES[b]}.xlsx' for b in FILES}
    from . import snapshot as snapshot_
    snap = snapshot_.build(res, site, edits)   # NXLD-snapshot/2 (совместим с /1)
    snap_json = json.dumps(snap, ensure_ascii=False, default=str, indent=1)
    about = about_df(res)
    written = []
    for b in res['selected']:
        if skip_existing and os.path.exists(os.path.join(outdir, file_names[b])):   # готовый файл после падения сборки — не пересобирать
            written.append(os.path.join(outdir, file_names[b])); continue
        if only and b not in only: continue
        S = res['sheets'].get(b, {})
        if 'SEO' in res['selected']:   # листы, переехавшие в 06 «SEO», в своих файлах не повторяются
            S = {k_: v_ for k_, v_ in S.items() if k_ not in sheet_catalog.MOVED_TO_06.get(b, ())}
        items = [x for x in res['findings'] if x['блок'] == b]
        summ = kv_df(res['summary'].get(b, {}))
        if b == 'Общий анализ':
            # индекс (первый лист) строится отдельно; «О данных», «Сводка», «Главное» вошли в него (ТЗ 16.2)
            from .anatomy import appendix
            sheets = {k: v for k, v in {**S, **appendix(res)}.items() if k not in ('Люди и боты', 'Каналы')}   # их данные — в сводке «Активность»   # «Файлы» строится оформленным листом в конце (report_files)   # «Карта сайта» заменена «Анатомией сайта» и приложениями к ней (ТЗ, 3 октября)
            if 'Боты' not in res['selected']: sheets['IP'] = res['ips']      # иначе лист IP — в 04 Bots
            hidden = snap_json
        elif b == 'Нагрузка и безопасность':   # 03 — по правилам 01 и 02: обзор вместо «Сводки» и «О данных»
            from . import report_load
            sheets = {'Обзор': pd.DataFrame(), **report_load.sheets_for(S)}
            hidden = None
        elif b == 'Боты':   # 04 — по правилам 01–03: обзор вместо «Сводки» и «О данных»
            from . import report_bots
            sheets = report_bots.sheets_for(S, res)
            hidden = None
        elif b == 'SEO':   # 06 — как поисковики видят сайт
            sheets = {'Обзор': pd.DataFrame()}
            hidden = None
        elif b == 'Маркетинг':   # 05 — по правилам 01–04: обзор вместо «Сводки», «О данных» и копий листов 01
            from . import report_marketing
            sheets = report_marketing.sheets_for(S, res)
            hidden = None
        elif b == 'Ошибки':   # 02 — по правилам Overview: сводка вместо «Сводки» и «О данных» (они в Overview)
            from . import report_errors
            sheets = report_errors.sheets_for(S)
            hidden = None
        else:
            sheets = {'Сводка': summ, 'О данных': about}
            if b == 'Маркетинг':
                O = res['sheets'].get('Общий анализ', {})
                sheets.update({f'Общее: {k}': O[k] for k in ('Журнал активности', 'Разделы', 'Типы страниц', 'Страницы', 'Конверсии') if k in O})
            sheets.update(S)
            if b == 'Боты': sheets['IP'] = res['ips']
            hidden = None
        if res.get('compare') is not None:
            cmp_ = res['compare']
            sheets['Было → стало'] = cmp_ if b == 'Общий анализ' else cmp_[cmp_['блок'] == b]
        path = os.path.join(outdir, file_names[b])
        names = write_xlsx(path, sheets, hidden)
        # «Проблемы» — карточками, первым листом блока (в Overview — вторым, после индекса); ТЗ 16.5
        wb = load_workbook(path)
        report_problems.build_problems(wb, res, res['findings'] if b == 'Общий анализ' else items, file_names[b], with_block=(b == 'Общий анализ'))
        names = {'Проблемы': 'Проблемы', **names}
        if b == 'Ошибки':
            report_errors.build(wb, res, S, site)
        if b == 'Нагрузка и безопасность':
            report_load.build(wb, res, S, site)
        if b == 'Боты':
            from . import report_bots
            report_bots.build(wb, res, S, site)
        if b == 'Маркетинг':
            from . import report_marketing
            report_marketing.build(wb, res, S, site)
        if b == 'SEO':
            from . import report_seo
            report_seo.build(wb, res, site)
        if b == 'Общий анализ':
            if report_anatomy.build_anatomy(wb, res, names, index=1) is not None:
                names = {'Проблемы': 'Проблемы', 'Анатомия сайта': 'Анатомия сайта', **{k: v for k, v in names.items() if k != 'Проблемы'}}
            from . import report_activity   # сводка по реестру обращающихся, рядом с «Анатомией»
            if report_activity.build_activity(wb, res, set(wb.sheetnames), index=2, files={k: v for k, v in file_names.items() if k in res['selected']}) is not None:
                names['Активность'] = 'Активность'
            report_tables.conversions(wb, S.get('Конверсии'))
            report_tables.facets_sheet(wb, S.get('Фасеты'))
            for nm_ in ('Разделы', 'Типы страниц', 'Страницы'): report_tables.pages_sheet(wb, S.get(nm_), nm_, nm_)
            report_tables.activity_sheet(wb, S.get('Журнал активности'), outages=(res.get('errors') or {}).get('сбои'))
            report_tables.intake(wb, res)
            names['Точки приёма данных'] = 'Точки приёма данных'
            if report_tables.embedded_sheet(wb, res) is not None:   # сразу за «Анатомией сайта»
                names['Динамические блоки'] = 'Динамические блоки'
                if 'Анатомия сайта' in wb.sheetnames:
                    w_ = wb['Динамические блоки']; wb._sheets.remove(w_); wb._sheets.insert(wb.sheetnames.index('Анатомия сайта') + 1, w_)
            if report_tables.params_sheet(wb, res) is not None: names['Параметры запросов'] = 'Параметры запросов'
            if 'Фасеты' in wb.sheetnames:   # перед «Фасетами»: «Точки приёма данных», «Параметры запросов»
                mv = [wb[n_] for n_ in ('Точки приёма данных', 'Параметры запросов') if n_ in wb.sheetnames]
                rest = [w for w in wb._sheets if w not in mv]
                i_ = rest.index(wb['Фасеты']); wb._sheets = rest[:i_] + mv + rest[i_:]
            pos = wb.sheetnames.index('Анатомия сайта') + 1 if 'Анатомия сайта' in wb.sheetnames else None
            for k in [k for k in list(names) if k.startswith('Анатомия —')][::-1]:   # приложения — сразу за «Анатомией»
                if pos and names[k] in wb.sheetnames:
                    wb.move_sheet(names[k], offset=pos - wb.sheetnames.index(names[k]))
            if report_tables.service_files(wb, res) is not None: names['Файлы'] = 'Файлы'
            if report_files.build_files(wb, res) is not None: names['Логи'] = 'Логи'
            tail_ = [n_ for n_ in ('Файлы', 'Логи', '_snapshot') if n_ in wb.sheetnames]   # в конце: «Файлы», «Логи», затем снимок
            wb._sheets = [w for w in wb._sheets if w.title not in tail_] + [wb[n_] for n_ in tail_]
            ORDER = ['Обзор', 'Проблемы', 'Анатомия сайта', 'Активность', 'Журнал активности', 'Конверсии', 'Разделы', 'Типы страниц', 'Страницы',
                     'Динамические блоки', 'Файлы', 'Фасеты', 'Точки приёма данных', 'Параметры запросов']
            TAIL = ['Логи', '_snapshot']   # всё прочее — между списком и «Логами»
            byname = {w.title: w for w in wb._sheets}
            head_ = [byname[n_] for n_ in ORDER if n_ in byname]
            tail_ = [byname[n_] for n_ in TAIL if n_ in byname]
            wb._sheets = head_ + [w for w in wb._sheets if w not in head_ and w not in tail_] + tail_
            report_index.build_index(wb, res, names)
        report_tables.humanize_urls(wb)  # кириллица в адресах — буквами (закодированная латиница остаётся уликой)
        report_tables.mask_pd_cells(wb)  # персональные данные в адресах — маскированно на всех листах
        if b not in ('Ошибки', 'Нагрузка и безопасность', 'Боты'): report_tables.redden_codes(wb)   # ошибки в списках кодов — красным; в 02 каждая строка — ошибка, там цвет — критичность
        if b in ('Боты', 'Маркетинг', 'SEO'): report_tables.paren_values(wb)   # «название (значение)» вместо двоеточия
        report_tables.sanitize(wb)   # представление листов, легенды, ##### — общий проход перед сохранением
        wb.save(path)
        written.append(path)
    if only:
        return dict(files=written, zip=None, stem=stem)
    if redmine and os.path.exists(redmine):
        tx = os.path.join(outdir, 'NXLD_Redmine.textile')
        text = open(redmine, encoding='utf-8').read()
    else:   # запасной черновик — под своим именем, чтобы его не спутали с текстом Детектива
        tx = os.path.join(outdir, 'NXLD_Redmine_черновик.textile')
        text = textile(res, site, file_names).replace('h2. NX Log Detective:', 'h2. Черновик. NX Log Detective:', 1)
        text = text.replace('\n\n', '\n\n_Черновик движка: связный текст пишет Детектив по brief.json (см. SKILL.md, шаг 5)._\n\n', 1)
    open(tx, 'w', encoding='utf-8').write(text)
    sp = os.path.join(outdir, f'{stem}.snapshot.json')
    open(sp, 'w', encoding='utf-8').write(snap_json)
    written += [tx, sp]
    if stix_bundle is not None:
        stp = os.path.join(outdir, f'{stem}.stix.json')
        open(stp, 'w', encoding='utf-8').write(json.dumps(stix_bundle, ensure_ascii=False, separators=(',', ':')))
        written.append(stp)
    for extra in res.get('extra_files', []):
        written.append(extra)
    zp = os.path.join(outdir, f'{stem}.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in written:
            z.write(f, os.path.basename(f))
    return dict(files=written, zip=zp, stem=stem)
