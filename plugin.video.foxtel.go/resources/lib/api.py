import uuid
import time
import json
import base64
import threading

import requests
from slyguy import userdata
from slyguy.exceptions import Error

from .constants import *


class APIError(Error):
    pass


class API:
    def __init__(self):
        self._local       = threading.local()
        self._dazn_token  = None
        self._dazn_expiry = 0

    @property
    def _session(self):
        s = getattr(self._local, 'session', None)
        if s is None:
            s = requests.Session()
            s.headers.update(HEADERS)
            self._local.session = s
        return s

    def new_session(self):
        self._dazn_token  = userdata.get('dazn_token')
        self._dazn_expiry = userdata.get('dazn_expiry', 0)
        self._sync_token_to_relay()

    @property
    def logged_in(self):
        return bool(self._dazn_token)

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def _jwt_payload(self, token):
        try:
            part = token.split('.')[1]
            part += '=' * (4 - len(part) % 4)
            return json.loads(base64.b64decode(part))
        except Exception:
            return {}

    def _store_token(self, token):
        exp = self._jwt_payload(token).get('exp', 0)
        userdata.set('dazn_token',  token)
        userdata.set('dazn_expiry', exp)
        self._dazn_token  = token
        self._dazn_expiry = exp

    def _ensure_token(self):
        if not self._dazn_token:
            raise APIError('Not logged in. Please log in first.')
        now = int(time.time())
        if self._dazn_expiry > 0 and now >= self._dazn_expiry - 300:
            try:
                self._refresh_token()
            except Exception:
                pass
        return self._dazn_token

    def _refresh_token(self):
        resp = self._session.post(
            DAZN_REFRESH_URL,
            json={'DeviceId': get_device_id()},
            headers={
                'Authorization':    'Bearer ' + self._dazn_token,
                'X-Correlation-Id': str(uuid.uuid4()),
            },
        )
        if resp.status_code != 200:
            raise APIError('Token refresh failed ({}): {}'.format(resp.status_code, resp.text[:200]))
        token = resp.json()['AuthToken']['Token']
        self._store_token(token)
        self._sync_token_to_relay()
        return token

    def _sync_token_to_relay(self):
        if not self._dazn_token:
            return
        try:
            requests.post(
                get_relay_url() + '/set_foxtel_token',
                json={'token': self._dazn_token, 'device_id': get_device_id()},
                timeout=3,
            )
        except Exception:
            pass

    def _auth_headers(self):
        token = self._ensure_token()
        return {'Authorization': 'Bearer ' + token, 'X-Correlation-Id': str(uuid.uuid4())}

    # ------------------------------------------------------------------
    # Login / logout
    # ------------------------------------------------------------------

    def login(self, email, password):
        """Sign in via relay (relay uses curl_cffi to bypass CloudFront WAF)."""
        resp = requests.post(
            get_relay_url() + '/foxtel/login',
            json={'email': email, 'password': password, 'device_id': get_device_id()},
            timeout=30,
        )
        if resp.status_code != 200:
            try:
                msg = resp.json().get('message', 'Login failed ({})'.format(resp.status_code))
            except Exception:
                msg = 'Login failed ({})'.format(resp.status_code)
            raise APIError(msg)
        token = resp.json()['token']
        self._store_token(token)
        userdata.set('email', email)
        # Relay already stored the token in foxtel_dazn_state via /foxtel/login

    def login_otp_request(self, email):
        """Step 1 of OTP login — send OTP to email via relay."""
        resp = requests.post(
            get_relay_url() + '/foxtel/otp/request',
            json={'email': email, 'device_id': get_device_id()},
            timeout=20,
        )
        if resp.status_code not in (200, 201, 204):
            try:
                msg = resp.json().get('message', 'OTP request failed ({})'.format(resp.status_code))
            except Exception:
                msg = 'OTP request failed ({})'.format(resp.status_code)
            raise APIError(msg)

    def login_otp_validate(self, email, otp_code):
        """Step 2 of OTP login — validate the code received by email via relay."""
        resp = requests.post(
            get_relay_url() + '/foxtel/otp/validate',
            json={'email': email, 'otp_code': otp_code, 'device_id': get_device_id()},
            timeout=20,
        )
        if resp.status_code != 200:
            try:
                msg = resp.json().get('message', 'OTP validation failed ({})'.format(resp.status_code))
            except Exception:
                msg = 'OTP validation failed ({})'.format(resp.status_code)
            raise APIError(msg)
        token = resp.json()['token']
        self._store_token(token)
        userdata.set('email', email)
        # Relay already stored the token via /foxtel/otp/validate

    def logout(self):
        for key in ('dazn_token', 'dazn_expiry', 'email'):
            userdata.delete(key)
        self._dazn_token  = None
        self._dazn_expiry = 0

    # ------------------------------------------------------------------
    # Live channel data (no auth, from mjh.nz)
    # ------------------------------------------------------------------

    def channel_data(self):
        try:
            data = self._session.get(LIVE_DATA_URL, timeout=10).json()
        except Exception:
            data = {}
        for code, ch in data.items():
            ch['name'] = CHANNEL_NAMES.get(code, code)
            ch['logo'] = channel_logo(code)
        for code, ch in EXTRA_CHANNELS.items():
            if code not in data:
                data[code] = dict(ch)
        return data

    # ------------------------------------------------------------------
    # DAZN EPG (auth required)
    # ------------------------------------------------------------------

    def epg(self, date=None):
        """Fetch DAZN EPG for a given date (YYYY-MM-DD). Returns raw response JSON."""
        import datetime
        if date is None:
            date = datetime.date.today().isoformat()
        resp = self._session.get(
            DAZN_EPG_URL,
            params={'Date': date, 'Evaluate': 5, 'Brand': FOXTEL_BRAND},
            headers=self._auth_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Rails (content browsing)
    # ------------------------------------------------------------------

    def rail(self, rail_id, page_type=None, raw_params=None):
        """Fetch a single DAZN content rail by ID."""
        params = {
            'id':           rail_id,
            'platform':     'web',
            'brand':        FOXTEL_BRAND,
            'country':      'au',
            'languageCode': 'en',
        }
        if raw_params:
            params['params'] = raw_params
        elif page_type:
            params['params'] = 'PageType:{};'.format(page_type)
        resp = self._session.get(
            DAZN_RAIL_URL,
            params=params,
            headers=self._auth_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def rails_page(self, group_id, content_type=None, raw_params=None):
        """Fetch a page's rail sections via the multi-rails endpoint.

        Returns a list of dicts, each with 'id', 'title', and 'params'.
        Rail titles are resolved by fetching each rail concurrently.
        """
        p = {
            'groupId':          group_id,
            'country':          'au',
            'brand':            FOXTEL_BRAND,
            'openBrowse':       'false',
            'userEntitlements': self._get_entitlement_tier(),
        }
        if raw_params:
            p['params'] = raw_params
        elif content_type:
            p['params'] = 'PageType:{};ContentType:{}'.format(content_type, content_type)
        resp = self._session.get(
            DAZN_RAILS_URL,
            params=p,
            headers=self._auth_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        stubs = []
        for item in (data.get('Rails') or data.get('rails') or []):
            rid    = item.get('Id') or item.get('id') or item.get('RailId') or ''
            rparams = item.get('Params') or item.get('params') or ''
            if rid:
                stubs.append({'id': rid, 'params': rparams})

        if not stubs:
            return []

        sections = []
        for stub in stubs:
            try:
                rdata = self.rail(stub['id'], raw_params=stub['params'] or None)
                title = rdata.get('Title') or rdata.get('title') or stub['id']
            except Exception:
                title = stub['id']
            sections.append({'id': stub['id'], 'title': title, 'params': stub['params']})

        return sections

    def _get_entitlement_tier(self):
        """Extract the primary entitlement tier ID from the stored JWT."""
        try:
            import base64 as _b64, json as _json
            token = self._dazn_token or ''
            part = token.split('.')[1]
            part += '=' * (4 - len(part) % 4)
            payload = _json.loads(_b64.b64decode(part))
            sets = payload.get('entitlements', {}).get('entitlementSets', [])
            if sets:
                return sets[0].get('id', 'tv_base_platinum')
        except Exception:
            pass
        return 'tv_base_platinum'

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query, page=1, size=50):
        resp = self._session.get(
            DAZN_SEARCH_URL,
            params={'q': query, 'size': size, 'page': page, 'Brand': FOXTEL_BRAND, 'Market': 'au'},
            headers=self._auth_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Playback (via relay — relay handles DAZN TLS fingerprinting)
    # ------------------------------------------------------------------

    def stream(self, asset_id, quality='4k', is_live=False):
        """Get stream info for an asset via the relay.

        The relay calls api.playback.indazn.com/v5/Playback using the
        Foxtel DAZN token that was synced via /set_foxtel_token.
        Returns a dict with manifest_url, license_url, cdn cookie info.
        """
        params = {'id': asset_id, 'quality': quality}
        resp = self._session.get(
            get_relay_url() + '/foxtel/token',
            params=params,
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=25,
        )
        if resp.status_code != 200:
            raise APIError('Relay error ({}): {}'.format(resp.status_code, resp.text[:300]))
        data = resp.json()
        if data.get('status') != 'success':
            raise APIError('Relay: ' + data.get('message', 'unknown error'))

        mpd_url = '{}/foxtel/mpd_kodi?id={}&quality={}'.format(
            get_relay_url(), asset_id, quality)
        if is_live:
            mpd_url += '&avc_only=1'

        return {
            'manifest_url': mpd_url,
            'license_url':  data.get('license_url', ''),
            'cdn_name':     data.get('cdn_name', ''),
            'cdn_value':    data.get('cdn_val', ''),
            'wv_secure':    data.get('wv_secure', False),
        }
