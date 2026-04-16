import random
from hashlib import md5
from collections import OrderedDict

SSL_CIPHERS = 'AES128-GCM-SHA256:AES256-GCM-SHA384:CHACHA20-POLY1305-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:AES256-GCM-SHA384:AES128-SHA:AES256-SHA'
SSL_CIPHERS = SSL_CIPHERS.split(':')
random.shuffle(SSL_CIPHERS)
SSL_CIPHERS = ':'.join(SSL_CIPHERS)
SSL_OPTIONS = 0
APP_VERSION = '2.1.2'
USER_AGENT = 'platform/{}/{}'.format(APP_VERSION, md5('agent/apps/android/kayo'.encode()).hexdigest())

HEADERS = OrderedDict([
    ('accept-language', 'en_US'),
  #  ('auth0-client', 'eyJuYW1lIjoiQXV0aDAuQW5kcm9pZCIsImVudiI6eyJhbmRyb2lkIjoiMzAifSwidmVyc2lvbiI6IjIuNy4wIn0='),
    ('user-agent', USER_AGENT),
    # ('traceparent', '......'),
    # ('newrelic', '....'),
    # ('tracestate', '....'),
    # ('content-type', 'application/json; charset=utf-8'),
    # ('content-length', ''),
    # ('accept-encoding', 'gzip'),
    # ('x-newrelic-id', '.....'),
])

LIVE_SITEID = '206'
VOD_SITEID  = '296'

DEFAULT_NICKNAME = 'Kodi-{mac_address} on {system}'
DEFAULT_DEVICEID = '{username}{mac_address}'

BASE_URL = 'https://foxtel-go-sw.foxtelplayer.foxtel.com.au/go-mobile-570'
API_URL = BASE_URL + '/api{}'
BUNDLE_URL = BASE_URL + '/bundleAPI/getHomeBundle.php'
IMG_URL = BASE_URL + '/imageHelper.php?id={id}:png&w={width}{fragment}'

SEARCH_URL = 'https://foxtel-prod-elb.digitalsmiths.net/sd/foxtel/taps/assets/search/prefix'
PLAY_URL = 'https://foxtel-go-sw.foxtelplayer.foxtel.com.au/now-box-140/api/playback.class.api.php/{endpoint}/{site_id}/1/{id}'
LIVE_DATA_URL = 'https://i.mjh.nz/Foxtel/app.json'  # fallback only — see foxtel_epg_server.py
EPG_URL = 'https://aussietv.xyz/Foxtel/epg.xml'

AES_IV = 'b2d40461b54d81c8c6df546051370328'
PLT_DEVICE = 'andr_phone'
EPG_EVENTS_COUNT = 6

TYPE_LIVE  = '1'
TYPE_VOD   = '2'

ASSET_MOVIE  = '1'
ASSET_TVSHOW = '4'
ASSET_BOTH   = ''

# Maps Foxtel API channelCode (3-letter shortcode) → iptv-org xmltv_id
# Used so the M3U tvg-id matches the channel IDs in the iptv-org/epg XMLTV output.
# Channels with no xmltv_id in iptv-org will fall back to their channelCode.
# Source: https://github.com/iptv-org/epg/blob/master/sites/foxtel.com.au/foxtel.com.au.channels.xml
EPG_ID_MAP = {
    'AJE': 'AlJazeera.qa@Arabic',
    'ANI': 'AnimalPlanet.au@SD',
    'ANT': 'ANT1Pacific.gr@SD',
    'ARN': 'Arena.au@SD',
    'AUR': 'AuroraTV.au@SD',
    'BXS': 'BoxSets.au@SD',
    'CL2': 'Classics.au@Plus2',
    'FKC': 'Classics.au@SD',
    'VH1': 'ClubMTV.au@SD',
    'CMT': 'CMT.au@SD',
    'CNB': 'CNBCAustralia.au@SD',
    'CNN': 'CNNInternational.us@AsiaPacific',
    'HI2': 'Comedy.au@Plus2',
    'HIT': 'Comedy.au@SD',
    'IO2': 'FoxCrime.au@Plus2',
    'IOI': 'Crime.au@SD',
    'DS2': 'DiscoveryChannel.au@Plus2',
    'DIS': 'DiscoveryChannel.au@SD',
    'DIT': 'DiscoveryTurbo.au@Australia',
    'DRM': 'DreamWorksChannel.au@SD',
    'ES2': 'ESPN2.au@SD',
    'ESP': 'ESPN.au@SD',
    'EXP': 'ExpoChannel.au@SD',
    'FOX': 'Fox8.au@SD',
    'FO2': 'Fox8.au@Plus2',
    'FS1': 'FoxCricket.au@SD',
    'FAF': 'FoxFooty.au@SD',
    'SP2': 'FoxLeague.au@SD',
    'FNC': 'FoxNewsChannel.us@SD',
    'FS3': 'FoxSports503.au@SD',
    'FSP': 'FoxSports505.au@SD',
    'SPS': 'FoxSports506.au@SD',
    'FSN': 'FoxSportsNews.au@SD',
    'F1S': 'FoxtelOne.au@SD',
    'ACC': 'GOOD.au@SD',
    'DID': 'InvestigationDiscovery.au@SD',
    'LS2': 'LifeStyle.au@Plus2',
    'LF2': 'LifestyleFood.au@Plus2',
    'FOD': 'LifestyleFood.au@SD',
    'LHO': 'LifestyleHome.au@SD',
    'LST': 'LifeStyle.au@SD',
    'LMS': 'LMN.au@SD',
    'TMF': 'MTVHits.au@SD',
    'NHK': 'NHKWorldJapan.jp@SD',
    'NMU': 'NickMusic.au@SD',
    'RAI': 'RaiItalia.it@Australia',
    'RL2': 'RealLife.au@Plus2',
    'RLS': 'RealLife.au@SD',
    'SBN': 'SBSViceland.au@Sydney',
    'S4B': 'SBSWorldMovies.au@Sydney',
    'SWW': 'SBSWorldWatch.au@Sydney',
    'SW2': 'Showcase.au@Plus2',
    'SHC': 'Showcase.au@SD',
    'ASP': 'SkyNewsExtra.au@SD',
    'SR2': 'SkyRacing2.au@SD',
    'DT2': 'TLC.au@Plus2',
    'DTA': 'TLC.au@SD',
    'TVS': 'TVSN.au@SD',
    'UKT': 'BBCUKTV.au@Australia',
    'HAL': 'UniversalTV.au@SD',
}

STREAM_PRIORITY = {
    'WIREDHD'  : 16,
    'WIREDHIGH': 15,
    'WIFIHD'   : 14,
    'WIFIHIGH' : 13,
    'FULL'     : 12,
    'WIFILOW'  : 11,
    '3GHIGH'   : 10,
    '3GLOW'    : 9,
    'DEFAULT'  : 0,
}
