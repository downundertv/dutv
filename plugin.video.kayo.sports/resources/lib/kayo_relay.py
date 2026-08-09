#!/usr/bin/env python3
"""
Kayo Relay Server - DAZN token refresh flow with correct request format

Ad-break handling:
  When C:\kayo\slate\ contains pre-generated DASH segments (run generate_slate.py once),
  the relay uses STATEFUL SLATE MODE:
    - First ad period detected â†' lock a "slate-break" Period into per-asset state.
    - Every subsequent manifest poll returns the same Period ID for the whole break.
    - O11V4 sees a STABLE period â†' zero reinits during ad break (just 2 total: enter + exit).
    - A still image / background plays instead of the ad content.
  When slate segments are not present, falls back to MERGE MODE (original behaviour).
"""
from flask import Flask, request, jsonify, Response
import requests
from curl_cffi import requests as curl_requests
import time
import uuid
import random
import json as _json
import io
import os
import re
import copy
import struct
import base64
import threading
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

# Register XML namespace prefixes so ET.tostring() preserves readable names
# when we re-serialise DASH manifests.
ET.register_namespace('',     'urn:mpeg:dash:schema:mpd:2011')
ET.register_namespace('cenc', 'urn:mpeg:cenc:2013')
ET.register_namespace('xsi',  'http://www.w3.org/2001/XMLSchema-instance')
ET.register_namespace('xlink','http://www.w3.org/1999/xlink')

app = Flask(__name__)

AUTH_URL         = "https://auth.kayosports.com.au/oauth/token"
PROFILES_URL     = "https://profileapi.kayosports.com.au/user/profile"
CLIENT_ID        = "qjmv9ZvaMDS9jGvHOxVfImLgQ3G5NrT2"
USER_AGENT       = "au.com.foxsports.core.App/1.1.5 (Linux;Android 8.1.0) ExoPlayerLib/2.7.3"
CONTENT_URL      = "https://api.kayosports.com.au/content/types/landing/names"
RAIL_URL         = "https://ruleset-rail-router.discovery.indazn.com/jp/v1/Rail"
LIVE_RAIL_ID     = "8801b4fd-02c2-41ab-a21b-c1a9d4352b57"  # "Live & Upcoming" rail
DAZN_REFRESH_URL = "https://ott-authz-bff-prod.ar.indazn.com/v5/RefreshAccessToken"
DAZN_PLAY_URL    = "https://api.playback.indazn.com/v5/Playback"

DEVICE_ID = "006360b93a"
GUID      = "5223f36f-ec0d-4d54-960f-049ea3b6a766"

SEED_DAZN_TOKEN = "eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCIsImtpZCI6IjJXZlVweldreUxEcS1aOXkyRG1Yb0VwNXM3SHBYd3FnZGluallsS3c5NWsifQ.eyJ1c2VyIjoiYXV0aDB8NjlhOGI2ZDIyYjExZWIxYmQ0NDUyMDBiIiwiaXNzdWVkIjoxNzc5MzUzNzc4LCJ1c2Vyc3RhdHVzIjoiQWN0aXZlUGFpZCIsInNvdXJjZVR5cGUiOiJLQVlPIiwicHJvZHVjdFN0YXR1cyI6eyJUZW5uaXNUViI6IlBhcnRpYWwiLCJCSU5HRSI6IlBhcnRpYWwiLCJGSUJBIjoiUGFydGlhbCIsIk5ITCI6IlBhcnRpYWwiLCJMaWdhU2VndW5kYSI6IlBhcnRpYWwiLCJOYXRpb25hbExlYWd1ZVRWIjoiUGFydGlhbCIsIlJhbGx5VFYiOiJQYXJ0aWFsIiwiTkZMIjoiUGFydGlhbCIsIlBHQSI6IlBhcnRpYWwiLCJEQVpOIjoiUGFydGlhbCIsIkVMRiI6IlBhcnRpYWwiLCJLQVlPIjoiQWN0aXZlUGFpZCJ9LCJ2aWV3ZXJJZCI6IjMwMzZmZTE2ZDMyNDk4NmM0NTcyNTBiNTQwODQxYTI3ZTMwM2QzYjQiLCJjb3VudHJ5IjoiYXUiLCJjb250ZW50Q291bnRyeSI6ImF1IiwibGFuZ3VhZ2UiOiJlbiIsImlzUHVyY2hhc2FibGUiOnRydWUsImhvbWVDb3VudHJ5IjoiYXUiLCJ1c2VyVHlwZSI6MywiZGV2aWNlSWQiOiJhdXRoMHw2OWE4YjZkMjJiMTFlYjFiZDQ0NTIwMGItMDA2MzYwYjkzYXxrYXlvIiwiaXNEZXZpY2VQbGF5YWJsZSI6dHJ1ZSwicGxheWFibGVFbGlnaWJpbGl0eVN0YXR1cyI6IlBMQVlBQkxFIiwiY2FucmVkZWVtZ2MiOiJFbmFibGVkIiwianRpIjoiY2FhYWEwYmItMTM5ZC00ZDBkLThkM2MtYTdkNjlmN2RiNzZjIiwiaWRwVHlwZSI6ImlkcC1wYXNzd29yZCIsInByb3ZpZGVyTmFtZSI6ImRhem4iLCJwcm92aWRlckN1c3RvbWVySWQiOiI0Y2UwMThlYy00OGZmLTQ2N2YtYmMyMy1mZDdjMzQ1Y2I0MzMiLCJlbnRpdGxlbWVudHMiOnsiZW50aXRsZW1lbnRTZXRzIjpbeyJpZCI6InRpZXJfcHJlbWl1bV9rYXlvIiwicHJvZHVjdFR5cGUiOiJ0aWVyIiwiZW50aXRsZW1lbnRzIjpbImFfYSIsImVudGl0bGVtZW50X2FsbG93X3dhdGNoX2NvbmN1cnJlbmN5IiwiZW50aXRsZW1lbnRfbXVsdGlwbGVfZGV2aWNlc185OTkiXSwiaGRyIjp0cnVlLCJkb2xieSI6dHJ1ZSwibXVsdGl2aWV3Ijp0cnVlLCJwcm9kdWN0R3JvdXAiOiJLQVlPIiwiYnJhbmQiOiJLQVlPIiwiYWxsb3c0ayI6dHJ1ZX1dLCJmZWF0dXJlcyI6eyJDT05DVVJSRU5DWSI6eyJrYXlvX21heF9kZXZpY2VzIjoyLCJtYXhfZGV2aWNlcyI6Mn0sIkRFVklDRSI6eyJtYXhfcmVnaXN0ZXJlZF9kZXZpY2VzIjo5OTksImFjY2Vzc19kZXZpY2UiOiJhbnkifX19LCJsaW5rZWRTb2NpYWxQYXJ0bmVycyI6W10sInV0IjoiUCIsInppcCI6IjYwMzgiLCJhY3IiOiJhcC1zb3V0aGVhc3QtMiIsImVtYWlsIjoiVCIsInBob25lTnVtYmVyIjoiVCIsInByb2ZpbGVJZCI6IjMwMzZmZTE2ZDMyNDk4NmM0NTcyNTBiNTQwODQxYTI3ZTMwM2QzYjQiLCJicmFuZCI6ImtheW8iLCJleHAiOjE3NzkzNjA5NzgsImlzcyI6Imh0dHBzOi8vYXV0aC5hci5pbmRhem4uY29tIn0.KMzh9h2kN1vxC2tLbcOfZJ6sokYqwiF3kLhcxRp3dq-3Zf70nGQ81eGz6SqfYefqzaS48eXjXtC2HZv8GKsE3OdDG9mQTJDFrS2aKt3ijdiuDrIx1TEHrs7gR0DSTS_OMMg1uI5aqqifze0arM2nrawaDCPT79VNrNAAx8kHi_AZU11wjsHnyiOEI6Qd_H6RUnIW4y3dh3WrxSpSYhRHKvFOYJ3bQ2Wf1G3_TXvEkAlBaXFeo_NqmAvBTRhSECHyY1PizWWDvvN1wBaEPw_-TqvSRhPn1wSgpZhvr2iTH14Jc2m16c6olqiZ-QrKWcibIhdrABLNmp9VOqr3EmrEmw"

_RELAY_DIR              = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE              = os.path.join(_RELAY_DIR, "dazn_token.txt")
KAYO_TOKEN_FILE         = os.path.join(_RELAY_DIR, "kayo_token.txt")
KAYO_REFRESH_TOKEN_FILE = os.path.join(_RELAY_DIR, "kayo_refresh_token.txt")
KAYO_API_BASE    = "https://api.kayosports.com.au/v3"
KAYO_PROFILE_BASE= "https://profileapi.kayosports.com.au"

kayo_token_state         = {"token": None, "expiry": 0}
kayo_refresh_token_state = {"token": None}

# Cache for inline panel contents fetched during landing calls.
# Keyed by the full panel href URL. TTL 10 minutes.
# Populated by /kayo/landing; served by /kayo/panel as fallback when 503.
_panel_cache = {}

# Cache for full landing responses (sport/competition landings).
# Keyed by "name:sport" e.g. "sport:afl". TTL 5 minutes fresh, 60 min stale fallback.
_landing_cache = {}
_LANDING_TTL   = 300   # 5 min — fresh serving
_LANDING_STALE = 3600  # 60 min — serve stale if API fails

# 4K asset keepalive — persists the last known UHD event asset_id per linear channel.
# After a 4K game ends, DAZN keeps the event asset live (showing "standby for 4K action"
# or similar filler).  By remembering the asset_id we can keep serving UHD quality even
# after the Rail event expires, rather than falling back to the FHD permanent channel slot.
_4k_keepalive     = {}   # {channel_id: {'asset_id': str, 'saved_at': float}}
_asset_to_channel = {}   # {asset_id: channel_id} — refreshed on each Rail fetch
_4K_KEEPALIVE_TTL = 4 * 3600  # keep for 4 hours after the game ends

# Cache for Live & Upcoming Rail events.  The DAZN Rail API occasionally fails
# immediately after a stream closes (rate-limit / transient error), which would
# blank the widget.  Serve stale data on error so the widget stays populated.
_rail_events_cache      = {'events': [], 'expiry': 0}
_rail_events_cache_lock = threading.Lock()
_RAIL_EVENTS_TTL        = 60   # seconds — fresh serving window

def _load_kayo_token_from_file():
    try:
        with open(KAYO_TOKEN_FILE, "r", encoding="utf-8-sig") as f:
            token = f.read().strip()
        if token and token.startswith("eyJ"):
            kayo_token_state["token"]  = token
            kayo_token_state["expiry"] = time.time() + 82800  # treat as valid for 23h
            print("Loaded Kayo token from file")
            return token
    except Exception:
        pass
    return None

def _load_kayo_refresh_token():
    try:
        with open(KAYO_REFRESH_TOKEN_FILE, "r", encoding="utf-8-sig") as f:
            token = f.read().strip()
        if token:
            kayo_refresh_token_state["token"] = token
            return token
    except Exception:
        pass
    return None

def _save_kayo_refresh_token(token):
    try:
        with open(KAYO_REFRESH_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token)
        kayo_refresh_token_state["token"] = token
    except Exception as e:
        print(f"Warning: could not save kayo refresh token: {e}")

def _kayo_auto_refresh():
    """Use stored refresh_token to get a new Kayo access_token without credentials."""
    refresh_tok = kayo_refresh_token_state.get("token") or _load_kayo_refresh_token()
    if not refresh_tok:
        return None
    print("Kayo token expired  -  attempting refresh_token grant...")
    try:
        r = curl_requests.post(
            AUTH_URL,
            json={
                "grant_type":    "refresh_token",
                "client_id":     CLIENT_ID,
                "refresh_token": refresh_tok,
            },
            headers={
                "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Content-Type": "application/json",
                "Origin":       "https://kayosports.com.au",
                "Referer":      "https://kayosports.com.au/",
            },
            timeout=20,
            impersonate="safari17_0",
        )
        if r.status_code != 200:
            print(f"Kayo refresh_token grant failed ({r.status_code}): {r.text[:200]}")
            return None
        data = r.json()
        new_access  = data.get("access_token", "")
        new_refresh = data.get("refresh_token", "")
        if not new_access:
            return None
        with open(KAYO_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(new_access)
        kayo_token_state["token"]  = new_access
        kayo_token_state["expiry"] = time.time() + 82800
        if new_refresh:
            _save_kayo_refresh_token(new_refresh)
        print("Kayo access_token auto-refreshed via refresh_token grant.")
        return new_access
    except Exception as e:
        print(f"Kayo refresh_token grant error: {e}")
        return None

def get_kayo_token():
    if kayo_token_state["token"] and time.time() < kayo_token_state["expiry"]:
        return kayo_token_state["token"]
    # Token expired  -  try refresh_token grant before falling back to file
    refreshed = _kayo_auto_refresh()
    if refreshed:
        return refreshed
    return _load_kayo_token_from_file()

_load_kayo_token_from_file()
_load_kayo_refresh_token()


def _jwt_exp(token):
    """Return the 'exp' Unix timestamp from a JWT payload without verifying signature."""
    import base64 as _b64
    try:
        pad = token.split('.')[1]
        pad += '=' * (4 - len(pad) % 4)
        claims = _json.loads(_b64.urlsafe_b64decode(pad))
        return int(claims.get("exp", 0))
    except Exception:
        return 0

# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  CHANNEL MAP - DAZN asset ID -> channel name
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
CHANNEL_MAP = {
    "1l47a9ir5hj0o1wi5j0pkm5fpb": "Fox Footy",
    "1tc0mhfzkbbti165v1rsuewtek": "Fox League",
    "jo74ryszmcvd1pzmbzp50q84a":  "Fox Cricket",
    "lbod12u9fiwx17r3cpnjxagrb":  "ESPN",
    "7n14fwhpjix71fdn6iyz6jabd":  "ESPN2",
    "xjauo23ins1b1hnss5covnvxw":  "Fox Sports 503",
    "12555dnxvg0f319t9w1tgjdvid": "Fox Sports 505",
    "231pfo674jx615m2uo32ahsex":  "Fox Sports 506",
    "17eyitoe96uwb1qbwz8r6dplok": "Fox Sports 507",
    "1ns8p240ac6bz1ovcbxx538enp": "Fox Sports News",
    "e5okck7f0rny12j9xv1kc9w12":  "Racing.com",
    "5nfomyujg3z610ssm0szjoef4":  "MainEvent UFC",
}

# Maps Kayo API channel_id values to proper names
CHANNEL_ID_MAP = {
    "fsa501":      "Fox Cricket",
    "fsa502":      "Fox League",
    "fsa503":      "Fox Sports 503",
    "fsa504":      "Fox Footy",
    "fsa505":      "Fox Sports 505",
    "fsa506":      "Fox Sports 506",
    "fsa507":      "Fox Sports 507",
    "fsan":        "Fox Sports News",
    "espn1":       "ESPN",
    "espn2":       "ESPN2",
    "racing.com":  "Racing.com",
    "mainevent":   "MainEvent UFC",
    "maineventufc":"MainEvent UFC",
    "kayo":        None,  # filter out Hindi simulcast
}

# Titles that are just channel placeholders, not real events
PLACEHOLDER_TITLES = {
    "Fox Cricket", "Fox League", "Fox Footy", "Fox Sports News",
    "Fox Sports 503", "Fox Sports 505", "Fox Sports 506", "Fox Sports 507",
    "ESPN1", "ESPN2", "ESPN", "Racing.com", "MainEvent UFC",
}

# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  SLATE CONFIGURATION
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Directory where generate_slate.py puts the pre-generated DASH segments.
SLATE_DIR = r"C:\kayo\slate"

# The external URL this relay is reachable at (ngrok tunnel).
# Slate segment URLs injected into DASH manifests use this prefix so O11V4
# on the Finnish VPS can fetch them through the tunnel.
# Update this if your ngrok URL changes.
RELAY_BASE_URL = "https://research-gratuity-overboard.ngrok-free.dev"

# â"€â"€ Per-asset ad break state â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Keyed by asset_id. Populated when an ad break is first detected; cleared when
# DRM content resumes.  Guarded by _ad_state_lock for thread safety.
_ad_state_lock = threading.Lock()
_ad_state      = {}
# Format: {asset_id: {"period_start": "PT1234.5S", "since": <unix_timestamp>}}

# Stateful lock for MODE 2 (no slate files). Stores a deep-copy of the first
# ad period seen so the same Period ID is returned on every poll, preventing
# O11V4 from reiniting on each manifest refresh during an ad break.
_ad_state_merge = {}
# Format: {asset_id: {"locked_period": ET.Element, "since": float}}

# Background watcher threads — one per asset_id while an ad break is active.
# The watcher polls the raw DAZN manifest every 1 second and clears _ad_state
# immediately when the break ends, giving instant detection instead of waiting
# for O11V4's next manifest poll (which could be up to minimumUpdatePeriod away).
_ad_watch_threads      = {}   # {asset_id: threading.Thread}
_ad_watch_threads_lock = threading.Lock()

# Maximum time (seconds) to hold ad-break state without a positive detection.
# Prevents the slate from being permanently stuck when a game ends, the stream
# hiccups, or detection loses track of a long ad break.
MAX_AD_STATE_SECONDS = 600  # 10 minutes

# â"€â"€ Slate period template (lazy-loaded from slate.mpd) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
_slate_cache_lock    = threading.Lock()
_slate_period_xml    = None   # ET.Element  -  always deep-copy before use
_slate_loaded        = False
_slate_segment_count = 15     # updated when slate.mpd is successfully parsed


def _ensure_slate_loaded():
    """
    Parse slate.mpd once and cache the Period element as a reusable template.
    Thread-safe; subsequent calls are no-ops once loaded (or once a failure
    has been recorded  -  we don't retry on every request).
    """
    global _slate_period_xml, _slate_loaded, _slate_segment_count
    with _slate_cache_lock:
        if _slate_loaded:
            return
        _slate_loaded = True  # set before any return so failures don't spin

        slate_mpd_path = os.path.join(SLATE_DIR, "slate.mpd")
        if not os.path.exists(slate_mpd_path):
            app.logger.warning(
                "[slate] slate.mpd not found at %s  -  "
                "slate disabled, using merge fallback. "
                "Run generate_slate.py to enable the still-image ad break feature.",
                SLATE_DIR,
            )
            return

        try:
            # Count available video segments to know the loop length
            segs = [f for f in os.listdir(SLATE_DIR) if re.match(r"^seg_0_\d+\.m4s$", f)]
            _slate_segment_count = len(segs) if segs else 15
            app.logger.info("[slate] %d video segments found in %s", _slate_segment_count, SLATE_DIR)

            # Register all namespaces so they survive ET serialisation
            mpd_text = open(slate_mpd_path, encoding="utf-8").read()
            for _evt, (pfx, uri) in ET.iterparse(io.StringIO(mpd_text), events=["start-ns"]):
                ET.register_namespace(pfx, uri)

            root = ET.fromstring(mpd_text)

            # Find the first Period regardless of whether a DASH namespace is present
            period = None
            for child in root:
                tag_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag_local == "Period":
                    period = child
                    break

            if period is None:
                app.logger.warning("[slate] No Period element found in slate.mpd  -  slate disabled")
                return

            # Assign the stable ID that prevents O11V4 from reinitialising on every poll
            period.set("id", "slate-break")

            # Rewrite all relative segment/init URLs to absolute relay URLs so O11V4
            # on the remote VPS can fetch them through the ngrok tunnel.
            for elem in period.iter():
                for attr in ("initialization", "media"):
                    val = elem.get(attr)
                    if val and not val.startswith("http"):
                        elem.set(attr, f"{RELAY_BASE_URL}/slate/{val.lstrip('/')}")

            _slate_period_xml = period
            app.logger.info(
                "[slate] Period template loaded  -  %d segments, URLs rewritten to %s/slate/",
                _slate_segment_count, RELAY_BASE_URL,
            )

        except Exception as exc:
            app.logger.error("[slate] Failed to load slate.mpd: %s", exc)


def _get_slate_period(start_attr):
    """
    Return a deep copy of the cached slate Period element with the supplied
    start= attribute set.  Returns None if slate is not available.

    The 'duration' attribute is stripped so O11V4 infers the period's length
    from the next content period's start instead.  This prevents O11V4 from
    skipping the slate when it calculates that the elapsed time since period
    start already exceeds the static MPD's declared duration.
    """
    _ensure_slate_loaded()
    if _slate_period_xml is None:
        return None
    p = copy.deepcopy(_slate_period_xml)
    if start_attr:
        p.set("start", start_attr)
    # Strip static duration  -  in a live multi-period manifest the period ends
    # when the next period begins, so an explicit duration is wrong here.
    p.attrib.pop("duration", None)
    return p


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  TOKEN MANAGEMENT
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def _load_token_from_file():
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8-sig") as f:
            token = f.read().strip()
        if token and token.startswith("eyJ"):
            print("Loaded DAZN token from file")
            return token
    except Exception:
        pass
    print("Using seed DAZN token")
    return SEED_DAZN_TOKEN

def _save_token_to_file(token):
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token)
    except Exception as e:
        print(f"Warning: could not save token to file: {e}")

_dazn_seed = _load_token_from_file()
_dazn_exp  = _jwt_exp(_dazn_seed)
dazn_state = {
    "token":  _dazn_seed,
    # Use actual JWT exp so an already-expired token triggers immediate refresh.
    # If exp is missing or in the past, set to 0 so the first get_dazn_token()
    # call triggers a refresh right away.
    "expiry": _dazn_exp if _dazn_exp > int(time.time()) + 60 else 0,
}
# Lock prevents concurrent DAZN auth refreshes (e.g. when multiple widget calls
# all reset dazn_state['expiry'] = 0 and then simultaneously hit get_dazn_token).
_dazn_refresh_lock = threading.Lock()

kayo_cache = {}

def rand_hex(n=6):
    return ''.join(random.choices('0123456789ABCDEF', k=n))

def _dazn_refresh_with_bearer(bearer_token):
    """
    Call DAZN RefreshAccessToken with the given bearer.
    Works with both an existing DAZN JWT (normal refresh cycle) AND a fresh
    Kayo Auth0 access_token (initial bootstrap when the stored DAZN JWT has
    expired and can no longer be used to refresh itself).
    Returns the new DAZN JWT string, or raises on failure.
    """
    headers = {
        "Authorization":    f"Bearer {bearer_token}",
        "Content-Type":     "application/json",
        "Origin":           "https://kayosports.com.au",
        "Referer":          "https://kayosports.com.au/",
        "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "X-Correlation-Id": str(uuid.uuid4()),
    }
    r = curl_requests.post(DAZN_REFRESH_URL, json={"DeviceId": DEVICE_ID}, headers=headers, timeout=15, impersonate="safari17_0")
    print(f"DAZN refresh status: {r.status_code}")
    r.raise_for_status()
    token = r.json().get("AuthToken", {}).get("Token")
    if not token:
        raise Exception("No token in DAZN refresh response")
    return token


def get_dazn_token():
    if time.time() < dazn_state["expiry"] - 300:
        return dazn_state["token"]

    with _dazn_refresh_lock:
        # Re-check after acquiring the lock — another thread may have refreshed while we waited.
        if time.time() < dazn_state["expiry"] - 300:
            return dazn_state["token"]

        print("DAZN token expiring/expired  -  refreshing...")

        # Pass 1: refresh using current DAZN token (normal rolling refresh).
        try:
            token = _dazn_refresh_with_bearer(dazn_state["token"])
            dazn_state["token"]  = token
            dazn_state["expiry"] = int(time.time()) + 3600
            _save_token_to_file(token)
            print("DAZN token refreshed via DAZN bearer.")
            return token
        except Exception as e:
            print(f"DAZN-bearer refresh failed ({e}), trying Kayo token exchange...")

        # Pass 2: exchange stored Kayo token for a fresh DAZN JWT.
        kayo_tok = kayo_token_state.get("token") or get_kayo_token()
        if kayo_tok:
            try:
                token = _dazn_refresh_with_bearer(kayo_tok)
                dazn_state["token"]  = token
                dazn_state["expiry"] = int(time.time()) + 3600
                _save_token_to_file(token)
                print("DAZN token refreshed via Kayo token exchange.")
                return token
            except Exception as e2:
                print(f"Kayo token exchange also failed ({e2})")

        # All refresh attempts failed  -  retry in 30 s so a transient failure
        # auto-recovers without requiring a manual channel switch.
        dazn_state["expiry"] = int(time.time()) + 30
        return dazn_state["token"]

def _profile_id_from_dazn_jwt():
    """Extract profileId/viewerId from the stored DAZN JWT without any network call."""
    import base64 as _b64
    for token in (dazn_state.get("token", ""), _load_token_from_file()):
        try:
            if not token or not token.startswith("eyJ"):
                continue
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = _json.loads(_b64.urlsafe_b64decode(payload_b64))
            pid = payload.get("profileId") or payload.get("viewerId")
            if pid:
                return pid
        except Exception:
            continue
    return None


def authenticate_kayo(username, password):
    cache_key = f"{username}:{password}"
    if cache_key in kayo_cache:
        cached = kayo_cache[cache_key]
        if time.time() < cached['expiry']:
            return cached
    print(f"Authenticating {username}...")
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json", "Origin": "https://kayosports.com.au"}
    try:
        r = requests.post(AUTH_URL, json={
            "audience": "kayosports.com.au",
            "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
            "scope": "openid offline_access",
            "realm": "prod-martian-database",
            "client_id": CLIENT_ID,
            "username": username,
            "password": password,
        }, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        access_token = data["access_token"]
        auth_headers = {**headers, "Authorization": f"Bearer {access_token}"}
        profile_id = None
        pr = requests.get(PROFILES_URL, headers=auth_headers, timeout=10)
        if pr.status_code == 200:
            profiles = pr.json()
            if isinstance(profiles, list) and profiles:
                profile_id = profiles[0].get("id")
        result = {
            "access_token": access_token,
            "profile_id": profile_id,
            "expiry": int(time.time() + data.get("expires_in", 86400) - 60),
            "headers": auth_headers
        }
        kayo_cache[cache_key] = result
        return result
    except Exception as e:
        # Kayo auth blocked (Akamai WAF, rate limit, etc.)  -  fall back to
        # profile_id extracted from the stored DAZN JWT. get_stream() uses
        # get_dazn_token() directly so the Kayo access_token isn't needed.
        profile_id = _profile_id_from_dazn_jwt()
        if profile_id:
            print(f"Kayo auth failed ({e})  -  using profile_id from DAZN JWT: {profile_id}")
            result = {
                "access_token": None,
                "profile_id": profile_id,
                "expiry": int(time.time()) + 300,  # retry in 5 min
                "headers": headers,
            }
            kayo_cache[cache_key] = result
            return result
        raise

def get_dazn_asset_id(kayo_cms_id, auth_headers):
    try:
        r = requests.get(f"{CONTENT_URL}/home", headers=auth_headers, timeout=15)
        if r.status_code == 200:
            for panel in r.json().get("panels", []):
                for content in panel.get("contents", []):
                    item = content.get("data", {})
                    ct   = item.get("clickthrough", {})
                    if str(item.get("id", "")) == str(kayo_cms_id) or ct.get("asset", "") == str(kayo_cms_id):
                        dazn_id = ct.get("foxtelCmsAssetId")
                        if dazn_id:
                            return dazn_id
    except Exception as e:
        print(f"DAZN ID lookup error: {e}")
    return None

def get_stream(dazn_asset_id, profile_id, kayo_access_token=None, capabilities=None):
    # DAZN Playback API requires a proper DAZN JWT (iss: auth.ar.indazn.com).
    # The Kayo Auth0 access_token has a different issuer and is NOT accepted by
    # the Playback API.  Always use get_dazn_token() which handles auto-refresh
    # and can bootstrap via Kayo token exchange when the stored DAZN JWT expires.
    # kayo_access_token parameter kept for backwards-compat but is unused here.
    # capabilities: omit "hevc" to force DAZN to return an AVC/H.264 manifest.
    # "mta,hevc" or higher tells DAZN the device supports HEVC and it returns HEVC.
    if capabilities is None:
        capabilities = "mta,4k,uhd,hdr,hevc"
    bearer = get_dazn_token()
    session_id = f"{int(time.time()*1000)}-{profile_id}-{dazn_asset_id}-{rand_hex(6)}"
    params = {
        "AppVersion":         "2.10.1",
        "DrmType":            "WIDEVINE",
        "Format":             "MPEG-DASH",
        "PlayerId":           "@dazn/peng-androidtv-core/androidtv/androidtv-rxplayer",
        "Platform":           "androidtv",
        "Model":              "AFTKA",        # Fire TV Stick 4K Max
        "Secure":             "true",         # Widevine L1 (CDN token issuance requires L1; L3 gets CDN 401)
        "Manufacturer":       "Amazon",
        "PlayReadyInitiator": "false",
        "Capabilities":       capabilities,
        "AssetId":            dazn_asset_id,
        "MtaLanguageCode":    "",
        "LanguageCode":       "en",
        "SessionId":          session_id,
    }
    body = {}
    headers = {
        "Authorization":  f"Bearer {bearer}",
        "Content-Type":   "application/json; charset=UTF-8",
        "User-Agent":     "Dalvik/2.1.0 (Linux; U; Android 9; AFTKA Build/PS7267.2877N)",
        "X-Correlation-Id": str(uuid.uuid4()),
        "X-Dazn-Device":  GUID,
        "Accept":         "application/json",
        "Accept-Language": "en-AU,en;q=0.9",
    }
    print(f"DAZN playback for: {dazn_asset_id} session: {session_id}")
    r = curl_requests.post(DAZN_PLAY_URL, params=params, json=body, headers=headers, timeout=15, impersonate="safari17_0")
    print(f"DAZN response: {r.status_code} - {r.text[:300]}")
    if r.status_code in (401, 403):
        is_uuid = len(dazn_asset_id) == 36 and dazn_asset_id.count('-') == 4
        msg = "Episode unavailable  -  this content may have expired (Kayo only keeps episodes for ~30 days)." \
              if is_uuid else \
              f"DAZN authorisation failed ({r.status_code}). Try re-logging in."
        raise Exception(msg)
    r.raise_for_status()
    data = r.json()
    details = data.get("PlaybackDetails", [])
    if not details:
        raise Exception("No playback details")
    # Prefer cdn.indazn.com ("ac-vod") over dtcdn.dazn.com ("fs-vod")  -  the latter
    # has been observed returning instant 504s while indazn.com CDN works reliably.
    best = next((c for c in details if "cdn.indazn.com" in c.get("ManifestUrl", "")), None) \
        or next((c for c in details if "ak" in c.get("CdnName", "").lower()), None) \
        or details[0]
    cdn_token = best.get("CdnToken", {})
    return {
        "url":       best.get("ManifestUrl"),
        "la_url":    best.get("LaUrl", ""),
        "cdn_token": f"{cdn_token.get('Name','')}={cdn_token.get('Value','')}",
        "pssh":      data.get("License", {}).get("Pssh", ""),
    }

# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  SCHEDULE HELPERS
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def _decode_jwt_payload(token):
    """Decode JWT payload (no verification) to extract claims."""
    import base64
    try:
        payload = token.split('.')[1]
        payload += '=' * (4 - len(payload) % 4)
        return _json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}

def fetch_kayo_rail_schedule():
    """Fetch Live & Upcoming events from DAZN Rail API — cached 60 s, stale on error."""
    now = time.time()
    with _rail_events_cache_lock:
        if now < _rail_events_cache['expiry']:
            return list(_rail_events_cache['events'])

        try:
            dazn_token = get_dazn_token()
            jwt = _decode_jwt_payload(dazn_token)
            viewer_id = jwt.get("viewerId", "3036fe16d324986c457250b540841a27e303d3b4")
            dazn_id   = jwt.get("user",     "auth0|69a8b6d22b11eb1bd445200b")

            params = {
                "platform":     "web",
                "id":           LIVE_RAIL_ID,
                "viewerId":     viewer_id,
                "country":      "au",
                "brand":        "kayo",
                "languageCode": "en",
                "params":       "PageType:Home;ContentType:None",
                "size":         "50",
            }
            headers = {
                "x-brand":    "kayo",
                "x-daznid":   dazn_id,
                "accept":     "application/json, text/plain, */*",
                "referer":    "https://kayosports.com.au/",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            }
            r = requests.get(RAIL_URL, params=params, headers=headers, timeout=15)
            r.raise_for_status()

            events = []
            seen = set()
            for tile in r.json().get("Tiles", []):
                event_id = tile.get("EventId", "")
                asset_id = tile.get("AssetId", "")
                title    = tile.get("Title", "")

                if not event_id or event_id in seen:
                    continue
                if title.startswith("Hindi -") or title in PLACEHOLDER_TITLES:
                    continue

                seen.add(event_id)

                provider = (tile.get("LinearProvider") or "").lower()
                if provider == "kayo":
                    continue  # Kayo-only, no linear channel mapping

                channel_name = CHANNEL_ID_MAP.get(provider) or provider or "Unknown"
                sport        = (tile.get("Sport") or {}).get("Title", "")
                he           = tile.get("HeEventTypeConfig") or {}

                events.append({
                    "id":         event_id,
                    "asset_id":   asset_id,
                    "title":      title,
                    "sport":      sport,
                    "channel":    channel_name,
                    "channel_id": provider,
                    "time":       tile.get("Start", ""),
                    "end_time":   tile.get("End", ""),
                    "type":       "live" if tile.get("Type") == "Live" else "upcoming",
                    "is_4k":      he.get("is4k", False),
                    "is_hdr":     he.get("isHdr", False),
                    "thumb":      _dazn_thumb(tile.get("HeroImage")),
                    "fanart":     _dazn_fanart(tile.get("HeroImage")),
                })

            # Keep reverse lookup fresh so /token can map asset_id -> channel_id for keepalive
            global _asset_to_channel
            _asset_to_channel = {
                ev['asset_id']: ev['channel_id']
                for ev in events
                if ev.get('asset_id') and ev.get('channel_id')
            }

            _rail_events_cache['events'] = events
            _rail_events_cache['expiry'] = now + _RAIL_EVENTS_TTL
            return events

        except Exception as e:
            app.logger.warning("Rail fetch failed (%s) — serving stale cache", e)
            # Serve stale data so the widget stays populated after stream close
            return list(_rail_events_cache['events'])

def fetch_kayo_schedule(auth_headers):
    """
    Fetch events from Kayo API and try to map them to channels.
    Saves raw API response to home_raw.json for debugging.
    """
    r = requests.get(
        f"{CONTENT_URL}/home",
        headers={**auth_headers, 'Origin': 'https://kayosports.com.au'},
        timeout=15
    )
    r.raise_for_status()
    raw = r.json()
    try:
        with open("home_raw.json", "w") as f:
            _json.dump(raw, f, indent=2)
    except Exception:
        pass
    events = []
    seen = set()
    for panel in raw.get("panels", []):
        panel_title = panel.get("title", "")
        for content in panel.get("contents", []):
            item = content.get("data", {})
            ct   = item.get("clickthrough", {})
            asset_id = ct.get("foxtelCmsAssetId") or ct.get("asset")
            if not asset_id or asset_id in seen:
                continue
            seen.add(asset_id)
            itype = item.get("type", ct.get("type", ""))
            channel_id = (ct.get("channel") or "").lower().strip()
            if channel_id in CHANNEL_ID_MAP and CHANNEL_ID_MAP[channel_id] is None:
                continue
            channel_name = (
                CHANNEL_ID_MAP.get(channel_id) or
                CHANNEL_MAP.get(asset_id) or
                channel_id or
                "Unknown"
            )
            title = ct.get("title") or item.get("title", "")
            if title in PLACEHOLDER_TITLES or title.startswith("Hindi -"):
                continue
            events.append({
                "id":         asset_id,
                "title":      title,
                "type":       itype,
                "sport":      ct.get("sportName", ""),
                "time":       ct.get("transmissionTime") or ct.get("startTime", ""),
                "channel":    channel_name or "Unknown",
                "channel_id": channel_id,
                "panel":      panel_title,
            })
    return events

def format_schedule_text(events):
    """Format events as a readable text schedule grouped by channel."""
    from datetime import datetime, timezone
    by_channel = {}
    no_channel = []
    for e in events:
        ch = e.get("channel") or "Unknown Channel"
        if ch == "Unknown Channel":
            no_channel.append(e)
        else:
            by_channel.setdefault(ch, []).append(e)
    lines = []
    lines.append("=" * 55)
    lines.append("  KAYO SPORTS SCHEDULE")
    lines.append(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 55)
    def fmt_time(t):
        if not t:
            return "Unknown time"
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            from datetime import timedelta
            awst = dt + timedelta(hours=8)
            return awst.strftime("%a %d %b %I:%M %p AWST")
        except Exception:
            return t
    for channel, ch_events in sorted(by_channel.items()):
        lines.append(f"\n{'â"€'*55}")
        lines.append(f"  ðŸ“º {channel}")
        lines.append(f"{'â"€'*55}")
        for e in sorted(ch_events, key=lambda x: x.get("time", "")):
            lines.append(f"  {fmt_time(e['time'])}")
            lines.append(f"    {e['title']} ({e['sport']})")
    if no_channel:
        lines.append(f"\n{'â"€'*55}")
        lines.append("  ðŸ“º Channel Unknown")
        lines.append(f"{'â"€'*55}")
        for e in sorted(no_channel, key=lambda x: x.get("time", "")):
            lines.append(f"  {fmt_time(e['time'])}")
            lines.append(f"    {e['title']} ({e['sport']})")
    lines.append(f"\n{'='*55}")
    lines.append(f"  Total: {len(events)} events")
    lines.append("=" * 55)
    return "\n".join(lines)

# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  ROUTES
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.route('/health')
def health():
    return jsonify({"status": "ok", "message": "Kayo relay running (DAZN API)"})

@app.route('/login', methods=['GET', 'POST'])
def login():
    try:
        username = request.args.get('user', '')
        password = request.args.get('password', '')
        if not username or not password:
            return jsonify({"status": "error", "message": "Username and password required"}), 400
        auth = authenticate_kayo(username, password)
        return jsonify({"status": "success", "message": "Authenticated",
                        "token": auth["access_token"], "profile_id": auth["profile_id"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 401

@app.route('/manifest', methods=['GET', 'POST'])
def manifest():
    try:
        username = request.args.get('user', '')
        password = request.args.get('password', '')
        kayo_id  = (request.args.get('id', '') or request.args.get('channel_id', '') or request.args.get('event_id', ''))
        if not username or not password:
            return jsonify({"status": "error", "message": "Credentials required"}), 400
        if not kayo_id:
            return jsonify({"status": "error", "message": "Asset ID required"}), 400
        auth = authenticate_kayo(username, password)
        if kayo_id.isdigit():
            dazn_id = get_dazn_asset_id(kayo_id, auth["headers"])
            if not dazn_id:
                return jsonify({"status": "error", "message": f"Could not find DAZN ID for {kayo_id}"}), 404
        else:
            dazn_id = kayo_id
        stream = get_stream(dazn_id, auth["profile_id"])
        return jsonify({"status": "success", **stream})
    except Exception as e:
        print(f"Manifest error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def _get_live_4k_event_for_channel(channel_id):
    """Return the live 4K event asset_id for a channel, or None. Rail result cached 60s."""
    now = time.time()
    with _4k_rail_cache_lock:
        if now < _4k_rail_cache['expiry']:
            events = _4k_rail_cache['events']
        else:
            try:
                events = fetch_kayo_rail_schedule()
            except Exception as e:
                print(f'[4k_upgrade] Rail fetch failed: {e}')
                events = _4k_rail_cache['events']  # use stale on error
            _4k_rail_cache['events'] = events
            _4k_rail_cache['expiry'] = now + 60
    for ev in events:
        if ev.get('channel_id') == channel_id and ev.get('type') == 'live' and ev.get('is_4k'):
            return ev.get('asset_id')
    return None


@app.route('/token', methods=['GET'])
def token():
    """
    Returns a fresh manifest URL + CDN token for a given DAZN asset ID.

    All clients (Kodi devices, O11V4, XUI-One) that request the same asset_id
    share a single cached DAZN playback session for up to 50 minutes.
    This makes every viewer of the same channel appear as one stream to DAZN,
    regardless of how many people are watching.
    """
    try:
        asset_id = request.args.get('id', '')
        if not asset_id:
            return jsonify({'status': 'error', 'message': 'Asset ID required'}), 400

        # quality=fhd -> request FHD H.264 manifest (omit hevc from capabilities so
        # DAZN returns an AVC manifest; including hevc causes HEVC even at fhd quality)
        quality      = request.args.get('quality', '4k').lower()
        force_fhd    = (quality == 'fhd')
        capabilities = 'mta' if force_fhd else 'mta,4k,uhd,hdr,hevc'
        cache_key    = ('fhd:' + asset_id) if force_fhd else asset_id

        # 4K linear upgrade: if this is a permanent 4K channel slot and a live 4K event
        # is on that channel, silently substitute the event asset_id so DAZN returns a
        # UHD manifest. Falls back to the linear slot (FHD) when no live event found.
        linear_asset_id = None  # set when we substitute, so we can alias the cache below
        upgrade_ttl     = None
        if not force_fhd and asset_id in _LINEAR_4K_ASSET_TO_CHANNEL and request.args.get('upgrade_4k') == '1':
            ch_id    = _LINEAR_4K_ASSET_TO_CHANNEL[asset_id]
            ev_asset = _get_live_4k_event_for_channel(ch_id)
            if ev_asset:
                print(f'[token] 4K upgrade: {asset_id} → {ev_asset} (channel {ch_id})')
                linear_asset_id = asset_id  # remember original so we can alias cache
                asset_id        = ev_asset
                cache_key       = ev_asset
                upgrade_ttl     = _4K_UPGRADE_CACHE_TTL

        now = time.time()

        # Fast path  -  return cached session if still valid
        with _stream_cache_lock:
            cached = _stream_cache.get(cache_key)
            if cached and now < cached['expiry']:
                print(f"[token] cache hit for {cache_key} ({int(cached['expiry'] - now)}s remaining)")
                # Keep the linear→event alias fresh so /mpd_kodi?id=LINEAR finds this session.
                # The alias is otherwise only written on cache miss; without this refresh,
                # a subsequent linear-channel request hits the event cache and returns early
                # without ever writing the alias that /mpd_kodi depends on.
                if linear_asset_id:
                    _stream_cache[linear_asset_id] = cached
                    _mpd_url_cache.pop(linear_asset_id, None)
                return jsonify(cached['response'])

        # Cache miss  -  call DAZN Playback API
        dazn_tok = get_dazn_token()
        try:
            import base64 as _b64
            _pad = dazn_tok.split('.')[1]
            _pad += '=' * (-len(_pad) % 4)
            _claims = _json.loads(_b64.urlsafe_b64decode(_pad))
            profile_id = _claims.get('profileId') or _claims.get('viewerId')
        except Exception:
            profile_id = None
        if not profile_id:
            profile_id = _profile_id_from_dazn_jwt()
        if not profile_id:
            raise Exception('Cannot determine profile_id from DAZN token')

        try:
            stream = get_stream(asset_id, profile_id, capabilities=capabilities)
        except Exception as _e:
            _es = str(_e)
            if '401' in _es or '403' in _es or 'authoris' in _es.lower():
                app.logger.warning("[token] DAZN auth error (%s)  -  force-expiring JWT and retrying", _es[:80])
                dazn_state["expiry"] = 0  # triggers immediate JWT refresh in get_dazn_token()
                stream = get_stream(asset_id, profile_id, capabilities=capabilities)
            else:
                raise
        cdn      = stream["cdn_token"]
        cdn_name = cdn.split("=", 1)[0] if "=" in cdn else ""
        cdn_val  = cdn.split("=", 1)[1] if "=" in cdn else ""
        resp = {
            "status":      "success",
            "url":         stream["url"],
            "cdn_token":   cdn,
            "cdn_name":    cdn_name,
            "cdn_val":     cdn_val,
            "license_url": stream.get("la_url", ""),
            "dazn_token":  dazn_tok,
        }

        ttl = upgrade_ttl if upgrade_ttl else _STREAM_CACHE_TTL
        with _stream_cache_lock:
            _stream_cache[cache_key] = {'response': resp, 'expiry': now + ttl}
            # Alias the linear asset_id → event session so /mpd_kodi?id=LINEAR finds it.
            # The plugin always constructs /mpd_kodi with the original asset_id it was
            # given, not the upgraded event asset_id the relay chose internally.
            if linear_asset_id:
                _stream_cache[linear_asset_id] = {'response': resp, 'expiry': now + ttl}
        # Keep mpd_url_cache in sync so /mpd gets the same session
        _mpd_url_cache.pop(cache_key, None)
        if linear_asset_id:
            _mpd_url_cache.pop(linear_asset_id, None)
        print(f"[token] cached new session for {cache_key} (ttl={ttl}s)")

        # 4K keepalive — remember this asset per channel so the UHD standby screen
        # keeps playing after the game ends and the Rail event expires.
        if not force_fhd:
            ch_id = _asset_to_channel.get(asset_id, '')
            # Caller can supply channel= explicitly (Kodi plugin does this for 4K channels)
            # so we don't depend on a prior Rail fetch having populated _asset_to_channel.
            if not ch_id:
                ch_id = request.args.get('channel', '').lower().strip()
            if ch_id:
                _4k_keepalive[ch_id] = {'asset_id': asset_id, 'saved_at': now}
                print(f'[token] 4K keepalive saved: {ch_id} -> {asset_id}')

        return jsonify(resp)
    except Exception as e:
        print(f"Token error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/cache_clear', methods=['GET'])
def cache_clear():
    """Force-expire stream cache for one or all assets. GET /cache_clear or /cache_clear?id=ASSET_ID"""
    asset_id = request.args.get('id', '').strip()
    with _stream_cache_lock:
        if asset_id:
            removed = 1 if _stream_cache.pop(asset_id, None) else 0
            _mpd_url_cache.pop(asset_id, None)
        else:
            removed = len(_stream_cache)
            _stream_cache.clear()
            _mpd_url_cache.clear()
    # Also clear any held ad-break state for the same asset(s) so a fresh
    # playback session doesn't open mid-slate due to stale state.
    with _ad_state_lock:
        if asset_id:
            _ad_state.pop(asset_id, None)
            _ad_state_merge.pop(asset_id, None)
        else:
            _ad_state.clear()
            _ad_state_merge.clear()
    return jsonify({"status": "ok", "cleared": removed, "asset_id": asset_id or "all"})

@app.route('/4k_keepalive', methods=['GET'])
def get_4k_keepalive():
    """
    Return the last known UHD event asset_id for a linear channel.

    GET /4k_keepalive?channel=fsa502

    Used by the plugin when no live 4K event is visible in the Rail — the
    post-game "standby for 4K action" filler is still being served via the
    event asset for up to _4K_KEEPALIVE_TTL seconds after it was last played.

    Returns:
      {status:'ok',    asset_id:'...', age_minutes:N}  — use this asset_id
      {status:'expired', age_minutes:N}                — TTL elapsed, fall back to FHD
      {status:'none'}                                  — never played a 4K asset for this channel
    """
    channel = request.args.get('channel', '').lower().strip()
    if not channel:
        return jsonify({'status': 'error', 'message': 'channel param required'}), 400
    entry = _4k_keepalive.get(channel)
    if not entry:
        return jsonify({'status': 'none'})
    age = time.time() - entry['saved_at']
    if age > _4K_KEEPALIVE_TTL:
        return jsonify({'status': 'expired', 'age_minutes': int(age / 60)})
    return jsonify({
        'status':      'ok',
        'asset_id':    entry['asset_id'],
        'age_minutes': int(age / 60),
    })


@app.route('/4k_keepalive/set', methods=['GET'])
def set_4k_keepalive():
    """
    Manually seed the 4K keepalive for a channel.
    GET /4k_keepalive/set?channel=fsa502&asset=ASSET_ID
    Useful when the relay was restarted after a game ended and the keepalive was lost.
    """
    channel  = request.args.get('channel', '').lower().strip()
    asset_id = request.args.get('asset', '').strip()
    if not channel or not asset_id:
        return jsonify({'status': 'error', 'message': 'channel and asset params required'}), 400
    _4k_keepalive[channel] = {'asset_id': asset_id, 'saved_at': time.time()}
    print(f'[keepalive] manually set: {channel} -> {asset_id}')
    return jsonify({'status': 'ok', 'channel': channel, 'asset_id': asset_id})


DAZN_EPG_URL = "https://epg.discovery.indazn.com/au/v1/Epg"


def _dazn_img(key, w, h):
    if not key:
        return ''
    return (f'https://image.discovery.indazn.com/jp/v3/jp/none/{key}'
            f'/fill/none/top/none/80/{w}/{h}/webp/image?brand=kayo')

def _dazn_thumb(hero_image):
    """Square thumbnail (1x1) — fits Kodi poster/thumb slot."""
    key = (hero_image or {}).get('Square', '')
    return _dazn_img(key, 400, 400)

def _dazn_fanart(hero_image):
    """Landscape fanart (16x9) — fits Kodi fanart/background slot."""
    key = (hero_image or {}).get('Landscape', '')
    return _dazn_img(key, 1280, 720)


def _fetch_epg(date_str):
    """Fetch DAZN EPG tiles for a given date (YYYY-MM-DD). Returns list of tile dicts."""
    dazn_token = get_dazn_token()
    jwt = _decode_jwt_payload(dazn_token)
    dazn_id = jwt.get("user", "auth0|69a8b6d22b11eb1bd445200b")
    headers = {
        "Authorization": f"Bearer {dazn_token}",
        "x-brand":    "kayo",
        "x-daznid":   dazn_id,
        "accept":     "application/json",
        "referer":    "https://kayosports.com.au/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    }
    params = {
        "platform":     "web",
        "brand":        "kayo",
        "country":      "au",
        "languageCode": "en",
        "date":         date_str,
    }
    r = requests.get(DAZN_EPG_URL, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    tiles = r.json().get("Tiles", [])
    result = []
    for t in tiles:
        title = t.get("Title", "")
        if title.startswith("Hindi -") or not title:
            continue
        asset_id = t.get("AssetId", "")
        if not asset_id:
            continue
        sport_raw = t.get("Sport", "")
        if isinstance(sport_raw, dict):
            sport = sport_raw.get("Title", "")
        else:
            sport = str(sport_raw) if sport_raw else ""
        he = t.get("HeEventTypeConfig") or {}
        result.append({
            "asset_id":    asset_id,
            "title":       title,
            "type":        t.get("Type", ""),
            "display_type": t.get("DisplayType", ""),
            "start":       t.get("Start", ""),
            "end":         t.get("End", ""),
            "description": t.get("Description", ""),
            "sport":       sport,
            "is_4k":       he.get("is4k", False),
            "thumb":       _dazn_thumb(t.get("HeroImage")),
            "fanart":      _dazn_fanart(t.get("HeroImage")),
        })
    return result


@app.route('/epg_raw', methods=['GET'])
def epg_raw():
    """Debug: dump first 2 raw DAZN EPG tiles to see available fields."""
    from datetime import datetime, timezone
    date_str = request.args.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    dazn_token = get_dazn_token()
    jwt = _decode_jwt_payload(dazn_token)
    dazn_id = jwt.get("user", "")
    headers = {
        "Authorization": f"Bearer {dazn_token}",
        "x-brand": "kayo", "x-daznid": dazn_id,
        "accept": "application/json", "referer": "https://kayosports.com.au/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    params = {"platform": "web", "brand": "kayo", "country": "au", "languageCode": "en", "date": date_str}
    r = requests.get(DAZN_EPG_URL, params=params, headers=headers, timeout=15)
    tiles = r.json().get("Tiles", [])
    return jsonify({"raw_tiles": tiles[:2], "total": len(tiles)})


@app.route('/epg', methods=['GET'])
def epg_tiles():
    """
    Returns VOD/replay tiles from the DAZN EPG for a given date.
    GET /epg?date=YYYY-MM-DD   (defaults to today in UTC)
    """
    from datetime import datetime, timezone
    date_str = request.args.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        tiles = _fetch_epg(date_str)
        return jsonify({"status": "success", "date": date_str, "tiles": tiles, "count": len(tiles)})
    except Exception as e:
        print(f"EPG error ({date_str}): {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


_all_tiles_cache = {'tiles': None, 'time': 0}
_ALL_TILES_TTL   = 1800  # 30 minutes


def _get_all_tiles_cached():
    """Fetch EPG for past 21 days + next 7 days in parallel, cached for 30 min."""
    import threading
    now = time.time()
    if _all_tiles_cache['tiles'] is not None and now - _all_tiles_cache['time'] < _ALL_TILES_TTL:
        return _all_tiles_cache['tiles']
    from datetime import date as _date, timedelta
    today = _date.today()
    dates = [(today + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(-21, 7)]
    results = {}
    lock = threading.Lock()

    def _fetch(d):
        try:
            tiles = _fetch_epg(d)
            with lock:
                results[d] = tiles
        except Exception:
            pass

    threads = [threading.Thread(target=_fetch, args=(d,)) for d in dates]
    for t in threads: t.start()
    for t in threads: t.join(timeout=20)

    all_tiles = []
    for d in dates:
        all_tiles.extend(results.get(d, []))

    _all_tiles_cache['tiles'] = all_tiles
    _all_tiles_cache['time']  = now
    return all_tiles


def _fetch_recent_epg_tiles(tile_type='catchup'):
    """
    Fetch last 7 days of EPG in parallel and return tiles filtered by type.
    tile_type: 'catchup' | 'minis' | 'all'
    Cached per type for 10 minutes.
    """
    import threading
    from datetime import date as _date, timedelta
    cache_key = f'_recent_{tile_type}'
    now = time.time()
    cached = _all_tiles_cache.get(cache_key)
    if cached and now - cached['time'] < 600:
        return cached['tiles']

    today   = _date.today()
    dates   = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
    results = {}
    lock    = threading.Lock()

    def _fetch(d):
        try:
            tiles = _fetch_epg(d)
            with lock:
                results[d] = tiles
        except Exception:
            pass

    threads = [threading.Thread(target=_fetch, args=(d,)) for d in dates]
    for t in threads: t.start()
    for t in threads: t.join(timeout=15)

    all_tiles = []
    for d in dates:
        all_tiles.extend(results.get(d, []))

    if tile_type == 'catchup':
        filtered = [t for t in all_tiles if t.get('type') == 'CatchUp' and t.get('asset_id')]
    elif tile_type == 'minis':
        filtered = [t for t in all_tiles if t.get('display_type') == 'MinisHighlights' and t.get('asset_id')]
    elif tile_type == 'highlights':
        filtered = [t for t in all_tiles if t.get('type') == 'Highlights'
                    and t.get('display_type') != 'MinisHighlights' and t.get('asset_id')]
    else:
        filtered = [t for t in all_tiles if t.get('asset_id')]

    filtered.sort(key=lambda t: t.get('start', ''), reverse=True)
    _all_tiles_cache[cache_key] = {'tiles': filtered, 'time': now}
    return filtered


@app.route('/recent_replays', methods=['GET'])
def recent_replays():
    """
    Returns tiles from the last 7 days sorted newest first.
    GET /recent_replays          → CatchUp replays only
    GET /recent_replays?type=minis → MinisHighlights only
    GET /recent_replays?type=all   → everything
    """
    tile_type = request.args.get('type', 'catchup').lower()
    try:
        tiles = _fetch_recent_epg_tiles(tile_type)
        return jsonify({'status': 'success', 'tiles': tiles, 'count': len(tiles)})
    except Exception as e:
        # Return empty success rather than 500 — same reason as /events above.
        # The plugin calls this from a background thread after stream close; 500s
        # cause Python exceptions that accumulate into a PyEval_ReleaseThread crash.
        app.logger.warning("Recent replays error (returning empty): %s", e)
        return jsonify({'status': 'success', 'tiles': [], 'count': 0})


@app.route('/sports', methods=['GET'])
def sports_list():
    """Returns available sports with tile counts, aggregated across recent+upcoming dates."""
    try:
        from collections import Counter
        tiles  = _get_all_tiles_cached()
        counts = Counter(t['sport'] for t in tiles if t.get('sport'))
        sports = [{'raw': s, 'count': c} for s, c in counts.most_common() if s]
        return jsonify({'status': 'success', 'sports': sports})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/sport_tiles', methods=['GET'])
def sport_tiles_route():
    """Returns all tiles for a given raw DAZN sport name across recent+upcoming dates."""
    raw_sport = request.args.get('sport', '')
    if not raw_sport:
        return jsonify({'error': 'sport required'}), 400
    try:
        tiles = [t for t in _get_all_tiles_cached() if t.get('sport') == raw_sport]
        return jsonify({'status': 'success', 'tiles': tiles, 'count': len(tiles)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/competition_tiles', methods=['GET'])
def competition_tiles_route():
    """
    Returns recent/upcoming tiles for a named sport, filtered from the EPG cache.
    GET /competition_tiles?sport=<dazn_sport_title>
    The sport param is the DAZN Sport.Title value (e.g. "Australian Rules Football").
    Covers past 7 days and next 2 days (same window as /sport_tiles).
    """
    sport_title = request.args.get('sport', '')
    if not sport_title:
        return jsonify({'error': 'sport required'}), 400
    try:
        all_tiles = _get_all_tiles_cached()
        tiles = [t for t in all_tiles if t.get('sport', '').lower() == sport_title.lower()]
        return jsonify({'status': 'success', 'tiles': tiles, 'count': len(tiles)})
    except Exception as e:
        print(f"Competition tiles error ({sport_title}): {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


FIXTURES_URL     = "https://epg.discovery.indazn.com/eu/v5/epgWithDatesRange"
_fixtures_cache  = {}
_FIXTURES_TTL    = 1800  # 30 min — auto-refreshes when Kayo updates their schedule


def _fetch_fixtures():
    """
    Full day schedule: today's past/live events (from daily EPG) + upcoming
    fixtures for next 6 days (from epgWithDatesRange). No duplicate asset IDs.
    Cached 30 min.
    """
    from datetime import datetime, timezone, timedelta
    now = time.time()
    if _fixtures_cache.get('ts', 0) and now - _fixtures_cache['ts'] < _FIXTURES_TTL:
        return _fixtures_cache['data']

    perth_now  = datetime.now(timezone.utc) + timedelta(hours=8)
    today_perth = perth_now.strftime('%Y-%m-%d')

    tiles      = []
    seen_ids   = set()

    # --- Part 1: today's full schedule from the daily EPG (CatchUp + Live) ---
    # This covers games that already happened today so the user can replay them.
    REPLAY_TYPES = {'CatchUp', 'Live'}
    try:
        epg_tiles = _fetch_epg(today_perth)
        for t in epg_tiles:
            if t.get('type') not in REPLAY_TYPES:
                continue
            aid = t.get('asset_id', '')
            if not aid or aid in seen_ids:
                continue
            seen_ids.add(aid)
            tiles.append({
                'asset_id':    aid,
                'title':       t.get('title', ''),
                'sport':       t.get('sport', ''),
                'competition': '',
                'start':       t.get('start', ''),
                'thumb':       t.get('thumb', ''),
                'fanart':      t.get('fanart', ''),
                'catchup':     t.get('type') == 'CatchUp',
            })
    except Exception as e:
        app.logger.warning('[fixtures] today EPG fetch failed: %s', e)

    # --- Part 2: upcoming fixtures (UpComing + Live) for today → today+6 ---
    end_perth = (perth_now + timedelta(days=6)).strftime('%Y-%m-%d')
    hdrs = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
    p    = {'country': 'au', 'languageCode': 'en', 'openBrowse': 'false',
            'timeZoneOffset': '480', 'startDate': today_perth, 'endDate': end_perth,
            'brand': 'kayo'}
    resp = requests.get(FIXTURES_URL, params=p, headers=hdrs, timeout=15)
    resp.raise_for_status()

    FIXTURE_TYPES = {'UpComing', 'Live'}
    for t in resp.json().get('Tiles', []):
        if t.get('Type') not in FIXTURE_TYPES:
            continue
        aid = t.get('AssetId', '')
        if not aid or aid in seen_ids:
            continue
        seen_ids.add(aid)
        hero = t.get('HeroImage') or {}
        img  = t.get('Image') or {}
        tiles.append({
            'asset_id':    aid,
            'title':       t.get('Title', ''),
            'sport':       (t.get('Sport') or {}).get('Title', ''),
            'competition': (t.get('Competition') or {}).get('Title', ''),
            'start':       t.get('Start', ''),
            'thumb':       _dazn_image_url(hero.get('Landscape') or img.get('Id') or ''),
            'fanart':      _dazn_image_url(hero.get('Landscape') or ''),
            'catchup':     False,
        })

    tiles.sort(key=lambda x: x['start'])
    _fixtures_cache['ts']   = now
    _fixtures_cache['data'] = tiles
    return tiles


@app.route('/fixtures', methods=['GET'])
def fixtures_route():
    """
    Upcoming fixtures for the next 14 days from the DAZN epgWithDatesRange API.
    Public endpoint — no DAZN token required. Cached 30 min; auto-refreshes.
    Returns a flat list sorted by start time. Plugin groups by date.
    """
    try:
        tiles = _fetch_fixtures()
        return jsonify({'status': 'success', 'tiles': tiles, 'count': len(tiles)})
    except Exception as e:
        app.logger.error('[fixtures] error: %s', e)
        return jsonify({'status': 'error', 'message': str(e)}), 500


SHOW_RAILS_URL      = "https://rails.discovery.indazn.com/jp/v9/rails"
SHOW_EPISODES_RAIL  = "0ef0b1f9-6dfe-4f2c-ba2d-cdf67ccf070b"
SHOW_RAILS_CACHE = {}
SHOW_RAILS_TTL   = 300  # 5 min

def _dazn_rail_headers():
    dazn_token = get_dazn_token()
    jwt = _decode_jwt_payload(dazn_token)
    viewer_id = jwt.get("viewerId", "3036fe16d324986c457250b540841a27e303d3b4")
    dazn_id   = jwt.get("user",     "auth0|69a8b6d22b11eb1bd445200b")
    return viewer_id, dazn_id, {
        "x-brand":    "kayo",
        "x-daznid":   dazn_id,
        "accept":     "application/json, text/plain, */*",
        "referer":    "https://kayosports.com.au/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    }

def _resolve_rail(rail_id, viewer_id, headers, page_params="PageType:Shows;ContentType:None", size=50):
    params = {
        "platform": "web", "id": rail_id, "viewerId": viewer_id,
        "country": "au", "brand": "kayo", "languageCode": "en",
        "params": page_params, "size": str(size),
    }
    r = requests.get(RAIL_URL, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

def _dazn_image_url(image_id, image_type="image-tile"):
    if not image_id:
        return ""
    return f"https://image.discovery.indazn.com/jp/v3/jp/none/{image_id}?imwidth=480"

@app.route('/dazn/show_rails', methods=['GET'])
def dazn_show_rails():
    """Returns DAZN show category rails (AFL Shows, NRL Shows, Latest Episodes, etc.)
    GET /dazn/show_rails"""
    now = time.time()
    cached = SHOW_RAILS_CACHE.get('rails')
    if cached and now < cached['expires']:
        return Response(cached['body'], status=200, content_type="application/json")
    try:
        viewer_id, dazn_id, headers = _dazn_rail_headers()
        # Step 1: get rail IDs
        r = requests.get(SHOW_RAILS_URL, params={
            "groupId": "shows", "country": "au",
            "userEntitlements": "tier_premium_kayo", "brand": "kayo",
        }, headers=headers, timeout=15)
        r.raise_for_status()
        rail_stubs = r.json().get("Rails", [])
        rails = []
        for stub in rail_stubs:
            rail_id = stub["Id"]
            try:
                rail = _resolve_rail(rail_id, viewer_id, headers)
                title = rail.get("Title") or ""
                tiles = rail.get("Tiles", [])
                if not title or not tiles:
                    continue
                rails.append({"id": rail_id, "title": title, "tile_count": len(tiles)})
            except Exception:
                continue
        body = _json.dumps({"rails": rails}).encode("utf-8")
        SHOW_RAILS_CACHE['rails'] = {'body': body, 'expires': now + SHOW_RAILS_TTL}
        return Response(body, status=200, content_type="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route('/dazn/show_tiles', methods=['GET'])
def dazn_show_tiles():
    """Returns tiles for a DAZN show rail.
    GET /dazn/show_tiles?rail_id=<guid>
    Tiles with nav=Show have an asset_id that is a Competition ID (show series).
    Tiles with nav=None are direct playable episodes."""
    rail_id = request.args.get('rail_id', '')
    if not rail_id:
        return jsonify({"error": "rail_id required"}), 400
    try:
        viewer_id, dazn_id, headers = _dazn_rail_headers()
        rail = _resolve_rail(rail_id, viewer_id, headers)
        tiles_out = []
        for t in rail.get("Tiles", []):
            asset_id  = t.get("AssetId", "")
            nav_to    = t.get("NavigateTo") or ""
            nav_params= t.get("NavParams") or ""
            start     = t.get("Start") or ""
            end       = t.get("End") or ""
            img       = t.get("Image") or {}
            bg        = t.get("BackgroundImage") or img
            tiles_out.append({
                "asset_id":   asset_id,
                "title":      t.get("Title", ""),
                "description":t.get("Description") or "",
                "start":      start,
                "end":        end,
                "type":       t.get("Type", ""),
                "nav_to":     nav_to,
                "nav_params": nav_params,
                "thumb":      _dazn_image_url(img.get("Id", "")),
                "fanart":     _dazn_image_url(bg.get("Id", "")),
                "playable":   nav_to != "Show",
            })
        return jsonify({"rail_id": rail_id, "title": rail.get("Title",""), "tiles": tiles_out})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route('/dazn/show_episodes', methods=['GET'])
def dazn_show_episodes():
    """Returns episodes for a DAZN show using the fixed Episodes rail with ContentId.
    GET /dazn/show_episodes?competition_id=<id>"""
    competition_id = request.args.get('competition_id', '')
    if not competition_id:
        return jsonify({"error": "competition_id required"}), 400
    try:
        viewer_id, dazn_id, headers = _dazn_rail_headers()
        page_params = f"PageType:Show;ContentType:Competition;ContentId:{competition_id}"
        rail = _resolve_rail(SHOW_EPISODES_RAIL, viewer_id, headers, page_params=page_params, size=50)
        episodes = []
        for t in rail.get("Tiles", []):
            asset_id = t.get("AssetId", "")
            if not asset_id or t.get("NavigateTo"):
                continue
            img = t.get("Image") or {}
            bg  = t.get("BackgroundImage") or img
            episodes.append({
                "asset_id":    asset_id,
                "title":       t.get("Title", ""),
                "description": t.get("Description") or "",
                "start":       t.get("Start") or "",
                "end":         t.get("End") or "",
                "thumb":       _dazn_image_url(img.get("Id", "")),
                "fanart":      _dazn_image_url(bg.get("Id", "")),
            })
        return jsonify({"competition_id": competition_id, "episodes": episodes})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route('/events', methods=['GET'])
def events():
    """Returns list of current live/upcoming events from Kayo (via DAZN Rail API)."""
    try:
        events_list = fetch_kayo_rail_schedule()
        return jsonify({'status': 'success', 'events': events_list, 'count': len(events_list)})
    except Exception as e:
        # Return empty success rather than 500.  The Kodi plugin calls this endpoint
        # from a background refresh thread immediately after every stream close.  A 500
        # response causes the plugin to throw a Python exception inside CPythonInvoker;
        # on ARM32/MT8696 (Fire TV) repeated exceptions corrupt the Python thread state,
        # ultimately causing PyEval_ReleaseThread to call abort() — crashing Kodi to the
        # Amazon home screen after ~3 channel switches.  An empty list is handled
        # gracefully by the plugin (widget shows nothing) and keeps the thread state clean.
        app.logger.warning("Rail events error (returning empty): %s", e)
        return jsonify({'status': 'success', 'events': [], 'count': 0})

@app.route('/schedule', methods=['GET'])
def schedule():
    """Legacy endpoint  -  use /events instead (powered by DAZN Rail API)."""
    return jsonify({'status': 'error', 'message': 'Use /events instead'}), 410

@app.route('/cdm', methods=['GET', 'POST'])
def cdm():
    try:
        username  = request.args.get('user', '')
        password  = request.args.get('password', '')
        challenge = request.args.get('challenge', '')
        if not username or not password:
            return jsonify({"status": "error", "message": "Credentials required"}), 400
        auth       = authenticate_kayo(username, password)
        dazn_token = get_dazn_token()
        kayo_id    = request.args.get('id', '1l47a9ir5hj0o1wi5j0pkm5fpb')
        stream     = get_stream(kayo_id, auth["profile_id"])
        la_url     = stream["la_url"]
        headers = {
            "Authorization": f"Bearer {dazn_token}",
            "Content-Type":  "application/octet-stream",
            "Origin":        "https://kayosports.com.au",
            "Referer":       "https://kayosports.com.au/",
            "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        }
        import base64
        challenge_bytes = base64.b64decode(challenge) if challenge else b''
        r = curl_requests.post(la_url, data=challenge_bytes, headers=headers, timeout=15, impersonate="safari17_0")
        print(f"License response: {r.status_code}")
        if r.status_code != 200:
            return jsonify({"status": "error", "message": f"License error: {r.status_code}"}), 500
        license_b64 = base64.b64encode(r.content).decode()
        return jsonify({"status": "success", "license": license_b64})
    except Exception as e:
        print(f"CDM error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/license', methods=['GET', 'POST'])
def license_proxy():
    """Proxy Widevine license requests to DAZN license server with auth."""
    try:
        asset_id   = request.args.get('id', '1l47a9ir5hj0o1wi5j0pkm5fpb')
        dazn_token = get_dazn_token()
        profile_id = _profile_id_from_dazn_jwt()
        if not profile_id:
            return jsonify({"status": "error", "message": "Cannot determine profile_id from DAZN token"}), 500
        stream     = get_stream(asset_id, profile_id)
        la_url     = stream["la_url"]
        challenge  = request.get_data()
        headers = {
            "Authorization": f"Bearer {dazn_token}",
            "Content-Type":  "application/octet-stream",
            "Origin":        "https://kayosports.com.au",
            "Referer":       "https://kayosports.com.au/",
            "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        }
        print(f"License proxy for asset: {asset_id}, challenge size: {len(challenge)}")
        r = curl_requests.post(la_url, data=challenge, headers=headers, timeout=15, impersonate="safari17_0")
        print(f"License response: {r.status_code}")
        return Response(r.content, status=r.status_code, content_type='application/octet-stream')
    except Exception as e:
        print(f"License proxy error: {e}")
        return str(e), 500

@app.route('/dazn_token', methods=['GET'])
def dazn_token_endpoint():
    """Returns the current fresh DAZN token."""
    try:
        token = get_dazn_token()
        return jsonify({"status": "success", "token": token})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/token_debug', methods=['GET'])
def token_debug():
    """
    Dump the raw DAZN Playback API response for a single asset using the
    current production params.  ONE request only  -  never hammers DAZN.

    GET /token_debug?id=ASSET_ID
    """
    asset_id = request.args.get('id', '').strip()
    if not asset_id:
        return jsonify({"error": "id required"}), 400

    bearer = get_dazn_token()
    try:
        import base64 as _b64
        _pad = bearer.split('.')[1]
        _pad += '=' * (-len(_pad) % 4)
        _claims = _json.loads(_b64.urlsafe_b64decode(_pad))
        profile_id = _claims.get('profileId') or _claims.get('viewerId')
    except Exception:
        profile_id = _profile_id_from_dazn_jwt()

    session_id = f"{int(time.time()*1000)}-{profile_id}-{asset_id}-{rand_hex(6)}"
    params = {
        "AppVersion":         "2.10.1",
        "DrmType":            "WIDEVINE",
        "Format":             "MPEG-DASH",
        "PlayReadyInitiator": "false",
        "AssetId":            asset_id,
        "MtaLanguageCode":    "",
        "LanguageCode":       "en",
        "SessionId":          session_id,
        "PlayerId":     "@dazn/peng-androidtv-core/androidtv/androidtv-rxplayer",
        "Platform":     "androidtv",
        "Model":        "AFTKA",
        "Manufacturer": "Amazon",
        "Secure":       "true",
        "Capabilities": "mta,4k,uhd,hdr,hevc",
    }
    body = {}
    headers = {
        "Authorization":  f"Bearer {bearer}",
        "Content-Type":   "application/json; charset=UTF-8",
        "User-Agent":     "Dalvik/2.1.0 (Linux; U; Android 9; AFTKA Build/PS7267.2877N)",
        "X-Correlation-Id": str(uuid.uuid4()),
        "X-Dazn-Device":  GUID,
        "Accept":         "application/json",
        "Accept-Language": "en-AU,en;q=0.9",
    }
    try:
        r = curl_requests.post(
            DAZN_PLAY_URL, params=params, json=body, headers=headers,
            timeout=20, impersonate="safari17_0",
        )
        data = r.json() if r.status_code == 200 else {"error": r.text[:500]}
        details = data.get("PlaybackDetails", [])
        return jsonify({
            "asset_id":    asset_id,
            "profile_id":  profile_id,
            "status":      r.status_code,
            "resolutions": [d.get("Resolution", "") for d in details],
            "vdr":         [d.get("VideoDynamicRange", "") for d in details],
            "cdn_names":   [d.get("CdnName", "") for d in details],
            "manifest_urls": [d.get("ManifestUrl", "") for d in details],
            "full_response": data,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  SLATE SEGMENT ROUTE  -  /slate/<filename>
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.route("/slate/<path:filename>", methods=["GET"])
def serve_slate(filename):
    """
    Serve pre-generated slate DASH segments with automatic looping.

    Segment files are named  seg_0_N.m4s  (video) and  seg_1_N.m4s  (audio).
    Any segment number N is accepted and wrapped into the available range so
    O11V4 can request arbitrarily large numbers and always receives a valid file.

    Example: if there are 15 segments and O11V4 requests seg_0_47.m4s,
    it receives seg_0_2.m4s  ((47-1) % 15 + 1 = 2).

    Init segments (init_0.mp4, init_1.mp4) are served as-is.
    """
    _ensure_slate_loaded()

    # Match  seg_<rep>_<number>.m4s   -  everything else served by name
    m = re.match(r"^(seg_\d+_)(\d+)(\.m4s)$", filename)
    if m:
        prefix  = m.group(1)        # e.g. "seg_0_"
        seg_num = int(m.group(2))
        suffix  = m.group(3)        # ".m4s"
        count   = _slate_segment_count or 15
        wrapped = ((seg_num - 1) % count) + 1
        actual  = f"{prefix}{wrapped}{suffix}"
    else:
        actual = filename

    filepath = os.path.join(SLATE_DIR, actual)
    if not os.path.exists(filepath):
        app.logger.warning("[slate] File not found: %s (requested: %s)", actual, filename)
        return f"Slate file not found: {actual}", 404

    with open(filepath, "rb") as fh:
        data = fh.read()

    ct = "video/mp4" if filename.endswith((".mp4", ".m4s")) else "application/octet-stream"
    return Response(data, content_type=ct, headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control":               "no-cache",
    })


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  SLATE STATUS  -  /slate_status
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.route("/slate_manifest", methods=["GET"])
def slate_manifest():
    """
    Dynamic DASH manifest for the slate stream.  Kodi plays this as a real
    ISA stream (no DRM) during ad breaks instead of showing an overlay.

    Segment numbers are wall-clock-based so ISA always has a live segment
    to request.  The /slate/<filename> endpoint wraps any number back into the
    available file range so it loops forever.
    """
    _ensure_slate_loaded()
    if _slate_period_xml is None:
        return "Slate segments not available — run generate_slate.py", 503

    SEG_DUR_S  = 2.0
    timescale  = 1000000
    seg_dur_ts = int(SEG_DUR_S * timescale)

    # Fixed epoch: availability start = 2020-01-01T00:00:00Z (unix 1577836800)
    EPOCH = 1577836800.0
    AVAIL = "2020-01-01T00:00:00Z"
    current_seg = int((time.time() - EPOCH) / SEG_DUR_S) + 1

    base = RELAY_BASE_URL
    mpd = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"'
        ' type="dynamic"'
        f' availabilityStartTime="{AVAIL}"'
        ' minimumUpdatePeriod="PT2S"'
        ' minBufferTime="PT4S"'
        ' timeShiftBufferDepth="PT60S"'
        ' suggestedPresentationDelay="PT4S"'
        ' profiles="urn:mpeg:dash:profile:isoff-live:2011">\n'
        '  <Period id="slate" start="PT0S">\n'
        '    <AdaptationSet id="0" contentType="video" startWithSAP="1"'
        ' segmentAlignment="true" bitstreamSwitching="true"'
        ' frameRate="25/1" maxWidth="1280" maxHeight="720" par="16:9">\n'
        '      <Representation id="0" mimeType="video/mp4" codecs="avc1.640029"'
        ' bandwidth="500000" width="1280" height="720" sar="1:1">\n'
        f'        <SegmentTemplate timescale="{timescale}" duration="{seg_dur_ts}"'
        f' initialization="{base}/slate/init_0.mp4"'
        f' media="{base}/slate/seg_0_$Number$.m4s"'
        f' startNumber="{current_seg - 30}"/>\n'
        '      </Representation>\n'
        '    </AdaptationSet>\n'
        '    <AdaptationSet id="1" contentType="audio" startWithSAP="1"'
        ' segmentAlignment="true" bitstreamSwitching="true">\n'
        '      <Representation id="1" mimeType="audio/mp4" codecs="mp4a.40.2"'
        ' bandwidth="64000" audioSamplingRate="48000">\n'
        '        <AudioChannelConfiguration'
        ' schemeIdUri="urn:mpeg:dash:23003:3:audio_channel_configuration:2011" value="2"/>\n'
        f'        <SegmentTemplate timescale="{timescale}" duration="{seg_dur_ts}"'
        f' initialization="{base}/slate/init_1.mp4"'
        f' media="{base}/slate/seg_1_$Number$.m4s"'
        f' startNumber="{current_seg - 30}"/>\n'
        '      </Representation>\n'
        '    </AdaptationSet>\n'
        '  </Period>\n'
        '</MPD>\n'
    )
    app.logger.info("[slate_manifest] serving dynamic manifest, current_seg=%d", current_seg)
    return Response(mpd.encode("utf-8"), mimetype="application/dash+xml", headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache, no-store, must-revalidate",
    })


@app.route("/slate_status", methods=["GET"])
def slate_status():
    """
    Quick check on slate feature health and currently active ad breaks.

    curl http://localhost:5001/slate_status
    """
    _ensure_slate_loaded()
    with _ad_state_lock:
        active_breaks = {
            aid: {
                "period_start":    v["period_start"],
                "seconds_elapsed": int(time.time() - v["since"]),
            }
            for aid, v in _ad_state.items()
        }
    return jsonify({
        "slate_enabled":    _slate_period_xml is not None,
        "slate_dir":        SLATE_DIR,
        "slate_segments":   _slate_segment_count,
        "relay_base_url":   RELAY_BASE_URL,
        "active_ad_breaks": active_breaks,
        "mode":             "stateful_slate" if _slate_period_xml is not None else "merge_fallback",
    })


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  MANIFEST PROXY  -  /mpd
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

# Per-asset manifest URL cache.
# Avoids calling the DAZN Playback API on every 2.23-second manifest refresh.
# Cache entries expire after 50 minutes; the hourly pod restart clears state anyway.
_mpd_url_cache = {}

# Per-asset stream cache shared across ALL clients (Kodi, O11V4, etc.).
# All clients requesting the same asset_id reuse the same DAZN playback session,
# making them appear as a single stream to DAZN regardless of how many viewers.
# TTL matches _mpd_url_cache (50 min). Guarded by a lock for thread safety.
_stream_cache      = {}
_stream_cache_lock = threading.Lock()
_STREAM_CACHE_TTL  = 3000  # 50 minutes

# Persistent HTTPS session for CDN segment proxying.
# Reuses TCP+TLS connections across segment requests, eliminating the
# ~100ms handshake overhead that causes per-segment buffering glitches.
_cdn_session = requests.Session()
_cdn_adapter = requests.adapters.HTTPAdapter(
    pool_connections=4,   # CDN usually resolves to 1-2 distinct hosts
    pool_maxsize=20,      # max concurrent connections per host
    max_retries=0,
)
_cdn_session.mount("https://", _cdn_adapter)
_cdn_session.mount("http://",  _cdn_adapter)

# 4K linear channel upgrade: maps linear asset_id → channel_id (provider string).
# When the plugin requests one of these, the relay checks the Rail API for a live
# 4K event on that channel and substitutes the event asset_id so ISA gets UHD quality.
# Falls back to the linear asset (FHD) when no live 4K event is found.
_LINEAR_4K_ASSET_TO_CHANNEL = {
    'jo74ryszmcvd1pzmbzp50q84a':   'fsa501',  # Fox Cricket 4K
    '1tc0mhfzkbbti165v1rsuewtek':  'fsa502',  # Fox League 4K
    'xjauo23ins1b1hnss5covnvxw':   'fsa503',  # Fox Sports 503 4K
    '1l47a9ir5hj0o1wi5j0pkm5fpb':  'fsa504',  # Fox Footy 4K
    '12555dnxvg0f319t9w1tgjdvid':  'fsa505',  # Fox Sports 505 4K
    '231pfo674jx615m2uo32ahsex':   'fsa506',  # Fox Sports 506 4K
}
_4k_rail_cache      = {'events': [], 'expiry': 0}
_4k_rail_cache_lock = threading.Lock()
_4K_UPGRADE_CACHE_TTL = 600  # 10 min — shorter than normal stream cache to limit stale event sessions


def _get_stream_cached(asset_id, quality='4k'):
    """
    Return a cached stream URL entry for the given asset_id.
    Checks _stream_cache (shared with /token route) first, then calls
    get_stream() directly  -  no HTTP self-call to avoid port mismatch issues.
    quality='fhd' requests FHD H.264 capabilities; '4k' requests 4K HEVC.
    """
    force_fhd    = (quality == 'fhd')
    capabilities = "mta" if force_fhd else "mta,4k,uhd,hdr,hevc"
    cache_key    = ('fhd:' + asset_id) if force_fhd else asset_id

    entry = _mpd_url_cache.get(cache_key)
    if entry and time.time() < entry["expiry"]:
        return entry

    # Reuse session already obtained by /token if available
    with _stream_cache_lock:
        sc = _stream_cache.get(cache_key)
    if sc and time.time() < sc["expiry"]:
        d            = sc["response"]
        manifest_url = d["url"]
        cdn_name     = d.get("cdn_name", "")
        cdn_val      = d.get("cdn_val", "")
        app.logger.info(f"[mpd_proxy] reusing /token session for {cache_key}")
    else:
        # No cached session  -  call get_stream() directly (no HTTP hop)
        app.logger.info(f"[mpd_proxy] cache miss for {cache_key}  -  calling get_stream() directly")
        import base64 as _b64
        dazn_tok = get_dazn_token()
        try:
            _pad = dazn_tok.split('.')[1]
            _pad += '=' * (-len(_pad) % 4)
            _claims = _json.loads(_b64.urlsafe_b64decode(_pad))
            profile_id = _claims.get('profileId') or _claims.get('viewerId')
        except Exception:
            profile_id = None
        if not profile_id:
            profile_id = _profile_id_from_dazn_jwt()
        if not profile_id:
            raise Exception('Cannot determine profile_id from DAZN token')

        try:
            stream = get_stream(asset_id, profile_id, capabilities=capabilities)
        except Exception as _e:
            _es = str(_e)
            if '401' in _es or '403' in _es or 'authoris' in _es.lower():
                app.logger.warning(
                    "[mpd_proxy] DAZN auth error for %s (%s)  -  force-expiring JWT and retrying",
                    cache_key, _es[:80],
                )
                dazn_state["expiry"] = 0  # triggers immediate JWT refresh in get_dazn_token()
                stream = get_stream(asset_id, profile_id, capabilities=capabilities)
            else:
                raise
        cdn      = stream["cdn_token"]
        cdn_name = cdn.split("=", 1)[0] if "=" in cdn else ""
        cdn_val  = cdn.split("=", 1)[1] if "=" in cdn else ""
        manifest_url = stream["url"]

        # Populate _stream_cache so /token fast-paths on the next request
        resp_dict = {
            "status": "success", "url": manifest_url,
            "cdn_token": cdn, "cdn_name": cdn_name, "cdn_val": cdn_val,
            "license_url": stream.get("la_url", ""), "dazn_token": dazn_tok,
        }
        now = time.time()
        with _stream_cache_lock:
            _stream_cache[cache_key] = {"response": resp_dict, "expiry": now + _STREAM_CACHE_TTL}

    # Derive the BaseURL (directory prefix) from the manifest URL
    parsed   = urlparse(manifest_url)
    path_dir = parsed.path.rsplit("/", 1)[0] + "/"
    base_url = f"{parsed.scheme}://{parsed.netloc}{path_dir}"

    entry = {
        "manifest_url": manifest_url,
        "cdn_name":     cdn_name,
        "cdn_val":      cdn_val,
        "base_url":     base_url,
        "expiry":       time.time() + 3000,
    }
    _mpd_url_cache[cache_key] = entry
    return entry


def _ad_watcher(asset_id):
    """
    Background thread that polls the raw DAZN manifest every 1 second while an
    ad break is active and clears _ad_state[asset_id] the instant the break ends.
    This gives sub-second ad break end detection instead of waiting up to
    minimumUpdatePeriod (6 s) for O11V4 to trigger the next proxy manifest fetch.
    """
    DASH_NS              = "urn:mpeg:dash:schema:mpd:2011"
    SCTE35_NS            = "urn:scte:scte35:2013:xml"
    period_tag           = f"{{{DASH_NS}}}Period"
    event_stream_tag     = f"{{{DASH_NS}}}EventStream"
    adapt_set_tag        = f"{{{DASH_NS}}}AdaptationSet"
    content_prot_tag     = f"{{{DASH_NS}}}ContentProtection"
    splice_insert_tag    = f"{{{SCTE35_NS}}}SpliceInsert"
    segment_template_tag = f"{{{DASH_NS}}}SegmentTemplate"

    while True:
        # Stop if break state was cleared by process_mpd or cache_clear
        with _ad_state_lock:
            if asset_id not in _ad_state:
                break

        # Fetch raw manifest URL + CDN cookie from cache
        entry = _mpd_url_cache.get(asset_id) or _mpd_url_cache.get('fhd:' + asset_id)
        if not entry:
            time.sleep(1)
            continue

        manifest_url = entry.get("manifest_url")
        cdn_name     = entry.get("cdn_name")
        cdn_val      = entry.get("cdn_val")
        if not manifest_url:
            time.sleep(1)
            continue

        try:
            cookies = {cdn_name: cdn_val} if cdn_name and cdn_val else {}
            resp = requests.get(manifest_url, cookies=cookies, timeout=5)
            if resp.status_code != 200:
                time.sleep(1)
                continue
            mpd_text = resp.text
        except Exception:
            time.sleep(1)
            continue

        # Classify periods using same logic as process_mpd
        try:
            root        = ET.fromstring(mpd_text)
            all_periods = root.findall(period_tag)

            manifest_has_drm = any(
                len(adap.findall(content_prot_tag)) > 0
                for p in all_periods
                for adap in p.findall(adapt_set_tag)
            )

            classified = []
            for p in all_periods:
                is_ad, method = _is_ad_period(
                    p, event_stream_tag, adapt_set_tag,
                    content_prot_tag, splice_insert_tag, manifest_has_drm,
                    segment_template_tag=segment_template_tag,
                )
                classified.append((p, is_ad, method))

            # Post-game filler reclassification (same as process_mpd)
            last_drm_idx = -1
            for i, (p, is_ad, method) in enumerate(classified):
                if not is_ad:
                    has_drm = any(
                        len(adap.findall(content_prot_tag)) > 0
                        for adap in p.findall(adapt_set_tag)
                    )
                    if has_drm:
                        last_drm_idx = i
            classified = [
                (p, False, None)
                if (is_ad and method == "no_content_protection" and i > last_drm_idx)
                else (p, is_ad, method)
                for i, (p, is_ad, method) in enumerate(classified)
            ]

            any_ads             = any(is_ad for _, is_ad, _ in classified)
            drm_content_visible = any(
                len(adap.findall(content_prot_tag)) > 0
                for p, is_ad, _ in classified
                for adap in p.findall(adapt_set_tag)
                if not is_ad
            )
            any_content_visible = any(not is_ad for _, is_ad, _ in classified)
            content_returned    = drm_content_visible or (
                not manifest_has_drm and any_content_visible
            )

            if not any_ads and content_returned:
                with _ad_state_lock:
                    state = _ad_state.pop(asset_id, None)
                    _ad_state_merge.pop(asset_id, None)
                if state is not None:
                    elapsed = time.time() - state["since"]
                    app.logger.info(
                        "[ad_watcher] [%s] Ad break ENDED after %.1fs  -  watcher cleared state instantly",
                        asset_id, elapsed,
                    )
                break
        except Exception:
            pass

        time.sleep(1)

    # Clean up thread registry
    with _ad_watch_threads_lock:
        _ad_watch_threads.pop(asset_id, None)


def _start_ad_watcher(asset_id):
    """Spawn a background watcher thread for asset_id if one isn't already running."""
    with _ad_watch_threads_lock:
        if asset_id in _ad_watch_threads:
            return
        t = threading.Thread(target=_ad_watcher, args=(asset_id,), daemon=True,
                             name=f"ad-watcher-{asset_id}")
        _ad_watch_threads[asset_id] = t
        t.start()
        app.logger.info("[ad_watcher] [%s] Watcher thread started", asset_id)


def _is_ad_period(period, event_stream_tag, adapt_set_tag,
                  content_prot_tag, splice_insert_tag, manifest_has_drm,
                  segment_template_tag=None):
    """
    Return (is_ad, method_name) for a single DASH Period element.

    Detection methods (tried in order):
      1. SCTE-35 inline XML - SpliceInsert[@outOfNetworkIndicator='true']
      2. SCTE-35 EventStream - any schemeIdUri containing 'scte35' with
         outOfNetworkIndicator='true' on any descendant (covers binary SCTE-35)
      3. No ContentProtection - ONLY used when the manifest also contains at
         least one DRM-protected period (i.e. a live game is in progress).
         During non-live hours every period is unencrypted filler content, so
         absence of DRM is NOT a reliable ad signal then.  When a live game IS
         on, Kayo/DAZN encrypts all real content with Widevine while SSAI ad
         insertions remain clear - making no-DRM a reliable ad indicator.
      4. DAZN asset-segment naming - DAZN SSAI names pre-packaged ad segments
         with an asset- prefix (e.g. asset-1800_000000001.mp4).
         Live game segments use CDN-routed URLs without this prefix.  Works for
         unencrypted linear channels (e.g. ESPN) where Method 3 is disabled.
    """
    # Method 1 - inline SCTE-35 SpliceInsert
    for elem in period.iter():
        if elem.tag == splice_insert_tag and elem.get("outOfNetworkIndicator") == "true":
            return True, "scte35_splice_insert"

    # Method 2 - any SCTE-35 EventStream
    for es in period.findall(event_stream_tag):
        if "scte35" in es.get("schemeIdUri", "").lower():
            for elem in es.iter():
                if elem.get("outOfNetworkIndicator") == "true":
                    return True, "scte35_event_stream"

    # Method 3 - no ContentProtection (only active during live games)
    if manifest_has_drm:
        adapt_sets = period.findall(adapt_set_tag)
        if adapt_sets:
            has_drm = any(len(adap.findall(content_prot_tag)) > 0 for adap in adapt_sets)
            if not has_drm:
                return True, "no_content_protection"

    # Method 4 - DAZN asset-segment naming convention
    if segment_template_tag:
        for seg in period.iter(segment_template_tag):
            media = seg.get("media", "")
            if media.lower().startswith("asset-"):
                return True, "dazn_asset_segment"

    return False, None


def process_mpd(mpd_text, base_url, asset_id):
    """
    Parse a live DASH MPD and process ad breaks for O11V4 delivery.

    â"€â"€ MODE 1: STATEFUL SLATE (when C:\\kayo\\slate\\slate.mpd exists) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    On the first poll where an ad break is detected:
      â€¢ Record the first ad period's 'start' attribute as the anchor.
      â€¢ Replace ALL ad periods with a single synthetic "slate-break" Period
        whose segments are served locally from this relay (never expire).
      â€¢ The Period ID is always "slate-break"  -  O11V4 sees no ID change across
        polls â†' ZERO reinits during the entire ad break.
      â€¢ Only 2 reinits per break total: one entering (contentâ†'slate codec change)
        and one exiting (slateâ†'content codec + DRM change).

    On subsequent polls while DRM content is absent:
      â€¢ Inject the same locked slate Period again (same ID, same start attr).

    When DRM content returns:
      â€¢ Clear the per-asset state. O11V4 does its normal single reinit back to
        encrypted live content.

    â"€â"€ MODE 2: MERGE FALLBACK (when slate is not set up) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    Consecutive ad Periods are collapsed into one (keep first, drop the rest).
    This was the previous behaviour. O11V4 sees at most 2 reinits per break,
    but the kept ad period's CDN segments age out after a few seconds, so this
    only partially mitigates the crash.

    â"€â"€ Always: inject <BaseURL> â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    The DAZN CDN segment URLs are relative; the injected BaseURL makes them
    resolvable by O11V4 regardless of which DASH period is playing.
    """
    # Register all namespace prefixes so they survive ET serialisation
    for _evt, (prefix, uri) in ET.iterparse(io.StringIO(mpd_text), events=["start-ns"]):
        ET.register_namespace(prefix, uri)

    root = ET.fromstring(mpd_text)

    DASH_NS               = "urn:mpeg:dash:schema:mpd:2011"
    SCTE35_NS             = "urn:scte:scte35:2013:xml"
    period_tag            = f"{{{DASH_NS}}}Period"
    base_url_tag          = f"{{{DASH_NS}}}BaseURL"
    event_stream_tag      = f"{{{DASH_NS}}}EventStream"
    adapt_set_tag         = f"{{{DASH_NS}}}AdaptationSet"
    content_prot_tag      = f"{{{DASH_NS}}}ContentProtection"
    splice_insert_tag     = f"{{{SCTE35_NS}}}SpliceInsert"
    segment_template_tag  = f"{{{DASH_NS}}}SegmentTemplate"

    # Strip <Location> so O11V4 never redirects manifest polls away from our proxy.
    # DAZN includes a Location element pointing back to the raw CDN URL; if O11V4
    # follows it, all subsequent polls bypass this relay and hit DAZN directly,
    # defeating the ad-break handling entirely.
    location_tag = f"{{{DASH_NS}}}Location"
    for loc in root.findall(location_tag):
        root.remove(loc)
        app.logger.info("[mpd_proxy] [%s] Stripped <Location> redirect", asset_id)

    all_periods = root.findall(period_tag)

    # Does ANY period in this manifest have DRM?  If yes we're in a live-game
    # context and can use absence-of-DRM as an ad signal (Method 3).
    manifest_has_drm = any(
        len(adap.findall(content_prot_tag)) > 0
        for p in all_periods
        for adap in p.findall(adapt_set_tag)
    )
    app.logger.info(
        "[mpd_proxy] [%s] manifest_has_drm=%s  -  %s",
        asset_id, manifest_has_drm,
        "Method 3 active (live game)" if manifest_has_drm else "Method 3 disabled (non-live)",
    )

    # Classify every period
    classified = []  # [(period_elem, is_ad, method_str)]
    for p in all_periods:
        is_ad, method = _is_ad_period(
            p, event_stream_tag, adapt_set_tag,
            content_prot_tag, splice_insert_tag, manifest_has_drm,
            segment_template_tag=segment_template_tag,
        )
        classified.append((p, is_ad, method))

    any_ads = any(is_ad for _, is_ad, _ in classified)

    # Post-process: unclassify Method-3-only detections that trail all DRM content.
    # A period with no ContentProtection that sits AFTER the last DRM period in the
    # manifest is post-game filler, not an SSAI ad insertion. Only SCTE-35 evidence
    # (Methods 1 & 2) is trusted for trailing periods.
    last_drm_idx = -1
    for i, (p, is_ad, method) in enumerate(classified):
        if not is_ad:
            has_drm = any(
                len(adap.findall(content_prot_tag)) > 0
                for adap in p.findall(adapt_set_tag)
            )
            if has_drm:
                last_drm_idx = i
    reclassified = []
    for i, (p, is_ad, method) in enumerate(classified):
        if is_ad and method == "no_content_protection" and i > last_drm_idx:
            app.logger.info(
                "[mpd_proxy] [%s] period idx=%d reclassified: post-game filler (no DRM period follows)",
                asset_id, i,
            )
            reclassified.append((p, False, None))
        else:
            reclassified.append((p, is_ad, method))
    classified = reclassified
    any_ads = any(is_ad for _, is_ad, _ in classified)

    # â"€â"€ Decide mode â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    _ensure_slate_loaded()

    if _slate_period_xml is not None:
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        #  MODE 1  -  STATEFUL SLATE
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        #
        # WHY THE STATE LOGIC IS CAREFUL ABOUT CLEARING:
        #
        # DAZN's live manifest has a sliding window. As an ad break progresses,
        # the last DRM-protected content period scrolls out of the window,
        # leaving ONLY ad periods visible. At that point manifest_has_drm=False,
        # which disables Method 3 (no-DRM detection). Methods 1 & 2 (SCTE-35)
        # may also be absent. Result: _is_ad_period() returns False for every
        # period and any_ads=False  -  even though ads are still playing.
        #
        # WRONG approach: clear state when any_ads=False  <- previous bug
        # WRONG approach v2: clear state when drm_content_visible=True <- new bug
        #   DAZN often serves content periods alongside current ad sub-periods
        #   (e.g. 7575850_1..9 + 7575938), so drm_content_visible fires mid-break
        #   and drops state  -  the tiny sub-periods then pass raw and crash O11V4.
        # CORRECT approach: clear state only when BOTH conditions are met:
        #   1. No ad periods visible at all (any_ads=False)
        #   2. At least one DRM content period is visible (genuine live return)
        # Also: if state is held and a NEW ad break starts (different start time
        #   than the locked period), update the locked position so the slate is
        #   injected at the correct point in the timeline.
        with _ad_state_lock:
            state = _ad_state.get(asset_id)

            if state is None:
                # Not in an ad break. Check if one is starting.
                if any_ads:
                    first_ad     = next(p for p, is_ad, _ in classified if is_ad)
                    period_start = first_ad.get("start", "PT0S")
                    state = {"period_start": period_start, "since": time.time()}
                    _ad_state[asset_id] = state
                    app.logger.info(
                        "[mpd_proxy] [%s] Ad break STARTED  -  slate locked at start=%s",
                        asset_id, period_start,
                    )
                    _start_ad_watcher(asset_id)
            else:
                drm_content_visible = any(
                    len(adap.findall(content_prot_tag)) > 0
                    for p, is_ad, _ in classified
                    for adap in p.findall(adapt_set_tag)
                    if not is_ad
                )
                # For non-DRM streams (e.g. Fox Footy — DRM at Representation level,
                # not AdaptationSet level) drm_content_visible is always False, so the
                # normal clearing condition never fires and the slate gets permanently
                # stuck after every ad break.  Fix: for non-DRM streams, trust the
                # absence of ad signals alone — if there are content periods visible
                # and no ad signals, the break has ended.
                any_content_visible = any(not is_ad for _, is_ad, _ in classified)
                content_returned = drm_content_visible or (
                    not manifest_has_drm and any_content_visible
                )
                if not any_ads and content_returned:
                    # All ad periods gone AND content is back â†' break truly ended
                    elapsed = time.time() - state["since"]
                    _ad_state.pop(asset_id, None)
                    app.logger.info(
                        "[mpd_proxy] [%s] Ad break ENDED after %.1fs  -  no ads + content visible (drm=%s)",
                        asset_id, elapsed, drm_content_visible,
                    )
                    state = None
                elif any_ads:
                    # Still in an ad break. If the first ad period's start has
                    # shifted (new ad break after state was set from an old one),
                    # update the locked position so the slate lands at the right spot.
                    first_ad = next(p for p, is_ad, _ in classified if is_ad)
                    current_start = first_ad.get("start", "PT0S")
                    if current_start != state["period_start"]:
                        state["period_start"] = current_start
                        state["since"] = time.time()
                        _ad_state[asset_id] = state
                        app.logger.info(
                            "[mpd_proxy] [%s] Ad break SHIFTED  -  re-locking slate at start=%s",
                            asset_id, current_start,
                        )
                    else:
                        app.logger.debug(
                            "[mpd_proxy] [%s] Ad break ongoing (%.1fs)  -  holding slate at %s",
                            asset_id, time.time() - state["since"], state["period_start"],
                        )
                else:
                    # any_ads=False but drm_content_visible=False  -  detection
                    # is unreliable (content scrolled out of live window mid-break).
                    # Hold state, but force-clear after MAX_AD_STATE_SECONDS to prevent
                    # permanent slate when a game ends or the stream hiccups.
                    elapsed = time.time() - state["since"]
                    if elapsed > MAX_AD_STATE_SECONDS:
                        _ad_state.pop(asset_id, None)
                        app.logger.info(
                            "[mpd_proxy] [%s] Ad break TIMEOUT after %.1fs  -  force clearing stale state",
                            asset_id, elapsed,
                        )
                        state = None
                    else:
                        app.logger.debug(
                            "[mpd_proxy] [%s] Ad break ambiguous (%.1fs)  -  holding slate (no ads detected, no DRM visible)",
                            asset_id, elapsed,
                        )

        if state:
            # Find where the first ad period sits among root's direct children
            root_children = list(root)
            first_ad_elem = next(p for p, is_ad, _ in classified if is_ad)
            try:
                insert_idx = root_children.index(first_ad_elem)
            except ValueError:
                insert_idx = len(root_children)

            # Remove every ad period from the manifest
            for p, is_ad, _ in classified:
                if is_ad:
                    root.remove(p)

            # Insert the stable slate period at the vacated position
            slate_p = _get_slate_period(state["period_start"])
            if slate_p is not None:
                root.insert(insert_idx, slate_p)
                app.logger.info(
                    "[mpd_proxy] [%s] Slate period injected (start=%s, %ds into break)",
                    asset_id, state["period_start"], int(time.time() - state["since"]),
                )

            # Reduce minimumUpdatePeriod so O11V4 polls every 2s during the break
            # (default is PT6S). Combined with the background watcher clearing state
            # within ~1s, this gives ≤3s total latency from break end to content.
            root.set("minimumUpdatePeriod", "PT2S")

    else:
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        #  MODE 2  -  STATEFUL MERGE (no slate files available)
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        # Lock the FIRST ad period seen and return it unchanged on every
        # subsequent poll. O11V4 sees the same Period ID throughout the ad
        # break â†' zero period-change reinits. The locked period's CDN segments
        # will 404 once the live window advances past them (~60-90s), triggering
        # a single reinit  -  far better than reiniting every 10-15s.
        # Clear state only when BOTH: no ads visible AND DRM content visible.
        # Same fix as MODE 1  -  drm_content_visible alone fires mid-break when
        # DAZN shows a future content period alongside current ad sub-periods.
        with _ad_state_lock:
            merge_state = _ad_state_merge.get(asset_id)

            drm_content_visible = any(
                len(adap.findall(content_prot_tag)) > 0
                for p, is_ad, _ in classified
                for adap in p.findall(adapt_set_tag)
                if not is_ad
            )
            any_content_visible = any(not is_ad for _, is_ad, _ in classified)
            content_returned = drm_content_visible or (
                not manifest_has_drm and any_content_visible
            )

            if merge_state is None:
                if any_ads:
                    import copy
                    first_ad = next(p for p, is_ad, _ in classified if is_ad)
                    merge_state = {
                        "locked_period": copy.deepcopy(first_ad),
                        "since":         time.time(),
                    }
                    _ad_state_merge[asset_id] = merge_state
                    app.logger.info(
                        "[mpd_proxy] [%s] Merge ad break STARTED  -  period id=%s locked",
                        asset_id, first_ad.get("id", "?"),
                    )
            else:
                if not any_ads and content_returned:
                    elapsed = time.time() - merge_state["since"]
                    _ad_state_merge.pop(asset_id, None)
                    app.logger.info(
                        "[mpd_proxy] [%s] Merge ad break ENDED after %.1fs  -  no ads + content visible (drm=%s)",
                        asset_id, elapsed, drm_content_visible,
                    )
                    merge_state = None
                else:
                    elapsed = time.time() - merge_state["since"]
                    if elapsed > MAX_AD_STATE_SECONDS:
                        _ad_state_merge.pop(asset_id, None)
                        app.logger.info(
                            "[mpd_proxy] [%s] Merge ad break TIMEOUT after %.1fs  -  force clearing stale state",
                            asset_id, elapsed,
                        )
                        merge_state = None
                    else:
                        app.logger.debug(
                            "[mpd_proxy] [%s] Merge ad break ongoing (%.1fs)  -  holding locked period",
                            asset_id, elapsed,
                        )

        if merge_state is not None:
            # Remove all current periods, inject the locked one
            for p in all_periods:
                root.remove(p)
            import copy
            root.append(copy.deepcopy(merge_state["locked_period"]))
            app.logger.info(
                "[mpd_proxy] [%s] Merge: locked period re-injected (%ds into break)",
                asset_id, int(time.time() - merge_state["since"]),
            )

    # â"€â"€ Always inject BaseURL â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    # The raw DAZN manifest has a root-relative BaseURL like /out/v1/ABC/DEF/
    # We route all CDN segment fetches through mpd_proxy â†' relay so O11V4 on
    # the Finnish VPS never touches the Australian CDN directly (geo-throttled).
    # PLUS absolute Period-level BaseURLs at /v1/dashsegment/... that redirect
    # to /tm/... paths which return 403 from non-AU IPs.
    #
    # Strategy:
    #   1. Read the root-level BaseURL (root-relative) and make it absolute.
    #      Correct:  https://cdn.host/out/v1/ABC/DEF/   â†' HTTP 200 âœ"
    #      Wrong:    https://cdn.host/v1/dash/HASH/.../out/v1/...  â†' HTTP 400 âœ—
    #   2. Remove ALL BaseURL elements at every level (root, Period, AdaptationSet,
    #      Representation). Period-level ones at /v1/dashsegment/... cause 301â†'403.
    #   3. Inject a single correct absolute BaseURL at the MPD root.
    existing_root_bus = root.findall(base_url_tag)
    if existing_root_bus:
        raw_bu = (existing_root_bus[0].text or "").strip()
        if raw_bu.startswith("http"):
            effective_base = raw_bu
        elif raw_bu.startswith("/"):
            parsed_base    = urlparse(base_url)
            effective_base = f"{parsed_base.scheme}://{parsed_base.netloc}{raw_bu}"
        else:
            effective_base = base_url
    else:
        effective_base = base_url

    # O11V4 fetches CDN segments directly using the cookie from the /token endpoint.
    # Akamai CDN is global  -  no geo-restriction at segment delivery layer.

    # Remove ALL BaseURL elements at every level of the tree
    for elem in root.iter():
        nested = [child for child in list(elem) if child.tag == base_url_tag]
        for child in nested:
            elem.remove(child)

    bu_elem      = ET.Element(base_url_tag)
    bu_elem.text = effective_base
    root.insert(0, bu_elem)

    return f'<?xml version="1.0" encoding="UTF-8"?>\n{ET.tostring(root, encoding="unicode")}'


def _build_widevine_pssh(key_ids_hex):
    """
    Build a version-0 Widevine PSSH box that lists every key ID in *key_ids_hex*.

    key_ids_hex : iterable of raw hex strings (32 hex chars = 16 bytes), e.g.
                  ["18474f47cea2596e9118dcb11ebadc99",
                   "3677d81170f25ee2a41d80e960f2f68a"]
                  UUID-format strings (with dashes) are also accepted.

    Returns : base64-encoded PSSH box (str), ready to drop into a
              <cenc:pssh> element.

    PSSH box layout (version 0):
      4  bytes  box size (big-endian)
      4  bytes  'pssh'
      1  byte   version = 0x00
      3  bytes  flags   = 0x000000
      16 bytes  Widevine system ID
      4  bytes  data length
      N  bytes  WidevineCencHeader protobuf
                  per key_id: field 2 wire-type 2 → \\x12\\x10 + 16 raw bytes
    """
    WV_SYS_ID = bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed")
    proto = b""
    for kid in key_ids_hex:
        raw = bytes.fromhex(kid.replace("-", ""))
        if len(raw) != 16:
            raise ValueError(f"Key ID must be 16 bytes, got {len(raw)} for {kid!r}")
        proto += b"\x12\x10" + raw          # protobuf field 2, len-delim, 16 bytes
    inner = b'\x00\x00\x00\x00' + WV_SYS_ID + struct.pack('>I', len(proto)) + proto
    box   = struct.pack('>I', 8 + len(inner)) + b'pssh' + inner
    return base64.b64encode(box).decode('ascii')


def _extract_keyids_from_pssh(pssh_b64):
    """
    Decode a base64 Widevine PSSH box and return all key ID hex strings found
    inside the WidevineCencHeader protobuf.

    Handles both version-0 (key IDs in protobuf field 2) and version-1
    (key IDs in the KID list section of the box header).

    Returns a list of 32-char lowercase hex strings (empty list on any error).
    """
    try:
        raw = base64.b64decode(pssh_b64.strip())
        if len(raw) < 32 or raw[4:8] != b'pssh':
            return []
        version = raw[8]
        offset  = 28          # skip: 4 size + 4 'pssh' + 4 ver/flags + 16 sysid
        if version == 1:
            # v1: explicit KID list before the data blob
            kid_count = struct.unpack('>I', raw[offset:offset + 4])[0]
            offset += 4
            return [raw[offset + i * 16: offset + i * 16 + 16].hex()
                    for i in range(kid_count)]
        else:
            # v0: key IDs are inside the protobuf data
            data_len = struct.unpack('>I', raw[offset:offset + 4])[0]
            offset  += 4
            proto    = raw[offset: offset + data_len]
            kids     = []
            i = 0
            while i < len(proto) - 1:
                # field 2 (key_id), wire-type 2 (LEN), fixed length 16
                if proto[i] == 0x12 and proto[i + 1] == 0x10 and i + 18 <= len(proto):
                    kids.append(proto[i + 2: i + 18].hex())
                    i += 18
                else:
                    i += 1
            return kids
    except Exception:
        return []


def _fix_multikey_audio(mpd_text):
    """
    DAZN manifests assign separate Widevine key IDs to different stream types
    (video, AAC, AC3, EAC3) and, for multi-period content, to each Period.
    ISA makes one Widevine licence request using the PSSH from the first
    ContentProtection it encounters; if that PSSH only names one key ID, DAZN
    returns only that key — all other streams/periods stay encrypted/silent.

    On devices with a Widevine TEE that supports only one concurrent session
    (e.g. MediaTek MT8696 in Fire TV Stick 4K AFTKA), ISA creating a separate
    session per Period causes the TEE to evict the earlier session; when AddData
    then tries to decrypt the first period's frames the key is gone → error.

    Fix — two-pass approach:
      Pass 1: collect ALL unique key IDs from ALL Periods across the whole MPD.
      Pass 2: write a single combined PSSH (containing every key ID) into every
              Widevine ContentProtection element in every Period.

    ISA then issues ONE licence challenge that names every key ID; DAZN returns
    all keys in one response; only one Widevine session is created; the TEE
    never needs to evict — audio plays and multi-period content decrypts.
    """
    try:
        DASH_NS   = "urn:mpeg:dash:schema:mpd:2011"
        CENC_NS   = "urn:mpeg:cenc:2013"
        WV_URI    = "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"

        period_tag    = f"{{{DASH_NS}}}Period"
        cp_tag        = f"{{{DASH_NS}}}ContentProtection"
        cenc_pssh_tag = f"{{{CENC_NS}}}pssh"
        cenc_kid_attr = f"{{{CENC_NS}}}default_KID"

        root = ET.fromstring(mpd_text)

        # --- Pass 1: collect all unique key IDs across the entire manifest ---
        all_kids = []   # ordered, deduped hex strings (no dashes)
        all_wv_cps = [] # (period_id, cp_element) tuples for pass 2

        for period in root.iter(period_tag):
            for cp in period.iter(cp_tag):
                if WV_URI.lower() not in cp.get("schemeIdUri", "").lower():
                    continue
                all_wv_cps.append((period.get("id", "?"), cp))

                pssh_el = cp.find(cenc_pssh_tag)
                if pssh_el is not None and pssh_el.text:
                    for kid in _extract_keyids_from_pssh(pssh_el.text):
                        if kid and kid not in all_kids:
                            all_kids.append(kid)

                kid_attr = (
                    cp.get(cenc_kid_attr) or cp.get("default_KID") or ""
                ).strip().replace("-", "").lower()
                if kid_attr and kid_attr not in all_kids:
                    all_kids.append(kid_attr)

        if len(all_kids) < 2:
            # 0 or 1 unique key across the whole manifest — nothing to combine
            return mpd_text

        combined_b64 = _build_widevine_pssh(all_kids)
        app.logger.info(
            "[mpd_kodi] merging %d key IDs across %d periods into one combined PSSH: %s",
            len(all_kids),
            len(root.findall(period_tag)),
            all_kids,
        )

        # --- Pass 2: replace every Widevine CP's PSSH with the combined one ---
        for _pid, cp in all_wv_cps:
            pssh_el = cp.find(cenc_pssh_tag)
            if pssh_el is not None:
                pssh_el.text = combined_b64
            else:
                pssh_el = ET.SubElement(cp, cenc_pssh_tag)
                pssh_el.text = combined_b64

        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")

    except Exception as exc:
        app.logger.warning(
            "[mpd_kodi] multi-key audio fix failed (%s) — manifest unchanged", exc
        )
        return mpd_text


def _strip_ad_periods_for_kodi(mpd_text):
    """
    Remove ad Period elements from a DASH manifest before sending it to ISA.

    Handles two cases:
      A. DRM streams (AFL etc): strip unprotected periods that appear before
         the last DRM period — ISA crashes on DRM→clear transitions.
      B. Non-DRM streams (Golf, ESPN etc): DAZN inserts 60-second SCTE-35
         splice-insert placeholder periods. ISA crashes at every period
         boundary, so strip any period containing a SpliceInsert element
         with outOfNetworkIndicator='true'.

    GUARD — never empty the manifest: if stripping would leave zero periods,
    return unchanged so ISA crashes to menu rather than hanging forever.
    """
    try:
        DASH_NS           = "urn:mpeg:dash:schema:mpd:2011"
        SCTE35_NS         = "urn:scte:scte35:2014:xml+bin"
        WV_URI            = "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"
        period_tag        = f"{{{DASH_NS}}}Period"
        cp_tag            = f"{{{DASH_NS}}}ContentProtection"
        splice_insert_tag = f"{{{SCTE35_NS}}}SpliceInsert"

        root = ET.fromstring(mpd_text)
        all_periods = root.findall(period_tag)

        def _period_has_drm(p):
            for cp in p.iter(cp_tag):
                uri = cp.get("schemeIdUri", "")
                if "widevine" in uri.lower() or WV_URI in uri.lower():
                    return True
            return False

        def _period_has_scte35(p):
            for elem in p.iter():
                if elem.tag == splice_insert_tag and elem.get("outOfNetworkIndicator") == "true":
                    return True
            return False

        drm_periods = [p for p in all_periods if _period_has_drm(p)]

        if drm_periods:
            # Case A: DRM stream — strip unprotected periods before last DRM period
            last_drm_idx = max(all_periods.index(p) for p in drm_periods)
            ad_periods = [
                p for i, p in enumerate(all_periods)
                if not _period_has_drm(p) and i < last_drm_idx
            ]
        else:
            # Case B: No-DRM stream — strip SCTE-35 splice-insert ad periods
            ad_periods = [p for p in all_periods if _period_has_scte35(p)]

        if not ad_periods:
            return mpd_text

        remaining = len(all_periods) - len(ad_periods)
        if remaining < 1:
            app.logger.info(
                "[mpd_kodi] ad-strip: all periods are ads — skipping strip to avoid empty manifest"
            )
            return mpd_text

        for p in ad_periods:
            root.remove(p)

        app.logger.info(
            "[mpd_kodi] stripped %d ad period(s) (%s), %d period(s) remain",
            len(ad_periods),
            "no-drm scte35" if not drm_periods else "no-drm pre-last-drm",
            remaining,
        )
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    except Exception as exc:
        app.logger.warning("[mpd_kodi] ad-strip failed (%s) — returning manifest unchanged", exc)
        return mpd_text


def _strip_dolby_audio_for_kodi(mpd_text):
    """
    Remove AC3 (ac-3) and EAC3 (ec-3) Dolby audio AdaptationSets from DASH
    manifests served to Kodi.  On MediaTek MT8696 (Fire TV Stick 4K AFTKA),
    switching audio tracks mid-stream (e.g. AC3 → AAC) while
    OMX.MTK.VIDEO.DECODER.HEVC.secure is running causes
    CMediaCodecVideoBuffer::ReleaseOutputBuffer errors, corrupting the codec
    state and crashing the app on stop.  Leaving only AAC eliminates the
    track-switching crash and keeps video at full HEVC quality.

    Only strips Dolby if at least one AAC AdaptationSet remains,
    so audio is never completely removed.
    """
    try:
        DASH_NS   = 'urn:mpeg:dash:schema:mpd:2011'
        adapt_tag = f'{{{DASH_NS}}}AdaptationSet'
        repr_tag  = f'{{{DASH_NS}}}Representation'

        root = ET.fromstring(mpd_text)

        removed_total = 0
        for period in root.iter(f'{{{DASH_NS}}}Period'):
            adapts = period.findall(adapt_tag)
            # Categorise audio AdaptationSets by codec family
            dolby_adapts = []
            aac_adapts   = []
            for a in adapts:
                mime = a.get('mimeType', '')
                if 'audio' not in mime:
                    continue
                codecs = a.get('codecs', '')
                # Check codecs on AdaptationSet itself, or on first Representation
                if not codecs:
                    first_repr = a.find(repr_tag)
                    if first_repr is not None:
                        codecs = first_repr.get('codecs', '')
                codecs = codecs.lower()
                # Strip both AC3 and EAC3.  On MediaTek MT8696 (Fire TV AFTKA), switching
                # audio tracks mid-stream (e.g. AC3 → AAC) while HEVC.secure is running
                # causes CMediaCodecVideoBuffer::ReleaseOutputBuffer errors, corrupting the
                # codec state and crashing the app on stop.  AAC-only avoids any mid-stream
                # track switching issues on this hardware.
                if codecs.startswith('ac-3') or codecs.startswith('ec-3') or codecs.startswith('ac3') or codecs.startswith('eac3'):
                    dolby_adapts.append(a)
                elif codecs.startswith('mp4a') or codecs.startswith('aac'):
                    aac_adapts.append(a)

            # Only strip Dolby if AAC is present as a fallback
            if dolby_adapts and aac_adapts:
                for a in dolby_adapts:
                    period.remove(a)
                    removed_total += 1

        if removed_total == 0:
            return mpd_text

        app.logger.info('[mpd_kodi] stripped %d Dolby (AC3/EAC3) audio AdaptationSet(s) — AAC fallback present', removed_total)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
    except Exception as exc:
        app.logger.warning('[mpd_kodi] dolby-strip failed (%s) — returning unchanged', exc)
        return mpd_text


def _strip_hevc_for_kodi(mpd_text):
    """
    Remove HEVC (hvc1/hev1) video AdaptationSets, keeping only AVC (avc1) representations.

    On MT8696 (Fire TV Stick 4K AFTKA), the HEVC decoder (OMX.MTK.VIDEO.DECODER.HEVC)
    does not fully release between Kodi sessions.  After 3 plays the hardware decoder
    pool is exhausted and Kodi aborts with SIGABRT / PyEval_ReleaseThread(NULL).
    AVC uses a completely separate decoder family and has no pool exhaustion issue.

    Only strips HEVC if at least one AVC AdaptationSet remains, so video is never
    completely removed.  Called when the plugin passes avc_only=1.
    """
    try:
        DASH_NS   = 'urn:mpeg:dash:schema:mpd:2011'
        period_tag = f'{{{DASH_NS}}}Period'
        adapt_tag  = f'{{{DASH_NS}}}AdaptationSet'
        repr_tag   = f'{{{DASH_NS}}}Representation'

        root = ET.fromstring(mpd_text)
        removed_total = 0

        for period in root.iter(period_tag):
            adapts = period.findall(adapt_tag)

            hevc_adapts = []
            avc_adapts  = []

            for a in adapts:
                mime = a.get('mimeType', '')
                if not mime:
                    first_repr = a.find(repr_tag)
                    if first_repr is not None:
                        mime = first_repr.get('mimeType', '')
                if 'video' not in mime:
                    continue
                codecs = a.get('codecs', '')
                if not codecs:
                    first_repr = a.find(repr_tag)
                    if first_repr is not None:
                        codecs = first_repr.get('codecs', '')
                codecs = codecs.lower()
                if codecs.startswith('hvc') or codecs.startswith('hev'):
                    hevc_adapts.append(a)
                elif codecs.startswith('avc') or codecs.startswith('mp4v'):
                    avc_adapts.append(a)

            # Only strip HEVC if AVC is present as a fallback
            if hevc_adapts and avc_adapts:
                for a in hevc_adapts:
                    period.remove(a)
                    removed_total += 1

        if removed_total == 0:
            return mpd_text

        app.logger.info('[mpd_kodi] avc_only: stripped %d HEVC video AdaptationSet(s)', removed_total)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
    except Exception as exc:
        app.logger.warning('[mpd_kodi] hevc-strip failed (%s) — returning unchanged', exc)
        return mpd_text


def _strip_past_periods_for_kodi(mpd_text):
    """
    For dynamic (live) DASH manifests, strip Period elements that have already
    ended (start + duration < now).  Kodi triggers a MediaCodec secure-decoder
    reinit at every Period boundary; when an ended Period immediately precedes
    the live Period, the reinit fires before the first decoder is released and
    CDVDVideoCodecAndroidMediaCodec::Open reports 'InstanceGuard locked',
    causing video to fail on Fire TV and Shield Tube.

    Only strips Periods that have BOTH a 'start' and 'duration' attribute.
    The live Period has no 'duration' attribute and is always kept.
    """
    try:
        from datetime import datetime, timezone as _tz
        DASH_NS    = 'urn:mpeg:dash:schema:mpd:2011'
        period_tag = f'{{{DASH_NS}}}Period'

        root = ET.fromstring(mpd_text)

        if root.get('type', 'static') != 'dynamic':
            return mpd_text

        ast_str = root.get('availabilityStartTime')
        if not ast_str:
            return mpd_text

        ast = datetime.fromisoformat(ast_str.replace('Z', '+00:00'))
        now_pts = (datetime.now(_tz.utc) - ast).total_seconds()

        def _dur_to_secs(d):
            if not d:
                return None
            m = re.match(r'PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?', d)
            if not m:
                return None
            return float(m.group(1) or 0) * 3600 + float(m.group(2) or 0) * 60 + float(m.group(3) or 0)

        removed = 0
        for p in list(root.findall(period_tag)):
            start_s = _dur_to_secs(p.get('start'))
            dur_s   = _dur_to_secs(p.get('duration'))
            if start_s is None or dur_s is None:
                continue  # open-ended live period — keep
            if start_s + dur_s < now_pts:
                root.remove(p)
                removed += 1
                app.logger.info(
                    '[mpd_kodi] stripped ended period id=%s (ended %.0fs ago)',
                    p.get('id', '?'), now_pts - (start_s + dur_s),
                )

        if removed == 0:
            return mpd_text

        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
    except Exception as exc:
        app.logger.warning('[mpd_kodi] past-period strip failed (%s) — returning unchanged', exc)
        return mpd_text


def _fix_presentation_delay_for_kodi(mpd_text):
    """
    Override suggestedPresentationDelay on DAZN live manifests.
    DAZN sets this to ~3600 seconds (1 hour) on linear channels, which tells
    ISA to start playback 1 hour behind the live edge.  This causes stream
    restarts (e.g. after an ad break) to resume hours in the past instead of
    at the live edge.  Setting it to PT30S keeps ISA close to live.
    """
    new_text = re.sub(
        r'suggestedPresentationDelay="[^"]*"',
        'suggestedPresentationDelay="PT30S"',
        mpd_text,
        count=1,
    )
    if new_text != mpd_text:
        app.logger.info('[mpd_kodi] suggestedPresentationDelay overridden to PT30S')
    return new_text


# Per-asset cache of last manifest that contained at least one DRM period.
# Used by _kodi_ad_guard to serve stale-but-safe DRM content during deep
# ad breaks where the live window contains ONLY unprotected periods.
_kodi_good_mpd      = {}   # {asset_id: str}
_kodi_good_mpd_lock = threading.Lock()


def _kodi_ad_guard(asset_id, mpd_text):
    """
    Prevent ISA from crashing on unprotected (ad) periods in Kodi manifests.

    ISA crashes when it transitions from a DRM-protected period to an
    unprotected one.  This function strips unprotected periods from the
    manifest before ISA sees them.  Two cases:

    CASE A — mixed manifest (DRM + ad periods present):
      Strip the unprotected periods; cache the result as "last good" and return it.
      ISA stays in its DRM session and buffers while segment 404s accumulate.

    CASE B — all-ad manifest (DAZN live window contains ONLY ad periods):
      Stripping would leave zero periods → ISA infinite freeze.
      Return the cached last-good DRM manifest instead.  ISA buffers on
      segment 404s until content resumes, then we serve the fresh manifest.

    CASE C — DRM-only manifest (no ads):
      Update the cache and return unchanged.
    """
    DASH_NS    = 'urn:mpeg:dash:schema:mpd:2011'
    WV_URI     = 'urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed'
    period_tag = f'{{{DASH_NS}}}Period'
    cp_tag     = f'{{{DASH_NS}}}ContentProtection'

    try:
        root        = ET.fromstring(mpd_text)
        all_periods = root.findall(period_tag)

        def _has_drm(p):
            for cp in p.iter(cp_tag):
                uri = cp.get('schemeIdUri', '')
                if 'widevine' in uri.lower() or WV_URI in uri.lower():
                    return True
            return False

        drm_periods = [p for p in all_periods if _has_drm(p)]
        ad_periods  = [p for p in all_periods if not _has_drm(p)]

        # CASE C — no ads at all
        if not ad_periods:
            with _kodi_good_mpd_lock:
                _kodi_good_mpd[asset_id] = mpd_text
            return mpd_text

        # CASE A — mixed: strip ads that appear before the last DRM period
        if drm_periods:
            last_drm_idx = max(all_periods.index(p) for p in drm_periods)
            to_strip = [p for i, p in enumerate(all_periods)
                        if not _has_drm(p) and i < last_drm_idx]
            for p in to_strip:
                root.remove(p)
            stripped = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
            with _kodi_good_mpd_lock:
                _kodi_good_mpd[asset_id] = stripped
            if to_strip:
                app.logger.info('[mpd_kodi] [%s] stripped %d ad period(s) — %d DRM period(s) remain',
                                asset_id, len(to_strip), len(drm_periods))
            return stripped

        # CASE B — deep ad break, all periods unprotected
        with _kodi_good_mpd_lock:
            cached = _kodi_good_mpd.get(asset_id)
        if cached:
            app.logger.info('[mpd_kodi] [%s] all-ad break — serving cached DRM manifest (dynamic) to prevent ISA exit',
                            asset_id)
            # Make ISA treat this as a live stream so it keeps polling instead of
            # finishing playback and dropping to the menu.
            try:
                croot = ET.fromstring(cached)
                croot.set('type', 'dynamic')
                croot.set('minimumUpdatePeriod', 'PT2S')
                # Remove mediaPresentationDuration so ISA doesn't see an end time
                croot.attrib.pop('mediaPresentationDuration', None)
                return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(croot, encoding='unicode')
            except Exception:
                return cached
        app.logger.warning('[mpd_kodi] [%s] all-ad break but no cached DRM manifest yet — returning as-is',
                           asset_id)
        return mpd_text

    except Exception as exc:
        app.logger.warning('[mpd_kodi] ad-guard failed (%s) — returning manifest unchanged', exc)
        return mpd_text


@app.route("/cdn/<quality>/<asset_id>/<path:cdn_path>", methods=["GET", "HEAD"])
def cdn_segment_proxy(quality, asset_id, cdn_path):
    """
    Proxy CDN segment/init requests for Kodi/ISA, injecting the current CDN
    cookie from _stream_cache on every request.

    The static CDN cookie baked into ISA's Item headers at stream start expires
    after ~1 hour, causing ISA to stall (403 on segments).  By routing all
    segment URLs through this endpoint the relay can inject a live cookie at
    any time — _stream_cache refreshes at 50 min, well before CDN expiry.

    URL rewriting happens in mpd_kodi(): BaseURL is converted from
      https://cdn.host/out/v1/HASH/
    to
      http://localhost:5004/cdn/<quality>/<asset_id>/cdn.host/out/v1/HASH/
    so ISA's template expansion produces URLs that land here.
    """
    cdn_url   = "https://" + cdn_path
    cache_key = ("fhd:" + asset_id) if (quality == "fhd") else asset_id

    # Read cookie without expiry check — during the brief refresh window the
    # stale entry is still valid from the CDN's perspective (CDN token outlives
    # our 50-min cache TTL by at least 10 min).
    with _stream_cache_lock:
        sc = _stream_cache.get(cache_key)

    headers = {}
    if sc:
        d        = sc.get("response", {})
        cdn_name = d.get("cdn_name", "")
        cdn_val  = d.get("cdn_val", "")
        if cdn_name and cdn_val:
            headers["Cookie"] = f"{cdn_name}={cdn_val}"
    else:
        app.logger.warning("[cdn_proxy] no stream cache for %s — fetching without cookie", cache_key)

    # Forward Range header — ISA uses byte-range requests for init segments
    range_hdr = request.headers.get("Range")
    if range_hdr:
        headers["Range"] = range_hdr

    try:
        r = _cdn_session.get(cdn_url, headers=headers, timeout=20, stream=True)
        resp_headers = {
            "Content-Type": r.headers.get("Content-Type", "application/octet-stream"),
        }
        for hdr in ("Content-Length", "Content-Range", "Accept-Ranges"):
            if hdr in r.headers:
                resp_headers[hdr] = r.headers[hdr]
        return Response(r.iter_content(chunk_size=65536), status=r.status_code,
                        headers=resp_headers)
    except Exception as exc:
        app.logger.error("[cdn_proxy] [%s] %s: %s", asset_id, cdn_url[:100], exc)
        return jsonify({"error": str(exc)}), 502


@app.route("/mpd_kodi", methods=["GET"])
def mpd_kodi():
    """
    Kodi-facing manifest proxy  -  fetches MPD from DAZN CDN with CDN cookie attached,
    returns it verbatim.  Exists because SlyGuy's internal proxy strips custom headers
    (including the dazn-token CDN cookie) before hitting the CDN, causing DAZN to
    return "Unable to obtain template manifest".  By serving from the relay, the CDN
    cookie is always present.  No XML processing  -  ContentProtection is untouched.

    GET /mpd_kodi?id=<dazn_asset_id>
    """
    asset_id = request.args.get("id", "").strip()
    if not asset_id:
        return jsonify({"error": "id parameter is required"}), 400
    quality   = request.args.get("quality", "4k").lower()
    avc_only  = request.args.get("avc_only", "0") == "1"
    cache_key = ('fhd:' + asset_id) if (quality == 'fhd') else asset_id
    try:
        entry   = _get_stream_cached(asset_id, quality=quality)
        cookies = {entry["cdn_name"]: entry["cdn_val"]} if entry["cdn_name"] else {}
        r = requests.get(entry["manifest_url"], cookies=cookies, timeout=15)
        if r.status_code in (401, 403, 404, 410):
            # Session expired  -  evict both caches so _get_stream_cached fetches a fresh session
            _mpd_url_cache.pop(cache_key, None)
            with _stream_cache_lock:
                _stream_cache.pop(cache_key, None)
            entry   = _get_stream_cached(asset_id, quality=quality)
            cookies = {entry["cdn_name"]: entry["cdn_val"]} if entry["cdn_name"] else {}
            r = requests.get(entry["manifest_url"], cookies=cookies, timeout=15)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "application/dash+xml")

        # Absolutize root-relative BaseURL so Kodi fetches segments directly from
        # the CDN instead of requesting them from the relay (where no /out/v1/ route exists).
        # DAZN manifests contain e.g. <BaseURL>/out/v1/ABC/DEF/</BaseURL>; Kodi resolves
        # this against the manifest URL (which points at the relay) â†' 404 on every segment.
        # Replace with https://cdn.host/out/v1/ABC/DEF/ so Kodi goes direct to CDN.
        parsed_manifest = urlparse(entry["manifest_url"])
        cdn_origin      = f"{parsed_manifest.scheme}://{parsed_manifest.netloc}"

        # --- BaseURL absolutisation ---
        # Case 1: manifest has a root-relative <BaseURL> like /out/v1/...
        #   Replace with https://cdn.host/out/v1/... so Kodi fetches segments from CDN.
        # The regex allows optional whitespace (including newlines) inside the tag.
        mpd_text = re.sub(
            r'<BaseURL>\s*(/[^<]*?)\s*</BaseURL>',
            lambda m: '<BaseURL>{}{}</BaseURL>'.format(cdn_origin, m.group(1).strip()),
            r.text,
        )

        # Case 2: manifest has NO <BaseURL> at all and uses relative segment paths
        #   (e.g. ../abc123/index_video_...).  Kodi resolves relative URLs against the
        #   manifest URL — which points at the relay — so every segment request hits the
        #   relay and returns 404.  Fix: inject a <BaseURL> at the MPD root level set to
        #   the CDN directory that contains the manifest file.
        if '<BaseURL>' not in mpd_text:
            # CDN manifest directory = scheme://host + path up to (and including) last /
            manifest_path = parsed_manifest.path
            cdn_dir = cdn_origin + manifest_path[:manifest_path.rfind('/') + 1]
            # Inject right after the opening <MPD ...> tag (before the first child)
            mpd_text = re.sub(
                r'(<MPD\b[^>]*>)',
                r'\1\n  <BaseURL>' + cdn_dir + r'</BaseURL>',
                mpd_text,
                count=1,
            )
            app.logger.info("[mpd_kodi] injected BaseURL %s (no BaseURL in manifest)", cdn_dir)

        # Rewrite every <BaseURL> that points to the CDN to go through the
        # relay segment proxy instead.  ISA's static CDN cookie (baked into
        # Item headers at stream start) expires after ~1 hour; routing segments
        # through /cdn/... lets the relay inject a live cookie on each request.
        #
        # IMPORTANT: use request.host_url (the URL the client used to reach THIS
        # endpoint) rather than "localhost:5004".  ISA runs on Fire TV / Shield —
        # localhost on those devices is the device itself, not the relay laptop.
        # request.host_url is automatically correct whether ISA reaches the relay
        # via ngrok, a LAN IP, or any other route.
        relay_base   = request.host_url.rstrip('/')
        relay_netloc = urlparse(relay_base).netloc
        def _rewrite_base_url(m):
            url = m.group(1)
            # Don't rewrite already-relay URLs (guard against double-rewrite)
            if relay_netloc in url or "127.0.0.1" in url:
                return m.group(0)
            no_scheme = re.sub(r"^https?://", "", url)
            return f"<BaseURL>{relay_base}/cdn/{quality}/{asset_id}/{no_scheme}</BaseURL>"
        mpd_text = re.sub(r"<BaseURL>(https?://[^<]+)</BaseURL>", _rewrite_base_url, mpd_text)

        # Strip already-ended periods from live manifests.  DAZN live streams
        # accumulate past periods (e.g. an ended ad break before the live period).
        # ISA triggers a MediaCodec codec reinit at every period boundary; the
        # reinit on an ended→live transition hits the InstanceGuard before the
        # previous secure-decoder instance releases, causing video failure on
        # Fire TV and Shield Tube ("InstanceGuard locked").
        mpd_text = _strip_past_periods_for_kodi(mpd_text)

        # Override DAZN's large suggestedPresentationDelay (~1 hour on linear
        # channels) so ISA starts near the live edge rather than an hour behind.
        mpd_text = _fix_presentation_delay_for_kodi(mpd_text)

        # Stateful ad-break guard: strip unprotected periods from Kodi manifests.
        # During deep ad breaks (all periods unprotected), serves the last known
        # good DRM manifest so ISA buffers instead of crashing to menu.
        mpd_text = _kodi_ad_guard(asset_id, mpd_text)

        # Strip Dolby (AC3/EAC3) audio AdaptationSets.  On MediaTek MT8696 (Fire TV
        # Stick 4K AFTKA) opening OMX.MTK.VIDEO.DECODER.HEVC.secure simultaneously
        # with an EAC3 MediaCodec session causes queueSecureInputBuffer to return
        # an error immediately ("AddData error"), making video unplayable.  AAC-only
        # streams play fine on the same device.  Stripping Dolby forces ISA to fall
        # back to the AAC AdaptationSet; Shield Pro and other devices handle AAC fine.
        # NOTE: tested without this strip — Fire TV drops to 540p H.264 instead of
        # crashing, but video quality loss is worse than losing Dolby audio.
        mpd_text = _strip_dolby_audio_for_kodi(mpd_text)

        # Strip HEVC video representations when requested by the plugin (avc_only=1).
        # MT8696 (Fire TV AFTKA) HEVC decoder pool exhausts after 3 sessions — crashes Kodi.
        if avc_only:
            mpd_text = _strip_hevc_for_kodi(mpd_text)

        # Merge per-stream Widevine key IDs into a single combined PSSH per Period.
        # DAZN 4K manifests use separate key IDs for video and audio; ISA makes one
        # licence request from the first PSSH it sees (video) — DAZN returns only
        # the video key, leaving audio undecrypted (silent).  By placing a PSSH
        # that names both key IDs in every ContentProtection element, ISA's single
        # challenge covers all keys and DAZN returns all of them.
        mpd_text = _fix_multikey_audio(mpd_text)

        # VOD replays: DAZN serves them as type="dynamic" even though they're finished.
        # ISA sees dynamic → treats as live stream → jumps to live edge, no scrubbing.
        # Fix: detect VOD by CDN hostname and convert to type="static" with duration.
        # Live streams stay dynamic so ISA keeps polling instead of exiting to menu.
        try:
            entry      = _get_stream_cached(asset_id)
            droot      = ET.fromstring(mpd_text)
            # Detect VOD: CDN URL contains "ac-vod" (DAZN replay CDN)
            # OR the manifest already has mediaPresentationDuration set —
            # completed events keep this attribute even when type="dynamic".
            # Live in-progress streams never have it.
            is_vod = (
                "ac-vod" in entry.get("manifest_url", "")
                or bool(droot.get('mediaPresentationDuration'))
            )
            if is_vod:
                droot.set('type', 'static')
                # Compute total duration from periods if mediaPresentationDuration missing
                if 'mediaPresentationDuration' not in droot.attrib:
                    DASH_NS    = "urn:mpeg:dash:schema:mpd:2011"
                    period_tag = f"{{{DASH_NS}}}Period"
                    total = 0.0
                    for p in droot.findall(period_tag):
                        dur = p.get('duration', '')
                        m   = re.match(r'^PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?$', dur)
                        if m:
                            total += float(m.group(1) or 0)*3600 + float(m.group(2) or 0)*60 + float(m.group(3) or 0)
                    if total > 0:
                        droot.set('mediaPresentationDuration', 'PT{:.3f}S'.format(total))
                droot.attrib.pop('minimumUpdatePeriod', None)
                app.logger.info('[mpd_kodi] [%s] VOD: forced type=static', asset_id)
            else:
                # Live stream — keep dynamic so ISA polls for new segments
                if droot.get('type', 'static') == 'static':
                    droot.set('type', 'dynamic')
                    droot.attrib.pop('mediaPresentationDuration', None)
                    app.logger.info('[mpd_kodi] [%s] live: forced type=dynamic (was static)', asset_id)
                if 'minimumUpdatePeriod' not in droot.attrib:
                    droot.set('minimumUpdatePeriod', 'PT4S')
            mpd_text = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(droot, encoding='unicode')
        except Exception as exc:
            app.logger.warning('[mpd_kodi] dynamic/static-force failed (%s) — serving as-is', exc)

        return Response(mpd_text.encode("utf-8"), mimetype=content_type,
                        headers={"Access-Control-Allow-Origin": "*",
                                 "Cache-Control": "no-cache, no-store, must-revalidate"})
    except Exception as exc:
        app.logger.error("[mpd_kodi] %s: %s", asset_id, exc)
        return jsonify({"error": str(exc)}), 502


@app.route("/mpd", methods=["GET"])
def mpd_proxy():
    """
    O11V4-facing DASH manifest proxy.

    GET /mpd?id=<dazn_asset_id>

    On each call:
      1. Returns the cached DAZN manifest URL (calls /token only on first use or expiry).
      2. Fetches the raw MPD from the DAZN CDN.
      3. Processes ad breaks via process_mpd()  -  slate mode or merge fallback.
      4. Returns the cleaned MPD as application/dash+xml.
    """
    asset_id = request.args.get("id", "").strip()
    if not asset_id:
        return jsonify({"error": "id parameter is required"}), 400

    try:
        # â"€â"€ 1. Get manifest URL from cache (fast path) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        entry = _get_stream_cached(asset_id)

        # â"€â"€ 2. Fetch raw MPD from CDN â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        cookies  = {entry["cdn_name"]: entry["cdn_val"]} if entry["cdn_name"] else {}
        mpd_resp = requests.get(entry["manifest_url"], cookies=cookies, timeout=15)

        # If the CDN URL has expired, force a cache refresh and retry once
        if mpd_resp.status_code in (401, 403, 404, 410):
            app.logger.warning(
                "[mpd_proxy] CDN returned %d for %s  -  invalidating cache and retrying",
                mpd_resp.status_code, asset_id,
            )
            _mpd_url_cache.pop(asset_id, None)
            with _stream_cache_lock:
                _stream_cache.pop(asset_id, None)
            entry    = _get_stream_cached(asset_id)
            cookies  = {entry["cdn_name"]: entry["cdn_val"]} if entry["cdn_name"] else {}
            mpd_resp = requests.get(entry["manifest_url"], cookies=cookies, timeout=15)

        mpd_resp.raise_for_status()

        # â"€â"€ 3 + 4. Process and return â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        processed = process_mpd(mpd_resp.text, entry["base_url"], asset_id)
        return Response(
            processed,
            mimetype="application/dash+xml",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control":               "no-cache, no-store, must-revalidate",
            },
        )

    except requests.RequestException as exc:
        app.logger.error("[mpd_proxy] network error: %s", exc)
        return jsonify({"error": f"fetch failed: {exc}"}), 502

    except ET.ParseError as exc:
        app.logger.error("[mpd_proxy] XML parse error: %s", exc)
        return jsonify({"error": f"MPD XML error: {exc}"}), 502

    except Exception as exc:
        import traceback
        app.logger.error("[mpd_proxy] unexpected: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc)}), 500


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  DIAGNOSTIC  -  /mpd_debug
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.route("/mpd_debug", methods=["GET"])
def mpd_debug():
    """
    Like /mpd but returns a JSON summary instead of the filtered XML.
    Useful for checking how many periods were removed and which method caught them.
    Also shows current ad break state and slate status.

    GET /mpd_debug?id=<dazn_asset_id>
    """
    asset_id = request.args.get("id", "").strip()
    if not asset_id:
        return jsonify({"error": "id required"}), 400
    try:
        entry    = _get_stream_cached(asset_id)
        cookies  = {entry["cdn_name"]: entry["cdn_val"]} if entry["cdn_name"] else {}
        mpd_resp = requests.get(entry["manifest_url"], cookies=cookies, timeout=15)
        mpd_resp.raise_for_status()

        for _evt, (prefix, uri) in ET.iterparse(io.StringIO(mpd_resp.text), events=["start-ns"]):
            ET.register_namespace(prefix, uri)
        root = ET.fromstring(mpd_resp.text)

        DASH_NS               = "urn:mpeg:dash:schema:mpd:2011"
        SCTE35_NS             = "urn:scte:scte35:2013:xml"
        period_tag            = f"{{{DASH_NS}}}Period"
        event_stream_tag      = f"{{{DASH_NS}}}EventStream"
        adapt_set_tag         = f"{{{DASH_NS}}}AdaptationSet"
        content_prot_tag      = f"{{{DASH_NS}}}ContentProtection"
        splice_insert_tag     = f"{{{SCTE35_NS}}}SpliceInsert"
        segment_template_tag  = f"{{{DASH_NS}}}SegmentTemplate"

        all_periods = root.findall(period_tag)
        manifest_has_drm = any(
            len(adap.findall(content_prot_tag)) > 0
            for p in all_periods
            for adap in p.findall(adapt_set_tag)
        )
        classified = []
        for p in all_periods:
            is_ad, method = _is_ad_period(
                p, event_stream_tag, adapt_set_tag,
                content_prot_tag, splice_insert_tag, manifest_has_drm,
                segment_template_tag=segment_template_tag,
            )
            classified.append((p, is_ad, method))

        # Simulate the merge logic for the summary
        period_info = []
        i = 0
        while i < len(classified):
            p, is_ad, method = classified[i]
            adapt_sets = p.findall(adapt_set_tag)
            has_drm    = any(len(a.findall(content_prot_tag)) > 0 for a in adapt_sets)
            has_splice = any(
                e.tag == splice_insert_tag and e.get("outOfNetworkIndicator") == "true"
                for e in p.iter()
            )
            has_scte35 = any(
                "scte35" in es.get("schemeIdUri", "").lower()
                for es in p.findall(event_stream_tag)
            )

            if is_ad:
                action = "KEEP (first ad  -  placeholder)"
                i += 1
                while i < len(classified) and classified[i][1]:
                    rp, _, rm = classified[i]
                    ra   = rp.findall(adapt_set_tag)
                    rdrm = any(len(a.findall(content_prot_tag)) > 0 for a in ra)
                    period_info.append({
                        "id":            rp.get("id", "?"),
                        "start":         rp.get("start", "?"),
                        "duration":      rp.get("duration", "?"),
                        "is_ad":         True,
                        "detect_method": rm,
                        "has_drm":       rdrm,
                        "action":        f"REMOVE (merged into run, method={rm})",
                    })
                    i += 1
            else:
                action = "keep (content)"
                i += 1

            period_info.insert(len(period_info), {
                "id":                      p.get("id", "?"),
                "start":                   p.get("start", "?"),
                "duration":                p.get("duration", "?"),
                "is_ad":                   is_ad,
                "detect_method":           method,
                "has_drm":                 has_drm,
                "has_splice_insert":       has_splice,
                "has_scte35_event_stream": has_scte35,
                "action":                  action,
            })

        would_remove = sum(1 for p in period_info if "REMOVE" in p.get("action", ""))

        # Current ad break state for this asset
        with _ad_state_lock:
            state = _ad_state.get(asset_id)
        ad_state_info = None
        if state:
            ad_state_info = {
                "period_start":    state["period_start"],
                "seconds_elapsed": int(time.time() - state["since"]),
            }

        _ensure_slate_loaded()
        return jsonify({
            "asset_id":           asset_id,
            "manifest_url":       entry["manifest_url"][:80] + "...",
            "base_url":           entry["base_url"],
            "manifest_has_drm":   manifest_has_drm,
            "mode":               "live-game (Method 3 active)" if manifest_has_drm else "non-live (Method 3 disabled)",
            "slate_enabled":      _slate_period_xml is not None,
            "processing_mode":    "stateful_slate" if _slate_period_xml is not None else "merge_fallback",
            "active_ad_break":    ad_state_info,
            "total_periods":      len(all_periods),
            "would_keep":         len(all_periods) - would_remove,
            "would_remove":       would_remove,
            "ad_breaks_detected": sum(1 for p in period_info if p.get("action","").startswith("KEEP (first ad")),
            "periods":            period_info,
        })
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "trace": traceback.format_exc()}), 500


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  FILE DISTRIBUTION  -  /kayo.py
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.route("/mpd_ad_break", methods=["GET"])
def mpd_ad_break_route():
    """
    Returns whether the current manifest has active ad periods (per _is_ad_period() logic).
    Uses SCTE-35 and no-DRM detection — correctly identifies an ad break even when DRM
    content periods are still visible in the sliding window alongside the ad period.

    GET /mpd_ad_break?id=<dazn_asset_id>
    Returns: {"is_ad_break": true/false, "has_drm": true/false, "asset_id": "..."}
    """
    asset_id = request.args.get("id", "").strip()
    if not asset_id:
        return jsonify({"error": "id required"}), 400
    try:
        entry   = _get_stream_cached(asset_id)
        cookies = {entry["cdn_name"]: entry["cdn_val"]} if entry["cdn_name"] else {}
        r       = requests.get(entry["manifest_url"], cookies=cookies, timeout=10)

        # CDN manifest URLs expire during long games — refresh the token and retry
        if r.status_code == 404:
            app.logger.info("[mpd_ad_break] %s manifest 404 — refreshing token", asset_id)
            _stream_cache.pop(asset_id, None)
            profile_id = _profile_id_from_dazn_jwt()
            stream     = get_stream(asset_id, profile_id)
            cdn        = stream["cdn_token"]
            cdn_name   = cdn.split("=", 1)[0] if "=" in cdn else ""
            cdn_val    = cdn.split("=", 1)[1] if "=" in cdn else ""
            _stream_cache[asset_id] = {
                "manifest_url": stream["manifest_url"],
                "cdn_name": cdn_name, "cdn_val": cdn_val,
                "la_url": stream.get("la_url", ""),
                "expiry": time.time() + 3000,
            }
            cookies = {cdn_name: cdn_val} if cdn_name else {}
            r       = requests.get(stream["manifest_url"], cookies=cookies, timeout=10)

        r.raise_for_status()

        for _evt, (pfx, uri) in ET.iterparse(io.StringIO(r.text), events=["start-ns"]):
            ET.register_namespace(pfx, uri)
        root = ET.fromstring(r.text)

        DASH_NS               = "urn:mpeg:dash:schema:mpd:2011"
        SCTE35_NS             = "urn:scte:scte35:2013:xml"
        period_tag            = f"{{{DASH_NS}}}Period"
        event_stream_tag      = f"{{{DASH_NS}}}EventStream"
        adapt_set_tag         = f"{{{DASH_NS}}}AdaptationSet"
        content_prot_tag      = f"{{{DASH_NS}}}ContentProtection"
        splice_insert_tag     = f"{{{SCTE35_NS}}}SpliceInsert"
        segment_template_tag  = f"{{{DASH_NS}}}SegmentTemplate"

        all_periods = root.findall(period_tag)
        manifest_has_drm = any(
            len(adap.findall(content_prot_tag)) > 0
            for p in all_periods
            for adap in p.findall(adapt_set_tag)
        )

        # Identify the currently active period by wall-clock time so that stale
        # ad periods lingering in the manifest sliding window don't keep
        # is_ad_break=True after live content has resumed.
        def _parse_dur_s(s):
            if not s or s == '?':
                return None
            m = re.match(r'^PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?$', s)
            if not m:
                return None
            return float(m.group(1) or 0)*3600 + float(m.group(2) or 0)*60 + float(m.group(3) or 0)

        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        active_p  = None
        avail_str = root.get('availabilityStartTime', '')
        if avail_str and all_periods:
            try:
                avail = _dt.fromisoformat(avail_str.replace('Z', '+00:00'))
                now   = _dt.now(_tz.utc)
                for p in all_periods:
                    s_secs = _parse_dur_s(p.get('start', 'PT0S'))
                    if s_secs is None:
                        continue
                    p_start = avail + _td(seconds=s_secs)
                    d_secs  = _parse_dur_s(p.get('duration'))
                    if d_secs is not None:
                        if p_start <= now < p_start + _td(seconds=d_secs):
                            active_p = p
                            break
                    else:
                        if p_start <= now:
                            active_p = p   # open-ended last period, keep scanning
            except Exception:
                pass

        # If the background watcher already cleared ad state for this asset,
        # the break is definitively over — trust it immediately without re-analysing
        # the manifest (the watcher does 1s polling; the manifest fetch here is slower).
        with _ad_state_lock:
            watcher_says_clear = asset_id not in _ad_state

        if watcher_says_clear and active_p is not None:
            # Double-check: only trust the watcher if the active period also looks clean.
            # This guards against the watcher clearing state prematurely on a brief gap.
            active_is_ad = _is_ad_period(
                active_p, event_stream_tag, adapt_set_tag,
                content_prot_tag, splice_insert_tag, manifest_has_drm,
                segment_template_tag=segment_template_tag,
            )[0]
            if not active_is_ad:
                app.logger.info("[mpd_ad_break] %s -> watcher cleared + active period clean -> is_ad_break=False",
                                asset_id)
                return jsonify({"is_ad_break": False, "has_drm": manifest_has_drm,
                                "asset_id": asset_id})

        if active_p is None:
            active_p = all_periods[-1] if all_periods else None

        is_ad_break = bool(active_p is not None and _is_ad_period(
            active_p, event_stream_tag, adapt_set_tag,
            content_prot_tag, splice_insert_tag, manifest_has_drm,
            segment_template_tag=segment_template_tag,
        )[0])

        # If wall-clock detection picked a period that looks clean but ANY other
        # period is still showing ad signals, trust the broader scan — the active
        # period calculation can be off by one period near break boundaries.
        if not is_ad_break:
            any_period_is_ad = any(
                _is_ad_period(
                    p, event_stream_tag, adapt_set_tag,
                    content_prot_tag, splice_insert_tag, manifest_has_drm,
                    segment_template_tag=segment_template_tag,
                )[0]
                for p in all_periods
            )
            if any_period_is_ad:
                is_ad_break = True
                app.logger.info("[mpd_ad_break] %s -> active period clean but other periods have ads -> is_ad_break=True",
                                asset_id)

        app.logger.info("[mpd_ad_break] %s -> is_ad_break=%s has_drm=%s active_period=%s",
                        asset_id, is_ad_break, manifest_has_drm,
                        active_p.get('id', '?') if active_p is not None else 'none')
        return jsonify({"is_ad_break": is_ad_break, "has_drm": manifest_has_drm,
                        "asset_id": asset_id})
    except Exception as exc:
        app.logger.warning("[mpd_ad_break] %s: %s", asset_id, exc)
        return jsonify({"is_ad_break": False, "has_drm": True, "error": str(exc)}), 502


@app.route("/mpd_has_drm", methods=["GET"])
def mpd_has_drm_route():
    """
    Returns whether the current DAZN manifest for this asset has any DRM-protected
    periods. Used by the Kodi plugin KayoPlayer monitor to detect when an ad break
    has ended so it can auto-restart the stream.

    GET /mpd_has_drm?id=<dazn_asset_id>
    Returns: {"has_drm": true/false, "asset_id": "..."}
      has_drm=true  -> DRM content visible in sliding window -> safe to restart
      has_drm=false -> only ad periods visible -> still in break, keep waiting
    """
    asset_id = request.args.get("id", "").strip()
    if not asset_id:
        return jsonify({"error": "id required"}), 400
    try:
        entry   = _get_stream_cached(asset_id)
        cookies = {entry["cdn_name"]: entry["cdn_val"]} if entry["cdn_name"] else {}
        r       = requests.get(entry["manifest_url"], cookies=cookies, timeout=10)
        r.raise_for_status()

        DASH_NS    = "urn:mpeg:dash:schema:mpd:2011"
        period_tag = "{%s}Period"              % DASH_NS
        adapt_tag  = "{%s}AdaptationSet"      % DASH_NS
        cp_tag     = "{%s}ContentProtection"  % DASH_NS

        root    = ET.fromstring(r.text)
        has_drm = any(
            len(adap.findall(cp_tag)) > 0
            for p    in root.findall(period_tag)
            for adap in p.findall(adapt_tag)
        )
        app.logger.info("[mpd_has_drm] %s -> has_drm=%s", asset_id, has_drm)
        return jsonify({"has_drm": has_drm, "asset_id": asset_id})
    except Exception as exc:
        app.logger.warning("[mpd_has_drm] %s: %s", asset_id, exc)
        return jsonify({"has_drm": False, "error": str(exc)}), 502


@app.route("/kayo.py", methods=["GET"])
def serve_kayo_script():
    """Serves the current kayo.py so the VPS container can pull it via curl."""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kayo.py")
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content, mimetype="text/plain")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Foxtel EPG cache — full 24/7 programme data for all Kayo/Fox Sports channels
# Source: aussietv.xyz/Foxtel/epg.xml (Foxtel XMLTV feed with real show listings)
# ---------------------------------------------------------------------------
_mjh_epg_cache      = None          # dict: dazn_asset_id -> [(start, end, title, desc)]
_mjh_epg_cache_time = 0             # unix timestamp of last fetch
_MJH_EPG_URL        = 'http://aussietv.xyz/Foxtel/epg.xml'
_MJH_EPG_TTL        = 1800          # refresh every 30 minutes

# Map Foxtel XMLTV channel IDs -> DAZN asset IDs (our channel IDs)
# aussietv.xyz switched from 'FoxFooty.au@SD' style IDs to short 3-letter codes.
# Run /epg_debug to verify — "matched" shows active mappings, "unmapped_in_feed"
# shows sample titles for any channel IDs not yet mapped.
_MJH_CHANNEL_MAP = {
    'FAF': '1l47a9ir5hj0o1wi5j0pkm5fpb',    # Fox Footy    — AFL minis/matches confirmed
    'SP2': '1tc0mhfzkbbti165v1rsuewtek',    # Fox League   — NRL/Sunday Night Matty Johns confirmed
    'FS1': 'jo74ryszmcvd1pzmbzp50q84a',     # Fox Cricket  — The Hundred cricket confirmed
    'FS3': 'xjauo23ins1b1hnss5covnvxw',     # Fox Sports 503 — USPGA/golf multi-sport
    'FSP': '12555dnxvg0f319t9w1tgjdvid',    # Fox Sports 505 — golf/supercars/tennis mix
    'SPS': '231pfo674jx615m2uo32ahsex',     # Fox Sports 506 — MotoGP/motorsport confirmed
    'FSS': '17eyitoe96uwb1qbwz8r6dplok',    # Fox Sports 507 — surfing/WSL confirmed
    'FSN': '1ns8p240ac6bz1ovcbxx538enp',    # Fox Sports News confirmed
    'ESP': 'lbod12u9fiwx17r3cpnjxagrb',     # ESPN — MLB/lacrosse confirmed
    'UFC': '5nfomyujg3z610ssm0szjoef4',     # Main Event UFC confirmed
    'RTV': 'e5okck7f0rny12j9xv1kc9w12',    # Racing.com confirmed
    # FS2 removed — it's a drama channel (Spooks/Vera/Marple), not Fox Sports 505
    # ESPN 2 not found in feed (ES2 only has 1 prog — a single Dutch soccer match)
}

@app.route("/epg_debug", methods=["GET"])
def epg_debug():
    """
    Debug endpoint — fetch aussietv.xyz Foxtel EPG and report:
      - All channel IDs found in the feed with programme counts
      - Which ones match _MJH_CHANNEL_MAP and which don't
      - Current cache status
    Hit http://localhost:5004/epg_debug to diagnose blank EPG slots.
    """
    import re as _re
    try:
        r = requests.get(_MJH_EPG_URL, timeout=20,
                         headers={'User-Agent': 'KayoRelay/1.0', 'Accept-Encoding': 'gzip'})
        r.raise_for_status()
        xml = r.text
    except Exception as exc:
        return jsonify({"error": str(exc), "url": _MJH_EPG_URL}), 502

    # Count programmes and collect sample titles per channel ID
    ch_counts = {}
    ch_titles = {}
    prog_re   = _re.compile(r'<programme([^>]*)>(.*?)</programme>', _re.DOTALL)
    attr_ch   = _re.compile(r'channel="([^"]+)"')
    title_re  = _re.compile(r'<title[^>]*>([^<]+)</title>')
    for m in prog_re.finditer(xml):
        attrs, body = m.group(1), m.group(2)
        ch_m = attr_ch.search(attrs)
        if not ch_m:
            continue
        cid = ch_m.group(1)
        ch_counts[cid] = ch_counts.get(cid, 0) + 1
        if len(ch_titles.get(cid, [])) < 3:
            t = title_re.search(body)
            if t:
                ch_titles.setdefault(cid, []).append(t.group(1).strip())

    # Reverse map: asset_id -> channel name for display
    _asset_to_name = {v: k for k, v in CHANNEL_MAP.items()}

    matched    = {cid: {"asset": _MJH_CHANNEL_MAP[cid],
                         "channel": _asset_to_name.get(_MJH_CHANNEL_MAP[cid], '?'),
                         "count": ch_counts.get(cid, 0),
                         "samples": ch_titles.get(cid, [])}
                  for cid in _MJH_CHANNEL_MAP if cid in ch_counts}
    not_mapped = {cid: {"count": cnt, "samples": ch_titles.get(cid, [])}
                  for cid, cnt in sorted(ch_counts.items(), key=lambda x: -x[1])
                  if cid not in _MJH_CHANNEL_MAP}
    not_found  = {cid: asset for cid, asset in _MJH_CHANNEL_MAP.items() if cid not in ch_counts}

    return jsonify({
        "epg_url":               _MJH_EPG_URL,
        "cache_age_s":           int(time.time() - _mjh_epg_cache_time) if _mjh_epg_cache_time else None,
        "matched":               matched,
        "not_in_feed":           not_found,
        "unmapped_in_feed":      not_mapped,
        "total_feed_programmes": sum(ch_counts.values()),
    })


def _fetch_mjh_epg():
    """
    Fetch and parse the Foxtel XMLTV EPG feed from aussietv.xyz.
    Returns a dict: {dazn_asset_id: [(start_dt, end_dt, title, desc), ...]}
    Cached for 30 minutes; on fetch error returns last cached value or {}.
    Covers all Fox Sports channels, ESPN, ESPN2, Racing.com, Main Event UFC.
    """
    global _mjh_epg_cache, _mjh_epg_cache_time
    from datetime import datetime, timezone as _tz, timedelta

    now = time.time()
    if _mjh_epg_cache is not None and (now - _mjh_epg_cache_time) < _MJH_EPG_TTL:
        return _mjh_epg_cache

    def _parse_xmltv_ts(ts):
        """Parse XMLTV timestamp 'YYYYMMDDHHMMSS +HHMM' -> UTC datetime."""
        ts = ts.strip()
        dt_str  = ts[:14]
        tz_str  = ts[14:].strip() if len(ts) > 14 else '+0000'
        sign    = 1 if tz_str.startswith('+') else -1
        tz_h    = int(tz_str[1:3]) if len(tz_str) >= 5 else 0
        tz_m    = int(tz_str[3:5]) if len(tz_str) >= 5 else 0
        dt      = datetime.strptime(dt_str, '%Y%m%d%H%M%S').replace(tzinfo=_tz.utc)
        return dt - timedelta(hours=sign * tz_h, minutes=sign * tz_m)

    try:
        r = requests.get(_MJH_EPG_URL, timeout=20,
                         headers={'User-Agent': 'KayoRelay/1.0', 'Accept-Encoding': 'gzip'})
        r.raise_for_status()
        xml = r.text

        # Parse using regex — avoids namespace issues with ET on XMLTV files.
        # Attribute order in the XMLTV file is: channel, start, stop — so we
        # capture the whole opening tag and extract each attribute separately.
        result = {asset_id: [] for asset_id in _MJH_CHANNEL_MAP.values()}
        prog_re  = re.compile(r'<programme([^>]*)>(.*?)</programme>', re.DOTALL)
        attr_ch  = re.compile(r'channel="([^"]+)"')
        attr_st  = re.compile(r'start="([^"]+)"')
        attr_sp  = re.compile(r'stop="([^"]+)"')
        title_re = re.compile(r'<title[^>]*>([^<]+)</title>')
        desc_re  = re.compile(r'<desc[^>]*>([^<]+)</desc>')

        for m in prog_re.finditer(xml):
            attrs, body = m.group(1), m.group(2)
            ch_m = attr_ch.search(attrs)
            st_m = attr_st.search(attrs)
            sp_m = attr_sp.search(attrs)
            if not (ch_m and st_m and sp_m):
                continue
            ch_id     = ch_m.group(1)
            start_raw = st_m.group(1)
            stop_raw  = sp_m.group(1)
            asset_id = _MJH_CHANNEL_MAP.get(ch_id)
            if not asset_id:
                continue
            title_m = title_re.search(body)
            if not title_m:
                continue
            title = title_m.group(1).strip()
            if 'No listing available' in title or not title:
                continue
            desc_m = desc_re.search(body)
            desc   = desc_m.group(1).strip() if desc_m else ''
            try:
                start_dt = _parse_xmltv_ts(start_raw)
                end_dt   = _parse_xmltv_ts(stop_raw)
            except Exception:
                continue
            if end_dt <= start_dt:
                continue
            result[asset_id].append((start_dt, end_dt, title, desc))

        # Sort each channel's list by start time
        for lst in result.values():
            lst.sort(key=lambda x: x[0])

        _mjh_epg_cache      = result
        _mjh_epg_cache_time = now
        total = sum(len(v) for v in result.values())
        app.logger.info('[epg] fetched Foxtel EPG: %d real programmes across %d channels',
                        total, sum(1 for v in result.values() if v))
        return result

    except Exception as exc:
        app.logger.warning('[epg] Foxtel EPG fetch failed (%s) — using cache or empty', exc)
        return _mjh_epg_cache or {}


@app.route("/epg.xml", methods=["GET"])
def epg_xml():
    """
    XMLTV EPG feed for Kayo Sports channels.

    Channel IDs are DAZN asset_ids, matching tvg-id values in the Kodi plugin
    playlist() output and /slots.m3u.  This means TiviMate / IPTV Simple can
    auto-match channels to EPG entries without any manual mapping.

    Covers:
      - All permanent linear channels (Fox Footy, Fox League, ESPN, etc.)
      - Permanent 4K channel variants (Fox Footy 4K, Fox League 4K, etc.) that
        are always present and show 4K-flagged events; gaps filled with HD content

    Programme data comes from two sources:
      1. DAZN Rail API — live/upcoming sport events (same source as /events)
      2. aussietv.xyz/Foxtel/epg.xml — full 24/7 Foxtel schedule for all channels
         (Fox Sports News, Fox Footy, Fox League, Fox Cricket, ESPN, ESPN2, etc.)
    Rail API events take priority; Foxtel EPG fills gaps between sport events.
    Any remaining gaps are filled with a "Kayo Sports" placeholder.

    Proxy this via aussietv.xyz/Kayo/epg.php for a stable public URL.
    """
    from datetime import datetime, timedelta, timezone

    # -- Channel name -> DAZN asset_id (permanent linear slots) ---------------
    NAME_TO_ASSET = {v: k for k, v in CHANNEL_MAP.items()}

    # Channel logos — tv-logo community repo (all 200 OK, publicly accessible)
    _TVLOGO = 'https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/australia/'
    CHANNEL_LOGOS = {
        'Fox Footy':      _TVLOGO + 'fox-sports-footy-504-au.png',
        'Fox League':     _TVLOGO + 'fox-sports-league-502-au.png',
        'Fox Cricket':    _TVLOGO + 'fox-sports-cricket-501-au.png',
        'ESPN':           _TVLOGO + 'espn-au.png',
        'ESPN2':          _TVLOGO + 'espn-2-au.png',
        'Fox Sports 503': _TVLOGO + 'fox-sports-503-au.png',
        'Fox Sports 505': _TVLOGO + 'fox-sports-505-au.png',
        'Fox Sports 506': _TVLOGO + 'fox-sports-506-au.png',
        'Fox Sports 507': _TVLOGO + 'fox-sports-507-au.png',
        'Fox Sports News': _TVLOGO + 'fox-sports-news-au.png',
        'Racing.com':     _TVLOGO + 'racing-com-au.png',
        'MainEvent UFC':  _TVLOGO + 'fox-sports-regular-au.png',
    }

    def esc(s):
        return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

    def fmt_ts(dt):
        """datetime -> XMLTV timestamp string."""
        return dt.strftime('%Y%m%d%H%M%S +0000')

    def parse_iso(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace('Z', '+00:00'))
        except Exception:
            return None

    # -- Fetch schedule --------------------------------------------------------
    try:
        events_list = fetch_kayo_rail_schedule()
    except Exception as e:
        app.logger.error('[epg] fetch_kayo_rail_schedule failed: %s', e)
        events_list = []

    # Supplementary 24/7 schedule from i.mjh.nz (Racing.com, Main Event, etc.)
    mjh_data = _fetch_mjh_epg()

    # -- Permanent 4K channels (channel_id -> display_name, mirrors plugin constants) --
    PERM_4K = [
        ('fsa504', 'Fox Footy 4K'),       # AFL
        ('fsa503', 'Fox Sports 503 4K'),  # AFL
        ('fsa502', 'Fox League 4K'),      # NRL
        ('fsa505', 'Fox Sports 505 4K'),  # Netball
        ('fsa506', 'Fox Sports 506 4K'),  # Motorsport (F1 / V8)
        ('fsa501', 'Fox Cricket 4K'),     # Cricket
    ]
    # EPG channel ID for permanent 4K slots: '4k-fsa504' etc — matches tvg-id in m3u8
    PERM_4K_IDS = {'4k-' + cid: name for cid, name in PERM_4K}

    # -- EPG window: now-1h to now+48h ----------------------------------------
    now          = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=1)
    window_end   = now + timedelta(hours=48)

    # -- Build per-channel programme lists ------------------------------------
    # Structure: channel_id -> [(start_dt, end_dt, xml_block_string), ...]
    # Keyed by DAZN asset_id for linear channels, '4k-{channel_id}' for 4K channels
    ch_progs = {asset_id: [] for asset_id in NAME_TO_ASSET.values()}

    # Initialise permanent 4K channel slots
    for epg_id in PERM_4K_IDS:
        ch_progs[epg_id] = []

    # Linear channel programmes + mirror to permanent 4K channel when event is 4K
    for ev in events_list:
        ch_name    = ev.get('channel', '')
        asset_id   = NAME_TO_ASSET.get(ch_name)
        channel_id = ev.get('channel_id', '')       # e.g. 'fsa504'
        if not asset_id:
            continue
        start_dt = parse_iso(ev.get('time', ''))
        if not start_dt:
            continue
        end_dt = parse_iso(ev.get('end_time', '')) or (start_dt + timedelta(hours=3))
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=3)

        title = esc(ev.get('title', 'Unknown'))
        sport = esc(ev.get('sport', ''))
        badge = ' [4K]' if ev.get('is_4k') else ''
        desc  = ('LIVE' if ev.get('type') == 'live' else 'Upcoming') + ' on ' + esc(ch_name)

        # Linear channel entry
        block = (
            '  <programme start="' + fmt_ts(start_dt) + '" stop="' + fmt_ts(end_dt) + '" channel="' + asset_id + '">\n'
            '    <title lang="en">' + title + badge + '</title>\n'
            + ('    <category lang="en">' + sport + '</category>\n' if sport else '')
            + '    <desc lang="en">' + desc + '</desc>\n'
            '  </programme>'
        )
        ch_progs[asset_id].append((start_dt, end_dt, block))

        # Also add to the permanent 4K channel if this channel has one
        perm_4k_id = '4k-' + channel_id
        if perm_4k_id in ch_progs:
            badge4k = ' [4K]' if ev.get('is_4k') else ' [HD]'
            desc4k  = ('LIVE' if ev.get('type') == 'live' else 'Upcoming') + ' — ' + esc(ch_name) + ' 4K'
            block4k = (
                '  <programme start="' + fmt_ts(start_dt) + '" stop="' + fmt_ts(end_dt) + '" channel="' + perm_4k_id + '">\n'
                '    <title lang="en">' + title + badge4k + '</title>\n'
                + ('    <category lang="en">' + sport + '</category>\n' if sport else '')
                + '    <desc lang="en">' + desc4k + '</desc>\n'
                '  </programme>'
            )
            ch_progs[perm_4k_id].append((start_dt, end_dt, block4k))

    # -- Merge Foxtel EPG data into ch_progs ----------------------------------
    # Rail API events are now populated; add Foxtel EPG entries only where they
    # don't overlap an existing Rail API event. Fills all 24/7 channels with
    # real programme names from the full Foxtel schedule.
    for asset_id, mjh_list in mjh_data.items():
        if asset_id not in ch_progs:
            continue
        rail_entries = ch_progs[asset_id]
        for ms, me, title, desc in mjh_list:
            if me <= window_start or ms >= window_end:
                continue
            # Skip if overlaps any Rail API entry (sport events take priority)
            if any(ms < re and me > rs for rs, re, _ in rail_entries):
                continue
            block = (
                '  <programme start="' + fmt_ts(ms) + '" stop="' + fmt_ts(me) + '" channel="' + asset_id + '">\n'
                '    <title lang="en">' + esc(title) + '</title>\n'
                + ('    <desc lang="en">' + esc(desc) + '</desc>\n' if desc else '')
                + '  </programme>'
            )
            ch_progs[asset_id].append((ms, me, block))

    # -- Mirror linear Foxtel EPG to 4K channel slots -------------------------
    # 4K slots only get Rail API events; during off-peak hours (no game in Rail)
    # they'd show "Kayo Sports" filler.  Fill those gaps with the corresponding
    # linear channel's Foxtel EPG titles instead (e.g. "AFL Tonight", "NRL 360").
    _4K_CID_TO_LINEAR = {
        'fsa504': NAME_TO_ASSET.get('Fox Footy', ''),
        'fsa502': NAME_TO_ASSET.get('Fox League', ''),
        'fsa501': NAME_TO_ASSET.get('Fox Cricket', ''),
        'fsa503': NAME_TO_ASSET.get('Fox Sports 503', ''),
        'fsa505': NAME_TO_ASSET.get('Fox Sports 505', ''),
        'fsa506': NAME_TO_ASSET.get('Fox Sports 506', ''),
    }
    for cid, linear_asset in _4K_CID_TO_LINEAR.items():
        perm_4k_id = '4k-' + cid
        if perm_4k_id not in ch_progs or not linear_asset:
            continue
        existing_4k = ch_progs[perm_4k_id]
        for ms, me, title, desc in mjh_data.get(linear_asset, []):
            if me <= window_start or ms >= window_end:
                continue
            if any(ms < ee and me > es for es, ee, _ in existing_4k):
                continue
            block4k = (
                '  <programme start="' + fmt_ts(ms) + '" stop="' + fmt_ts(me) + '" channel="' + perm_4k_id + '">\n'
                '    <title lang="en">' + esc(title) + '</title>\n'
                + ('    <desc lang="en">' + esc(desc) + '</desc>\n' if desc else '')
                + '  </programme>'
            )
            ch_progs[perm_4k_id].append((ms, me, block4k))

    # -- Gap-fill each channel ------------------------------------------------
    # For every channel, walk the EPG window and insert "Kayo Sports" filler
    # blocks wherever there is no scheduled programme.  This prevents blank
    # slots in TiviMate / IPTV Simple / Kodi PVR.
    GAP_MIN   = timedelta(minutes=5)   # ignore gaps smaller than this
    FILLER_TITLE = 'Kayo Sports'
    FILLER_DESC  = 'Live sports on Kayo'

    all_prog_blocks = []

    for asset_id, progs in ch_progs.items():
        # Sort, then keep only those that overlap the window
        progs.sort(key=lambda x: x[0])
        progs = [(s, e, b) for s, e, b in progs if e > window_start and s < window_end]

        cursor = window_start

        for start_dt, end_dt, block in progs:
            gap = start_dt - cursor
            if gap > GAP_MIN:
                # Insert filler to cover the gap
                all_prog_blocks.append(
                    '  <programme start="' + fmt_ts(cursor) + '" stop="' + fmt_ts(start_dt) + '" channel="' + asset_id + '">\n'
                    '    <title lang="en">' + FILLER_TITLE + '</title>\n'
                    '    <desc lang="en">' + FILLER_DESC + '</desc>\n'
                    '  </programme>'
                )
            all_prog_blocks.append(block)
            if end_dt > cursor:
                cursor = end_dt

        # Fill any remaining tail up to window_end
        if cursor < window_end - GAP_MIN:
            all_prog_blocks.append(
                '  <programme start="' + fmt_ts(cursor) + '" stop="' + fmt_ts(window_end) + '" channel="' + asset_id + '">\n'
                '    <title lang="en">' + FILLER_TITLE + '</title>\n'
                '    <desc lang="en">' + FILLER_DESC + '</desc>\n'
                '  </programme>'
            )

    # -- Assemble final XML ---------------------------------------------------
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<tv source-info-name="Kayo Sports" generator-info-name="kayo-relay">']

    # 1. Permanent linear channel declarations
    for ch_name, asset_id in NAME_TO_ASSET.items():
        logo = CHANNEL_LOGOS.get(ch_name, '')
        lines.append('  <channel id="' + asset_id + '">')
        lines.append('    <display-name lang="en">' + esc(ch_name) + '</display-name>')
        if logo:
            lines.append('    <icon src="' + logo + '" />')
        lines.append('  </channel>')

    # 2. Permanent 4K channel declarations (always present, match tvg-id in m3u8)
    # Map channel_id -> linear channel name for logo lookup
    _CHANNEL_ID_TO_NAME = {
        'fsa501': 'Fox Cricket', 'fsa502': 'Fox League', 'fsa503': 'Fox Sports 503',
        'fsa504': 'Fox Footy',   'fsa505': 'Fox Sports 505', 'fsa506': 'Fox Sports 506',
        'fsa507': 'Fox Sports 507', 'espn1': 'ESPN', 'espn2': 'ESPN2',
        'maineventufc': 'MainEvent UFC',
    }
    for cid, display_name in PERM_4K_IDS.items():
        raw_cid = cid[3:]   # strip '4k-' prefix
        logo    = CHANNEL_LOGOS.get(_CHANNEL_ID_TO_NAME.get(raw_cid, ''), '')
        lines.append('  <channel id="' + cid + '">')
        lines.append('    <display-name lang="en">' + esc(display_name) + '</display-name>')
        if logo:
            lines.append('    <icon src="' + logo + '" />')
        lines.append('  </channel>')

    # 3. All programme blocks (real events + gap-fill filler)
    lines.extend(all_prog_blocks)

    lines.append('</tv>')
    return Response(
        '\n'.join(lines),
        mimetype='application/xml',
        headers={
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'public, max-age=300',
        },
    )


@app.route("/cdn/<path:cdnpath>", methods=["GET"])
def cdn_proxy(cdnpath):
    """
    CDN segment proxy  -  called by mpd_proxy on the VPS.

    Forwards GET /cdn/<host>/<path>?<qs> to https://<host>/<path>?<qs> using
    the Australian IP of this relay server, bypassing Finnish VPS geo-throttling.
    The CDN cookie (set on kayo.py's manifest action) is forwarded by O11V4 on
    every media request and passed through here verbatim.
    """
    target = f"https://{cdnpath}"
    if request.query_string:
        target += f"?{request.query_string.decode('utf-8', errors='replace')}"

    fwd_headers = {}
    cookie = request.headers.get("Cookie", "")
    if cookie:
        fwd_headers["Cookie"] = cookie

    try:
        r = requests.get(target, headers=fwd_headers, timeout=30, stream=True)
        def generate():
            for chunk in r.iter_content(65536):
                yield chunk
        return Response(
            generate(),
            status=r.status_code,
            content_type=r.headers.get("Content-Type", "application/octet-stream"),
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except Exception as exc:
        app.logger.error("[cdn_proxy] %s â†' %s", cdnpath, exc)
        return Response(str(exc), status=502)


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  KAYO CONTENT API PROXY
#  Routes Kodi plugin calls through the relay so the Fire TV never needs
#  to hit api.kayosports.com.au directly (avoids Akamai WAF / token expiry issues).
#  curl_cffi Chrome impersonation handles Akamai TLS fingerprinting.
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _kayo_headers():
    token = get_kayo_token()
    if not token:
        return None, ("No Kayo token. Log in via the Kodi plugin or paste token into C:\\kayo\\kayo_token.txt", 401)
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent":    "au.com.foxsports.core.App/1.1.5 (Linux;Android 8.1.0) ExoPlayerLib/2.7.3",
        "Accept":        "application/json",
        "Origin":        "https://kayosports.com.au",
    }, None


@app.route('/kayo_login', methods=['GET', 'POST'])
def kayo_login_endpoint():
    """
    Bootstrap Kayo token without needing the Fire TV.
    GET  /kayo_login?user=EMAIL&password=PASS
    POST /kayo_login  body: {"user": "EMAIL", "password": "PASS"}
    Uses curl_cffi Chrome impersonation to bypass Akamai WAF.
    """
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        username = data.get('user', '')
        password = data.get('password', '')
    else:
        username = request.args.get('user', '')
        password = request.args.get('password', '')

    if not username or not password:
        return jsonify({"error": "user and password required"}), 400

    try:
        r = curl_requests.post(
            AUTH_URL,
            json={
                'audience':   'kayosports.com.au',
                'grant_type': 'http://auth0.com/oauth/grant-type/password-realm',
                'scope':      'openid offline_access',
                'realm':      'prod-martian-database',
                'client_id':  CLIENT_ID,
                'username':   username,
                'password':   password,
            },
            headers={
                'User-Agent':   'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Content-Type': 'application/json',
                'Origin':       'https://kayosports.com.au',
                'Referer':      'https://kayosports.com.au/',
            },
            timeout=20,
            impersonate="safari17_0",
        )
        if r.status_code != 200:
            return jsonify({"error": f"Kayo login failed ({r.status_code}): {r.text[:300]}"}), r.status_code

        token = r.json().get('access_token', '')
        if not token:
            return jsonify({"error": "No access_token in response"}), 500

        with open(KAYO_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token)
        kayo_token_state["token"]  = token
        kayo_token_state["expiry"] = time.time() + 82800
        print(f"Kayo token bootstrapped via /kayo_login for {username}")
        return jsonify({"status": "ok", "message": f"Kayo token stored for {username}"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/set_kayo_token', methods=['POST'])
def set_kayo_token():
    """Store a fresh Kayo Auth0 access_token (and optional refresh_token) from the Kodi plugin after login."""
    data = request.get_json(force=True, silent=True) or {}
    token         = data.get('token', '').strip()
    refresh_token = data.get('refresh_token', '').strip()
    if not token and not refresh_token:
        return jsonify({"error": "token or refresh_token required"}), 400
    token_changed = False
    if token and token.startswith('eyJ'):
        if token != kayo_token_state.get("token", ""):
            token_changed = True
            try:
                with open(KAYO_TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(token)
            except Exception as e:
                print(f"Warning: could not save kayo token: {e}")
            # Use actual JWT expiry so an already-expired token doesn't get treated as fresh
            actual_exp = _jwt_exp(token)
            kayo_token_state["token"]  = token
            kayo_token_state["expiry"] = actual_exp if actual_exp > int(time.time()) + 60 else 0
    if refresh_token:
        _save_kayo_refresh_token(refresh_token)
    if token_changed:
        print("Kayo token changed via /set_kayo_token" + (" + refresh_token stored" if refresh_token else ""))
        # New Kayo token — force DAZN token refresh on the next DAZN request.
        dazn_state['expiry'] = 0
    else:
        print("/set_kayo_token: token unchanged, skipping DAZN expiry reset")
    return jsonify({'status': 'ok'})


def _kayo_content_get(url, params, headers, retries=2, delay=1.0):
    """GET a Kayo content API URL, retrying on 503 'no healthy upstream'."""
    last_r = None
    for attempt in range(retries):
        try:
            r = curl_requests.get(url, params=params, headers=headers, timeout=20, impersonate="safari17_0")
            if r.status_code != 503:
                return r
            last_r = r
        except Exception as e:
            if attempt == retries - 1:
                raise
        time.sleep(delay)
    return last_r


# â"€â"€ Show landing disk cache â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Stores successful show landing responses keyed by show_id+season_id.
# Survives relay restarts. Served as fallback when the API returns 503.
_SHOW_CACHE_DIR = r"C:\kayo\show_cache"
os.makedirs(_SHOW_CACHE_DIR, exist_ok=True)

def _show_cache_path(show_id, season_id=''):
    safe = f"{show_id}_{season_id}" if season_id else show_id
    return os.path.join(_SHOW_CACHE_DIR, f"{safe}.json")

def _show_cache_save(show_id, season_id, body_bytes):
    try:
        entry = {'ts': time.time(), 'body': body_bytes.decode('utf-8', errors='replace')}
        with open(_show_cache_path(show_id, season_id), 'w', encoding='utf-8') as f:
            _json.dump(entry, f)
    except Exception:
        pass

def _show_cache_load(show_id, season_id, max_age=86400):
    """Return cached body bytes or None. max_age=None means no age limit."""
    try:
        path = _show_cache_path(show_id, season_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            entry = _json.load(f)
        if max_age is not None:
            age = time.time() - entry.get('ts', 0)
            if age > max_age:
                return None
        return entry['body'].encode('utf-8')
    except Exception:
        return None


# Tracks show IDs currently being retried in background so we don't double-spawn
_show_retry_active = set()
_show_retry_lock   = threading.Lock()

def _show_background_retry(show_id, season_id):
    """Background thread: retry show landing every 3 min until it succeeds or 10 attempts."""
    with _show_retry_lock:
        key = (show_id, season_id)
        if key in _show_retry_active:
            return
        _show_retry_active.add(key)
    try:
        for attempt in range(10):
            time.sleep(180)  # 3 minutes  -  longer than CDN max-age=150
            try:
                token = get_kayo_token()
                if not token:
                    continue
                hdrs = {'Authorization': 'Bearer ' + token,
                        'User-Agent': 'Mozilla/5.0 Chrome/120.0.0.0',
                        'Accept': 'application/json',
                        'Origin': 'https://kayosports.com.au'}
                params = {'evaluate': '5', 'show': show_id}
                if season_id:
                    params['season'] = season_id
                r = curl_requests.get(f"{CONTENT_URL}/show", params=params,
                                      headers=hdrs, timeout=20, impersonate='safari17_0')
                if r.status_code == 200:
                    _show_cache_save(show_id, season_id, r.content)
                    print(f"[show cache] background retry success for show={show_id}")
                    return
            except Exception as ex:
                print(f"[show cache] background retry error: {ex}")
    finally:
        with _show_retry_lock:
            _show_retry_active.discard((show_id, season_id))


@app.route('/kayo/landing', methods=['GET'])
def kayo_landing():
    """Proxy: GET /kayo/landing?name=sport&sport=afl&evaluate=5"""
    headers, err = _kayo_headers()
    if err:
        return err[0], err[1]
    name   = request.args.get('name', 'home')
    params = {'evaluate': request.args.get('evaluate', '5')}
    for p in ('sport', 'series', 'team', 'show', 'season'):
        v = request.args.get(p)
        if v:
            params[p] = v

    # Landing cache key  -  only cache sport/competition landings, not show landings
    cache_key = None
    if name not in ('show',):
        sport_key  = params.get('sport') or params.get('series') or params.get('team') or ''
        cache_key  = f"{name}:{sport_key}"
        now        = time.time()
        cached_entry = _landing_cache.get(cache_key)
        if cached_entry and now < cached_entry['expires']:
            return Response(cached_entry['body'], status=200, content_type="application/json")

    try:
        r = _kayo_content_get(f"{CONTENT_URL}/{name}", params, headers)
        # Cache inline panel contents so /kayo/panel can serve them if the panel URL later 503s
        if r.status_code == 200:
            try:
                data = _json.loads(r.content)
                now = time.time()
                for panel_row in data.get('panels', []):
                    href = (panel_row.get('links') or {}).get('panels', '')
                    inline = panel_row.get('contents', [])
                    if href and inline:
                        _panel_cache[href] = {
                            'title':    panel_row.get('title', ''),
                            'contents': inline,
                            'expires':  now + 600,
                        }
            except Exception:
                pass
            # Store in landing cache
            if cache_key:
                _landing_cache[cache_key] = {'body': r.content, 'expires': now + _LANDING_TTL}
        elif r.status_code == 503 and cache_key:
            # API failed  -  serve stale landing if we have one
            stale = _landing_cache.get(cache_key)
            if stale:
                print(f"[landing cache] serving stale for {cache_key}")
                return Response(stale['body'], status=200, content_type="application/json")
        # Also cache show landing responses when fetched via /kayo/landing?name=show
        if r.status_code == 200 and name == 'show':
            show_id_v = params.get('show', '')
            season_id_v = params.get('season', '')
            if show_id_v:
                _show_cache_save(show_id_v, season_id_v, r.content)
        elif r.status_code == 503 and name == 'show':
            show_id_v = params.get('show', '')
            season_id_v = params.get('season', '')
            if show_id_v:
                cached = _show_cache_load(show_id_v, season_id_v, max_age=None)
                if cached:
                    print(f"[show cache] serving via /kayo/landing for show={show_id_v}")
                    return Response(cached, status=200, content_type="application/json")
        return Response(r.content, status=r.status_code, content_type="application/json")
    except Exception as e:
        # Exception path  -  serve stale landing if available
        if cache_key:
            stale = _landing_cache.get(cache_key)
            if stale:
                print(f"[landing cache] serving stale after exception for {cache_key}")
                return Response(stale['body'], status=200, content_type="application/json")
        return jsonify({"error": str(e)}), 502


@app.route('/kayo/panel', methods=['GET'])
def kayo_panel():
    """Proxy: GET /kayo/panel?href=<full_kayo_api_url>&profile=<optional>"""
    headers, err = _kayo_headers()
    if err:
        return err[0], err[1]
    href = request.args.get('href', '')
    if not href:
        return jsonify({"error": "href required"}), 400
    params = {}
    profile = request.args.get('profile', '')
    if profile:
        params['profile'] = profile
    last_r = None
    try:
        for attempt in range(4):
            try:
                r = curl_requests.get(href, params=params, headers=headers, timeout=20, impersonate="safari17_0")
                if r.status_code != 503:
                    return Response(r.content, status=r.status_code, content_type="application/json")
                last_r = r
            except Exception as e:
                if attempt == 3:
                    raise
            time.sleep(2.0)
        # All retries failed  -  try inline content cache
        cached = _panel_cache.get(href)
        if cached and cached['expires'] > time.time():
            return jsonify({'title': cached['title'], 'contents': cached['contents']})
        return Response(last_r.content, status=503, content_type="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route('/kayo/show', methods=['GET'])
def kayo_show():
    """Proxy: GET /kayo/show?show_id=X&season_id=Y"""
    headers, err = _kayo_headers()
    if err:
        return err[0], err[1]
    show_id   = request.args.get('show_id', '')
    season_id = request.args.get('season_id', '')
    params = {'evaluate': '5', 'show': show_id}
    if season_id:
        params['season'] = season_id
    try:
        r = _kayo_content_get(f"{CONTENT_URL}/show", params, headers)
        if r.status_code == 200:
            _show_cache_save(show_id, season_id, r.content)
            return Response(r.content, status=200, content_type="application/json")
        # API failed  -  try disk cache (no age limit when API is down)
        cached = _show_cache_load(show_id, season_id, max_age=None)
        if cached:
            print(f"[show cache] serving stale cache for show={show_id}")
            return Response(cached, status=200, content_type="application/json")
        if season_id:
            cached = _show_cache_load(show_id, '', max_age=None)
            if cached:
                print(f"[show cache] falling back to full show cache for show={show_id} season={season_id}")
                return Response(cached, status=200, content_type="application/json")
        # Nothing in cache  -  kick off background retry so next visit might work
        threading.Thread(target=_show_background_retry, args=(show_id, season_id), daemon=True).start()
        return Response(r.content, status=r.status_code, content_type="application/json")
    except Exception as e:
        # Last resort: try disk cache (no age limit when API is down)
        cached = _show_cache_load(show_id, season_id, max_age=None)
        if cached:
            print(f"[show cache] serving stale cache after exception for show={show_id}")
            return Response(cached, status=200, content_type="application/json")
        if season_id:
            cached = _show_cache_load(show_id, '', max_age=None)
            if cached:
                print(f"[show cache] falling back to full show cache after exception for show={show_id} season={season_id}")
                return Response(cached, status=200, content_type="application/json")
        threading.Thread(target=_show_background_retry, args=(show_id, season_id), daemon=True).start()
        return jsonify({"error": str(e)}), 502


@app.route('/debug/show_cache', methods=['GET'])
def debug_show_cache():
    """List all cached shows and their age. GET /debug/show_cache"""
    result = {}
    try:
        for fname in os.listdir(_SHOW_CACHE_DIR):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(_SHOW_CACHE_DIR, fname)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    entry = _json.load(f)
                age_s = int(time.time() - entry.get('ts', 0))
                result[fname] = {'age_seconds': age_s, 'body_bytes': len(entry.get('body', ''))}
            except Exception as ex:
                result[fname] = {'error': str(ex)}
    except Exception as ex:
        return jsonify({'error': str(ex)}), 500
    return jsonify(result)


@app.route('/debug/asset', methods=['GET'])
def debug_asset():
    """Call Kayo private assets API to see playback fields. GET /debug/asset?id=261366"""
    asset_id = request.args.get('id', '')
    if not asset_id:
        return jsonify({'error': 'id required'}), 400
    headers, err = _kayo_headers()
    if err:
        return err[0], err[1]
    try:
        r = curl_requests.get(
            f"https://api.kayosports.com.au/v3/private/assets/{asset_id}",
            params={'hud': 'true'},
            headers=headers, timeout=20, impersonate="safari17_0",
        )
        return Response(r.content, status=r.status_code, content_type="application/json")
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/debug/item', methods=['GET'])
def debug_item():
    """Dump raw fields of video items from a landing/panel for debugging asset ID issues.
    GET /debug/item?name=home  or  /debug/item?href=<panel_url>"""
    headers, err = _kayo_headers()
    if err:
        return err[0], err[1]
    href = request.args.get('href', '')
    name = request.args.get('name', 'home')
    try:
        if href:
            r = curl_requests.get(href, headers=headers, timeout=20, impersonate="safari17_0")
        else:
            r = curl_requests.get(
                f"{CONTENT_URL}/{name}",
                params={'evaluate': '5'}, headers=headers, timeout=20, impersonate="safari17_0",
            )
        data = r.json()
        items = []
        for panel in data.get('panels', []):
            for c in panel.get('contents', []):
                if c.get('contentType') == 'video':
                    d  = c.get('data', {})
                    ct = d.get('clickthrough', {})
                    pb = d.get('playback', {})
                    items.append({
                        'panel':              panel.get('title'),
                        'contentType':        c.get('contentType'),
                        'data_id':            d.get('id'),
                        'data_type':          d.get('type'),
                        'clickthrough':       ct,
                        'playback_info':      pb.get('info'),
                        'playback_keys':      list(pb.keys()),
                    })
                    if len(items) >= 20:
                        break
            if len(items) >= 20:
                break
        return jsonify({'count': len(items), 'items': items})
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/debug/panel_cache', methods=['GET'])
def debug_panel_cache():
    """Show current panel cache state. GET /debug/panel_cache"""
    now = time.time()
    return jsonify({
        k: {'title': v['title'], 'count': len(v['contents']), 'ttl_sec': int(v['expires'] - now)}
        for k, v in _panel_cache.items()
    })


@app.route('/debug/show_raw', methods=['GET'])
def debug_show_raw():
    """Test Kayo show API directly. GET /debug/show_raw?show_id=138707"""
    headers, err = _kayo_headers()
    if err:
        return err[0], err[1]
    show_id = request.args.get('show_id', '138707')
    show_url  = request.args.get('show_url', '')  # e.g. /shows/show-afl-360!138707
    show_slug = ''
    if show_url:
        part = show_url.split('/shows/')[-1]
        show_slug = part.split('!')[0]  # e.g. show-afl-360
    results = {}
    candidates = [
        # Old content API
        ('content_show_id',      f"{CONTENT_URL}/show",          {'evaluate': '3', 'show': show_id}),
        # v3 content API patterns
        ('v3_show_id',           f"https://api.kayosports.com.au/v3/content/types/shows/{show_id}", {}),
        ('v3_shows_param',       f"https://api.kayosports.com.au/v3/shows/{show_id}",              {}),
        ('v3_panels_show',       f"https://api.kayosports.com.au/v3/panels/show",                  {'show': show_id, 'evaluate': '3'}),
        ('v3_panels_shows',      f"https://api.kayosports.com.au/v3/panels/shows",                 {'show': show_id}),
        # DAZN discovery patterns
        ('dazn_series',          f"https://discovery.indazn.com/au/v1/Series",                     {'seriesId': show_id}),
        ('dazn_catalog',         f"https://catalog.ott.ar.indazn.com/v2/catalog/series/{show_id}", {}),
    ]
    if show_slug:
        candidates += [
            ('v3_slug_panel',        f"https://api.kayosports.com.au/v3/panels/{show_slug}",           {'show': show_id}),
            ('content_slug',         f"{CONTENT_URL}/{show_slug}",                                     {'evaluate': '3'}),
        ]
    for label, url, params in candidates:
        try:
            r = curl_requests.get(url, params=params, headers=headers, timeout=10, impersonate="safari17_0")
            results[label] = {'status': r.status_code, 'body': r.text[:300]}
        except Exception as e:
            results[label] = {'error': str(e)}
    return jsonify(results)


@app.route('/debug/sections', methods=['GET'])
def debug_sections():
    """Dump raw section items (shows) from a landing page or panel.
    GET /debug/sections?sport=afl
    GET /debug/sections?href=https://api.kayosports.com.au/v3/panels/aNrsWam7X8z?sport=afl&landing=sport"""
    headers, err = _kayo_headers()
    if err:
        return err[0], err[1]
    href  = request.args.get('href', '')
    sport = request.args.get('sport', '')
    name  = request.args.get('name', 'sport')
    try:
        if href:
            r = curl_requests.get(href, headers=headers, timeout=20, impersonate="safari17_0")
        else:
            params = {'evaluate': '5'}
            if sport:
                params['sport'] = sport
            r = _kayo_content_get(f"{CONTENT_URL}/{name}", params, headers)
        if r.status_code != 200:
            return jsonify({'error': 'Kayo returned {}'.format(r.status_code), 'body': r.text[:500]}), 502
        try:
            data = r.json()
        except Exception as e:
            return jsonify({'error': 'JSON parse failed: {}'.format(str(e)), 'body': r.text[:500]}), 502
        items = []
        # Landing pages have 'panels'; panel responses have 'contents' directly
        panels = data.get('panels') or [{'title': data.get('title', ''), 'contents': data.get('contents', [])}]
        for panel_row in panels:
            for c in panel_row.get('contents', []):
                if c.get('contentType') == 'section':
                    d  = c.get('data', {})
                    ct = d.get('clickthrough', {})
                    items.append({
                        'panel':        panel_row.get('title'),
                        'data_id':      d.get('id'),
                        'data_type':    d.get('type'),
                        'links':        d.get('links', {}),
                        'clickthrough': ct,
                    })
        return jsonify({'count': len(items), 'items': items})
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/kayo/search', methods=['GET'])
def kayo_search():
    """Proxy: GET /kayo/search?q=afl+360&size=250&page=1"""
    headers, err = _kayo_headers()
    if err:
        return err[0], err[1]
    params = {
        'q':    request.args.get('q', ''),
        'size': request.args.get('size', '250'),
        'page': request.args.get('page', '1'),
    }
    try:
        r = _kayo_content_get(
            "https://api.kayosports.com.au/search/types/landing",
            params, headers, retries=3, delay=2.0,
        )
        return Response(r.content, status=r.status_code, content_type="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route('/debug/rail', methods=['GET'])
def debug_rail():
    """Dump raw DAZN Rail API tiles so we can diagnose missing EPG events.
    GET /debug/rail
    Returns JSON with all tiles, showing EventId, Title, LinearProvider, Start, End.
    """
    try:
        dazn_token = get_dazn_token()
        jwt = _decode_jwt_payload(dazn_token)
        viewer_id = jwt.get("viewerId", "3036fe16d324986c457250b540841a27e303d3b4")
        dazn_id   = jwt.get("user",     "auth0|69a8b6d22b11eb1bd445200b")
        params = {
            "platform":     "web",
            "id":           LIVE_RAIL_ID,
            "viewerId":     viewer_id,
            "country":      "au",
            "brand":        "kayo",
            "languageCode": "en",
            "params":       "PageType:Home;ContentType:None",
            "size":         "50",
        }
        headers = {
            "x-brand":    "kayo",
            "x-daznid":   dazn_id,
            "accept":     "application/json, text/plain, */*",
            "referer":    "https://kayosports.com.au/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        }
        r = requests.get(RAIL_URL, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        tiles = r.json().get("Tiles", [])
        summary = []
        for t in tiles:
            summary.append({
                "EventId":        t.get("EventId"),
                "AssetId":        t.get("AssetId"),
                "Title":          t.get("Title"),
                "LinearProvider": t.get("LinearProvider"),
                "Type":           t.get("Type"),
                "Start":          t.get("Start"),
                "End":            t.get("End"),
                "Sport":          (t.get("Sport") or {}).get("Title"),
            })
        return jsonify({"tile_count": len(tiles), "tiles": summary})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route('/probe_ads', methods=['GET'])
def probe_ads():
    """
    Probe the DAZN Playback API with different adParams combinations to find
    which one returns a manifest with no ad periods.

    GET /probe_ads?id=ASSET_ID

    Tests 5 variants and returns for each:
      - how many Periods are in the manifest
      - whether any Period has no Widevine ContentProtection (= ad period)
      - the raw adParams sent
    """
    asset_id = request.args.get('id', '').strip()
    if not asset_id:
        return jsonify({'error': 'id param required'}), 400

    bearer = get_dazn_token()
    try:
        import base64 as _b64
        _pad = bearer.split('.')[1]
        _pad += '=' * (-len(_pad) % 4)
        _claims = _json.loads(_b64.urlsafe_b64decode(_pad))
        profile_id = _claims.get('profileId') or _claims.get('viewerId')
    except Exception:
        profile_id = _profile_id_from_dazn_jwt()

    session_id_base = f"{int(time.time()*1000)}-{profile_id}-{asset_id}"

    variants = [
        {"label": "current (useMT=True)",        "adParams": {"useMT": True,  "isLat": "0", "rdid": "", "idtype": "", "ppid": profile_id, "correlator": str(int(time.time()*1000))}},
        {"label": "useMT=False",                 "adParams": {"useMT": False, "isLat": "0", "rdid": "", "idtype": "", "ppid": profile_id, "correlator": str(int(time.time()*1000))}},
        {"label": "empty adParams {}",           "adParams": {}},
        {"label": "no adParams key",             "adParams": None},
        {"label": "isLat=1 (limit ad tracking)", "adParams": {"useMT": True,  "isLat": "1", "rdid": "", "idtype": "", "ppid": profile_id, "correlator": str(int(time.time()*1000))}},
    ]

    results = []
    WV_SYSTEM_ID = '{urn:mpeg:cenc:2013}ContentProtection'

    for v in variants:
        try:
            params = {
                "AppVersion": "2.10.1", "DrmType": "WIDEVINE", "Format": "MPEG-DASH",
                "PlayerId": "@dazn/peng-androidtv-core/androidtv/androidtv-rxplayer",
                "Platform": "androidtv", "Model": "AFTKA", "Secure": "true",
                "Manufacturer": "Amazon", "PlayReadyInitiator": "false",
                "Capabilities": "mta,4k,uhd,hdr,hevc",
                "AssetId": asset_id, "MtaLanguageCode": "", "LanguageCode": "en",
                "SessionId": f"{session_id_base}-{rand_hex(4)}",
            }
            body = {} if v["adParams"] is None else {"adParams": v["adParams"]}
            headers = {
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json; charset=UTF-8",
                "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; AFTKA Build/PS7267.2877N)",
                "X-Correlation-Id": str(uuid.uuid4()),
                "X-Dazn-Device": GUID,
                "Accept": "application/json",
            }
            r = curl_requests.post(DAZN_PLAY_URL, params=params, json=body, headers=headers, timeout=15, impersonate="safari17_0")
            if r.status_code != 200:
                results.append({"label": v["label"], "error": f"HTTP {r.status_code}", "body": r.text[:200]})
                time.sleep(1)
                continue

            data = r.json()
            details = data.get("PlaybackDetails", [])
            manifest_url = details[0].get("ManifestUrl", "") if details else ""

            # Fetch manifest and count periods / detect ad periods
            period_count = 0
            ad_period_count = 0
            period_info = []

            if manifest_url:
                cdn_token = details[0].get("CdnToken", {})
                cdn_header = f"{cdn_token.get('Name','')}={cdn_token.get('Value','')}" if cdn_token else ""
                mhdr = {"Cookie": cdn_header} if cdn_header else {}
                mr = requests.get(manifest_url, headers=mhdr, timeout=10)
                if mr.status_code == 200:
                    try:
                        root = ET.fromstring(mr.text)
                        ns = {'mpd': 'urn:mpeg:dash:schema:mpd:2011', 'cenc': 'urn:mpeg:cenc:2013'}
                        periods = root.findall('.//{urn:mpeg:dash:schema:mpd:2011}Period') or root.findall('.//Period')
                        period_count = len(periods)
                        for p in periods:
                            pid = p.get('id', 'no-id')
                            dur = p.get('duration', '')
                            # Check for Widevine ContentProtection anywhere in period
                            has_drm = bool(p.findall('.//{urn:mpeg:cenc:2013}ContentProtection') or
                                           p.findall('.//{urn:mpeg:cenc:2013}pssh') or
                                           p.findall('.//{urn:mpeg:cenc:2013}default_KID'))
                            # Also check any ContentProtection with widevine schemeIdUri
                            if not has_drm:
                                for cp in p.iter():
                                    if 'ContentProtection' in cp.tag:
                                        scheme = cp.get('schemeIdUri', '')
                                        if 'widevine' in scheme.lower() or 'edef8ba9' in scheme.lower():
                                            has_drm = True
                                            break
                            is_ad = not has_drm
                            if is_ad:
                                ad_period_count += 1
                            period_info.append({"id": pid, "duration": dur, "has_drm": has_drm, "is_ad": is_ad})
                    except Exception as pe:
                        period_info = [{"parse_error": str(pe)}]

            results.append({
                "label":           v["label"],
                "period_count":    period_count,
                "ad_period_count": ad_period_count,
                "periods":         period_info,
                "manifest_url":    manifest_url[:80] + "..." if len(manifest_url) > 80 else manifest_url,
                "ad_params_sent":  v["adParams"],
            })
            time.sleep(1)  # avoid hammering DAZN

        except Exception as e:
            results.append({"label": v["label"], "error": str(e)})
            time.sleep(1)

    return jsonify({"asset_id": asset_id, "results": results})


@app.route("/l3_test", methods=["GET"])
def l3_test():
    """
    Diagnostic: call DAZN Playback API with Secure=false to understand L3 CDN auth format.
    GET /l3_test?id=<asset_id>
    Returns ManifestUrl, CdnToken structure, and the result of fetching the manifest.
    """
    asset_id = request.args.get('id', '1tc0mhfzkbbti165v1rsuewtek')  # Fox League default
    try:
        bearer     = get_dazn_token()
        profile_id = _profile_id_from_dazn_jwt() or 'unknown'
        session_id = f"{int(time.time()*1000)}-{profile_id}-{asset_id}-{rand_hex(6)}"
        params = {
            "AppVersion":         "2.10.1",
            "DrmType":            "WIDEVINE",
            "Format":             "MPEG-DASH",
            "PlayerId":           "@dazn/peng-androidtv-core/androidtv/androidtv-rxplayer",
            "Platform":           "androidtv",
            "Model":              "AFTKA",
            "Secure":             "false",
            "Manufacturer":       "Amazon",
            "PlayReadyInitiator": "false",
            "Capabilities":       "mta",
            "AssetId":            asset_id,
            "MtaLanguageCode":    "",
            "LanguageCode":       "en",
            "SessionId":          session_id,
        }
        headers = {
            "Authorization":   f"Bearer {bearer}",
            "Content-Type":    "application/json; charset=UTF-8",
            "User-Agent":      "Dalvik/2.1.0 (Linux; U; Android 9; AFTKA Build/PS7267.2877N)",
            "X-Correlation-Id": str(uuid.uuid4()),
            "X-Dazn-Device":   GUID,
            "Accept":          "application/json",
            "Accept-Language": "en-AU,en;q=0.9",
        }
        r = curl_requests.post(DAZN_PLAY_URL, params=params, json={}, headers=headers, timeout=15, impersonate="safari17_0")

        result = {"dazn_status": r.status_code, "dazn_response_snippet": r.text[:2000]}

        if r.status_code == 200:
            data    = r.json()
            details = data.get("PlaybackDetails", [])
            result["num_playback_details"] = len(details)
            if details:
                best        = next((c for c in details if "cdn.indazn.com" in c.get("ManifestUrl", "")), None) or details[0]
                cdn_token   = best.get("CdnToken", {})
                manifest_url = best.get("ManifestUrl", "")
                cdn_name    = cdn_token.get('Name', '')
                cdn_val     = cdn_token.get('Value', '')
                result["manifest_url"]       = manifest_url
                result["cdn_token_name"]     = cdn_name
                result["cdn_token_value"]    = (cdn_val[:80] + "...") if len(cdn_val) > 80 else cdn_val
                result["cdn_token_all_keys"] = list(cdn_token.keys())
                result["la_url"]             = best.get("LaUrl", "")
                result["all_manifest_urls"]  = [c.get("ManifestUrl", "") for c in details]
                # Try fetching the manifest with the CDN cookie
                if manifest_url:
                    cookies = {cdn_name: cdn_val} if cdn_name else {}
                    try:
                        mreq = requests.get(manifest_url, cookies=cookies, timeout=10)
                        result["cdn_fetch_status"]       = mreq.status_code
                        result["cdn_fetch_content_type"] = mreq.headers.get("Content-Type", "")
                        result["cdn_fetch_body_start"]   = mreq.text[:300]
                    except Exception as me:
                        result["cdn_fetch_error"] = str(me)

        # Write full details to file for inspection
        with open('C:/kayo/l3_debug.json', 'w') as fh:
            _json.dump({"params": params, "dazn_status": r.status_code, "dazn_body": r.text, "result": result}, fh, indent=2)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    print("\n" + "=" * 55)
    print("  Kayo Relay Server (DAZN API)")
    print("=" * 55)
    print("  /health")
    print("  /login?user=EMAIL&password=PASS")
    print("  /manifest?user=EMAIL&password=PASS&id=ASSET_ID")
    print("  /token?id=ASSET_ID")
    print("  /license?id=ASSET_ID")
    print("  /events")
    print("  /epg?date=YYYY-MM-DD      <- VOD/replay tiles by date")
    print("  /schedule")
    print("  /schedule?format=text")
    print("  /mpd?id=ASSET_ID           <- manifest proxy (ad-filtered)")
    print("  /mpd_debug?id=ASSET_ID     <- shows period analysis without streaming")
    print("  /slate/<filename>          <- serves looping slate segments")
    print("  /slate_status              <- slate feature health + active ad breaks")
    print("  /kayo.py                   <- serves kayo.py for VPS container pull")
    print("  /cdn/<host>/<path>         <- CDN segment proxy (AU IP)")
    print("=" * 55 + "\n")

    # Attempt to pre-load slate on startup (non-fatal if missing)
    _ensure_slate_loaded()

    port = int(os.environ.get("RELAY_PORT", "5004"))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)


