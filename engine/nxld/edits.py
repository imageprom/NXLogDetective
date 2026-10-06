"""NXLD: правки Детектива после расследования (edits.json) — до тревог и оформления.

Оформление их не применяет: report.build вызывает apply, потом alarms и derive."""


def apply(res, edits):
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
    if edits.get('справочник'):   # Детектив нашёл поиском незнакомые параметры — в справочник (learned) и сразу на лист
        from . import reference
        from .anatomy import param_groups
        site_ = (res.get('site_map', {}).get('site_hosts') or ['site'])[0]
        ref = reference.Reference((), (), site_)
        ok = {str(x['ключ']).lower(): x for x in ref.learn(edits['справочник'], site_)}
        ref.save()
        for r_ in res.get('params') or []:
            x = ok.get(str(r_['ключ']).lower()) or next((ok[m_.lower()] for m_ in r_.get('ключи', []) if m_.lower() in ok), None)
            if x and r_.get('группа') != 'Атаки и зонды':
                r_.update(группа=x['группа'], что=x.get('что', ''), источник='поиск', ссылка=x.get('ссылка', ''))
        if (res.get('anatomy') or {}).get('параметры') is not None: res['anatomy']['параметры'] = param_groups(res.get('site_map', {}), res)
    if edits.get('расширения'):   # Детектив нашёл, что за незнакомые файлы, — в справочник (learned/extensions.json) и сразу на лист «Файлы»
        from . import classify
        site_ = (res.get('site_map', {}).get('site_hosts') or ['site'])[0]
        ok = {str(x.get('расширение', '')).lower().lstrip('.'): x['группа'] for x in edits['расширения'] if x.get('группа')}
        classify.learn_extensions(edits['расширения'], site_)
        for r_ in res.get('files') or []:
            e_ = classify.ext_of(r_.get('адрес', ''))
            if r_.get('группа') == 'Неизвестный вид' and e_ in ok: r_['группа'] = ok[e_]
        res['unknown_extensions'] = [u for u in res.get('unknown_extensions') or [] if u['расширение'] not in ok]
    if edits.get('мониторинги'):   # Детектив нашёл, чей это мониторинг, — в справочник (learned/monitors.json)
        from . import visits
        visits.learn_monitors(edits['мониторинги'], (res.get('site_map', {}).get('site_hosts') or ['site'])[0])
    X_ = res.get('security') or {}
    if edits.get('проверка_утечек') and X_.get('утечки') is not None and len(X_['утечки']):   # скил открыл утёкшие файлы из сети (SKILL.md)
        L_ = X_['утечки']
        for f_, ch in edits['проверка_утечек'].items():
            m_ = L_['файл'] == f_
            if m_.any():
                L_.loc[m_, 'проверка'] = ch.get('итог', 'проверено'); L_.loc[m_, 'проверено'] = ch.get('когда', '')
                L_.loc[m_, 'внутри'] = ch.get('внутри', ''); L_.loc[m_, 'тревога'] = bool(ch.get('тревога'))
    if edits.get('проверка_утечек'):   # итог проверки — в карточку: что открыто, что закрыто, есть ли внутри существенное
        txt = '; '.join(f"{f_} — {ch.get('итог', 'проверено')}" + (f" ({ch['внутри']})" if ch.get('внутри') else '') for f_, ch in edits['проверка_утечек'].items())
        when = next((ch.get('когда') for ch in edits['проверка_утечек'].values() if ch.get('когда')), '')
        for x in res['findings']:
            if x['key'].split(':')[1:2] == ['exposed'] and 'Проверено из сети' not in str(x.get('факты', '')):
                x['факты'] = (str(x.get('факты', '')).rstrip('. ') + f". Проверено из сети{' ' + when if when else ''}: {txt}.").lstrip('. ')
    if edits.get('проверка_сайта'):   # скил открыл robots.txt, карту сайта и т. п. (SKILL.md): итог — на лист «Файлы для роботов» и в карточки
        Fr = (res.get('seo') or {}).get('файлы')
        for f_, ch in edits['проверка_сайта'].items():
            t_ = f"{ch.get('итог', '')}" + (f", {ch['когда']}" if ch.get('когда') else '') + (f": {ch['что']}" if ch.get('что') else '')
            if Fr is not None and len(Fr):
                if 'проверка' not in Fr: Fr['проверка'] = ''
                if (Fr['файл'] == f_).any(): Fr.loc[Fr['файл'] == f_, 'проверка'] = t_
            for x in res['findings']:
                if x['key'].endswith(':' + f_) and 'Проверено из сети' not in str(x.get('факты', '')):
                    x['факты'] = str(x.get('факты', '')).rstrip('. ') + f'. Проверено из сети: {t_}.'
    if edits.get('встраивание') and X_.get('встраивание') is not None and len(X_['встраивание']):   # скил сверил IP сайтов с нашим сервером
        Em_ = X_['встраивание']
        for h_, why in edits['встраивание'].items(): Em_.loc[Em_['сайт'] == h_, 'вывод'] = why
    if edits.get('проверка_сайта'):   # скил открыл адреса сайта из сети: robots.txt, карта сайта, главная (SKILL.md, раздел 4)
        res['проверка_сайта'] = dict(edits['проверка_сайта'])
    if edits.get('site_profile'):   # Детектив поправил «Что за сайт»
        res['site_profile'] = dict(res.get('site_profile') or {}, **edits['site_profile'])
    return res


apply_edits = apply
