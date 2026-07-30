import os
import uuid
import time
import json
import base64

import requests
from slyguy import userdata
from slyguy.exceptions import Error

from .constants import *


class APIError(Error):
    pass


class API:
    def __init__(self):
        self._session = requests.Session()
        self._kayo_token  = None
        self._dazn_token  = None
        self._dazn_expiry = 0
        self._subscribed  = None

    def new_session(self):
        self._kayo_token  = userdata.get('kayo_token')
        self._dazn_token  = userdata.get('dazn_token')
        self._dazn_expiry = userdata.get('dazn_expiry', 0)
        self._subscribed  = None
        self._load_bootstrap()
        self._sync_tokens_to_relay()

    def _sync_tokens_to_relay(self):
        kayo_token     = self._kayo_token or ''
        refresh_token  = userdata.get('kayo_refresh_token', '')
        if not kayo_token and not refresh_token:
            return
        try:
            self._session.post(RELAY_URL + '/set_kayo_token',
                               json={'token': kayo_token, 'refresh_token': refresh_token},
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
            self._session.post(RELAY_URL + '/set_kayo_token',
                               json={'token': kayo_token, 'refresh_token': refresh_token},
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
                    self._session.post(RELAY_URL + '/set_kayo_token',
                                       json={'token': kayo_token, 'refresh_token': refresh_token},
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
            RELAY_URL + '/events',
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get('events', [])

    def sports_list(self):
        resp = self._session.get(
            RELAY_URL + '/sports',
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get('sports', [])

    def sport_tiles(self, raw_sport):
        resp = self._session.get(
            RELAY_URL + '/sport_tiles',
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
            RELAY_URL + '/kayo/landing', params=params,
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
            RELAY_URL + '/kayo/panel', params=params,
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
            RELAY_URL + '/kayo/show', params=params,
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=25,
        )
        resp.raise_for_status()
        return resp.json()

    def competition_tiles(self, sport_title):
        resp = self._session.get(
            RELAY_URL + '/competition_tiles',
            params={'sport': sport_title},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get('tiles', [])

    def search(self, query, page=1, size=250):
        resp = self._session.get(
            RELAY_URL + '/kayo/search',
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
            RELAY_URL + '/recent_replays',
            params={'type': tile_type},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=25,
        )
        resp.raise_for_status()
        return resp.json().get('tiles', [])

    def epg(self, date):
        resp = self._session.get(
            RELAY_URL + '/epg',
            params={'date': date},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get('tiles', [])

    def stream(self, asset_id, channel_id=None, upgrade_4k=False):
        from slyguy import settings as _settings
        force_fhd = _settings.getBool('force_fhd', False)
        quality   = 'fhd' if force_fhd else '4k'

        params = {'id': asset_id, 'quality': quality}
        if channel_id:
            params['channel'] = channel_id
        if upgrade_4k:
            params['upgrade_4k'] = '1'

        resp = self._session.get(
            RELAY_URL + '/token',
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

        mpd_url = RELAY_URL + '/mpd_kodi?id=' + asset_id + '&quality=' + quality
        if not upgrade_4k:
            mpd_url += '&avc_only=1'

        return {
            'manifest_url': mpd_url,
            'license_url':  data.get('license_url', ''),
            'cookie_name':  cdn_name,
            'cookie_value': cdn_val,
            'dazn_token':   data.get('dazn_token', self._dazn_token or ''),
        }
