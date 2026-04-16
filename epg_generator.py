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
    'HAR': 'HAR', 'TRS': 'TRS', 'UFC': 'UFC',
    'RTV': 'RTV', 'NRW': 'NRW', 'NAP': 'NAP',
    'NNN': 'NNN', 'PUH': 'PUH',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def epoch_ms_to_xmltv(ms):
    dt = datetime.fromtimestamp(ms / 1000.0, tz=AEST)
    return dt.strftime('%Y%m%d%H%M%S +1000')

def fetch_json(url, session):
    r = session.get(url, headers=HEADERS, impersonate='chrome120', timeout=20)
    r.raise_for_status()
    return r.json()

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
