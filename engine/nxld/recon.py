"""NXLD: разведка — что за сайт: сервер, движок, шаблоны адресов, формы, метки, служебные файлы, свои."""
import re
from collections import Counter, defaultdict
import numpy as np, pandas as pd

ENGINES = [
    ('1С-Битрикс', r'^/bitrix/|^/local/(templates|components|js)/|^/upload/iblock/'),
    ('WordPress', r'^/wp-content/|^/wp-includes/|^/wp-json/'),
    ('Joomla', r'^/components/com_|^/media/jui/|^/media/system/'),
    ('UMI.CMS', r'^/images/cms/|^/udata/|^/emarket/'),
    ('Drupal', r'^/sites/default/files/|^/core/misc/|^/misc/drupal\.js'),
    ('MODX', r'^/assets/components/|^/connectors/'),
    ('OpenCart', r'^/catalog/view/theme/'),
    ('Webasyst/Shop-Script', r'^/wa-data/|^/wa-apps/|^/wa-content/'),
    ('NetCat', r'^/netcat/|^/netcat_files/'),
    ('HostCMS', r'^/hostcmsfiles/'),
    ('DLE', r'^/engine/classes/|^/templates/.+/js/libs\.js'),
    ('Tilda', r'^/tild[\w-]*\.(js|css)|tildacdn'),
    ('Next.js', r'^/_next/'),
    ('Nuxt', r'^/_nuxt/'),
    ('Django', r'^/static/admin/'),
    ('Laravel', r'^/livewire/|^/vendor/livewire/'),
]
ADMIN_PATHS = {
    '1С-Битрикс': r'^/bitrix/admin/', 'WordPress': r'^/wp-admin/|^/wp-login\.php', 'Joomla': r'^/administrator/',
    'UMI.CMS': r'^/admin/', 'Drupal': r'^/user/login|^/admin/', 'MODX': r'^/manager/', 'OpenCart': r'^/admin/',
    'Webasyst/Shop-Script': r'^/webasyst/', 'NetCat': r'^/netcat/admin/', 'HostCMS': r'^/admin/', 'DLE': r'^/admin\.php',
    'Django': r'^/admin/', 'Laravel': r'^/admin/',
}
GENERIC_ADMIN = r'^/admin/|^/administrator/|^/manager/|^/panel/|^/cp/|^/backend/'
PD_PARAMS = re.compile(r'(?:^|&)(name|fio|phone|tel|telephone|email|e-mail|mail|message|comment)=([^&]+)', re.I)
AD_PARAMS = ['yclid', 'gclid', 'gbraid', 'wbraid', 'fbclid', 'rb_clickid', '_openstat', 'utm_source', 'utm_medium', 'utm_campaign',
             'utm_content', 'utm_term', 'calltouch_tm', 'roistat', 'from', 'ysclid', 'erid', 'vkclid', 'msclkid']
SUCCESS_MARK = re.compile(r'success|thank|spasibo|thanks|ok=|sent|otpravleno', re.I)


def norm_segment(s):
    if re.fullmatch(r'\d+', s) or re.fullmatch(r'[0-9a-f]{16,}', s, re.I) or re.fullmatch(r'[0-9a-f-]{32,36}', s, re.I):
        return '*'
    if re.fullmatch(r'[a-z_-]{1,8}\d+[a-z]?', s, re.I):   # dom-1, s2, e14, n8, page3
        return re.sub(r'\d+[a-z]?$', '*', s)
    return s


def build_templates(R, page_mask, min_children=30):
    """Шаблоны адресов: числа и ID -> *; уровень (кроме первого — разделов), где >= min_children
    разных значений, каждое у >= 2 разных IP, -> *. Возвращает массив шаблонов по категориям base."""
    bases = R['base'].cat.categories.to_series()
    codes = R['base'].cat.codes.values[page_mask]
    ipc = R['ip'].cat.codes.values[page_mask]
    ipn = pd.DataFrame({'b': codes, 'i': ipc}).drop_duplicates().groupby('b').size()
    good = set(ipn[ipn >= 2].index.tolist())
    segs = [[norm_segment(x) for x in b.split('/')] for b in bases]
    for depth in range(2, 9):
        children = defaultdict(set)
        for i in good:
            sg = segs[i]
            if len(sg) <= depth or sg[depth] in ('', '*'): continue
            children[tuple(sg[:depth])].add(sg[depth])
        wide = {k for k, v in children.items() if len(v) >= min_children}
        if not wide: continue
        for sg in segs:
            if len(sg) > depth and tuple(sg[:depth]) in wide and sg[depth] not in ('', '*') and not re.search(r'\.(php|html?|aspx?|jsp)$', sg[depth]):
                sg[depth] = '*'
    return np.array(['/'.join(s) for s in segs], dtype=object)


def detect_engine(R):
    ok = R['ua_browser'].values & np.isin(R['status'].values, [200, 304])
    bases = R['base'].cat.categories.to_series()
    res = []
    codes = R['base'].cat.codes.values
    ipc = R['ip'].cat.codes.values
    for name, rx in ENGINES:
        m = bases.str.contains(rx, regex=True).values
        hit = ok & m[codes]
        n = int(hit.sum())
        if n:
            res.append(dict(движок=name, запросов_браузеров_200=n, IP=int(len(np.unique(ipc[hit])))))
    df = pd.DataFrame(res, columns=['движок', 'запросов_браузеров_200', 'IP'])
    found = df[df.IP >= 20].sort_values('IP', ascending=False)
    if not len(found):
        pg = ok & ~R['is_static'].values & (R['method'].values == 'GET')
        b = bases.values[codes[pg]]
        html = pd.Series(b).str.contains(r'(\.html?|/)$', regex=True).mean() if len(b) else 0
        php = pd.Series(b).str.contains(r'\.php$', regex=True).mean() if len(b) else 0
        label = 'Статический HTML (признаков CMS нет)' if html > 0.9 and php < 0.01 else ('PHP без известного движка' if php > 0.05 else 'Свой движок или не определён')
        found = pd.DataFrame([dict(движок=label, запросов_браузеров_200=int(pg.sum()), IP=int(len(np.unique(ipc[pg]))))])
    return found, df


def detect_server(R, E):
    info = {}
    st = R['status'].values
    info['nginx_499'] = int((st == 499).sum())
    info['протокол'] = R['proto'].value_counts().head(4).to_dict()
    if E is not None and len(E):
        ups = E['upstream'].fillna('')
        fcgi = ups[ups.str.startswith('fastcgi')].str.extract(r'(php[\w.-]*|/run/php/[^:"]+|php-fpm/[^:"]+)')[0].dropna()
        info['upstream'] = ups[ups != ''].str.replace(r'/[^/]*\.php.*$', '', regex=True).str.slice(0, 60).value_counts().head(5).to_dict()
        info['php_fpm'] = fcgi.value_counts().head(3).to_dict()
        paths = E['msg'].str.extract(r'(/home/bitrix/www|/var/www/[\w.-]+|/usr/share/nginx/html|/srv/[\w.-]+|/home/[\w.-]+/[\w.-]+|[A-Z]:\\\\[^ ]+)')[0].dropna()
        info['пути_на_сервере'] = paths.value_counts().head(5).to_dict()
        php = E['msg'].str.extract(r'PHP (Fatal error|Warning|Notice|Deprecated|Parse error)')[0].dropna()
        info['php_сообщения'] = php.value_counts().to_dict()
        info['error_log'] = 'nginx'
    if info.get('nginx_499') or (E is not None and len(E)):
        info['веб-сервер'] = 'nginx' + (' → Apache' if any(':8888' in k or 'apache' in k.lower() for k in info.get('upstream', {})) else '') + \
                             (' → PHP-FPM' if any(k.startswith('fastcgi') for k in info.get('upstream', {})) else '')
    else:
        info['веб-сервер'] = 'не определён (nginx или Apache)'
    return info


def detect_ad_params(R, entry_mask):
    q = R['query'].astype(str).values[entry_mask]
    keys = Counter()
    for s in q:
        if not s: continue
        for kv in s.split('&'):
            k = kv.split('=', 1)[0].lower()
            if k: keys[k] += 1
    n = int(entry_mask.sum())
    known = {k: keys[k] for k in AD_PARAMS if keys.get(k)}
    other = {k: v for k, v in keys.most_common(30) if k not in known and v >= max(20, n * 0.002)}
    return known, other


def detect_service_files(R):
    b = R['base'].astype(str)
    m = b.str.contains(r'^/robots\.txt$|sitemap[\w-]*\.xml|\.yml$|\.yml\.gz$|/export/|feed|/rss|\.xml$|favicon|manifest\.json|site\.webmanifest|^/\.well-known/', case=False, regex=True)
    S = R.loc[m.values, ['base', 'status', 'fam', 'bytes', 'day']]
    if not len(S):
        return pd.DataFrame()
    g = S.groupby('base', observed=True)
    out = pd.DataFrame({
        'запросов': g.size(),
        'коды': g['status'].agg(lambda s: ', '.join(f'{k}:{v}' for k, v in s.value_counts().items())),
        'кто_забирает': g['fam'].agg(lambda s: ', '.join(f'{k or "браузеры/прочие"}:{v}' for k, v in s.astype(str).value_counts().head(4).items())),
        'средний_размер_КБ': (g['bytes'].mean() / 1024).round(1),
        'первый_день': g['day'].agg(lambda s: str(min(s))), 'последний_день': g['day'].agg(lambda s: str(max(s))),
    }).reset_index().rename(columns={'base': 'адрес'})
    out = out[out['запросов'] >= 3].sort_values('запросов', ascending=False)
    return out


FORM_HINT = re.compile(r'form|callback|feedback|order|lead|request|zayav|subscribe|contact|send|submit|question|booking|zapis|anketa|quiz|calc', re.I)


def detect_forms(R, tpl):
    """Цели: POST от браузеров со страниц сайта. Признак успеха — по реакции сервера.
    AJAX-адреса, которые всегда отвечают 200 и не похожи на формы, целями не считаются."""
    m = (R['method'].values == 'POST') & R['ua_browser'].values & R['ref_internal'].values
    P = R.loc[m, ['ts', 'ip', 'base', 'query', 'status']].copy()
    if not len(P):
        return pd.DataFrame(), {}
    P['tpl'] = tpl[R['base'].cat.codes.values[m]]
    q = P['query'].astype(str)
    P['form'] = q.str.extract(r'(?:^|&)(?:form|form_id|WEB_FORM_ID|formid|form_name)=([^&]+)', flags=re.I)[0].fillna('')
    P['key'] = P['tpl'] + np.where(P['form'] != '', '?form=' + P['form'], '')
    rows, rules = [], {}
    for key, g in P.groupby('key'):
        n = len(g)
        if n < 3: continue
        vc = g['status'].value_counts()
        ok_share = g['status'].between(200, 399).mean()
        r3 = int(g['status'].isin([302, 303]).sum())
        r301 = (g['status'].isin([301, 308])).mean()
        hint = bool(FORM_HINT.search(key))
        if ok_share < 0.5:
            rule = 'не цель: адрес не принимает POST (404/405/ошибки)'
        elif r301 >= 0.5:
            rule = 'не цель: адрес перенаправляется (301)'
        elif r3 >= max(2, 0.1 * n) and (hint or (key.endswith('.php') and r3 >= 0.3 * n and g['ip'].nunique() >= 5)):
            rule = 'цель: успех = 3xx (редирект после отправки)'
        elif hint:
            rule = 'цель: успех по коду не различим (200)'
        else:
            rule = 'не цель: AJAX/служебный адрес'
        rules[key] = rule
        rows.append(dict(адрес=key, отправок=n, IP=g['ip'].nunique(), коды=', '.join(f'{k}:{v}' for k, v in vc.items()),
                         вывод=rule, первый=pd.to_datetime(g.ts.min(), unit='s'), последний=pd.to_datetime(g.ts.max(), unit='s')))
    D = pd.DataFrame(rows).sort_values(['вывод', 'отправок'], ascending=[True, False])
    goals = {k: v for k, v in rules.items() if v.startswith('цель')}
    return D, goals


def detect_get_pd(R):
    q = R['query'].astype(str)
    cats = R['query'].cat.categories.to_series()
    hit = cats.str.contains(PD_PARAMS, regex=True).values
    m = hit[R['query'].cat.codes.values] & (R['method'].values == 'GET')
    G = R.loc[m, ['ts', 'ip', 'base', 'query', 'status', 'ua', 'fam']].copy()
    return G[G['query'].astype(str).map(has_pd)]


SAFE_GROUPS = ('Реклама и аналитика', 'Поисковики и Яндекс')   # рекламные и поисковые идентификаторы — не ПД, не маскируются
PD_KEYS = re.compile(r'(?i)(phone|tel|telephone|mobile|email|e-mail|mail|fio|surname|lastname|last_name|passport|snils|inn)')
TEXT_KEYS = re.compile(r'(?i)(name|fio|message|comment)')   # свободный текст человека — при маскировке целиком ***
EMAIL = re.compile(r'([\w.-])[\w.-]*@([\w-])[\w.-]*')
SECRET_KEYS = ('sessid', 'phpsessid', 'token', 'access_token', 'api_key', 'apikey', 'key', 'password', 'passwd', 'user_checkword', 'checkword')
SECRET_RX = r'(?i)(?:^|&)(' + '|'.join(SECRET_KEYS) + r')='   # секреты в адресе: сессии, токены, пароли, код сброса пароля Битрикса — не ПД, но в отчёте не открыто
_SAFE, _REF = {}, []


def _key(k):
    """Ключ параметра для сверки: раскодирован, без «amp;» от экранированного &amp; (иначе amp;phone прошёл бы как служебный amp;*)."""
    from urllib.parse import unquote_plus
    k = unquote_plus(str(k)).strip()
    while k.lower().startswith('amp;'): k = k[4:]
    return k


def is_ad_key(k):
    """Ключ из групп справочника «Реклама и аналитика» / «Поисковики и Яндекс» (common.json, services, learned) или из AD_PARAMS."""
    k = _key(k).lower()
    if k not in _SAFE:
        if not _REF:
            from . import reference
            try: _REF.append(reference.Reference())
            except Exception: _REF.append(None)
        e = _REF[0].match(k) if _REF[0] is not None else None
        _SAFE[k] = k in AD_PARAMS or (e is not None and e.get('группа') in SAFE_GROUPS)
    return _SAFE[k]


def is_phone(v):
    """Похоже на телефон: из цифр, пробелов, скобок, дефисов и «+»; 10–11 цифр, начинается с 7 или 8; с «+» — 10–15 цифр. Длиннее 15 — не телефон."""
    v = str(v).strip()
    if not re.fullmatch(r'\+?[\d\s()-]+', v): return False
    d = re.sub(r'\D', '', v)
    if len(d) > 15: return False
    if v.startswith('+'): return 10 <= len(d) <= 15
    return len(d) in (10, 11) and d[0] in '78'


def is_secret_key(k):
    """Ключ секрета (сессия, токен, ключ API, пароль, USER_CHECKWORD) — без учёта регистра."""
    return _key(k).lower() in SECRET_KEYS


def _pd_kind(k, v):
    """Чем параметр k=v (v раскодирован) — персональные данные: 'phone', 'email', 'field' (поле ФИО/телефона/почты) или None."""
    if not v or is_ad_key(k) or re.search(r'autodiscover|/|\\.json', v, re.I): return None   # рекламные метки; зонды сканеров
    if re.search(r'@[\w-]+\.[a-z]{2,}', v, re.I): return 'email'
    if is_phone(v): return 'phone'
    if PD_KEYS.fullmatch(_key(k)): return 'field'
    return None


def has_pd(q):
    """Персональные данные — по значениям, а не по имени параметра: телефон, почта или явное поле ФИО/телефона/почты.
    name=Квартал Заречный — это название проекта в загрузке формы, не данные человека.
    Рекламные и поисковые идентификаторы (clid, yclid, gclid, utm_* …) — никогда не ПД."""
    from urllib.parse import unquote_plus
    for part in str(q).split('&'):
        k, _, v = part.partition('=')
        if _pd_kind(k, unquote_plus(v).strip()): return True
    return False


def _mask_digits(v):
    d = re.sub(r'\D', '', v)
    if len(d) < 4: return '***'
    return ('+' if v.strip().startswith('+') else '') + d[0] + (' ' + d[1] if len(d) >= 10 else '') + '** ***-**-' + d[-2:]


def mask_value(k, v):
    """Замаскированное значение параметра k или None, если маскировать нечего.
    Секрет — первые 4 символа и «…»; ПД — по _pd_kind; рекламные идентификаторы не трогаются."""
    from urllib.parse import unquote_plus
    if is_secret_key(k) and v: return str(v)[:4] + '…'
    u = unquote_plus(v).strip()
    kind = _pd_kind(k, u)
    if TEXT_KEYS.fullmatch(_key(k)) and u and not is_ad_key(k): return '***'
    if kind == 'phone': return _mask_digits(u)
    if kind == 'email': return EMAIL.sub(r'\1***@\2***', u)
    if kind == 'field': return _mask_digits(u) if re.search(r'(?i)phone|tel|mobile', _key(k)) else '***'
    return None


def has_secret(q):
    """Есть параметр-секрет с непустым значением (has_pd из-за них не срабатывает: это не ПД)."""
    return any(is_secret_key(k) and v for k, _, v in (p.partition('=') for p in str(q).split('&')))


def mask_secrets(s):
    """Только секреты: значение — первые 4 символа и «…»; остальное как было."""
    s = str(s)
    head, sep, q = s.partition('?') if '?' in s else ('', '', s)
    return head + sep + '&'.join(k + eq + v[:4] + '…' if eq and v and is_secret_key(k) else k + eq + v for k, eq, v in (p.partition('=') for p in q.split('&')))


def mask_pd(s):
    """Маскировка по параметрам: значения-ПД и секреты (сессия, токен, USER_CHECKWORD…); остальные параметры, порядок и разделители как были.
    Просто текст (без «?» и «=») — регулярками по всей строке."""
    s = str(s)
    if '?' not in s and '=' not in s:
        s = re.sub(r'(\+?\d)[\d\s()-]{6,}(\d\d)', lambda m: m.group(1) + '** ***-**-' + m.group(2), s)
        s = EMAIL.sub(r'\1***@\2***', s)
        return s
    head, sep, q = s.partition('?') if '?' in s else ('', '', s)
    out = []
    for part in q.split('&'):
        k, eq, v = part.partition('=')
        m = mask_value(k, v) if eq else None
        out.append(k + eq + m if m is not None else part)
    return head + sep + '&'.join(out)


def detect_hosting(E, rules_path=None):
    """Тип хостинга и ОС по путям на сервере из error-лога. Правила — data/hosting_rules.json."""
    import json, os
    rules_path = rules_path or os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'hosting_rules.json')
    cfg = json.load(open(rules_path, encoding='utf-8')) if os.path.exists(rules_path) else {'правила': [], 'иначе': 'тип хостинга по логам не определён'}
    if E is None or not len(E):
        return dict(тип='по логам не видно (нет error-лога)', путь=None, ос='по логам не видно (нет error-лога)', другие_пользователи=[])
    msg = E['msg'].astype(str)
    paths = msg.str.extractall(r'(/(?:var|mnt|home|srv|usr|opt|etc)/[^\s"\',:;)]+)')[0]
    win = msg.str.contains(r'[A-Za-z]:\\', regex=True).any()
    os_ = 'Linux/Unix (по путям на сервере; дистрибутив и версия по логам не видны)' if len(paths) else ('Windows (по путям на сервере)' if win else 'по логам не видно')
    roots = paths.str.extract(r'^(/var/www/[^/]+/data/www/[^/]+|/mnt/data/www/[^/]+|/home/[^/]+/[^/]+|/var/www/[^/]+)')[0].dropna()
    if not len(roots):
        return dict(тип=cfg['иначе'], путь=None, ос=os_, другие_пользователи=[])
    root = roots.value_counts().index[0]
    kind = cfg['иначе']
    for r in cfg.get('правила', []):
        if re.match(r['шаблон'], root):
            kind = r['тип']; break
    users = sorted(set(roots.str.extract(r'^/var/www/([^/]+)')[0].dropna()) - {re.sub(r'^/var/www/([^/]+).*', r'\1', root)})
    if users:
        kind += '; в логах видны другие пользователи сервера'
    return dict(тип=kind, путь=root, ос=os_, другие_пользователи=users[:10])


# --- Файлы: всё, что забирают как отдельный файл (не страницы) ---------------------------------
FILE_GROUPS = [   # порядок важен: первая подходящая группа
    ('Для роботов', r'^/(robots\.txt|sitemap[\w.-]*\.xml(\.gz)?|sitemap/.*|llms(-full)?\.txt|ai\.txt|ads\.txt|app-ads\.txt|humans\.txt)$'),
    ('Подтверждение прав', r'(^/yandex_[0-9a-f]+\.html$|^/google[0-9a-f]+\.html$|^/\.well-known/acme-challenge/)'), ('Служебные (.well-known)', r'^/\.well-known/'),
    ('Фиды и выгрузки', r'(/export/|/feeds?(/|\.xml$|$)|/rss(/|\.xml$|$)|\.ya?ml(\.gz)?$|yandex[\w-]*\.xml$|google[\w-]*\.xml$|\.csv$)'),
    ('Иконки и манифест', r'(favicon[\w.-]*\.(ico|png|svg)$|apple-touch[\w.-]*\.png$|/manifest\.json$|\.webmanifest$|/browserconfig\.xml$|\.ico$)'),
    ('Документы', r'\.(pdf|docx?|xlsx?|pptx?|rtf|odt|ods|odp|zip|rar|7z|gz|tar)$'),
    ('Данные для виджетов', r'\.(xml|json)$'),
    ('Картинки', r'\.(jpe?g|png|webp|gif|svg|avif|bmp|tiff?)$'),
    ('Шрифты', r'\.(woff2?|ttf|otf|eot)$'),
    ('Стили и скрипты', r'\.(css|js|mjs)$'),
    ('Карты кода', r'\.map$'),
    ('Видео и звук', r'\.(mp4|webm|mov|avi|m4v|mkv|mp3|ogg|wav|m4a|flac)$'),
    ('Прочие файлы', r'\.(?!(?:ru|com|net|org|su|info|io|by|kz|ua|biz|pro|online|site|store|shop|me|tv|рф)$)[A-Za-z0-9]{1,8}$'),   # всё остальное с расширением — файл (страницы отсеяны раньше)
]
PAGE_EXT = r'\.(php\d?|html?|shtml|aspx?|jsp|cgi|pl)$'   # это страницы, а не файлы
FOLD_AS = {'Картинки': 'картинки', 'Шрифты': 'шрифты', 'Видео и звук': 'видео'}   # свёртка без разбора расширения
PAGE_ASSETS = {'Картинки', 'Шрифты', 'Стили и скрипты', 'Иконки и манифест'}
# их запрашивают сами браузеры и роботы, без ссылки: 404 у них — факт, а не зонд
AUTO_ASKED = r'^/(robots\.txt|sitemap[\w-]*\.xml(\.gz)?|llms(-full)?\.txt|ai\.txt|ads\.txt|app-ads\.txt|\.well-known/security\.txt|favicon\.ico|apple-touch-icon[\w-]*\.png)$'


def _file_group(a):
    if re.search(PAGE_EXT, a, re.I) and not re.search(FILE_GROUPS[1][1], a, re.I): return None
    if '//' in a or re.search(r'/\.(?!well-known/)', a): return None   # скрытые файлы (.env, .git…) — это зонды, они на листах безопасности
    for nm, rx in FILE_GROUPS:
        if re.search(rx, a, re.I): return nm
    return None


def _top(s, n=4):
    vc = s.value_counts()
    return ', '.join(f'{k}:{v}' for k, v in vc.head(n).items())


def _others(src, n=5, skip=('со страниц сайта', 'без перехода')):
    vc = src[~src.isin(list(skip))].value_counts()
    vc = vc[vc > 0]
    out = ', '.join(f'{k}:{v}' for k, v in vc.head(n).items())
    return out + (f', и ещё {len(vc) - n}' if len(vc) > n else '')


def files_inventory(R, min_req=3, T=None, addr=None, people=None):
    """Все файлы, которые не страницы: для роботов, фиды, иконки, документы, данные виджетов, картинки, шрифты,
    стили и скрипты, карты кода, видео, прочее. Однотипные файлы одной папки сворачиваются в одну строку.
    Зонды сканеров отбрасываются: файл, ни разу не отданный (2xx/304), остаётся, только если его просят сами
    браузеры и роботы (AUTO_ASKED), много разных IP, или на него ссылаются страницы сайта с разных IP."""
    cats = R['base'].cat.categories.to_series().astype(str)
    if addr is not None:   # группа — по реестру адресов (справочник расширений); страницы и конструкты — не файлы
        grp_c = np.where((addr['форма'] == 'файл').values, addr['группа'].values, None)
    else:
        grp_c = cats.map(_file_group).values
    codes = R['base'].cat.codes.values
    keep = pd.notna(grp_c[codes])
    S = R.loc[keep, ['ip', 'status', 'fam', 'bytes', 'day', 'ref_host', 'ref_internal']].copy()
    S['_p'] = np.asarray(people)[keep] if people is not None else S['fam'].astype(str).eq('').values   # люди и свои
    if not len(S): return pd.DataFrame()
    bc = codes[keep]
    S['base'] = cats.values[bc]; S['grp'] = grp_c[bc]
    S['fam'] = S['fam'].astype(str).replace('', 'браузеры/прочие')
    rh = S['ref_host'].astype(str).str.split(',').str[0].str.strip()
    S['src'] = np.where(S['ref_internal'].values, 'со страниц сайта', np.where(rh.isin(['', 'nan', '-']), 'без перехода', rh))
    ok = (S['status'].between(200, 299) | (S['status'] == 304)).values
    good = set(pd.unique(S['base'].values[ok]))
    bad = S[~S['base'].isin(good)]
    # не отданные ни разу — файл сайта, только если его просили со страниц сайта люди или свои (битая ссылка на файл)
    # или его просят сами браузеры и роботы (robots, favicon); остальное — зонды, они на листах безопасности
    asked = set(bad.loc[bad['ref_internal'].values & bad['_p'].values, 'base'])
    for a_ in pd.unique(bad['base']):
        if re.search(AUTO_ASKED, a_, re.I) or a_ in asked: good.add(a_)
    S = S[S['base'].isin(good)]
    cnt = S['base'].value_counts()
    S = S[S['base'].map(cnt).values >= min_req]
    if not len(S): return pd.DataFrame()
    # свёртка: файлы одной группы в одной папке второго уровня с одним видом, если их >= 3
    U = S.drop_duplicates('base')[['base', 'grp']].copy()
    U['seg'] = U['base'].str.extract(r'^(/[^/]+/[^/]+/)')[0]
    U['ext'] = U['base'].str.extract(r'\.([A-Za-z0-9]+)$')[0].str.lower().fillna('')
    U['ext'] = [FOLD_AS.get(g, e) for g, e in zip(U['grp'], U['ext'])]
    U['key'] = U['base']
    m = U['seg'].notna() & (U['grp'] != 'Для роботов')
    n = U[m].groupby(['seg', 'ext', 'grp'])['base'].transform('size')
    f = U[m][n >= 3]
    U.loc[f.index, 'key'] = f['seg'] + '…/' + np.where(f['ext'] == '', '*', '*.' + f['ext'])
    S['key'] = S['base'].map(dict(zip(U['base'], U['key'])))
    rows = []
    for k, s in S.groupby('key', sort=False):
        files = pd.unique(s['base'])
        sub = ''
        if len(files) > 1:
            pre = k.split('…')[0]
            ch = pd.Series([x[len(pre):].split('/')[0] if '/' in x[len(pre):] else '' for x in files])
            ch = ch[ch != '']
            named = ch[~ch.str.fullmatch(r'[0-9a-f]{2,}|\d+')]   # хеш-папки движка не называем
            if named.nunique() >= 2 and len(named) >= len(ch) * 0.5:
                sub = f"папок {ch.nunique()}: " + ', '.join(ch.value_counts().index[:6]) + (' …' if ch.nunique() > 6 else '')
        rows.append(dict(адрес=k, группа=s['grp'].iloc[0], файлов=int(len(files)), внутри=sub, запросов=int(len(s)),
                         коды=', '.join(f'{c}:{v}' for c, v in s['status'].value_counts().sort_index().items()),
                         кто_забирает=_top(s['fam']), браузеры=int((s['fam'] == 'браузеры/прочие').sum()),
                         роботы=_others(s['fam'], skip=('браузеры/прочие',)), со_страниц=int((s['src'] == 'со страниц сайта').sum()),
                         напрямую=int((s['src'] == 'без перехода').sum()), другие_сайты=_others(s['src']),
                         средний_размер_КБ=round(float(s['bytes'].mean()) / 1024, 1),
                         первый_день=str(min(s['day'].astype(str))), последний_день=str(max(s['day'].astype(str)))))
    return pd.DataFrame(rows).sort_values('запросов', ascending=False)


# --- Параметры запросов: каждый ключ после «?» -----------------------------------------------------
ATTACK_VALUE = re.compile(r'\.\./|169\.254\.|file://|/etc/passwd|/proc/self|call_user_func|<script|union[\s+]+select|phpinfo|\$\{jndi|/bin/(ba)?sh|cmd\.exe|wget\s|curl\s|base64_decode|eval\(', re.I)
PROBE_VALUE = re.compile(r'\.invalid\b|redirect-?check|\.oast\.|interact\.sh|burpcollaborator|canarytokens|dnslog|\.example\.(com|org|net)\b', re.I)   # подставные адреса сканеров
NAV_KEYS = r'^(set_filter|del_filter|arrfilter\w*|q|search|query|find|poisk|pagen_\d+|page|p|view|display|show|mode|sort\w*|order\w*|by)$'   # как на «Точках приёма»


def _family(k, ref=None):
    """Семейство ключа: шаблон из справочника (PAGEN_*), иначе — имя до первой части с цифрами (itemsFilter_22_MIN → itemsFilter_*)."""
    f = ref.family(k) if ref is not None else None
    if f: return f
    m = re.match(r'^(.*?[A-Za-z])_(?=[^_]*\d)', k)
    return m.group(1) + '_*' if m else k


def query_params_inventory(R, human, groups, nav_keys=(), sys_prefixes=(), ref=None, top_n=300, staff=None, zone_prefixes=(), T=None):
    """Ключ (или семейство ключей) параметра → группа, что это, откуда знаем, запросы, люди, значения, где встречается.
    Порядок решения: кто спрашивает (атаки, сканеры) → справочник → поведение (навигация на страницах, системные папки, пачка) → имя.
    Семейство (itemsFilter_*) решается целиком по суммарному поведению и показывается одной строкой."""
    from urllib.parse import unquote
    qc = R['query'].cat.categories.to_series().astype(str)
    codes = R['query'].cat.codes.values
    has = codes >= 0
    L = len(qc)
    bc = lambda m: np.bincount(codes[m], minlength=L)
    cnt = bc(has)
    emb = R['is_embedded'].values if 'is_embedded' in R else np.zeros(len(R), bool)
    pg_ok = has & R['is_page'].values & ~emb & (R['method'].values == 'GET')   # обычные страницы, не вставки
    cnt_nav, cnt_nav_h = bc(pg_ok), bc(pg_ok & np.asarray(human))
    bstr = R['base'].cat.categories.to_series().astype(str)
    sys_b = bstr.map(lambda x: any(x.startswith(p_) for p_ in sys_prefixes)).values if sys_prefixes else np.zeros(len(bstr), bool)
    cnt_sys = bc(has & sys_b[R['base'].cat.codes.values])
    scan = R['fam_cat'].astype(str).values == 'Сканеры безопасности' if 'fam_cat' in R else np.zeros(len(R), bool)
    cnt_scan = bc(has & scan)
    cnt_int_h = bc(has & np.asarray(human) & R['ref_internal'].values)   # люди, пришедшие со страниц сайта
    cnt_emb = bc(has & emb)   # подгрузки внутри открытой страницы
    cnt_staff = bc(has & (np.asarray(staff) if staff is not None else np.zeros(len(R), bool)))
    R_zone_paths = list(zone_prefixes)
    # разделы, куда за весь лог ходили люди или сотрудники: зонд стучится туда, где никого не бывает
    sec_all = R['base'].astype(str).str.extract(r'^(/[^/?]*/?)')[0].values
    ok_ = (R['status'].values >= 200) & (R['status'].values < 300)   # переадресация — не ответ: сайт может слать 301 на любой адрес
    lived = set(pd.unique(sec_all[(np.asarray(human) | (np.asarray(staff) if staff is not None else np.zeros(len(R), bool))) & ok_]))   # живой раздел — людям там отвечают
    foreign_paths = list(getattr(ref, 'foreign_paths', ()) or ())   # папки и признаки движков, которых на сайте нет
    zone_b = bstr.map(lambda x: any(x.startswith(p_) for p_ in R_zone_paths)).values if R_zone_paths else np.zeros(len(bstr), bool)
    cnt_zone = bc(has & zone_b[R['base'].cat.codes.values])
    cnt_err = bc(has & (R['status'].values >= 400))
    srch = R['fam_cat'].astype(str).values == 'Поисковик' if 'fam_cat' in R else np.zeros(len(R), bool)
    cnt_srch = bc(has & srch)
    named = (R['fam'].astype(str).values != '') & ~scan & ~np.asarray(human)   # известные роботы (поисковики, SEO, ИИ…), не сканеры
    cnt_named = bc(has & named)
    other = getattr(ref, 'other', None)   # справочник всех движков: ключ чужого движка без людей — зонд под этот движок
    if T is None:
        from .thresholds import Sizes
        T = Sizes(визиты=int(pd.unique(R['vid'].values[np.asarray(human)]).size), запросы=len(R), ip=int(R['ip'].nunique()))
    t_people, t_int, t_nav, t_pack, t_frag = T('ключ_вызывают_люди'), T('ключ_со_страниц_сайта'), T('навигация_люди_на_страницах'), T('пачка_ключей'), T('обрывок_ключа')
    pairs = []   # (код запроса, ключ, значение)
    for i, q in enumerate(qc.values):
        if not cnt[i] or not q or q == 'nan': continue
        for kv in q.split('&'):
            k, _, v = kv.partition('=')
            k = unquote(k).strip()
            if re.fullmatch(r'\d+|[0-9a-f]{16,}', k) and not v: k = '(число без имени)'   # ?1778857049245644 — метка от кэша
            if 1 <= len(k) <= 40 and re.fullmatch(r'[\w\[\]\-.()а-я ;]+', k): pairs.append((i, k, v))
    if not pairs:   # в логе нет ни одного параметра — пустой реестр с теми же колонками (вызывающий код фильтрует по ним)
        return pd.DataFrame(columns=['параметр', 'ключ', 'ключи', 'группа', 'что', 'источник', 'ссылка', 'запросов', 'людей', 'значений', 'частое_значение',
                                     'значения', 'вместе_с', 'где', 'роботы'])
    P = pd.DataFrame(pairs, columns=['q', 'ключ', 'значение'])
    P['n'] = cnt[P['q'].values]
    hm = has & np.asarray(human)
    HV = pd.DataFrame({'q': codes[hm], 'vid': R['vid'].values[hm]}).drop_duplicates()
    sec = R['base'].astype(str).str.extract(r'^(/[^/?]*/?)')[0].values
    SQ = pd.DataFrame({'q': codes[has], 'sec': sec[has]}).groupby(['q', 'sec']).size().rename('m').reset_index()
    fams_ = R['fam'].astype(str).values
    FQ = pd.DataFrame({'q': codes[has & ~np.asarray(human)], 'fam': fams_[has & ~np.asarray(human)]}).groupby(['q', 'fam']).size().rename('m').reset_index()
    # написания одного ключа → самое частое; обрывки из битых адресов (начало более частого ключа) — прочь
    tot = P.groupby('ключ')['n'].sum()
    low = tot.groupby(tot.index.str.lower()).idxmax()
    P['ключ'] = P['ключ'].str.lower().map(low)
    tot = P.groupby('ключ')['n'].sum().sort_values(ascending=False)
    keys = list(tot.index)
    frag = {k for k in keys if not k.startswith('(') and ref is not None and ref.match(k) is None
            and any(K != k and K.lower().startswith(k.lower()) and tot[K] >= tot[k] for K in keys)}
    P = P[~P['ключ'].isin(frag)]
    P['семья'] = P['ключ'].map(lambda k: _family(k, ref))
    fam_size = P.groupby('семья')['ключ'].nunique()
    P['группа_ключей'] = np.where(P['семья'].map(fam_size).values >= 2, P['семья'].values, P['ключ'].values)
    navk = {str(k).lower() for k in nav_keys}
    qkeys = P.groupby('q')['группа_ключей'].agg(frozenset)

    def companions(k, qs):
        w = cnt[qs]; tot_ = w.sum(); c_ = {}
        for q_, w_ in zip(qs, w):
            for kk in qkeys[q_]: c_[kk] = c_.get(kk, 0) + w_
        return sorted([kk for kk, v in c_.items() if kk != k and v >= 0.9 * tot_], key=lambda kk: (-c_[kk], kk))   # при равенстве — по имени: порядок не плавает от запуска к запуску

    form_rx = next((rx for nm, rx in groups if nm == 'Данные форм'), r'^form')

    def top_sec(qs):
        s_ = SQ[SQ['q'].isin(qs)].groupby('sec')['m'].sum().sort_values(ascending=False)
        return (s_.index[0], s_.iloc[0] / max(1, s_.sum())) if len(s_) else ('', 0)

    def deduce(k, members, qs, n_, people, vc):
        """Дедукция: сначала поведение (кто вызывает, как, куда), имя — только гипотеза, которую поведение подтверждает.
        Представиться ключ может чем угодно; что это на самом деле, видно по тому, как им пользуются."""
        sec, sh = top_sec(qs)
        n_pg, n_pg_h, n_int_h = cnt_nav[qs].sum(), cnt_nav_h[qs].sum(), cnt_int_h[qs].sum()
        n_sys, n_zone, n_staff, n_err, n_emb = cnt_sys[qs].sum(), cnt_zone[qs].sum(), cnt_staff[qs].sum(), cnt_err[qs].sum(), cnt_emb[qs].sum()
        clues = []
        # кто вызывает
        by_people = people >= t_people and n_int_h >= t_int
        if by_people: clues.append(f'вызывают люди со страниц сайта ({_visits(people)})')
        elif n_staff >= 0.5 * n_: clues.append('работают сотрудники')
        elif people == 0: clues.append('людей нет')
        # как и куда
        if n_emb >= 0.5 * n_: clues.append('подгрузка внутри открытой страницы' + (f', обработчик {sec}' if sh >= 0.5 else ''))
        elif n_sys >= 0.8 * n_: clues.append(f'запросы в системные папки движка ({sec})')
        elif n_zone >= 0.8 * n_: clues.append(f'запросы в закрытый раздел {zone_of(qs)}')
        elif n_pg >= 0.5 * n_: clues.append(('переходы на страницы' if by_people else 'обращения к адресам') + (f' {sec}' if sh >= 0.5 else ''))
        elif sec and sh >= 0.5: clues.append(f'запросы в {sec}')
        if n_err >= 0.5 * n_: clues.append(f'ответы с ошибкой ({n_err / n_:.0%})')
        comp = companions(k, qs) if n_ >= t_pack else []
        with_ = ', '.join(comp[:6]) + (' …' if len(comp) > 6 else '') if len(comp) >= 4 else ''
        # гипотезы по имени — только если поведение совпадает с ожидаемым
        nav_hyp = any(re.fullmatch(NAV_KEYS, m_, re.I) or m_.lower() in navk for m_ in members)
        nav_ok = nav_hyp and n_pg >= 0.5 * n_ and n_pg_h >= t_nav and n_emb < 0.5 * n_       # навигация — это переходы по страницам-спискам
        txt = sum(int(w) for v_, w in vc.items() if re.search(r'[^\d\s.,:;-]', str(v_)) and len(str(v_)) >= 3)
        form_ok = bool(re.search(form_rx, k, re.I)) and by_people and n_pg < 0.5 * n_ and txt >= 0.5 * vc.sum()   # поле формы — люди отправляют текст в обработчик
        if nav_ok: return 'Поиск и навигация', 'меняет список на странице', clues + ['поведение соответствует имени: навигация'], with_
        if n_sys >= 0.8 * n_: return 'Служебные движка', 'служебный запрос движка', clues, with_
        if n_zone >= 0.8 * n_ and n_staff >= 0.5 * n_: return 'Логика сайта', f'служебный раздел {zone_of(qs)}', clues, with_
        if by_people:
            if form_ok: return 'Логика сайта', 'поле формы', clues + ['поведение соответствует имени: форма'], with_
            what = 'вызов внутри страницы (подгрузка, окно)' if n_emb >= 0.5 * n_ else 'параметр страниц сайта' if n_pg >= 0.5 * n_ else 'параметр сайта'
            return 'Логика сайта', what, clues, with_
        if with_: return 'Метки сервисов', 'приходит пачкой с другими ключами', clues + ['приходит пачкой'], with_
        return 'Неизвестные', '', clues, with_

    def zone_of(qs):
        bs = R_zone_paths
        return next((z for z in bs if any(str(s_).startswith(z.rstrip('/')) for s_ in [top_sec(qs)[0]])), bs[0] if bs else '')

    rows = []
    for k, g in P.groupby('группа_ключей'):
        qs = g['q'].unique()
        members = sorted(g['ключ'].unique(), key=lambda m_: -tot.get(m_, 0))
        n_ = int(cnt[qs].sum())
        vc = g.groupby('значение')['n'].sum().sort_values(ascending=False)
        vals = [unquote(str(v_).replace('+', ' '), errors='replace') for v_ in vc.index[:3]]
        top_v = vals[0] if vals else ''
        dec = lambda v_: unquote(unquote(str(v_), errors='replace'), errors='replace')   # бывает закодировано дважды (%252e)
        att = sum(int(w) for v_, w in vc.items() if ATTACK_VALUE.search(dec(v_)) or PROBE_VALUE.search(dec(v_)))
        people = int(HV[HV['q'].isin(qs)]['vid'].nunique())
        entry = ref.match(k) if ref is not None else None
        if entry is None and ref is not None and len(members) > 1:
            entry = next((e for e in (ref.match(m_) for m_ in members[:5]) if e), None)
        d_grp, d_what, clues, with_ = deduce(k, members, qs, n_, people, vc)
        what, src, link = '', '', ''
        few_people = people <= max(1, 0.02 * n_)
        foreign = other.match(k) if other is not None and entry is None and few_people else None
        foreign = foreign if foreign and str(foreign.get('файл', '')).startswith('engines/') else None
        s_top = SQ[SQ['q'].isin(qs)].groupby('sec')['m'].sum()
        main_secs = [x for x, v_ in s_top.items() if v_ >= 0.2 * n_]
        dead_secs = [x for x in main_secs if x not in lived and not any(str(x).startswith(z) for z in R_zone_paths)]   # свои разделы, где бывают люди и сотрудники, — не зонд
        f_path = next(((x, fp[1]) for fp in foreign_paths for x in dead_secs if str(x).startswith(fp[0]) or (fp[0].startswith('^') and re.match(fp[0], str(x)))), None) if few_people and entry is None else None
        nowhere = entry is None and bool(main_secs) and len(dead_secs) == len(main_secs) and cnt_sys[qs].sum() < 0.5 * n_   # раздела для людей нет: им там ни разу не ответили успешно
        dead = few_people and cnt_err[qs].sum() >= 0.9 * n_ and cnt_named[qs].sum() < 0.5 * n_   # обход старых ссылок роботами — не зонд
        if att >= 0.5 * vc.sum() or (cnt_scan[qs].sum() >= 0.5 * n_ and people == 0) or foreign or f_path or (dead and entry is None) or nowhere:
            grp_, src = 'Атаки и зонды', 'дедукция'
            why = ('значения похожи на атаку или подставной адрес' if att >= 0.5 * vc.sum() else 'запрашивают сканеры безопасности' if cnt_scan[qs].sum() >= 0.5 * n_
                   else f"параметр {foreign['название_файла']}, а сайт на другом движке" if foreign
                   else f"обращения к {f_path[0]} — это адрес {f_path[1]}, а сайт на другом движке" if f_path
                   else 'людей нет, почти все ответы — ошибки, отправляют не известные роботы' if dead
                   else f"обращения к {', '.join(main_secs[:2])}: такого раздела для людей нет — за весь период ни одного успешного ответа людям")
            what = f'зонд: {why}'
        elif entry is not None and not (entry.get('файл') == 'learned/params.json' and _strong(d_grp, entry['группа'], cnt_sys[qs].sum(), n_)):
            from .reference import level
            grp_, what, src = entry['группа'], entry.get('что', ''), entry.get('источник', 'документация')
            if level(entry) >= 3 and src == 'поиск': src = 'поиск, подтверждено'
            link = entry.get('ссылка', '')
            if ref is not None and d_grp not in ('Неизвестные', 'Логика сайта'): ref.observe(k, entry, d_grp)
        else:
            grp_, src = d_grp, 'дедукция'
            what = (d_what + ': ' if d_what else '') + '; '.join(clues)
            if entry is not None and ref is not None and d_grp not in ('Неизвестные', 'Логика сайта'): ref.observe(k, entry, d_grp)
        s_ = SQ[SQ['q'].isin(qs)].groupby('sec')['m'].sum().sort_values(ascending=False)
        f_ = FQ[FQ['q'].isin(qs)].groupby('fam')['m'].sum().sort_values(ascending=False)
        n_m = len(members)
        label = f"{k} — {n_m} {'ключ' if n_m % 10 == 1 and n_m % 100 != 11 else 'ключа' if 2 <= n_m % 10 <= 4 and not 12 <= n_m % 100 <= 14 else 'ключей'}" if n_m > 1 else k
        rows.append(dict(параметр=label, ключ=k, ключи=members[:30], группа=grp_, что=what, источник=src, ссылка=link,
                         запросов=n_, людей=people, значений=int(vc.index.nunique()), частое_значение=top_v[:60] if top_v else '(пусто)',
                         значения=[v_[:60] for v_ in vals], вместе_с=with_, где=', '.join(f'{a}:{int(b)}' for a, b in s_.head(3).items()),
                         роботы=', '.join(f'{a or "без имени"}:{int(b)}' for a, b in f_.head(3).items())))
    D = pd.DataFrame(rows).sort_values('запросов', ascending=False)
    D = D[~((D['группа'] == 'Неизвестные') & (D['ключ'].str.len() < 4) & (D['запросов'] < t_frag))]   # короткие редкие — обрывки
    D.loc[D['ключ'] == '(число без имени)', 'частое_значение'] = ''
    return D.head(top_n)


def _visits(n):
    w = 'визит' if n % 10 == 1 and n % 100 != 11 else 'визита' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'визитов'
    return f'{n:,}'.replace(',', '\u00a0') + ' ' + w


def _strong(b_grp, ref_grp, n_sys, n_):
    """Поведение спорит со справочником настолько, что на листе побеждает поведение (только для записей из поиска)."""
    if b_grp == 'Неизвестные': return False   # поведение ничего не установило — запись из поиска остаётся
    return b_grp != ref_grp and (b_grp != 'Служебные движка' or n_sys >= 0.95 * n_)


# --- Динамические блоки: что браузер подгружает сам или по действию человека ----------------------
def _block_kind(a, admin_paths=(), zone_paths=()):
    if any(a.startswith(p) for p in admin_paths): return 'Админка движка'
    if any(a.startswith(p) for p in zone_paths): return 'Служебный раздел сайта'
    if '/filter/' in a and '/apply/' in a: return 'Подгрузка фильтра каталога'
    if re.search(r'galer|gallery|photo|foto|slider|lightbox', a, re.I): return 'Галерея'
    if re.search(r'form|modal|popup|callback|getprice|consult|feedback', a, re.I): return 'Формы и окна'
    if re.search(r'\.html?$', a): return 'Встроенные страницы (виджеты, туры)'
    if re.search(r'ajax|component', a, re.I): return 'AJAX-блоки'
    return 'Неопознанные'


def embedded_inventory(R, human, emb_templates, admin_paths=(), zone_paths=(), T=None):
    """Блоки внутри страницы — каждый отдельной строкой:
    «авто» — браузер грузит сам сразу после страницы (формы и окна, встроенные страницы…);
    «по действию» — человек вызывает кликом со страницы сайта (галерея, «показать ещё», фильтр), не переход и не отправка формы.
    Перезагрузки списков по фильтру — одной строкой: их сочетания подробно на «Фасетах»."""
    E = pd.DataFrame(emb_templates or [])
    share = dict(zip(E['шаблон'].astype(str), E['доля_сразу_после_страницы'].astype(float))) if len(E) else {}
    tpl = R['tpl'].astype(str).values
    hum = np.asarray(human)
    emb = R['is_embedded'].values if 'is_embedded' in R else np.zeros(len(R), bool)
    goal = R['goal'].astype(str).values if 'goal' in R else np.array([''] * len(R))
    page_tpls = set(pd.unique(tpl[R['is_page'].values & hum]))
    act = hum & R['ref_internal'].values & ~R['is_static'].values & ~emb & (np.isin(goal, ['', 'nan'])) & (~R['is_page'].values | (R['method'].values == 'POST'))
    act &= ~np.isin(tpl, list(share))
    cols = lambda m: pd.DataFrame({'tpl': tpl[m], 'meth': R['method'].astype(str).values[m], 'vid': R['vid'].values[m], 'h': hum[m], 'st': R['status'].values[m], 'b': R['bytes'].values[m],
                                   'day': R['day'].astype(str).values[m], 'ref': R['ref_path'].astype(str).values[m]})
    def row(k, g, load, auto, n_blocks=1):
        return dict(блок=k, вид=('Подгрузка списка (фильтр, «показать ещё»)' if load == 'список' else _block_kind(k, admin_paths, zone_paths)),
                    загрузка='по действию' if load in ('действие', 'список') else 'авто', блоков=n_blocks, запросов=len(g),
                    визитов_людей=int(g.loc[g['h'], 'vid'].nunique()), автозагрузка=auto,
                    охват_страниц=int(g['ref'].replace('', np.nan).nunique()),
                    коды=', '.join(f'{c}:{v}' for c, v in g['st'].value_counts().sort_index().items()),
                    средний_размер_КБ=round(float(g['b'].mean()) / 1024, 1), первый_день=min(g['day']), последний_день=max(g['day']))
    rows = []
    if share:
        A = cols(np.isin(tpl, list(share)))
        for k, g in A.groupby('tpl'): rows.append(row(k, g, 'авто', round(100 * share.get(k, 0), 1)))
    B = cols(act)
    if len(B):
        lst = B['tpl'].map(lambda t: ('/filter/' in t and '/apply/' in t) or t in page_tpls) & (B['meth'] == 'GET')   # POST в обработчик — блок, а не список
        L = B[lst]
        if len(L): rows.append(row('перезагрузка списка без перехода (фильтр, «показать ещё»)', L, 'список', None, int(L['tpl'].nunique())))
        t_min = T('блок_по_действию') if T else 50
        for k, g in B[~lst].groupby('tpl'):
            redir = g['st'].between(300, 399).mean() >= 0.9   # только переадресации — не блок
            if g['vid'].nunique() >= t_min and not redir:
                r_ = row(k, g, 'действие', None)
                if k in page_tpls and (g['meth'] == 'POST').mean() >= 0.5 and (g['ref'] == k).mean() >= 0.5:   # страница отправляет POST сама себе
                    r_['вид'] = 'POST на саму страницу'; r_['блок'] = f'{k} — POST на саму страницу'
                rows.append(r_)
    return pd.DataFrame(rows).sort_values('запросов', ascending=False) if rows else pd.DataFrame()
