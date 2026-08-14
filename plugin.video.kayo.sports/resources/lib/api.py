import os
import uuid
import time
import json
import base64
import threading

import requests
from slyguy import userdata, settings
from slyguy.exceptions import Error

from .constants import *


class APIError(Error):
    pass


class API:
    def __init__(self):
        self._local = threading.local()
        self._kayo_token  = None
        self._dazn_token  = None
        self._dazn_expiry = 0
        self._subscribed  = None
        self._last_relay_sync = 0  # epoch seconds; avoids hammering relay from concurrent widget threads

    @property
    def _session(self):
        s = getattr(self._local, 'session', None)
        if s is None:
            s = requests.Session()
            self._local.session = s
        return s

    def new_session(self):
        self._kayo_token  = userdata.get('kayo_token')
        self._dazn_token  = userdata.get('dazn_token')
        self._dazn_expiry = userdata.get('dazn_expiry', 0)
        self._subscribed  = None
        self._load_bootstrap()
        self._sync_tokens_to_relay()

    def _get_wizard_username(self):
        """Read the panel username from plugin.program.duwizard settings.xml.
        The wizard stores panel credentials as <setting id="USERNAME">PASSWORD</setting>
        where the setting ID is the panel username and the value is the panel password."""
        try:
            import xbmc
            import xbmcvfs
            import xml.etree.ElementTree as ET
            path = xbmc.translatePath(
                'special://userdata/addon_data/plugin.program.duwizard/settings.xml')
            if not xbmcvfs.exists(path):
                return None
            with xbmcvfs.File(path) as f:
                content = f.read()
            tree = ET.fromstring(content)
            _SKIP = {
                'buildname','buildversion','buildtheme','latestversion','lastbuildcheck',
                'disableupdate','installmethod','seperate','installed','extract','errors',
                'defaultskin','defaultskinname','defaultskinignore','clearcache',
                'filesize_alert','filesizethumb_alert','email','oldlog','wizlog','crashlog',
                'developer','adult','auto-view','viewType','notify','noteid','notedismiss',
                'ogwiz','addon_debug','debuglevel','wizardlog','autocleanwiz','wizlogcleanby',
                'wizlogcleandays','wizlogcleansize','wizlogcleanlines','nextcleandate',
                'firstrun','password','show15','show16','show17','show18',
            }
            _SKIP_PFX = (
                'default.','login','keep','include','wizard','wiz','salts','specto',
                'trakt','meta','urlresolver','alluc','royalwe','velocity','exodus',
            )
            for setting in tree.findall('setting'):
                sid = setting.get('id', '')
                val = (setting.text or '').strip()
                if sid in _SKIP:
                    continue
                if any(sid.startswith(p) for p in _SKIP_PFX):
                    continue
                # The value is the panel/wizard username (numeric phone number)
                if val and val.isdigit():
                    return val
        except Exception:
            pass
        return None

    def _relay_token_payload(self, token, refresh_token=''):
        return {'token': token, 'refresh_token': refresh_token}

    def _sync_tokens_to_relay(self):
        now = time.time()
        if now - self._last_relay_sync < 5:
            return
        self._last_relay_sync = now
        relay = get_relay_url()
        # Always register display name so the dashboard can identify this viewer
        try:
            name = settings.get('display_name', '').strip() or (self._get_wizard_username() or '')
            if name:
                self._session.post(relay + '/register_name',
                                   json={'display_name': name}, timeout=5)
        except Exception:
            pass
        # Send Kayo token to relay if available
        kayo_token    = self._kayo_token or ''
        refresh_token = userdata.get('kayo_refresh_token', '')
        if not kayo_token and not refresh_token:
            return
        try:
            self._session.post(relay + '/set_kayo_token',
                               json=self._relay_token_payload(kayo_token, refresh_token),
                               timeout=5)
        except Exception:
            pass

    def _load_bootstrap(self):
        # Skip if already bootstrapped in a previous session
        if userdata.get('dazn_bootstrap_done'):
            return
        try:
            from . import dazn_bootstrap
            token = getattr(dazn_bootstrap, 'TOKEN', '').strip()
            if token.startswith('eyJ'):
                self.set_dazn_token(token)
                userdata.set('dazn_bootstrap_done', True)
        except ImportError:
            pass
        except Exception:
            pass

    @property
    def logged_in(self):
        return bool(self._kayo_token or self._dazn_token)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self, username, password):
        resp = self._session.post(KAYO_AUTH_URL, json={
            'audience':   'kayosports.com.au',
            'grant_type': 'http://auth0.com/oauth/grant-type/password-realm',
            'scope':      'openid offline_access',
            'realm':      'prod-martian-database',
            'client_id':  KAYO_CLIENT_ID,
            'username':   username,
            'password':   password,
        }, headers={
            'User-Agent':   UA_ANDROID,
            'Content-Type': 'application/json',
            'Origin':       'https://kayosports.com.au',
        })
        if resp.status_code != 200:
            raise APIError('Login failed ({}): {}'.format(resp.status_code, resp.text[:300]))
        data          = resp.json()
        kayo_token    = data['access_token']
        refresh_token = data.get('refresh_token', '')
        userdata.set('kayo_token', kayo_token)
        if refresh_token:
            userdata.set('kayo_refresh_token', refresh_token)
        self._kayo_token = kayo_token
        # Send Kayo token + refresh_token to relay so it can proxy content API calls
        # and auto-refresh without requiring a manual re-login.
        try:
            self._session.post(get_relay_url() + '/set_kayo_token',
                               json=self._relay_token_payload(kayo_token, refresh_token),
                               timeout=5)
        except Exception:
            pass
        # DAZN only accepts an existing DAZN JWT for refresh — it rejects Kayo Auth0 tokens.
        # Try anyway (works if we have a stored DAZN token to swap in), but don't fail login.
        try:
            self._refresh_dazn_token(kayo_token)
        except Exception:
            pass  # Caller must prompt for manual DAZN token bootstrap

    def set_dazn_token(self, token):
        exp = self._jwt_payload(token).get('exp', 0)
        userdata.set('dazn_token', token)
        userdata.set('dazn_expiry', exp)
        self._dazn_token  = token
        self._dazn_expiry = exp

    def device_code(self):
        resp = self._session.post(
            'https://auth.kayosports.com.au/oauth/device/code',
            json={
                'client_id': KAYO_CLIENT_ID,
                'scope':     'openid offline_access',
                'audience':  'kayosports.com.au',
            },
            headers={'Content-Type': 'application/json', 'Origin': 'https://kayosports.com.au'},
        )
        resp.raise_for_status()
        return resp.json()

    def device_login(self, device_code_val):
        resp = self._session.post(KAYO_AUTH_URL, json={
            'client_id':  KAYO_CLIENT_ID,
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            'device_code': device_code_val,
        }, headers={'Content-Type': 'application/json', 'Origin': 'https://kayosports.com.au'})
        if resp.status_code == 200:
            data          = resp.json()
            kayo_token    = data.get('access_token')
            refresh_token = data.get('refresh_token', '')
            if kayo_token:
                userdata.set('kayo_token', kayo_token)
                if refresh_token:
                    userdata.set('kayo_refresh_token', refresh_token)
                self._kayo_token = kayo_token
                try:
                    self._session.post(get_relay_url() + '/set_kayo_token',
                                       json=self._relay_token_payload(kayo_token, refresh_token),
                                       timeout=5)
                except Exception:
                    pass
                self._refresh_dazn_token(kayo_token)
                return True
        return False

    def logout(self):
        for key in ('kayo_token', 'dazn_token', 'dazn_expiry',
                    'profile_id', 'profile_name', 'avatar'):
            userdata.delete(key)
        self._kayo_token  = None
        self._dazn_token  = None
        self._dazn_expiry = 0
        self._subscribed  = None

    # ------------------------------------------------------------------
    # DAZN token management
    # ------------------------------------------------------------------

    def _jwt_payload(self, token):
        try:
            part = token.split('.')[1]
            part += '=' * (4 - len(part) % 4)
            return json.loads(base64.b64decode(part))
        except Exception:
            return {}

    def _refresh_dazn_token(self, bearer=None):
        if bearer is None:
            bearer = self._dazn_token or self._kayo_token
        if not bearer:
            raise APIError('No token available for DAZN refresh')
        resp = self._session.post(DAZN_REFRESH_URL, json={'DeviceId': DAZN_DEVICE_ID}, headers={
            'Authorization':  'Bearer ' + bearer,
            'Content-Type':   'application/json',
            'Origin':         'https://kayosports.com.au',
            'Referer':        'https://kayosports.com.au/',
            'User-Agent':     UA_WEB,
            'X-Correlation-Id': str(uuid.uuid4()),
        })
        if resp.status_code != 200:
            raise APIError('DAZN refresh failed ({}): {}'.format(resp.status_code, resp.text[:300]))
        dazn_token = resp.json()['AuthToken']['Token']
        exp = self._jwt_payload(dazn_token).get('exp', 0)
        userdata.set('dazn_token', dazn_token)
        userdata.set('dazn_expiry', exp)
        self._dazn_token  = dazn_token
        self._dazn_expiry = exp
        return dazn_token

    def _ensure_dazn_token(self):
        now = int(time.time())
        if not self._dazn_token:
            try:
                self._refresh_dazn_token()
            except Exception:
                raise APIError(
                    'No DAZN token. Go to Login -> Enter DAZN Token to set up streaming.'
                )
        elif self._dazn_expiry > 0 and now >= self._dazn_expiry - 300:
            try:
                self._refresh_dazn_token()
            except Exception:
                # DAZN exp quirk: token may claim expired but still work — use as-is
                pass
        return self._dazn_token

    # ------------------------------------------------------------------
    # Account / profile
    # ------------------------------------------------------------------

    def is_subscribed(self):
        if self._subscribed is not None:
            return self._subscribed
        # Having a valid Kayo or DAZN token means the user is authenticated — treat as subscribed.
        self._subscribed = bool(self._kayo_token or self._dazn_token)
        return self._subscribed

    def profiles(self):
        resp = self._session.get(
            KAYO_PROFILE_URL + '/user/profile',
            headers={'Authorization': 'Bearer ' + self._kayo_token},
        )
        resp.raise_for_status()
        return resp.json()

    def add_profile(self, name, avatar_id):
        resp = self._session.post(
            KAYO_PROFILE_URL + '/user/profile',
            json={'name': name, 'avatar_id': avatar_id, 'onboarding_status': 'welcomeScreen'},
            headers={'Authorization': 'Bearer ' + self._kayo_token},
        )
        resp.raise_for_status()
        return resp.json()

    def delete_profile(self, profile):
        resp = self._session.delete(
            KAYO_PROFILE_URL + '/user/profile/' + profile['id'],
            headers={'Authorization': 'Bearer ' + self._kayo_token},
        )
        resp.raise_for_status()

    def profile_avatars(self):
        resp = self._session.get(KAYO_RESOURCE_URL + '/production/avatars/avatars.json')
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Content browsing (Kayo content API — powers the Kayo website)
    # ------------------------------------------------------------------

    def _kayo_auth(self):
        return {'Authorization': 'Bearer ' + self._kayo_token}

    def channel_data(self):
        try:
            return self._session.get(LIVE_DATA_URL, timeout=10).json()
        except Exception:
            return {}

    def events(self):
        resp = self._session.get(
            get_relay_url() +'/events',
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get('events', [])

    def sports_list(self):
        resp = self._session.get(
            get_relay_url() +'/sports',
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get('sports', [])

    def sport_tiles(self, raw_sport):
        resp = self._session.get(
            get_relay_url() +'/sport_tiles',
            params={'sport': raw_sport},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get('tiles', [])

    def landing(self, name, sport=None, series=None, team=None):
        params = {'name': name, 'evaluate': 5}
        if sport:  params['sport']  = sport
        if series: params['series'] = series
        if team:   params['team']   = team
        resp = self._session.get(
            get_relay_url() +'/kayo/landing', params=params,
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=25,
        )
        resp.raise_for_status()
        return resp.json()

    def panel(self, href):
        params = {'href': href}
        profile_id = userdata.get('profile_id')
        if '/private/' in href and profile_id:
            params['profile'] = profile_id
        resp = self._session.get(
            get_relay_url() +'/kayo/panel', params=params,
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def show(self, show_id, season_id=None):
        params = {'show_id': show_id}
        if season_id:
            params['season_id'] = season_id
        resp = self._session.get(
            get_relay_url() +'/kayo/show', params=params,
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=25,
        )
        resp.raise_for_status()
        return resp.json()

    def competition_tiles(self, sport_title):
        resp = self._session.get(
            get_relay_url() +'/competition_tiles',
            params={'sport': sport_title},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get('tiles', [])

    def search(self, query, page=1, size=250):
        resp = self._session.get(
            get_relay_url() +'/kayo/search',
            params={'q': query, 'size': size, 'page': page},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Stream acquisition — via relay (relay handles DAZN TLS fingerprinting)
    # ------------------------------------------------------------------

    def recent_replays(self, tile_type='catchup'):
        resp = self._session.get(
            get_relay_url() +'/recent_replays',
            params={'type': tile_type},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=25,
        )
        resp.raise_for_status()
        return resp.json().get('tiles', [])

    def epg(self, date):
        resp = self._session.get(
            get_relay_url() +'/epg',
            params={'date': date},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get('tiles', [])

    def stream(self, asset_id, channel_id=None, upgrade_4k=False, is_live=False):
        from slyguy import settings as _settings
        force_fhd = _settings.getBool('force_fhd', False)

        if force_fhd:
            quality = 'fhd'
        elif is_live and not upgrade_4k:
            # Live non-4K: request FHD only so DAZN omits HEVC capabilities.
            # Keeps ARM32 HEVC decoder pool clear for channels that don't need it.
            quality = 'fhd'
        else:
            # 4K live, or any VOD: request 4K capabilities so DAZN returns HEVC
            # when available. DAZN serves AVC for non-HEVC content regardless.
            quality = '4k'

        params = {'id': asset_id, 'quality': quality}
        if channel_id:
            params['channel'] = channel_id
        if upgrade_4k:
            params['upgrade_4k'] = '1'

        resp = self._session.get(
            get_relay_url() +'/token',
            params=params,
            headers={
                'ngrok-skip-browser-warning': 'true',
                'User-Agent': UA_ANDROID,
            },
            timeout=20,
        )

        if resp.status_code != 200:
            raise APIError('Relay error ({}): {}'.format(resp.status_code, resp.text[:300]))

        data = resp.json()
        if data.get('status') != 'success':
            raise APIError('Relay: ' + data.get('message', 'unknown error'))

        cdn_name  = data.get('cdn_name', '')
        cdn_val   = data.get('cdn_val', '')

        mpd_url = get_relay_url() +'/mpd_kodi?id=' + asset_id + '&quality=' + quality
        # Strip HEVC from the manifest only for live non-4K plays (decoder pool protection).
        # VOD plays never need stripping — one stream at a time, no pool exhaustion.
        if is_live and not upgrade_4k:
            mpd_url += '&avc_only=1'

        return {
            'manifest_url': mpd_url,
            'license_url':  data.get('license_url', ''),
            'cookie_name':  cdn_name,
            'cookie_value': cdn_val,
            'dazn_token':   data.get('dazn_token', self._dazn_token or ''),
            'quality':      quality,
        }
