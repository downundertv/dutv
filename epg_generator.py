#\!/usr/bin/env python3
"""
epg_generator.py
================
Standalone EPG generator for GitHub Actions.
Fetches Foxtel schedule from the webepg JSON API and writes:
    Foxtel/epg.xml

Run:  python epg_generator.py
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape as xml_escape

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit('ERROR: curl_cffi not installed.  pip install curl_cffi')

# ── Config ────────────────────────────────────────────────────────────────────
REGION     = '8336'
BASE_URL   = 'https://www.foxtel.com.au/webepg/ws/foxtel'
DAYS_AHEAD = 3
DELAY      = 0.35
AEST       = timezone(timedelta(hours=10))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR    = os.path.join(SCRIPT_DIR, 'Foxtel')
OUT_FILE   = os.path.join(OUT_DIR, 'epg.xml')

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, */*',
    'Referer': 'https://www.foxtel.com.au/tv-guide/',
    'Accept-Language': 'en-AU,en;q=0.9',
}

EPG_ID_MAP = {
    # ── Entertainment ────────────────────────────────────────────────────────
    'FOX': 'Fox8.au@SD',
    'FO2': 'Fox8.au@Plus2',
    'ARN': 'Arena.au@SD',
    'AR2': 'Arena.au@Plus2',              # was MISSING
    'SHC': 'Showcase.au@SD',
    'SW2': 'Showcase.au@Plus2',
    'HIT': 'Comedy.au@SD',
    'HI2': 'Comedy.au@Plus2',
    'IOI': 'Crime.au@SD',
    'IO2': 'FoxCrime.au@Plus2',
    'CIN': 'RealCrime.au@SD',             # was MISSING — Real Crime HD
    'HAL': 'UniversalTV.au@SD',
    'RLS': 'RealLife.au@SD',
    'RL2': 'RealLife.au@Plus2',
    'BXS': 'BoxSets.au@SD',
    'FKC': 'Classics.au@SD',
    'CL2': 'Classics.au@Plus2',
    'ACS': 'AussieClassics.au@SD',        # was MISSING — Aussie Classics
    'HAR': 'Seinfeld.au@SD',              # was PLACEHOLDER — Seinfeld channel
    'TRS': 'Outlander.au@SD',             # was PLACEHOLDER — Outlander channel
    'PUH': 'PULP.au@SD',                  # was PLACEHOLDER — PULP
    'NRW': 'Max.au@SD',                   # was PLACEHOLDER — Max (formerly HBO Max)
    'MTC': 'Retro.au@SD',                 # was MISSING — Retro
 
    # ── British / UK ─────────────────────────────────────────────────────────
    'UKT': 'BBCUKTV.au@Australia',
    'UK2': 'BBCUKTV.au@Plus2',            # was MISSING — UKTV+2
    'FSU': 'British.au@HD',              # was MISSING — British HD
    'FS2': 'British.au@Plus2',           # was MISSING — British +2
    'BCS': 'BritishCinema.au@SD',        # was MISSING — British Cinema
 
    # ── Movies ───────────────────────────────────────────────────────────────
    'SHO': 'MoviesPremiere.au@HD',        # was MISSING — Movies Premiere HD
    'SH2': 'MoviesPremiere.au@Plus2',     # was MISSING — Movies Premiere +2
    'MVS': 'MoviesHits.au@HD',            # was MISSING — Movies Hits HD
    'SHF': 'MoviesFamily.au@HD',          # was MISSING — Movies Family HD
    'MTF': 'MoviesFamily.au@Plus2',       # was MISSING — Movies Family +2
    'SHA': 'MoviesAction.au@HD',          # was MISSING — Movies Action HD
    'MTA': 'MoviesAction.au@Plus2',       # was MISSING — Movies Action +2
    'SHY': 'MoviesComedy.au@HD',          # was MISSING — Movies Comedy HD
    'SHD': 'MoviesRomance.au@HD',         # was MISSING — Movies Romance HD
    'MO6': 'MoviesDrama.au@HD',           # was MISSING — Movies Drama HD
    'GRR': 'MoviesGreats.au@HD',          # was MISSING — Movies Greats HD
    'K02': 'Movies4K.au@UHD',             # was MISSING — Movies 4K Ultra HD
 
    # ── Lifestyle ────────────────────────────────────────────────────────────
    'LST': 'LifeStyle.au@SD',
    'LS2': 'LifeStyle.au@Plus2',
    'FOD': 'LifestyleFood.au@SD',
    'LF2': 'LifestyleFood.au@Plus2',
    'LHO': 'LifestyleHome.au@SD',
    'DTA': 'TLC.au@SD',
    'DT2': 'TLC.au@Plus2',
 
    # ── Documentary / Factual ────────────────────────────────────────────────
    'DIS': 'DiscoveryChannel.au@SD',
    'DS2': 'DiscoveryChannel.au@Plus2',
    'DIT': 'DiscoveryTurbo.au@Australia',
    'DI2': 'DiscoveryTurbo.au@Plus2',     # was MISSING — Discovery Turbo +2
    'DID': 'InvestigationDiscovery.au@SD',
    'HST': 'RealHistory.au@HD',           # was MISSING — Real History HD
    'DPS': 'DocPlay.au@HD',               # was MISSING — DocPlay HD
    'ANI': 'AnimalPlanet.au@SD',
 
    # ── Sport ────────────────────────────────────────────────────────────────
    'FS1': 'FoxCricket.au@SD',
    'SP2': 'FoxLeague.au@SD',
    'FAF': 'FoxFooty.au@SD',
    'FS3': 'FoxSports503.au@SD',
    'FSP': 'FoxSports505.au@SD',
    'SPS': 'FoxSports506.au@SD',
    'FSS': 'FoxSports507.au@SD',          # was MISSING — Fox Sports 507 HD
    'FSN': 'FoxSportsNews.au@SD',
    'F1S': 'FoxtelOne.au@SD',
    'F12': 'FoxtelOne.au@Plus2',          # was MISSING — Foxtel One +2
    'ESP': 'ESPN.au@SD',
    'ES2': 'ESPN2.au@SD',
    'UFC': 'MainEvent.au@SD',             # was PLACEHOLDER — Main Event UFC
    'SRA': 'SkyRacing1.au@SD',            # was MISSING — Sky Racing HD
    'SR2': 'SkyRacing2.au@SD',
    'SRW': 'SkyThoroughbredCentral.au@SD', # was MISSING — SKY Tbred Cent HD
    'RTV': 'Racingcom.au@SD',             # was PLACEHOLDER — Racing.com HD
 
    # ── News ─────────────────────────────────────────────────────────────────
    'FNC': 'FoxNewsChannel.us@SD',
    'CNN': 'CNNInternational.us@AsiaPacific',
    'CNB': 'CNBCAustralia.au@SD',
    'BLM': 'BloombergTV.us@Australia',    # was MISSING — Bloomberg Television
    'ASP': 'SkyNewsExtra.au@SD',
    'SKY': 'News24.au@SD',                # was MISSING — News24
    'FXW': 'News24Weather.au@SD',         # was MISSING — News24 Weather
    'SUK': 'SkyNewsUK.uk@HD',             # was MISSING — Sky News UK HD
    'GBN': 'GBNews.uk@SD',                # was MISSING — GB News
    'NNN': 'NBCNewsNow.us@SD',            # was PLACEHOLDER — NBC NEWS NOW
    'MSN': 'MSNOW.au@SD',                 # was MISSING — MS NOW
 
    # ── International ────────────────────────────────────────────────────────
    'AJE': 'AlJazeera.qa@Arabic',
    'NHK': 'NHKWorldJapan.jp@SD',
    'ANT': 'ANT1Pacific.gr@SD',
    'RAI': 'RaiItalia.it@Australia',
    'CCC': 'CGTN.cn@SD',                  # was MISSING — CGTN
    'CCD': 'CGTNDocumentary.cn@SD',       # was MISSING — CGTN-Documentary
    'SWW': 'SBSWorldWatch.au@Sydney',
    'SBN': 'SBSViceland.au@Sydney',
    'S4B': 'SBSWorldMovies.au@Sydney',
    'DAS': 'Daystar.us@SD',               # was MISSING — Daystar
    'SLT': 'SonLife.us@SD',               # was MISSING — SonLife
 
    # ── Music / Entertainment ────────────────────────────────────────────────
    'TMF': 'MTVHits.au@SD',
    'NMU': 'NickMusic.au@SD',
    'VH1': 'ClubMTV.au@SD',
    'CMT': 'CMT.au@SD',
    'DRM': 'DreamWorksChannel.au@SD',
    'FHT': 'FashionTV.fr@SD',             # was MISSING — Fashion TV
    'NAP': 'AustralianPlayed.au@SD',      # was PLACEHOLDER — Australian Played
 
    # ── Shopping / Other ────────────────────────────────────────────────────
    'TVS': 'TVSN.au@SD',
    'EXP': 'ExpoChannel.au@SD',
    'ACC': 'GOOD.au@SD',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def epoch_ms_to_xmltv(ms):
    dt = datetime.fromtimestamp(ms / 1000.0, tz=AEST)
    return dt.strftime('%Y%m%d%H%M%S +1000')

def fetch_json(url, session, retries=3, delay=15):
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, headers=HEADERS, impersonate='chrome120', timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < retries:
                print(f'    WARN: attempt {attempt} failed ({e}), retrying in {delay}s...')
                time.sleep(delay)
            else:
                raise

def get_events(slug, date_str, session):
    url = f'{BASE_URL}/channel/{slug}/{date_str}/0000?regionId={REGION}'
    try:
        return fetch_json(url, session).get('events', [])
    except Exception as e:
        print(f'    WARN: {slug} {date_str}: {e}')
        return []

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(AEST)
    print(f'[{now.strftime("%Y-%m-%d %H:%M:%S AEST")}] Foxtel EPG generator starting...')

    session = cffi_requests.Session()

    # Channel list
    print('  Fetching channel list...', end=' ', flush=True)
    data = fetch_json(f'{BASE_URL}/channel/FOX8-HD/FOX?regionId={REGION}', session)
    channels = data.get('channels', [])
    print(f'{len(channels)} channels')

    # Dates
    dates = [(now + timedelta(days=i)).strftime('%Y/%m/%d') for i in range(DAYS_AHEAD + 1)]
    print(f'  Dates: {dates[0]} to {dates[-1]}')

    # Events per channel
    channel_events = {}
    for idx, ch in enumerate(channels):
        tag  = ch.get('channelTag', '')
        slug = ch.get('url', '')
        name = ch.get('name', tag)
        if not (tag and slug):
            continue
        print(f'  [{idx+1:3d}/{len(channels)}] {name:<35s} ({tag}) ', end='', flush=True)
        seen = {}
        for d in dates:
            for ev in get_events(slug, d, session):
                eid = ev.get('eventId')
                if eid:
                    seen[eid] = ev
            time.sleep(DELAY)
        evs = sorted(seen.values(), key=lambda e: e.get('scheduledDate', 0))
        channel_events[tag] = evs
        print(f'{len(evs)} events')

    # Build XMLTV
    print('  Building XMLTV...', end=' ', flush=True)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE tv SYSTEM "xmltv.dtd">',
        '<tv generator-info-name="Foxtel EPG (github-actions)">',
    ]
    for ch in channels:
        tag     = ch.get('channelTag', '')
        xid     = EPG_ID_MAP.get(tag, tag)
        name    = xml_escape(ch.get('name', tag))
        imgs    = ch.get('channelImages', {})
        logo    = xml_escape(imgs.get('hq') or imgs.get('medium') or '')
        parts.append(f'  <channel id="{xml_escape(xid)}">')
        parts.append(f'    <display-name>{name}</display-name>')
        if logo:
            parts.append(f'    <icon src="{logo}"/>')
        parts.append('  </channel>')

    for ch in channels:
        tag    = ch.get('channelTag', '')
        xid    = EPG_ID_MAP.get(tag, tag)
        events = channel_events.get(tag, [])
        ch_esc = xml_escape(xid)
        for i, ev in enumerate(events):
            sms = ev.get('scheduledDate')
            if not sms:
                continue
            ems = events[i+1].get('scheduledDate', sms+1_800_000) if i+1 < len(events) else sms+1_800_000
            title  = xml_escape(ev.get('programTitle') or 'Unknown')
            ep_t   = ev.get('episodeTitle', '')
            ep_n   = ev.get('episodeNumber', '')
            ser_n  = ev.get('seriesNumber', '')
            rating = ev.get('parentalRating', '')
            img    = ev.get('imageUrl', '')
            movie  = ev.get('isMovie', False)
            prem   = ev.get('premiereInd', False)
            parts.append(f'  <programme start="{epoch_ms_to_xmltv(sms)}" stop="{epoch_ms_to_xmltv(ems)}" channel="{ch_esc}">')
            parts.append(f'    <title lang="en">{title}</title>')
            if ep_t:
                parts.append(f'    <sub-title lang="en">{xml_escape(ep_t)}</sub-title>')
            if ser_n and ep_n:
                try:
                    s, e = int(ser_n), int(ep_n)
                    parts.append(f'    <episode-num system="onscreen">S{s:02d}E{e:02d}</episode-num>')
                    parts.append(f'    <episode-num system="xmltv_ns">{s-1}.{e-1}.0/1</episode-num>')
                except (ValueError, TypeError):
                    pass
            elif ep_n:
                try:
                    parts.append(f'    <episode-num system="onscreen">E{int(ep_n):02d}</episode-num>')
                except (ValueError, TypeError):
                    pass
            if movie:  parts.append('    <category lang="en">Movie</category>')
            if prem:   parts.append('    <premiere/>')
            if img:    parts.append(f'    <icon src="{xml_escape(img)}"/>')
            if rating: parts.append(f'    <rating system="AUS"><value>{xml_escape(rating)}</value></rating>')
            parts.append('  </programme>')
    parts.append('</tv>')

    os.makedirs(OUT_DIR, exist_ok=True)
    content = '\n'.join(parts)
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

    total = sum(len(v) for v in channel_events.values())
    kb    = len(content) // 1024
    print(f'done.  {total} events, {kb} KB')
    print(f'  Written: {OUT_FILE}')

if __name__ == '__main__':
    main()
