"""NXLD: реестр адресов — одна классификация на весь отчёт (ТЗ, «Общие критерии: адрес и тот, кто обращается»).

У каждого запрошенного адреса три независимые оценки:
  форма        — страница / файл (с группой) / конструкт — по виду адреса и справочнику расширений;
  существование — живой (людям или своим 2xx) / переадресация / не существует (только 4xx) / сломан (5xx);
  смысл        — зонд (однозначный, неоднозначный) / для роботов / обычное — по справочникам.
Листы не держат своих условий, а берут срез реестра. Незнакомые расширения уходят Детективу (learned/extensions.json)."""
import json
import os
import re
import warnings
from urllib.parse import unquote

import numpy as np
import pandas as pd

REF = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference'))
# адресом это не является: шаблон JavaScript, склейка строк (' + href +), параметры без «?», кавычки и угловые скобки, двойные слэши.
# Пробел (%20) в адресе законен: «дом 1» в фильтре, имя файла с пробелом
CONSTRUCT = re.compile(r"\$\{|\{\{|%7B%7B|%24%7B|'\s*\+|\+\s*'|%27(%20|\s)*\+|\+(%20|\s)*%27|[\"<>]|%22|%3C|%3E|//|&|\\", re.I)


def _read(p):
    try:
        with open(p, encoding='utf-8') as f: return json.load(f)
    except Exception:
        return None


def load_extensions():
    """Справочник расширений + найденное Детективом (learned/extensions.json)."""
    E = _read(os.path.join(REF, 'extensions.json')) or {}
    L = _read(os.path.join(REF, 'learned', 'extensions.json')) or {}
    ext2grp = {}
    for g in E.get('группы', []):
        for e in g['расширения']: ext2grp[e.lower()] = g['группа']
    for x in L.get('расширения', []):
        if x.get('группа') and x.get('расширение'): ext2grp.setdefault(x['расширение'].lower(), x['группа'])
    by_addr = [(g['группа'], re.compile(g['шаблон'], re.I)) for g in E.get('по_адресу', [])]
    pages = {e.lower() for e in E.get('страницы', [])}
    tlds = {e.lower() for e in E.get('домены_в_хвосте', [])}
    H = E.get('скрытые_файлы') or {}
    hidden = {e.lower() for e in H.get('файлы', [])} | {x['расширение'].lower() for x in L.get('скрытые', []) if x.get('расширение')}
    return dict(ext2grp=ext2grp, by_addr=by_addr, pages=pages, tlds=tlds, hidden=hidden, hidden_group=H.get('группа', 'Конфиги'))


_EXT = None


def ext_of(path):
    """Расширение последнего звена адреса; у скрытых файлов (.env.local) — имя после точки (env)."""
    leaf = str(path).rstrip('/').rsplit('/', 1)[-1]
    if leaf.startswith('.'): return leaf[1:].split('.')[0].lower()
    m = re.search(r'\.([A-Za-z0-9]{1,10})$', leaf)
    return m.group(1).lower() if m else ''


def form_of(path):
    """(форма, группа, расширение, расширение_незнакомое) по виду адреса."""
    global _EXT
    if _EXT is None: _EXT = load_extensions()
    p = re.sub(r'^https?://[^/]+', '', str(path)) or '/'   # абсолютная форма запроса (GET http://сайт/путь) — законна
    if CONSTRUCT.search(p): return 'конструкт', '', '', False   # и //robots.txt: двойной слэш — не адрес
    p = unquote(p)   # /.%65%6e%76 — это /.env: вид файла определяем по раскодированному адресу
    if CONSTRUCT.search(p): return 'конструкт', '', '', False
    for g, rx in _EXT['by_addr']:
        if rx.search(p): return 'файл', g, ext_of(p), False
    leaf = p.rstrip('/').rsplit('/', 1)[-1]
    if leaf.startswith('.') and len(leaf) > 1:   # скрытый файл: .htaccess, .gitignore, .settings.php — настройки, а не страница
        nm = leaf[1:].lower()
        return 'файл', _EXT['hidden_group'], nm, nm not in _EXT['hidden']
    e = ext_of(p)
    if not e or e in _EXT['pages'] or e in _EXT['tlds']: return 'страница', '', e, False
    if re.fullmatch(r'\d+', e): return 'страница', '', e, False   # /v1.2 — версия в адресе, не расширение
    g = _EXT['ext2grp'].get(e)
    return 'файл', g or 'Неизвестный вид', e, g is None


def build(R, human, staff=None, engines=()):
    """Реестр по всем адресам лога (по категориям base). Возвращает DataFrame с индексом = код категории."""
    from .visits import probe_rx
    cats = R['base'].cat.categories.to_series().astype(str).reset_index(drop=True)
    F = pd.DataFrame([form_of(p) for p in cats], columns=['форма', 'группа', 'расширение', 'незнакомое'])
    F['адрес'] = cats.values
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        dec = cats.map(unquote)
        def hit(strength):
            rx_ = probe_rx(strength, engines)
            return (cats.str.contains(rx_, regex=True, case=False) | dec.str.contains(rx_, regex=True, case=False)).values
        F['зонд'] = np.where(hit(('однозначный',)), 'однозначный', np.where(hit(('неоднозначный',)), 'неоднозначный', ''))
    codes = R['base'].cat.codes.values
    st = R['status'].values
    who = np.asarray(human) | (np.asarray(staff) if staff is not None else np.zeros(len(R), bool))
    L = len(cats)
    ok = np.bincount(codes[who & (st >= 200) & (st < 300)], minlength=L)
    r3 = np.bincount(codes[who & (st >= 300) & (st < 400)], minlength=L)
    e4 = np.bincount(codes[(st >= 400) & (st < 500)], minlength=L)
    e5 = np.bincount(codes[st >= 500], minlength=L)
    ok_any = np.bincount(codes[(st >= 200) & (st < 300)], minlength=L)
    F['существование'] = np.select([ok > 0, ok_any > 0, r3 > 0, e5 > 0, e4 > 0], ['живой', 'живой', 'переадресация', 'сломан', 'не существует'], 'не существует')
    # фид или выгрузка — по поведению, а не по расширению: XML/YML/CSV, который забирают роботы и сервисы напрямую (Авито, Маркет, ЦИАН),
    # а не подгружают страницы сайта, — это выгрузка, а не данные для виджетов
    fam_ = (R['fam'].astype(str).values != '')
    ri_ = R['ref_internal'].values.astype(bool)
    n_all = np.bincount(codes, minlength=L)
    rob = np.bincount(codes[fam_], minlength=L)
    inn = np.bincount(codes[ri_], minlength=L)
    feedish = (F['группа'] == 'Данные для виджетов') & F['расширение'].isin(['xml', 'yml', 'csv', 'tsv']) & (n_all > 0)
    feedish &= (rob >= 0.5 * n_all) & (inn < 0.2 * n_all)
    F.loc[feedish, 'группа'] = 'Фиды и выгрузки'
    # /.well-known/: стандартные имена — служебные; нестандартный файл, который отдаётся, — постороннее в служебной папке (критично)
    wk = F['адрес'].str.startswith('/.well-known/') & ~F['группа'].isin(['Служебные (.well-known)', 'Подтверждение прав'])
    F['чужое_в_well_known'] = wk & (ok_any > 0)
    F['людям'] = ok > 0   # полный ответ получали люди или свои — это адрес сайта, а не находка сканера
    # зонд — путь, которого на сайте нет, или путь чужого движка. Неоднозначный «зонд», который отвечает людям и своим 2xx
    # как обычная страница, — страница сайта; страницы входа, регистрации и восстановления пароля движка сайта — тоже
    from .reference import engine_pages
    eng = engine_pages(engines)
    svc = cats.str.contains('|'.join(f'(?:{x})' for x in eng), regex=True, case=False).values if eng else np.zeros(L, bool)
    # стандартные имена /.well-known/ (extensions.json, «Служебные (.well-known)»: passkey-endpoints, assetlinks.json, security.txt…) —
    # служебные адреса в любой сети, не зонд: их просят браузеры и сервисы сами (автозаполнение паролей Apple через iCloud Private Relay и т. п.)
    F['служебная_страница'] = svc | (F['группа'] == 'Служебные (.well-known)').values
    F.loc[(F['зонд'] == 'неоднозначный') & (F['людям'] | svc), 'зонд'] = ''
    F['раздел'] = cats.str.extract(r'^(/[^/]*/?)')[0].values
    return F


def unknown_extensions(F, R, min_requests=3, top=30):
    """Незнакомые расширения с примерами — Детективу (brief «незнакомые_расширения»)."""
    # зонды — это атаки, а не словарь; несуществующие файлы просят только роботы наугад
    U = F[F['незнакомое'] & (F['зонд'] == '') & (F['существование'] != 'не существует')]
    if not len(U): return []
    n = np.bincount(R['base'].cat.codes.values, minlength=len(F))
    U = U.assign(запросов=n[U.index.values])
    g = U.groupby('расширение').agg(запросов=('запросов', 'sum'), адресов=('адрес', 'size'), примеры=('адрес', lambda s: list(s.head(3))))
    g = g[g['запросов'] >= min_requests].sort_values('запросов', ascending=False).head(top)
    return [dict(расширение=e, запросов=int(r['запросов']), адресов=int(r['адресов']), примеры=r['примеры']) for e, r in g.iterrows()]


def learn_extensions(items, site=''):
    """Запись Детектива: [{расширение, группа, что, ссылка}] → learned/extensions.json (без ссылки — не принимается)."""
    from .reference import anon
    p = os.path.join(REF, 'learned', 'extensions.json')
    L = _read(p) or {'расширения': []}
    have = {x['расширение'].lower() for x in L['расширения']}
    ok = []
    for it in items or []:
        e, g, url = str(it.get('расширение', '')).lower().lstrip('.'), it.get('группа'), str(it.get('ссылка', ''))
        if not e or not g or not url.startswith('http') or e in have: continue
        L['расширения'].append(dict(расширение=e, группа=g, что=it.get('что', ''), источник='поиск', ссылка=url, сайт=anon(site)))
        ok.append(e); have.add(e)
    if ok:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(L, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        global _EXT
        _EXT = None
    return ok
