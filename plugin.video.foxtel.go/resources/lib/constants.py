import hashlib
import requests as _requests
from collections import OrderedDict

FOXTEL_BRAND = 'foxtelgnc'
APP_VERSION  = '7.0.2'

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
DAZN_SIGNIN_URL  = 'https://authentication-prod.ar.indazn.com/v5/SignIn'
DAZN_REFRESH_URL = 'https://ott-authz-bff-prod.ar.indazn.com/v5/RefreshAccessToken'

# Foxtel OTP auth (for accounts that only support email+OTP, not password)
FOXTEL_OTP_URL      = 'https://ott-authz-bff-prod.ar.indazn.com/foxtelgnc/v1/auth/email-otp'
FOXTEL_OTP_VALIDATE = 'https://ott-authz-bff-prod.ar.indazn.com/foxtelgnc/v1/auth/validate-otp'

# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------
DAZN_RAIL_URL   = 'https://ruleset-router-foxtelgnc.discovery.indazn.com/jp/v1/Rail'
DAZN_RAILS_URL  = 'https://rails.discovery.indazn.com/jp/v9/rails'
DAZN_EPG_URL    = 'https://epg.discovery.indazn.com/jp/v6/Epg'
DAZN_EVENT_URL  = 'https://event.discovery.indazn.com/jp/v8/Event'
DAZN_SEARCH_URL = 'https://search.discovery.indazn.com/v4/search'
DAZN_IMG_URL    = 'https://image.discovery.indazn.com/jp/v3/jp'

# Channel/EPG data from mjh.nz (no auth needed)
LIVE_DATA_URL = 'https://i.mjh.nz/Foxtel/app.json'
EPG_URL       = 'http://aussietv.xyz/Foxtel/epg.xml'

# ---------------------------------------------------------------------------
# Relay
# ---------------------------------------------------------------------------
_RELAY_LAN_IPS = ['192.168.4.42', '192.168.4.46', '192.168.4.27']
_RELAY_PORT    = 5004
_VPS_RELAY_URL = 'http://103.106.231.181:5006'

_relay_url_auto = None

def get_relay_url():
    global _relay_url_auto
    try:
        from slyguy import settings as _s
        url = _s.get('relay_url', '').strip().rstrip('/')
        if url:
            return url
    except Exception:
        pass
    if _relay_url_auto is None:
        for _ip in _RELAY_LAN_IPS:
            _url = 'http://{}:{}'.format(_ip, _RELAY_PORT)
            try:
                _requests.get(_url + '/health', timeout=0.8)
                _relay_url_auto = _url
                break
            except Exception:
                pass
        else:
            _relay_url_auto = _VPS_RELAY_URL
    return _relay_url_auto

# ---------------------------------------------------------------------------
# Device / nickname
# ---------------------------------------------------------------------------
DEFAULT_NICKNAME  = 'Kodi'
DEFAULT_DEVICE_ID = '006360b93a'

def get_device_id():
    """Derive a 10-char hex device ID from the user's nickname setting.
    Two Kodi installs using the same nickname will produce the same device ID,
    causing Foxtel/DAZN to treat them as one device and share a device slot."""
    try:
        from slyguy import settings as _s
        nickname = _s.get('device_nickname', '').strip()
    except Exception:
        nickname = ''
    if not nickname:
        return DEFAULT_DEVICE_ID
    return hashlib.md5(('foxtelkodi-' + nickname.lower()).encode('utf-8')).hexdigest()[:10]

# ---------------------------------------------------------------------------
# User-agents
# ---------------------------------------------------------------------------
UA_ANDROID = 'au.com.foxtel.Go/{} (Linux;Android 12) ExoPlayerLib/2.18.2'.format(APP_VERSION)
UA_WEB     = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
               'AppleWebKit/537.36 (KHTML, like Gecko) '
               'Chrome/124.0.0.0 Safari/537.36')

# Base headers for all direct DAZN API calls
HEADERS = OrderedDict([
    ('user-agent',    UA_WEB),
    ('accept',        'application/json'),
    ('content-type',  'application/json'),
    ('origin',        'https://watch.foxtel.com.au'),
    ('referer',       'https://watch.foxtel.com.au/'),
])

# ---------------------------------------------------------------------------
# EPG helper
# ---------------------------------------------------------------------------
EPG_EVENTS_COUNT = 6

# ---------------------------------------------------------------------------
# Channel display names (from mjh.nz epg.xml.gz display-name elements)
# Maps 3-letter channel code → human-readable channel name
# ---------------------------------------------------------------------------
CHANNEL_NAMES = {
    'F1S': 'Foxtel One',
    'UKT': 'UKTV',
    'LST': 'LifeStyle',
    'FOX': 'FOX8',
    'ARN': 'Arena',
    'SHC': 'Showcase',
    'IOI': 'Crime',
    'HIT': 'Comedy',
    'FKC': 'Classics',
    'FSU': 'British',
    'DPS': 'DocPlay',
    'HAL': 'Universal TV',
    'DTA': 'TLC',
    'FOD': 'LifeStyle Food',
    'LHO': 'LifeStyle Home',
    'RTV': 'RACING.COM',
    'HAR': 'Seinfeld',
    'HST': 'Real History',
    'DIS': 'Discovery Channel',
    'NAT': 'Nature Time',
    'CIN': 'Real Crime',
    'DID': 'Investigation Discovery',
    'ANI': 'Animal Planet',
    'DIT': 'Discovery Turbo',
    'BXS': 'CSI',
    'FHT': 'FashionTV',
    'AUR': 'Aurora',
    'TVS': 'TVSN',
    'ACC': 'GOOD.',
    'SHO': 'Movies Premiere',
    'SHF': 'Movies Family',
    'SHA': 'Movies Action',
    'SHY': 'Movies Comedy',
    'SHD': 'Movies Romance',
    'MO6': 'Movies Drama',
    'GRR': 'Movies Greats',
    'FSN': 'FOX SPORTS NEWS',
    'RLS': 'Real Life',
    'NMU': 'Kids',
    'FS3': 'Fox Sports 503',
    'FSP': 'Fox Sports 505',
    'SPS': 'Fox Sports 506',
    'FSS': 'Fox Sports 507',
    'ESP': 'ESPN',
    'ES2': 'ESPN2',
    'SRA': 'Sky Racing 1',
    'SR2': 'Sky Racing 2',
    'SRW': 'Sky Racing Thoroughbred Central',
    'SKY': 'News24',
    'FXW': 'News24 Weather',
    'ASP': 'News24 World',
    'SUK': 'SKY NEWS UK',
    'FNC': 'FOX News',
    'CNN': 'CNN International',
    'MSN': 'MS NOW',
    'NNN': 'NBC News NOW',
    'CNB': 'CNBC',
    'BBC': 'BBC News',
    'BLM': 'Bloomberg Television',
    'AJE': 'Al Jazeera',
    'CCC': 'CGTN',
    'NHK': 'NHK World',
    'GBN': 'GB News',
    'TMF': 'Trending',
    'DRM': 'DreamWorks',
    'VH1': 'Club',
    'MTC': 'Retro',
    'CMT': 'CMC',
    'NRW': 'Max',
    'NAP': 'Australian Played',
    'FS1': 'FOX CRICKET',
    'SP2': 'FOX League',
    'FAF': 'FOX Footy',
    'BCS': 'British Cinema',
    'ACS': 'Aussie Classics',
    'PUH': 'PULP',
    'UP2': 'Pop Up Channel 1',
    'MVS': 'Movie Hits',
    'TRS': 'Pop Up Channel 2',
    'TDR': 'Outdoor Channel',
}

CHANNEL_GROUPS = {
    # Sports
    'FS1': 'Foxtel Sports', 'SP2': 'Foxtel Sports', 'FAF': 'Foxtel Sports',
    'FS3': 'Foxtel Sports', 'FSP': 'Foxtel Sports', 'SPS': 'Foxtel Sports',
    'FSS': 'Foxtel Sports', 'ESP': 'Foxtel Sports', 'ES2': 'Foxtel Sports',
    'FSN': 'Foxtel Sports', 'RTV': 'Foxtel Sports',
    'SRA': 'Foxtel Sports', 'SR2': 'Foxtel Sports', 'SRW': 'Foxtel Sports',
    'K01': 'Foxtel UHD',   'K02': 'Foxtel UHD',   'K03': 'Foxtel UHD',
    'K04': 'Foxtel UHD',   'K05': 'Foxtel UHD',   'K06': 'Foxtel UHD',
    # Movies
    'SHO': 'Foxtel Movies', 'SHF': 'Foxtel Movies', 'SHA': 'Foxtel Movies',
    'SHY': 'Foxtel Movies', 'SHD': 'Foxtel Movies', 'MO6': 'Foxtel Movies',
    'GRR': 'Foxtel Movies', 'BCS': 'Foxtel Movies', 'ACS': 'Foxtel Movies',
    'MVS': 'Foxtel Movies',
    # Entertainment
    'F1S': 'Foxtel Entertainment', 'UKT': 'Foxtel Entertainment',
    'FOX': 'Foxtel Entertainment', 'ARN': 'Foxtel Entertainment',
    'SHC': 'Foxtel Entertainment', 'IOI': 'Foxtel Entertainment',
    'HIT': 'Foxtel Entertainment', 'FKC': 'Foxtel Entertainment',
    'FSU': 'Foxtel Entertainment', 'HAL': 'Foxtel Entertainment',
    'HAR': 'Foxtel Entertainment', 'BXS': 'Foxtel Entertainment',
    'PUH': 'Foxtel Entertainment', 'RLS': 'Foxtel Entertainment',
    'UP2': 'Foxtel Entertainment', 'TRS': 'Foxtel Entertainment',
    # Lifestyle
    'LST': 'Foxtel Lifestyle', 'DTA': 'Foxtel Lifestyle',
    'FOD': 'Foxtel Lifestyle', 'LHO': 'Foxtel Lifestyle',
    'ACC': 'Foxtel Lifestyle', 'FHT': 'Foxtel Lifestyle',
    'TVS': 'Foxtel Lifestyle', 'AUR': 'Foxtel Lifestyle',
    # Documentary
    'DPS': 'Foxtel Documentary', 'HST': 'Foxtel Documentary',
    'DIS': 'Foxtel Documentary', 'NAT': 'Foxtel Documentary',
    'CIN': 'Foxtel Documentary', 'DID': 'Foxtel Documentary',
    'ANI': 'Foxtel Documentary', 'DIT': 'Foxtel Documentary',
    'TDR': 'Foxtel Documentary',
    # News
    'SKY': 'Foxtel News', 'FXW': 'Foxtel News', 'ASP': 'Foxtel News',
    'SUK': 'Foxtel News', 'FNC': 'Foxtel News', 'CNN': 'Foxtel News',
    'MSN': 'Foxtel News', 'NNN': 'Foxtel News', 'CNB': 'Foxtel News',
    'BBC': 'Foxtel News', 'BLM': 'Foxtel News', 'AJE': 'Foxtel News',
    'CCC': 'Foxtel News', 'NHK': 'Foxtel News', 'GBN': 'Foxtel News',
    # Kids
    'NMU': 'Foxtel Kids', 'DRM': 'Foxtel Kids',
    # Music
    'TMF': 'Foxtel Music', 'VH1': 'Foxtel Music', 'MTC': 'Foxtel Music',
    'CMT': 'Foxtel Music', 'NRW': 'Foxtel Music', 'NAP': 'Foxtel Music',
}

def channel_logo(code):
    """Return the official Foxtel CDN logo URL for a channel code, or '' if none."""
    _NO_LOGO = {'K01', 'K02', 'K03', 'K04', 'K05', 'K06'}
    if code in _NO_LOGO:
        return ''
    return 'https://www.foxtel.com.au/content/dam/foxtel/shared/channel/{c}/{c}_425x243.png'.format(c=code)

# Extra channels not present in mjh.nz data (e.g. UHD channels).
# These are appended to the channel listing returned by api.channel_data().
# asset_id / event_id come from /foxtel/discover on the relay.
EXTRA_CHANNELS = {
    'K01': {'name': 'Fox Sports UHD 1', 'chno': 580, 'logo': '', 'epg': []},
    'K02': {'name': 'Movies 4k UHD',    'chno': 420, 'logo': '', 'epg': []},
    'K03': {'name': 'Fox Sports UHD 2', 'chno': 581, 'logo': '', 'epg': []},
    'K04': {'name': 'Fox Sports UHD 3', 'chno': 582, 'logo': '', 'epg': []},
    'K05': {'name': 'Fox Sports UHD 4', 'chno': 583, 'logo': '', 'epg': []},
    'K06': {'name': 'Fox Sports UHD 5', 'chno': 584, 'logo': '', 'epg': []},
    'TDR': {'name': 'Outdoor Channel',  'chno': 199, 'logo': '', 'epg': []},
}
