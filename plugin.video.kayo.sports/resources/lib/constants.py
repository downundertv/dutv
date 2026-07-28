# Kayo Auth0
KAYO_AUTH_URL    = 'https://auth.kayosports.com.au/oauth/token'
KAYO_CLIENT_ID   = 'qjmv9ZvaMDS9jGvHOxVfImLgQ3G5NrT2'
KAYO_API_URL     = 'https://api.kayosports.com.au/v3'
KAYO_PROFILE_URL = 'https://profileapi.kayosports.com.au'
KAYO_RESOURCE_URL= 'https://resources.kayosports.com.au'

# DAZN backend
DAZN_REFRESH_URL  = 'https://ott-authz-bff-prod.ar.indazn.com/v5/RefreshAccessToken'
DAZN_PLAYBACK_URL = 'https://api.playback.indazn.com/v5/Playback'
DAZN_RAIL_URL     = 'https://ruleset-rail-router.discovery.indazn.com/jp/v1/Rail'
DAZN_RAIL_ID      = '8801b4fd-02c2-41ab-a21b-c1a9d4352b57'
DAZN_DEVICE_ID    = '006360b93a'
DAZN_GUID         = '5223f36f-ec0d-4d54-960f-049ea3b6a766'

# Relay — Perth laptop proxies DAZN Playback API (TLS fingerprinting via curl-cffi)
# Update RELAY_URL if the ngrok address changes.
RELAY_URL = 'https://research-gratuity-overboard.ngrok-free.dev'

# EPG / channel data (third-party, no auth needed)
LIVE_DATA_URL = 'https://i.mjh.nz/Kayo/app.json'
EPG_URL       = 'http://aussietv.xyz/Kayo/epg.php'   # overridden by epg_url setting

# Auth UI
CODE_URL = 'kayosports.com.au/connect'

# User-agent strings
UA_ANDROID = 'au.com.foxsports.core.App/1.1.5 (Linux;Android 8.1.0) ExoPlayerLib/2.7.3'
UA_WEB     = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

# Maps Kayo content API channel IDs to DAZN live channel asset IDs.
# Used to resolve live events from the Kayo home/sport landing pages.
CHANNEL_ID_TO_ASSET = {
    'fsa501':      'jo74ryszmcvd1pzmbzp50q84a',    # Fox Cricket
    'fsa502':      '1tc0mhfzkbbti165v1rsuewtek',    # Fox League
    'fsa503':      'xjauo23ins1b1hnss5covnvxw',     # Fox Sports 503
    'fsa504':      '1l47a9ir5hj0o1wi5j0pkm5fpb',    # Fox Footy
    'fsa505':      '12555dnxvg0f319t9w1tgjdvid',    # Fox Sports 505
    'fsa506':      '231pfo674jx615m2uo32ahsex',     # Fox Sports 506
    'fsa507':      '17eyitoe96uwb1qbwz8r6dplok',    # Fox Sports 507
    'fsan':        '1ns8p240ac6bz1ovcbxx538enp',    # Fox Sports News
    'espn1':       'lbod12u9fiwx17r3cpnjxagrb',     # ESPN
    'espn2':       '7n14fwhpjix71fdn6iyz6jabd',     # ESPN 2
    'racing.com':  'e5okck7f0rny12j9xv1kc9w12',    # Racing.com
    'mainevent':   '5nfomyujg3z610ssm0szjoef4',     # Main Event UFC
    'maineventufc':'5nfomyujg3z610ssm0szjoef4',
}

# Maps DAZN Sport.Title → Kayo content API sport slug for landing-page show panels.
SPORT_KAYO_SLUG = {
    'Australian Rules Football': 'afl',
    'Rugby League':              'nrl',
    'Cricket':                   'cricket',
    'Golf':                      'golf',
    'Motorsport':                'motorsport',
    'Basketball':                'basketball',
    'Netball':                   'netball',
    'Football':                  'football',
    'American Football':         'americanfootball',
    'MMA':                       'mma',
    'Baseball':                  'baseball',
    'Surfing':                   'surfing',
    'Cycling BMX':               'cycling',
    'Darts':                     'darts',
}

# Curated competition list: (display label, DAZN Sport.Title used in EPG tiles).
# The DAZN EPG API returns a Sport.Title on each tile; these are the known values.
# To add more: check relay /sport_tiles or /sports for available sport names.
COMPETITIONS = [
    ('AFL',             'Australian Rules Football'),
    ('NRL',             'Rugby League'),
    ('Cricket',         'Cricket'),
    ('Golf',            'Golf'),
    ('Motorsport',      'Motorsport'),
    ('Basketball',      'Basketball'),
    ('Netball',         'Netball'),
    ('Ice Hockey',      'Ice Hockey'),
    ('Football',        'Football'),
    ('American Football', 'American Football'),
    ('MMA',             'MMA'),
    ('Baseball',        'Baseball'),
    ('Surfing',         'Surfing'),
    ('Cycling',         'Cycling BMX'),
    ('Darts',           'Darts'),
]

# Channel logos keyed by DAZN asset_id — tv-logo community repo (publicly accessible)
_TVLOGO = 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/australia/'
CHANNEL_LOGO_MAP = {
    '1l47a9ir5hj0o1wi5j0pkm5fpb': _TVLOGO + 'fox-sports-footy-504-au.png',    # Fox Footy
    '1tc0mhfzkbbti165v1rsuewtek': _TVLOGO + 'fox-sports-league-502-au.png',    # Fox League
    'jo74ryszmcvd1pzmbzp50q84a':  _TVLOGO + 'fox-sports-cricket-501-au.png',   # Fox Cricket
    'lbod12u9fiwx17r3cpnjxagrb':  _TVLOGO + 'espn-au.png',                     # ESPN
    '7n14fwhpjix71fdn6iyz6jabd':  _TVLOGO + 'espn-2-au.png',                   # ESPN 2
    'xjauo23ins1b1hnss5covnvxw':  _TVLOGO + 'fox-sports-503-au.png',           # Fox Sports 503
    '12555dnxvg0f319t9w1tgjdvid': _TVLOGO + 'fox-sports-505-au.png',           # Fox Sports 505
    '231pfo674jx615m2uo32ahsex':  _TVLOGO + 'fox-sports-506-au.png',           # Fox Sports 506
    '17eyitoe96uwb1qbwz8r6dplok': _TVLOGO + 'fox-sports-507-au.png',           # Fox Sports 507
    '1ns8p240ac6bz1ovcbxx538enp': _TVLOGO + 'fox-sports-news-au.png',          # Fox Sports News
    'e5okck7f0rny12j9xv1kc9w12':  _TVLOGO + 'racing-com-au.png',               # Racing.com
    '5nfomyujg3z610ssm0szjoef4':  _TVLOGO + 'fox-sports-regular-au.png',       # Main Event UFC
}

# Permanent 4K channel slots — always present in the TV guide.
# Format: (channel_id, display_name, tvg_chno)
# channel_id matches DAZN LinearProvider values and CHANNEL_ID_TO_ASSET keys.
# At play time the plugin resolves to the live 4K event on that channel,
# or falls back to the HD linear feed when nothing 4K is on.
PERMANENT_4K_CHANNELS = [
    ('fsa501', 'Fox Cricket 4K',    5001),   # Cricket
    ('fsa502', 'Fox League 4K',     5002),   # NRL
    ('fsa503', 'Fox Sports 503 4K', 5003),   # AFL
    ('fsa504', 'Fox Footy 4K',      5004),   # AFL
    ('fsa505', 'Fox Sports 505 4K', 5005),   # Netball
    ('fsa506', 'Fox Sports 506 4K', 5006),   # Motorsport (F1 / V8)
]

# Known live-linear channel asset IDs — used as fallback if content API is unavailable
LIVE_CHANNELS = {
    'Fox Cricket':    'jo74ryszmcvd1pzmbzp50q84a',
    'Fox League':     '1tc0mhfzkbbti165v1rsuewtek',
    'Fox Sports 503': 'xjauo23ins1b1hnss5covnvxw',
    'Fox Footy':      '1l47a9ir5hj0o1wi5j0pkm5fpb',
    'Fox Sports 505': '12555dnxvg0f319t9w1tgjdvid',
    'Fox Sports 506': '231pfo674jx615m2uo32ahsex',
    'Fox Sports 507': '17eyitoe96uwb1qbwz8r6dplok',
    'ESPN':           'lbod12u9fiwx17r3cpnjxagrb',
    'ESPN 2':         '7n14fwhpjix71fdn6iyz6jabd',
    'Racing.com':     'e5okck7f0rny12j9xv1kc9w12',
    'Main Event UFC': '5nfomyujg3z610ssm0szjoef4',
    'Fox Sports News':'1ns8p240ac6bz1ovcbxx538enp',
}
