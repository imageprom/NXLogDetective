"""NXLD: анатомия сайта — как он устроен по логу (ТЗ, лист «Анатомия сайта»).

Показываем только то, что реально существует: страницы, которые отдавались людям с ответом 200.
Движок описывает устройство нейтрально; названия уровней — по словарю частых слов в адресах,
иначе «Уровень N». Смысл и тематику даёт Детектив (подсказки — в brief, раздел «тематика»).
"""
import re
from urllib.parse import unquote
from collections import Counter
import numpy as np
import pandas as pd

# слово в адресе → (элемент, список)
SLUG = {
    'flat': ('квартира', 'квартиры'), 'flats': ('квартира', 'квартиры'), 'apartments': ('квартира', 'квартиры'), 'kvartiry': ('квартира', 'квартиры'),
    'parking': ('машиноместо', 'машиноместа'), 'pantry': ('кладовая', 'кладовые'), 'commercial': ('помещение', 'коммерческие помещения'),
    'product': ('товар', 'товары'), 'products': ('товар', 'товары'), 'goods': ('товар', 'товары'), 'catalog': ('позиция каталога', 'каталог'),
    'katalog': ('позиция каталога', 'каталог'), 'shop': ('товар', 'магазин'), 'item': ('элемент', 'элементы'),
    'news': ('новость', 'новости'), 'novosti': ('новость', 'новости'), 'blog': ('запись блога', 'блог'), 'articles': ('статья', 'статьи'),
    'article': ('статья', 'статьи'), 'stati': ('статья', 'статьи'), 'journal': ('статья', 'журнал'), 'press': ('публикация', 'пресс-центр'),
    'reviews': ('отзыв', 'отзывы'), 'otzyvy': ('отзыв', 'отзывы'), 'action': ('акция', 'акции'), 'actions': ('акция', 'акции'),
    'akcii': ('акция', 'акции'), 'sales': ('акция', 'акции'), 'promo': ('акция', 'акции'), 'services': ('услуга', 'услуги'),
    'uslugi': ('услуга', 'услуги'), 'projects': ('проект', 'проекты'), 'portfolio': ('работа', 'портфолио'), 'gallery': ('альбом', 'галерея'),
    'faq': ('вопрос', 'вопросы'), 'vacancy': ('вакансия', 'вакансии'), 'vacancies': ('вакансия', 'вакансии'), 'events': ('событие', 'события'),
    'brands': ('бренд', 'бренды'), 'category': ('категория', 'категории'), 'tag': ('тег', 'теги'), 'realty': ('объект', 'объекты'),
    'docs': ('документ', 'документы'), 'documents': ('документ', 'документы'), 'video': ('видео', 'видео'), 'photo': ('фото', 'фото'),
    'filter': ('фильтр', 'фильтр'), 'search': ('поиск', 'поиск'),
}
FEED_HINT = {'news', 'novosti', 'blog', 'articles', 'article', 'stati', 'journal', 'press', 'reviews', 'otzyvy', 'action', 'actions', 'akcii', 'sales', 'promo', 'events', 'vacancy', 'vacancies', 'faq'}
CABINET = r'^/(personal|lk|cabinet|account|profile|my|dashboard|user|users|kabinet|lichnyy-kabinet|lichnyj-kabinet)/'
ENGINE_DIRS = {
    '1С-Битрикс': {'/bitrix/': 'ядро движка и служебные скрипты', '/local/': 'шаблоны и доработки сайта', '/upload/': 'загруженные файлы: картинки, документы'},
    'WordPress': {'/wp-content/': 'темы, плагины и загрузки', '/wp-includes/': 'ядро движка', '/wp-admin/': 'админка', '/wp-json/': 'REST API'},
    'Joomla': {'/components/': 'компоненты', '/modules/': 'модули', '/templates/': 'шаблоны', '/media/': 'медиа движка', '/images/': 'картинки', '/administrator/': 'админка'},
    'Drupal': {'/sites/': 'файлы сайта', '/core/': 'ядро движка', '/modules/': 'модули', '/themes/': 'темы'},
    'MODX': {'/assets/': 'шаблоны и файлы', '/manager/': 'админка', '/core/': 'ядро движка', '/connectors/': 'служебные запросы'},
    'OpenCart': {'/catalog/': 'шаблоны и скрипты витрины', '/image/': 'картинки', '/admin/': 'админка', '/system/': 'ядро'},
    'Tilda': {'/tild': 'файлы Тильды'},
}
MEDIA_EXT = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'avif', 'svg', 'ico', 'bmp', 'tif', 'tiff', 'mp4', 'webm', 'mov', 'avi', 'mp3', 'ogg', 'wav',
             'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'zip', 'rar', '7z'}
MEDIA_KIND = {**{e: 'картинки' for e in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'avif', 'svg', 'ico', 'bmp', 'tif', 'tiff')},
              **{e: 'видео и звук' for e in ('mp4', 'webm', 'mov', 'avi', 'mp3', 'ogg', 'wav')},
              **{e: 'документы' for e in ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx')}, **{e: 'архивы' for e in ('zip', 'rar', '7z')}}
FORM_NAME = [(r'callback|call_?back|zvonok|perezvon', 'обратный звонок'), (r'excurs', 'запись на экскурсию'), (r'price|cena|tsena|prais', 'запрос цены'),
             (r'consult', 'консультация'), (r'finish|otdelk', 'отделка'), (r'invest', 'для инвесторов'), (r'ipotek|mortgage|credit|kredit', 'ипотека и кредит'),
             (r'order|zakaz|checkout|basket|cart', 'заказ'), (r'subscr|podpis', 'подписка'), (r'feedback|contact|svyaz', 'обратная связь'),
             (r'question|vopros', 'вопрос'), (r'review|otzyv', 'отзыв'), (r'vacan|resume|rezyume', 'отклик на вакансию'), (r'register|registr|signup', 'регистрация'),
             (r'login|auth|signin', 'вход'), (r'tradein|trade-in', 'трейд-ин'), (r'booking|bron', 'бронирование')]
PARAM_GROUPS = [
    ('Реклама и аналитика', r'^(utm_\w+|yclid|gclid|fbclid|wbraid|gbraid|erid|calltouch\w*|roistat\w*|_openstat|from|ref|cm_id|ad_?id|campaign_?id|_ga|_gl|ymclid|vkclid|mc_\w+)$'),
    ('Служебные поисковиков и Яндекса', r'^(etext|ybaip|ysclid|y_ref|yabizcmpgn|yabizcmpgn\w*|lr|text|_ym\w*|utm_referer|utm_ya_campaign|utm_candidate|turbo\w*|amp)$'),
    ('Фильтры, сортировка и страницы', r'(filter|sort|order|page|pagen|limit|view|show|ajax|type|price|min|max|rooms|floor|sq|area|set_|arr|items|objects)'),
]
SERVICE_GROUPS = [
    ('Для роботов', r'^/(robots\.txt|sitemap[\w.-]*\.xml(\.gz)?|sitemap/.*)$'),
    ('Фиды и выгрузки', r'(/export/|/feeds?(/|\.xml|$)|\.yml$|\.csv$|yandex[\w-]*\.xml$|google[\w-]*\.xml$|/rss)'),
    ('Иконки и манифест', r'(favicon|apple-touch|manifest\.json|site\.webmanifest|browserconfig\.xml|\.ico$)'),
    ('Проверочные файлы', r'(yandex_[0-9a-f]+\.html|google[0-9a-f]+\.html|\.well-known/)'),
    ('Стили и скрипты', r'\.(css|js|mjs|map)$'),
    ('Данные для виджетов', r'\.(xml|json)$'),
]


def first_seg(p):
    s = p.strip('/').split('/')
    return '/' if not s[0] else f'/{s[0]}/'


def slug_name(seg, form):
    v = SLUG.get(seg.lower())
    return v[form] if v else None


def name_of(x, rules):
    for rx, nm in rules:
        if re.search(rx, x, re.I): return nm
    return None


def build(c, res):
    R = c.R
    st = R['status'].values
    m = res.get('site_map') or {}
    engine = ((m.get('engines') or [{}])[0] or {}).get('движок', '')
    cats, codes = R['base'].cat.categories, R['base'].cat.codes.values
    pg = c.human & R['is_page'].values & (st == 200) & (R['method'].values == 'GET')
    P = pd.DataFrame({'code': codes[pg], 'vid': R['vid'].values[pg]})
    views = P.groupby('code').size()
    visits = P.drop_duplicates().groupby('code').size()
    pages = pd.DataFrame({'адрес': cats[views.index].astype(str), 'просмотров': views.values, 'визитов': visits.reindex(views.index).values})
    junk = pages['адрес'].str.contains(r'[&;=\s]|%20|text/html', regex=True) | pages['адрес'].map(junk_path)
    pages = pages[~junk]          # битые и мусорные адреса — не часть устройства          # битые адреса — не часть устройства
    cl = pages['адрес'].map(clean_path)
    pages['фильтр'] = [f for _, f in cl]; pages['адрес'] = [p_ for p_, _ in cl]
    flt_pages = pages[pages['фильтр']].groupby('адрес').size()
    flt_visits = pages[pages['фильтр']].groupby('адрес')['визитов'].sum()
    pages = pages.groupby('адрес', as_index=False).agg(просмотров=('просмотров', 'sum'), визитов=('визитов', 'sum'))
    pages['раздел'] = pages['адрес'].map(first_seg)
    pages['глубина'] = pages['адрес'].map(lambda p: 0 if p.strip('/') == '' else len(p.strip('/').split('/')))
    tot_visits = int(P['vid'].nunique())
    sec_visits = P.assign(раздел=pd.Series(cats[P['code'].values].astype(str)).map(first_seg).values).drop_duplicates(['раздел', 'vid']).groupby('раздел').size()
    eng_dirs = ENGINE_DIRS.get(engine, {})
    min_v = max(20, int(0.0005 * tot_visits))
    A = dict(движок=engine, всего_страниц=len(pages), визитов=tot_visits)
    # --- админка и закрытые зоны
    zones, not_closed = [], set()
    if m.get('admin_regex'):
        adm = str(m['admin_regex']).lstrip('^')
        staff = m.get('staff_ips') or []
        staff = staff if isinstance(staff, list) else re.findall(r'\d+\.\d+\.\d+\.\d+', str(staff))
        zones.append(dict(что='Админка движка', адрес=adm, подробно=f"входили {len(staff)} адресов сотрудников" if staff else 'входов сотрудников по логу не видно', входили=len(staff)))
    OS = res.get('sheets', {}).get('Нагрузка и безопасность', {}).get('Открытые служебные разделы', pd.DataFrame())
    for _, r in (OS[(OS['форма_входа'] == 'да') & (OS['IP_с_200'] >= 3)].iterrows() if len(OS) and 'IP_с_200' in OS else []):
        zones.append(dict(что='Служебный раздел', адрес=r['раздел'], подробно='вход по паролю (форма входа)', входили=int(r['адресов_вошло']), неудачных=int(r.get('неудачных', 0)), POST=int(r.get('POST_входов', 0)),
                          без_входа=r['страницы_без_входа'] if r.get('адресов_без_входа', 0) else ''))
    for sec, v in sec_visits.items():
        if re.match(CABINET, sec) and v >= 5:
            g_ = pages[pages['раздел'] == sec]
            sm_ = np.isin(codes, np.where(cats.str.startswith(sec))[0])
            posts = int((sm_ & (R['method'].values == 'POST') & c.human).sum())
            if len(g_) < 2 and not posts:      # по названию кабинет, но входа и внутренних страниц нет — обычная страница
                not_closed.add(sec); continue
            sub = [x for x in levels(g_, sec) if x['глубина'] >= 2] if len(g_) else []
            ipc = np.isin(codes, np.where(cats.str.startswith(sec))[0]) & pg
            zones.append(dict(что='Личный кабинет', адрес=sec, визитов=int(v), IP=int(R['ip'].values[ipc].nunique() if hasattr(R['ip'].values[ipc], 'nunique') else len(set(R['ip'].values[ipc]))), подробно='', уровни=sub))
    hosts = m.get('site_hosts') or []
    for h in hosts[1:]:
        if re.search(r'(^|\.)(dev|test|stage|staging|demo|beta)\.', h + '.'):
            zones.append(dict(что='Тестовая копия', адрес=h, подробно='запросы к ней есть в этих логах'))
    A['зоны'] = zones
    # --- разделы: каталоги, ленты, простые
    cats_, feeds, simple = [], [], []
    for sec, g in pages.groupby('раздел'):
        v = int(sec_visits.get(sec, 0))
        if sec == '/' or v < min_v or sec in eng_dirs or any(sec.startswith(k) for k in eng_dirs) or (re.match(CABINET, sec) and sec not in not_closed):
            continue
        lv = levels(g, sec)
        heavy = [x for x in lv if x['адресов'] >= 10]
        word = sec.strip('/').lower()
        feedish = word in FEED_HINT and any(x['глубина'] == 2 and x['адресов'] >= 3 for x in lv) and max(x['глубина'] for x in lv) <= 2
        if not heavy and not feedish:
            simple.append(dict(раздел=sec, страниц=len(g), визитов=v))
            continue
        deep = max(x['глубина'] for x in (heavy or lv))
        el = [x for x in lv if x['глубина'] == deep][0]
        nf = int(flt_pages[flt_pages.index.str.startswith(sec)].sum()) if len(flt_pages) else 0
        nfv = int(flt_visits[flt_visits.index.str.startswith(sec)].sum()) if len(flt_visits) else 0
        cnt = Counter()
        for x in collapse(roles(lv), v): cnt[x['роль']] += x['адресов']
        lv = roles(lv)
        card = dict(раздел=sec, визитов=v, страниц=len(g), уровни=collapse(lv, v), элементов=el['адресов'], элемент=el['название'] if not el['название'].startswith('Уровень') else 'элемент',
                    глубина_элементов=deep, фильтры=filters_of(R, pg, sec), страниц_фильтра=nf, визитов_фильтра=nfv,
                    разделов=cnt['раздел'], подразделов=cnt['подраздел'], шаблоны=templates_of(R, pg, sec, deep))
        (feeds if (feedish or (deep <= 2 and word in FEED_HINT)) else cats_).append(card)
    A['каталоги'] = sorted(cats_, key=lambda x: -x['визитов'])
    A['ленты'] = sorted(feeds, key=lambda x: -x['визитов'])
    marks = section_marks(res)
    for s_ in simple:
        mk = [marks.get(s_['раздел'], '')]
        if s_['раздел'] in not_closed: mk.append('называется как кабинет, но входа по логу нет')
        if filters_of(R, pg, s_['раздел']) or (len(flt_pages) and flt_pages[flt_pages.index.str.startswith(s_['раздел'])].sum()): mk.append('фильтры')
        s_['пометки'] = ', '.join(x for x in mk if x)
    A['простые'] = sorted(simple, key=lambda x: -x['визитов'])
    A['главная'] = int(sec_visits.get('/', 0))
    # --- формы
    A['формы'], A['не_цели'] = forms(R, res, m)
    # --- папки движка
    A['папки'] = []
    for d, what in eng_dirs.items():
        idx = np.where(cats.str.startswith(d))[0]
        mm = np.isin(codes, idx)
        if mm.sum():
            ext = Counter(R['ext'].values[mm].astype(str)).most_common(4)
            A['папки'].append(dict(папка=d, что=what, запросов=int(mm.sum()), доля=float(round(mm.mean() * 100, 1)), типы=', '.join(f"{e or 'страницы'}" for e, _ in ext)))
    # --- медиа
    ext = R['ext'].astype(str).values
    mm = np.isin(ext, list(MEDIA_EXT)) & (st == 200)
    MD = pd.DataFrame({'p': cats[codes[mm]].astype(str), 'ext': ext[mm], 'b': R['bytes'].values[mm]})
    MD['папка'] = MD['p'].map(lambda p: '/' + '/'.join(p.strip('/').split('/')[:1]) + '/' if '/' in p.strip('/') else '/ (корень)')
    MD['вид'] = MD['ext'].map(MEDIA_KIND)
    media = []
    for f, g in MD.groupby('папка'):
        if len(g) < max(100, 0.01 * len(MD)): continue
        kinds = g.groupby('вид').agg(n=('b', 'size'), b=('b', 'sum')).sort_values('n', ascending=False)
        sub = g['p'].map(lambda p: '/' + '/'.join(p.strip('/').split('/')[:2]) + '/').value_counts().head(3)
        media.append(dict(папка=f, запросов=len(g), ГБ=float(round(g['b'].sum() / 1024 ** 3, 1)), виды='; '.join(f"{k} — {int(r['n']):,}".replace(',', ' ') for k, r in kinds.iterrows()),
                          подпапки=', '.join(sub.index)))
    A['медиа'] = sorted(media, key=lambda x: -x['запросов'])
    # --- служебные файлы, подгружаемые блоки, параметры
    A['служебные'] = service_groups(m, res)
    A['подгружаемые'] = embedded_groups(m)
    A['параметры'] = param_groups(m, res)
    A['подсказки'] = hints(pages, res, m)
    return A


def junk_path(p):
    for seg in p.strip('/').split('/'):
        if '.' in seg and not re.search(r'\.(html?|php)$', seg): return True
        if len(seg) >= 20 and re.search(r'[A-Z]', seg) and re.search(r'\d', seg): return True
    return False


def clean_path(p):
    """Страницы умного фильтра (/…/filter/…/apply/) относятся к своему списку: отрезаем хвост фильтра."""
    segs = p.strip('/').split('/')
    if 'filter' in segs:
        return '/' + '/'.join(segs[:segs.index('filter')]) + '/', True
    return p, False


def levels(g, sec):
    """Уровни раздела. Имя — по слову из адреса: список-подразделы (flat, parking) называются списком,
    а элемент получает имя ближайшего слова сверху. Промежуточные уровни без слова — «Уровень N»."""
    lv, word = [], sec.strip('/').lower()
    for d, gd in sorted(g.groupby('глубина'), key=lambda x: x[0]):
        segs = gd['адрес'].map(lambda p: p.strip('/').split('/')[d - 1].lower() if d else '')
        words = Counter(segs)
        small_set = d > 1 and len(words) <= 5 and all(re.fullmatch(r'[a-z_]+', w) for w in words)
        known = [w for w, _ in words.most_common() if w in SLUG]
        x = dict(глубина=int(d), адресов=len(gd), визитов=int(gd['визитов'].sum()), пример=gd.sort_values('визитов', ascending=False)['адрес'].iloc[0], шаблон=shape(gd['адрес']),
                 слова=', '.join(w for w, _ in words.most_common(4)) if small_set else '', слово_сверху=word, литерал=bool(small_set),
                 примеры={w: gd[segs == w].sort_values('визитов', ascending=False)['адрес'].iloc[0] for w, _ in words.most_common(5)} if small_set else {})
        if d == 1:
            x['название'] = 'Список'
        elif small_set and known:
            x['название'] = ', '.join(dict.fromkeys(slug_name(w, 1) for w in known)); word = known[0]
        elif small_set:
            x['название'] = f'Уровень {d}'; word = ''
        else:
            x['название'] = None
        lv.append(x)
    # переменные уровни: имя слова сверху получает только самый посещаемый из идущих подряд после этого слова
    i = 0
    while i < len(lv):
        if lv[i]['название'] is None:
            j = i
            while j < len(lv) and lv[j]['название'] is None and lv[j]['слово_сверху'] == lv[i]['слово_сверху']: j += 1
            run = lv[i:j]
            best = max(run, key=lambda y: y['визитов'])
            for y in run:
                nm = slug_name(y['слово_сверху'], 0) if y is best else None
                y['название'] = nm or f"Уровень {y['глубина']}"
            i = j
        else:
            i += 1
    return lv


def shape(addrs):
    """Шаблон уровня: одинаковые части — как есть, небольшой набор слов — {a|b}, остальное — *."""
    rows = [a.strip('/').split('/') for a in addrs]
    if not rows or rows == [['']]: return '/'
    out = []
    for i in range(max(len(r) for r in rows)):
        vals = Counter(r[i] for r in rows if len(r) > i)
        if len(vals) == 1: out.append(next(iter(vals)))
        elif len(vals) <= 5 and all(re.fullmatch(r'[a-z_]+', v) for v in vals): out.append('{' + '|'.join(v for v, _ in vals.most_common()) + '}')
        else:
            pre = re.match(r'^([a-z_-]*?)(?=\d)', next(iter(vals)))
            pre = pre.group(1) if pre else ''
            out.append(f'{pre}*' if pre and all(re.fullmatch(re.escape(pre) + r'\d+', v) for v in vals) else '*')
    return '/' + '/'.join(out) + '/'


def roles(lv):
    """Роль уровня: индексная, раздел, подраздел, элемент."""
    if not lv: return lv
    deep = max((x for x in lv if x['адресов'] >= 10), key=lambda y: y['глубина'], default=lv[-1])['глубина']
    for x in lv:
        d = x['глубина']
        x['роль'] = ('индексная' if d == 1 else 'элемент' if d == deep else 'подраздел' if x.get('литерал') else 'раздел' if d < deep else 'страница внутри элемента')
    return lv


def collapse(lv, sec_visits):
    """Промежуточные неназванные уровни с малым трафиком склеиваем в одну строку."""
    out, buf = [], []
    for x in lv:
        weak = x['название'].startswith('Уровень') and x['визитов'] < 0.02 * max(1, sec_visits)
        if weak:
            buf.append(x); continue
        if buf:
            out.append(merge(buf)); buf = []
        out.append(x)
    if buf: out.append(merge(buf))
    return out


def merge(buf):
    if len(buf) == 1: return buf[0]
    return dict(глубина=buf[0]['глубина'], до=buf[-1]['глубина'], адресов=sum(x['адресов'] for x in buf), визитов=sum(x['визитов'] for x in buf),
                пример=buf[-1]['пример'], шаблон=buf[-1].get('шаблон', ''), название='промежуточные уровни', роль='промежуточные', слова='')


def filters_of(R, pg, sec):
    qc = R['query'].cat.codes.values
    idx = np.where(R['base'].cat.categories.str.startswith(sec))[0]
    mm = pg & np.isin(R['base'].cat.codes.values, idx) & (qc >= 0)
    if not mm.any(): return []
    qs = R['query'].cat.categories[qc[mm]].astype(str)
    keys = Counter(k.split('=')[0] for q in qs for k in q.split('&') if k)
    keys = [(k, n) for k, n in keys.most_common(30) if re.search(PARAM_GROUPS[2][1], k, re.I) and not re.match(PARAM_GROUPS[0][1], k, re.I)]
    out = []
    for k, n in keys:
        base = re.sub(r'(_\d+)+$|\d+$', '_*', k)
        if base not in [b for b, _ in out]: out.append((base, n))
    return [f"{b}" for b, _ in out[:6]]


def templates_of(R, pg, sec, depth):
    idx = np.where(R['base'].cat.categories.str.startswith(sec))[0]
    mm = pg & np.isin(R['base'].cat.codes.values, idx)
    t = pd.Series(R['tpl'].values[mm]).astype(str)
    t = t[t.map(lambda p: len(p.strip('/').split('/')) == depth)]
    return t.value_counts().head(3).index.tolist()


def section_marks(res):
    out = {}
    OS = res.get('sheets', {}).get('Нагрузка и безопасность', {}).get('Открытые служебные разделы', pd.DataFrame())
    for _, r in (OS.iterrows() if len(OS) else []):
        if r.get('форма_входа') == 'да': out[r['раздел']] = 'вход'
    C = res.get('sheets', {}).get('Общий анализ', {}).get('Конверсии', pd.DataFrame())
    return out


def forms(R, res, m):
    C = res.get('sheets', {}).get('Общий анализ', {}).get('Конверсии', pd.DataFrame())
    rules = m.get('form_success_rules') or {}
    if isinstance(rules, str):
        try: rules = eval(rules)
        except Exception: rules = {}
    out = []
    if len(C):
        H = C[C['группа'] == 'Люди']
        for goal, g in C.groupby('цель'):
            hg = H[H['цель'] == goal]
            ent = hg['вход'].astype(str).map(first_seg).value_counts()
            where = 'на страницах всех разделов' if len(ent) >= 5 else ', '.join(ent.index[:3])
            rule = str(rules.get(goal, '')).replace('цель: ', '').replace('успех = 3xx (редирект после отправки)', 'переадресация после отправки (3xx)').replace('успех по коду не различим (200)', 'по коду ответа не различим (всегда 200)')
            nm = name_of(str(goal), FORM_NAME) or ('общий обработчик форм' if re.search(r'/form\.php$', str(goal)) else f"форма {re.sub(r'.*/', '', str(goal)).split('.')[0]}")
            ent = ent[[not re.match(r'^/(bitrix|local|upload|wp-\w+)/', e) for e in ent.index]]
            where = 'на страницах всех разделов' if len(ent) >= 5 else ', '.join(ent.index[:3])
            out.append(dict(форма=nm, адрес=str(goal), где=where,
                            успех=rule or 'по коду ответа', отправлено=len(hg), принято=int((hg['принята'] == 'да').sum()), ботов=int((g['группа'] == 'Боты').sum())))
    grp_ = {}
    for f in out:
        y = grp_.setdefault(f['форма'], dict(форма=f['форма'], адреса=[], где=Counter(), успех=Counter(), отправлено=0, принято=0, ботов=0))
        y['адреса'].append(f['адрес']); y['отправлено'] += f['отправлено']; y['принято'] += f['принято']; y['ботов'] += f['ботов']
        for w in (f['где'] or '').split(', '):
            if w: y['где'][w] += f['отправлено'] or 1
        y['успех'][f['успех']] += 1
    out = []
    for y in grp_.values():
        wh = [w for w, _ in y['где'].most_common()]
        out.append(dict(форма=y['форма'], адреса=y['адреса'], где='на страницах всех разделов' if 'на страницах всех разделов' in wh or len(wh) >= 5 else ', '.join(wh[:3]),
                        успех='; '.join(dict.fromkeys(y['успех'])), отправлено=y['отправлено'], принято=y['принято'], ботов=y['ботов']))
    out = sorted(out, key=lambda x: -x['отправлено'])
    nf = m.get('forms') or []
    if isinstance(nf, str):
        try: nf = eval(nf)
        except Exception: nf = []
    grp = Counter()
    for f in nf:
        if not isinstance(f, dict) or str(f.get('вывод', '')).startswith('цель'): continue
        a = str(f.get('адрес', ''))
        k = ('админка движка' if re.search(r'/bitrix/admin/|/wp-admin/|/administrator/', a) else 'загрузка файлов' if 'upload' in a
             else 'AJAX и служебные скрипты' if re.search(r'ajax|/tools/|/services/|autosave|\.php$', a) else 'отправки на главную и разделы (в основном сканеры)' if a.count('/') <= 2 else 'прочие')
        grp[k] += int(f.get('отправок', 0) or 0)
    return out, [dict(группа=k, отправок=v) for k, v in grp.most_common()]


def service_groups(m, res):
    sf = m.get('service_files') or []
    if isinstance(sf, str):
        try: sf = eval(sf)
        except Exception: sf = []
    g = {}
    for f in sf:
        if not isinstance(f, dict): continue
        a = str(f.get('адрес', ''))
        name = next((nm for nm, rx in SERVICE_GROUPS if re.search(rx, a, re.I)), 'Прочие')
        x = g.setdefault(name, dict(группа=name, файлов=0, запросов=0, ошибок=0, примеры=[]))
        x['файлов'] += 1; x['запросов'] += int(f.get('запросов', 0) or 0)
        x['ошибок'] += sum(int(n) for k, n in re.findall(r'(\d{3}):\s*(\d+)', str(f.get('коды', ''))) if k[0] in '45' and k != '499')
        if len(x['примеры']) < 3: x['примеры'].append(a)
    SV = res.get('sheets', {}).get('Ошибки', {}).get('Служебные файлы', pd.DataFrame())
    if len(SV):   # robots, sitemap и фиды — по полному листу, даже если их нет среди частых
        ok200 = set(SV.loc[SV['коды'].astype(str).str.contains(r'\b200:'), 'адрес'].astype(str))
        feeds_ = [a for a in SV['адрес'].astype(str).unique() if re.search(SERVICE_GROUPS[1][1], a, re.I) and '/.' not in a
                  and not re.search(r'config|application|database|docker|secret|credential|settings|env|compose|swagger|openapi|travis|gitlab|circleci', a, re.I)
                  and (a in ok200 and SV.loc[SV['адрес'].astype(str) == a, 'запросов'].sum() >= 20 or SV.loc[SV['адрес'].astype(str) == a, 'запросов'].sum() >= 50)]
        for a in feeds_:
            s = SV[SV['адрес'].astype(str) == a]
            x = g.setdefault('Фиды и выгрузки', dict(группа='Фиды и выгрузки', файлов=0, запросов=0, ошибок=0, примеры=[]))
            if a in x['примеры']: continue
            x['файлов'] += 1; x['запросов'] += int(s['запросов'].sum())
            x['ошибок'] += sum(int(n) for cc in s['коды'] for k, n in re.findall(r'(\d{3}):\s*(\d+)', str(cc)) if k[0] in '45' and k != '499')
            if len(x['примеры']) < 3: x['примеры'].append(a)
        for a in ('/robots.txt', '/sitemap.xml'):
            s = SV[SV['адрес'].astype(str) == a]
            if len(s) and 'Для роботов' not in g:
                g['Для роботов'] = dict(группа='Для роботов', файлов=0, запросов=0, ошибок=0, примеры=[])
            if len(s):
                x = g['Для роботов']
                if a not in x['примеры']:
                    x['файлов'] += 1; x['запросов'] += int(s['запросов'].sum()); x['примеры'].append(a)
                    x['ошибок'] += sum(int(n) for cc in s['коды'] for k, n in re.findall(r'(\d{3}):\s*(\d+)', str(cc)) if k[0] in '45' and k != '499')
    order = [nm for nm, _ in SERVICE_GROUPS] + ['Прочие']
    return [g[k] for k in order if k in g]


def embedded_groups(m):
    e = m.get('embedded_templates') or []
    if isinstance(e, str):
        try: e = eval(e)
        except Exception: e = []
    g = {}
    for x in e:
        if not isinstance(x, dict): continue
        a = str(x.get('шаблон', ''))
        name = ('Всплывающие формы' if re.search(r'form|modal|popup|callback', a, re.I) else 'Панель админки' if re.search(r'/admin/|wp-admin', a)
                else 'AJAX-блоки' if re.search(r'ajax|component', a, re.I) else 'Прочие блоки')
        y = g.setdefault(name, dict(группа=name, шаблонов=0, подгрузок=0, папка=re.sub(r'/[^/]*$', '/', a)))
        y['шаблонов'] += 1; y['подгрузок'] += int(float(x.get('запросов', 0) or 0))
    return sorted(g.values(), key=lambda y: -y['подгрузок'])


def param_groups(m, res):
    cnt = Counter()
    for k in ('ad_params', 'other_entry_params'):
        v = m.get(k) or {}
        if isinstance(v, str):
            try: v = eval(v)
            except Exception: v = {}
        for p, n in v.items():
            if len(str(p)) >= 2: cnt[p] += int(n)
    F = res.get('sheets', {}).get('Общий анализ', {}).get('Фильтры и поиск', pd.DataFrame())
    if len(F):
        for p, n in F.groupby('ключ')['применений'].sum().items():
            if len(str(p)) >= 2: cnt[p] = max(cnt[p], int(n))
    g = {nm: [] for nm, _ in PARAM_GROUPS}; g['Прочие'] = []
    for p, n in cnt.most_common():
        nm = next((nm for nm, rx in PARAM_GROUPS if re.search(rx, p, re.I)), 'Прочие')
        if nm == 'Прочие' and len(p) < 4: continue   # обрывки параметров из битых адресов
        g[nm].append((p, n))
    out = []
    for nm, xs in g.items():
        if not xs: continue
        shown = []
        for p, n in xs:
            b = re.sub(r'(_\d+)+$', '_*', p)
            if b not in [s for s, _ in shown]: shown.append((b, n))
        out.append(dict(группа=nm, параметров=len(xs), примеры=', '.join(s for s, _ in shown[:8]), применений=sum(n for _, n in xs)))
    return out


def hints(pages, res, m):
    """Подсказки о тематике для Детектива: слова из адресов, рекламные фразы, кампании, формы."""
    words = Counter(w for p, v in zip(pages['адрес'], pages['визитов']) for w in re.split(r'[/_.-]+', p.lower())
                    if len(w) >= 4 and not re.fullmatch(r'[0-9a-f]+|\d+|index|php|html|filter|apply|page', w) for _ in range(1))
    MK = res.get('sheets', {}).get('Маркетинг', {})
    ph = MK.get('Реклама: Фразы', pd.DataFrame())
    kc = MK.get('Реклама: Кампании', pd.DataFrame())
    col = next((c_ for c_ in ('фраза', 'utm_term', 'term') if c_ in ph), None) if len(ph) else None
    return dict(слова_адресов=[w for w, _ in words.most_common(30)],
                рекламные_фразы=[f for f in dict.fromkeys(unquote(str(q)).split('|')[0].strip() for q in ph.sort_values(ph.columns[1], ascending=False)[col].head(40))
                                 if f and not f.startswith('---')][:20] if col else [],
                кампании=kc['кампания'].astype(str).head(10).tolist() if len(kc) and 'кампания' in kc else [])
