"""NXLD: IP -> сеть (ASN, владелец), страна, тип сети. Без интернета, база в папке data."""
import os, re
import numpy as np, pandas as pd

DATA = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
_db = {}


def _load():
    if _db: return _db
    a = pd.read_csv(os.path.join(DATA, 'asn-ipv4-num.csv.gz'), header=None, names=['s', 'e', 'asn', 'org'], dtype={'org': str})
    c = pd.read_csv(os.path.join(DATA, 'country-ipv4-num.csv.gz'), header=None, names=['s', 'e', 'cc'])
    _db['a'] = (a.s.values.astype(np.int64), a.e.values.astype(np.int64), a.asn.values, a.org.fillna('').values)
    _db['c'] = (c.s.values.astype(np.int64), c.e.values.astype(np.int64), c.cc.values)
    return _db


def ip2int(ips):
    s = pd.Series(ips, dtype=str)
    p = s.str.split('.', expand=True)
    ok = (p.shape[1] == 4) & s.str.fullmatch(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
    out = np.full(len(s), -1, dtype=np.int64)
    if p.shape[1] == 4:
        v = p[ok].astype(np.int64).values
        out[ok.values] = v[:, 0] * 16777216 + v[:, 1] * 65536 + v[:, 2] * 256 + v[:, 3]
    return out


def lookup(ips):
    """DataFrame: ip, asn, org, cc, prefix_start, prefix_end, nettype."""
    db = _load()
    x = ip2int(ips)
    s, e, asn, org = db['a']
    i = np.searchsorted(s, x, side='right') - 1
    ok = (i >= 0) & (x >= 0) & (x <= e[np.clip(i, 0, None)])
    ii = np.clip(i, 0, None)
    cs, ce, cc = db['c']
    j = np.searchsorted(cs, x, side='right') - 1
    okc = (j >= 0) & (x >= 0) & (x <= ce[np.clip(j, 0, None)])
    df = pd.DataFrame({'ip': list(ips),
                       'asn': np.where(ok, asn[ii], 0).astype(np.int64),
                       'org': np.where(ok, org[ii], ''),
                       'cc': np.where(okc, cc[np.clip(j, 0, None)], ''),
                       'net_first': np.where(ok, s[ii], -1), 'net_last': np.where(ok, e[ii], -1)})
    df['nettype'] = [nettype(a_, o_, c_) for a_, o_, c_ in zip(df.asn, df.org, df.cc)]
    return df


HOST = re.compile(r'host|cloud|server|data ?cent|datacamp|ovh|digitalocean|amazon|microsoft|alibaba|tencent|timeweb|selectel|contabo|hetzner|leaseweb|m247|constant company|linode|akamai|fdcservers|delska|clouvider|limestone|purevoltage|3xk|techoff|unmanaged|aeza|beget|reg\.ru|firstbyte|vdsina|serverius|vultr|oracle|ionos|scaleway|netcup|kamatera|zenlayer|psychz|quadranet|colocrossing|choopa|g-core|gcore|stark industries|pq hosting|ishosting|justhost|sprinthost|mchost|masterhost|ruvds|smart ape|web2objects|hostkey|servers|vps|dedicated|colo|webzilla|ucloud|huawei|baidu|worldstream|nforce|hivelocity|equinix|xhost|cdn77|datapacket|melbicom|yandex\.cloud|cloud llc', re.I)
SEARCH_ASN = {13238: 'Яндекс', 15169: 'Google', 396982: 'Google Cloud', 8075: 'Microsoft', 714: 'Apple'}
RELAY_ASN = {13335: 'Cloudflare (WARP/прокси)', 714: 'Apple Private Relay'}
MOBILE_ASN = {8359, 3216, 16345, 31133, 25159, 12958, 20771, 29648, 31163, 31195, 31205, 31208, 31213, 31224, 35298, 12714, 15378, 25513, 48092, 2118, 12389}
BANK = re.compile(r'sber|tbank|tinkoff|vtb|alfa-bank|gazprombank|raiffeisen', re.I)
CDN_ASN = {13335: 'Cloudflare', 49612: 'DDoS-Guard', 57724: 'DDoS-Guard', 200449: 'Qrator', 197068: 'Qrator', 44094: 'StormWall', 59796: 'StormWall', 202001: 'ServicePipe', 20940: 'Akamai', 54113: 'Fastly'}


def nettype(asn, org, cc):
    if not asn: return 'неизвестно'
    if asn in RELAY_ASN: return 'VPN/прокси-релей'
    if asn in MOBILE_ASN: return 'мобильный оператор'
    if BANK.search(org or ''): return 'банк/корпорация'
    if asn == 13238: return 'Яндекс'
    if asn in (15169, 396982, 8075, 16509, 14618) or HOST.search(org or ''): return 'хостинг/облако'
    if cc == 'RU': return 'RU провайдер доступа'
    return 'зарубежный провайдер доступа'


# какие сети разрешены объявленным роботам (подлинность)
VERIFIED = {
    'YandexBot': {13238}, 'YandexRenderResourcesBot': {13238}, 'YandexImages': {13238}, 'YandexMetrika': {13238},
    'YaDirectFetcher': {13238}, 'YandexMarket': {13238}, 'Yandex: прочие роботы': {13238}, 'YandexAdditional (Нейро)': {13238},
    # Google Cloud (396982) — облако для всех клиентов: настоящие Googlebot и роботы OpenAI оттуда не ходят, а подделки — ходят
    'Googlebot': {15169}, 'Googlebot-Image': {15169}, 'AdsBot-Google': {15169},
    'Google: прочие роботы': {15169, 396982}, 'Bingbot': {8075}, 'Applebot': {714, 6185},
    'GPTBot (OpenAI)': {8075}, 'OAI-SearchBot (OpenAI)': {8075}, 'ChatGPT-User (OpenAI)': {8075},   # OpenAI публикует сети в Microsoft Azure
    'TelegramBot': {62041, 59930, 44907, 211157},   # сети Telegram Messenger
}
