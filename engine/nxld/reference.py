"""NXLD: справочники — что известно о движках, сервисах и решениях (data/reference, см. README там же).

Порядок решения для параметра: кто спрашивает → справочник → поведение → имя.
Справочник пополняется сам: незнакомые ключи Детектив ищет в сети и пишет в learned/ (с источником);
записи из learned поднимаются, когда подтверждаются на других сайтах, и опускаются, когда спорят с поведением.
Основные файлы (common, engines, services, solutions) движок не переписывает."""
import datetime as _dt
import glob
import json
import os
import re

REF_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'reference'))
LEARNED = os.path.join(REF_DIR, 'learned', 'params.json')
CHANGELOG = os.path.join(REF_DIR, 'learned', 'CHANGELOG.md')
GROUPS = ('Реклама и аналитика', 'Служебные поисковиков и Яндекса', 'Данные форм', 'Поиск и навигация', 'Служебные движка', 'Метки сервисов', 'Сброс кэша')
# доверие: подписать ключ можно с любого уровня; поднимать важность и заводить карточки — от 3
LEVEL = {'документация': 4, 'сборник': 3, 'наблюдение': 3, 'поиск': 2, 'поведение': 1, 'имя': 0}
STALE_DAYS = 180
CONFIRM_SITES = 2   # столько разных сайтов с тем же поведением — запись из поиска считается подтверждённой


def anon(site):
    """Сайт в справочнике — отпечатком, не адресом: справочник уходит в общий репозиторий, а различать сайты нужно только для подтверждений."""
    import hashlib
    s = str(site or '').lower().strip()
    return s if not s or s.startswith('сайт-') else 'сайт-' + hashlib.sha1(s.encode()).hexdigest()[:8]


def _read(path):
    try:
        with open(path, encoding='utf-8') as f: return json.load(f)
    except Exception:
        return None


def _rx(pattern):
    """Ключ справочника → регулярное выражение: без учёта регистра, * — любое продолжение."""
    return re.compile('^' + re.escape(pattern).replace('\\*', '.*') + '$', re.I)


def level(entry):
    if not entry: return 0
    lv = LEVEL.get(entry.get('источник', 'документация'), 4)
    if entry.get('источник') == 'поиск' and len({c.get('сайт') for c in entry.get('подтверждения', [])}) >= CONFIRM_SITES:
        lv = 3   # подтверждено на нескольких сайтах
    if len(entry.get('конфликты', [])) > len(entry.get('подтверждения', [])) + 1:
        lv = min(lv, 1)   # спорит с поведением чаще, чем подтверждается
    return lv


class Reference:
    def __init__(self, engines=(), paths=(), site=''):
        """engines — названия движков, найденных на сайте; paths — адреса из лога (для признаков решений)."""
        self.site, self.files, self.entries = anon(site), [], []   # entries: (приоритет, regex, запись, файл)
        names = {str(e).lower() for e in engines}
        sample = list(paths)[:200000]
        for path in sorted(glob.glob(os.path.join(REF_DIR, '**', '*.json'), recursive=True)):
            base = os.path.basename(path)
            if base.startswith('_') or os.sep + 'learned' + os.sep in path: continue
            d = _read(path)
            if not d: continue
            kind = d.get('вид', '')
            if kind == 'движок' and not ({d.get('название', '').lower(), d.get('id', '').lower()} & names): continue
            if kind == 'решение':
                sig = [re.compile(s, re.I) for s in d.get('признаки', [])]
                if not sig or not any(s.search(p) for s in sig for p in sample[:50000]): continue
            prio = {'решение': 0, 'движок': 1, 'сервис': 2, 'общий': 3}.get(kind, 3)
            self.files.append(dict(файл=os.path.relpath(path, REF_DIR), вид=kind, название=d.get('название', ''), data=d))
            for e in d.get('параметры', []):
                self.entries.append((prio, _rx(e['ключ']), dict(e, файл=os.path.relpath(path, REF_DIR), название_файла=d.get('название', ''))))
        self.learned = _read(LEARNED) or {'параметры': []}
        for e in self.learned['параметры']:
            self.entries.append((4, _rx(e['ключ']), dict(e, файл='learned/params.json', название_файла='найдено поиском')))
        self.log = []

    # ---------------- справочник: папки движка ----------------
    def folders(self, roles=None):
        """{путь: что} — папки и закрытые зоны найденных движков и решений; roles — только эти роли."""
        out = {}
        for f in self.files:
            if f['вид'] in ('движок', 'решение'):
                for x in f['data'].get('папки', []) + f['data'].get('зоны', []):
                    if roles is None or x.get('роль') in roles: out[x['путь']] = x['что']
        return out

    # ---------------- поиск ключа ----------------
    def match(self, key):
        """Лучшая запись для ключа: точное совпадение раньше шаблона, курированные файлы раньше learned, выше доверие — раньше."""
        hits = []
        for prio, rx, e in self.entries:
            if rx.match(key):
                exact = '*' not in e['ключ']
                hits.append((0 if exact else 1, prio if level(e) >= 2 or prio < 4 else 9, -level(e), -len(e['ключ']), e))
        if not hits: return None
        hits.sort(key=lambda h: h[:4])
        return hits[0][4]

    def family(self, key):
        """Шаблон семейства из справочника (PAGEN_*), если ключ подходит под шаблон."""
        e = self.match(key)
        return e['ключ'] if e and '*' in e['ключ'] else None

    # ---------------- самообучение ----------------
    def _today(self):
        return _dt.date.today().isoformat()

    def _find_learned(self, key):
        for e in self.learned['параметры']:
            if e['ключ'].lower() == str(key).lower(): return e
        return None

    def learn(self, items, site=None):
        """Записи, которые Детектив нашёл поиском: [{ключ, группа, что, ссылка, источник?}]. Без ссылки не сохраняются.
        Возвращает принятые записи (для отчёта)."""
        site = anon(site) if site else self.site
        ok = []
        for it in items or []:
            k, g, url = str(it.get('ключ', '')).strip(), it.get('группа'), str(it.get('ссылка', '')).strip()
            if not k or g not in GROUPS or not re.match(r'https?://', url):
                self.log.append(f"- отклонено: `{k}` — {'нет ссылки на источник' if not re.match(r'https?://', url) else 'неизвестная группа ' + str(g)}"); continue
            cur = self._find_learned(k)
            if cur and cur['группа'] == g and (cur.get('сайт') == site or any(c.get('сайт') == site for c in cur.get('подтверждения', []))):
                ok.append(dict(it, источник='поиск')); continue   # тот же сайт — повторная сборка, не подтверждение
            if cur and cur['группа'] == g:
                cur.setdefault('подтверждения', []).append(dict(сайт=site, дата=self._today(), как='поиск'))
                cur['проверено'] = self._today()
                if url not in cur.get('ссылки', [cur.get('ссылка')]): cur.setdefault('ссылки', [cur.get('ссылка')]).append(url)
                self.log.append(f"- подтверждено поиском: `{k}` — {g} ({site})")
            elif cur:
                cur.setdefault('конфликты', []).append(dict(сайт=site, дата=self._today(), группа=g, ссылка=url))
                if level(cur) <= 1:   # старая запись проиграла — заменяем
                    cur.update(группа=g, что=it.get('что', ''), ссылка=url, проверено=self._today(), подтверждения=[], конфликты=[])
                    self.log.append(f"- заменено: `{k}` → {g} ({url})")
                else:
                    self.log.append(f"- спор: `{k}` — было {cur['группа']}, поиск говорит {g} ({site})")
            else:
                e = dict(ключ=k, группа=g, что=str(it.get('что', ''))[:200], источник='поиск', ссылка=url, проверено=self._today(),
                         сайт=site, подтверждения=[], конфликты=[])
                if it.get('движок'): e['движок'] = it['движок']
                self.learned['параметры'].append(e)
                self.entries.append((4, _rx(k), dict(e, файл='learned/params.json', название_файла='найдено поиском')))
                self.log.append(f"- добавлено: `{k}` — {g}: {e['что']} ({url})")
            ok.append(dict(it, источник='поиск'))
        return ok

    def observe(self, key, entry, behavior_group, site=None):
        """Сверка записи из learned с поведением ключа на этом сайте: совпало — подтверждение, спорит — конфликт."""
        if not entry or entry.get('файл') != 'learned/params.json' or not behavior_group: return
        cur = self._find_learned(entry['ключ'])
        if not cur: return
        site = anon(site) if site else self.site
        if any(c.get('сайт') == site for c in cur.get('подтверждения', []) + cur.get('конфликты', [])): return
        if behavior_group == cur['группа']:
            cur.setdefault('подтверждения', []).append(dict(сайт=site, дата=self._today(), как='поведение'))
            self.log.append(f"- подтверждено поведением: `{cur['ключ']}` — {cur['группа']} ({site})")
        else:
            cur.setdefault('конфликты', []).append(dict(сайт=site, дата=self._today(), группа=behavior_group))
            self.log.append(f"- конфликт с поведением: `{cur['ключ']}` — справочник {cur['группа']}, на сайте {behavior_group} ({site})")

    def stale(self, entry):
        """Запись из поиска, которую пора перепроверить."""
        if not entry or entry.get('источник') != 'поиск': return False
        try: return (_dt.date.today() - _dt.date.fromisoformat(entry.get('проверено', '2000-01-01'))).days > STALE_DAYS
        except Exception: return True

    def save(self):
        if not self.log: return
        os.makedirs(os.path.dirname(LEARNED), exist_ok=True)
        with open(LEARNED, 'w', encoding='utf-8') as f:
            json.dump(self.learned, f, ensure_ascii=False, indent=2); f.write('\n')
        new = not os.path.exists(CHANGELOG)
        with open(CHANGELOG, 'a', encoding='utf-8') as f:
            if new: f.write('# Журнал самообучения справочника\n\nЧто ИИ добавил, подтвердил или оспорил. Ошибочную запись можно удалить из params.json — история останется здесь.\n')
            f.write(f"\n## {self._today()} — {self.site}\n" + '\n'.join(self.log) + '\n')
        self.log = []


def all_engine_names():
    return [(_read(p) or {}).get('название', '') for p in glob.glob(os.path.join(REF_DIR, 'engines', '*.json'))]


def load(site_map, paths=(), site=''):
    engines = [e.get('движок') for e in (site_map or {}).get('engines') or [] if isinstance(e, dict)]
    return Reference(engines, paths, site)
