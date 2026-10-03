#!/usr/bin/env python3
"""
epg_generator.py
================
Standalone EPG generator for GitHub Actions.

Source: DAZN discovery "Livetvschedule" Rail (brand=foxtelgnc). This is the same
backend that feeds the live streams, so channel ids line up with the relay and the
schedule matches what is actually streaming. The old foxtel.com.au/webepg endpoint
was abandoned by Foxtel (it now returns `events: []` for every channel/date).

The Rail only exposes **today + 3 days ahead** (startDay is clamped to 1 server-side;
there is no historical listing API). To support catchup/rewind, which needs guide
entries for programmes that already aired, this script MERGES each fresh snapshot into
the previously-committed Foxtel/epg.xml and keeps RETAIN_PAST_DAYS of history. Run
daily (or more often) and the back-catalogue accumulates into a rolling window.

Writes: Foxtel/epg.xml

Run:  python epg_generator.py
"""

import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape as xml_escape

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    sys.exit('ERROR: curl_cffi not installed.  pip install curl_cffi')

# ── Config ────────────────────────────────────────────────────────────────────
RAIL_URL   = 'https://ruleset-router-foxtelgnc.discovery.indazn.com/jp/v1/Rail'
RAIL_PARAMS = {
    'platform': 'web',
    'id': 'Livetvschedule',
    'country': 'au',
    'brand': 'foxtelgnc',
    'languageCode': 'en',
    'startDay': '1',   # server clamps to 1 (today); past days are not available
    'endDay': '3',     # today + 3 days ahead (max the backend allows)
}
MAX_PAGES        = 10     # safety bound; ~5 pages (20 tiles each) at time of writing
RETAIN_PAST_DAYS = 8      # keep aired programmes this long (matches relay catchup clamp)
DELAY            = 0.25   # politeness delay between page fetches

# Foxtel channel-logo CDN (keyed by channel tag) — stable, already used by the site.
_FOXTEL_LOGO = 'https://www.foxtel.com.au/content/dam/foxtel/shared/channel/{c}/{c}_425x243.png'

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR    = os.path.join(SCRIPT_DIR, 'Foxtel')
OUT_FILE   = os.path.join(OUT_DIR, 'epg.xml')

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, */*',
    'Origin': 'https://foxtelgo.foxtel.com.au',
    'Referer': 'https://foxtelgo.foxtel.com.au/',
    'Accept-Language': 'en-AU,en;q=0.9',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def iso_to_dt(s):
    """Parse an ISO-8601 instant (…Z or …+hh:mm) to an aware UTC datetime."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None

def dt_to_xmltv(dt):
    """Aware datetime -> XMLTV timestamp in UTC (DST-proof; clients localise)."""
    return dt.astimezone(timezone.utc).strftime('%Y%m%d%H%M%S +0000')

def xmltv_to_dt(s):
    """Parse an XMLTV 'YYYYMMDDHHMMSS +ZZZZ' timestamp to an aware UTC datetime."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), '%Y%m%d%H%M%S %z').astimezone(timezone.utc)
    except (ValueError, TypeError):
        try:  # tolerate a missing offset
            return datetime.strptime(s.strip()[:14], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

def channel_tag(tile):
    """Derive the Foxtel channel tag (playlist tvg-id) from a tile's entitlements."""
    for e in tile.get('EntitlementIds', []) or []:
        if e.startswith('e_'):
            return e[2:].upper()
    # fall back to the eventId prefix (e.g. F1S182468920 -> F1S)
    eid = ((tile.get('LinearSchedule') or {}).get('Now') or {}) \
            .get('AdditionalMetadata', {}).get('eventId', '')
    return eid[:3].upper() if eid else None

def fetch_json(session, params, retries=3, delay=15):
    for attempt in range(1, retries + 1):
        try:
            r = session.get(RAIL_URL, params=params, headers=HEADERS,
                            impersonate='chrome120', timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt < retries:
                print(f'    WARN: attempt {attempt} failed ({e}), retrying in {delay}s...')
                time.sleep(delay)
            else:
                raise


# ── Fetch live schedule from DAZN Rail ─────────────────────────────────────────

def fetch_schedule(session):
    """Return (channels, programmes).

    channels:   dict tag -> {'name', 'logo', 'number'}
    programmes: dict tag -> list of programme dicts (deduped, sorted by start)
    """
    channels = {}
    programmes = {}

    for page in range(1, MAX_PAGES + 1):
        params = dict(RAIL_PARAMS, page=str(page))
        data = fetch_json(session, params)
        tiles = data.get('Tiles') or []
        if not tiles:
            break
        print(f'    page {page}: {len(tiles)} channels')
        for tile in tiles:
            tag = channel_tag(tile)
            if not tag:
                continue
            ls = tile.get('LinearSchedule') or {}
            channels[tag] = {
                'name':   tile.get('Title', tag),
                'logo':   _FOXTEL_LOGO.format(c=tag),
                'number': ls.get('ChannelNumber'),
            }
            evs = [ls.get('Now'), ls.get('Next')] + (ls.get('Later') or [])
            seen = {}
            for ev in evs:
                if not ev:
                    continue
                start = iso_to_dt(ev.get('Start'))
                stop  = iso_to_dt(ev.get('End'))
                if not start or not stop or stop <= start:
                    continue
                md = ev.get('AdditionalMetadata') or {}
                key = md.get('eventId') or start.isoformat()
                seen[key] = {
                    'start':   start,
                    'stop':    stop,
                    'title':   ev.get('Title') or 'Unknown',
                    'episode': ev.get('EpisodeTitle') or '',
                    'desc':    ev.get('Description') or '',
                    'genres':  [g.get('name') for g in (ev.get('Genre') or []) if g.get('name')],
                    'movie':   (ev.get('ProgramType') == 'MOVIE'),
                    'live':    bool(ev.get('IsLive')),
                    'year':    ev.get('EventYear') or '',
                    'rating':  ev.get('TvRating') or '',
                    'season':  md.get('seasonNumber') or '',
                    'epnum':   md.get('episodeNumber') or '',
                }
            programmes[tag] = sorted(seen.values(), key=lambda p: p['start'])
        if not (data.get('Pagination') or {}).get('hasNextPage'):
            break
        time.sleep(DELAY)

    return channels, programmes


# ── Merge previously-committed epg.xml (accumulate catchup history) ────────────

def load_previous():
    """Return (channels, programmes) parsed from the existing OUT_FILE, if any."""
    channels, programmes = {}, {}
    if not os.path.exists(OUT_FILE):
        return channels, programmes
    try:
        tree = ET.parse(OUT_FILE)
    except Exception as e:
        print(f'  WARN: could not parse existing EPG ({e}); starting fresh')
        return channels, programmes
    root = tree.getroot()
    for ch in root.findall('channel'):
        tag = ch.get('id')
        if not tag:
            continue
        name = (ch.findtext('display-name') or tag).strip()
        icon = ch.find('icon')
        channels[tag] = {
            'name':   name,
            'logo':   icon.get('src') if icon is not None else _FOXTEL_LOGO.format(c=tag),
            'number': None,
        }
    for pr in root.findall('programme'):
        tag = pr.get('channel')
        start = xmltv_to_dt(pr.get('start'))
        stop  = xmltv_to_dt(pr.get('stop'))
        if not tag or not start or not stop:
            continue
        genres = [c.text for c in pr.findall('category') if c.text]
        season = epnum = ''
        for en in pr.findall('episode-num'):
            if en.get('system') == 'onscreen' and en.text:
                t = en.text.strip().upper()
                if 'S' in t and 'E' in t:
                    try:
                        season = str(int(t.split('S')[1].split('E')[0]))
                        epnum  = str(int(t.split('E')[1]))
                    except (ValueError, IndexError):
                        pass
        date_el = pr.findtext('date') or ''
        programmes.setdefault(tag, []).append({
            'start':   start,
            'stop':    stop,
            'title':   (pr.findtext('title') or 'Unknown').strip(),
            'episode': (pr.findtext('sub-title') or '').strip(),
            'desc':    (pr.findtext('desc') or '').strip(),
            'genres':  [g for g in genres if g and g != 'Movie'],
            'movie':   any(g == 'Movie' for g in genres),
            'live':    pr.find('live') is not None,
            'year':    date_el.strip(),
            'rating':  (pr.findtext('rating/value') or '').strip(),
            'season':  season,
            'epnum':   epnum,
        })
    return channels, programmes


def merge(old, new, now):
    """Union old+new programme lists per channel, dedupe by start, drop stale."""
    cutoff = now - timedelta(days=RETAIN_PAST_DAYS)
    merged = {}
    for tag in set(old) | set(new):
        by_start = {}
        for p in old.get(tag, []):          # old first…
            by_start[p['start']] = p
        for p in new.get(tag, []):          # …fresh wins on conflict
            by_start[p['start']] = p
        kept = [p for p in by_start.values() if p['stop'] >= cutoff]
        if kept:
            merged[tag] = sorted(kept, key=lambda p: p['start'])
    return merged


# ── Build XMLTV ────────────────────────────────────────────────────────────────

def build_xml(channels, programmes):
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE tv SYSTEM "xmltv.dtd">',
        '<tv generator-info-name="Foxtel EPG (DAZN rail, github-actions)">',
    ]
    for tag in sorted(channels):
        ch = channels[tag]
        parts.append(f'  <channel id="{xml_escape(tag)}">')
        parts.append(f'    <display-name>{xml_escape(ch["name"])}</display-name>')
        if ch.get('logo'):
            parts.append(f'    <icon src="{xml_escape(ch["logo"])}"/>')
        parts.append('  </channel>')

    for tag in sorted(programmes):
        ch_esc = xml_escape(tag)
        for p in programmes[tag]:
            parts.append(
                f'  <programme start="{dt_to_xmltv(p["start"])}" '
                f'stop="{dt_to_xmltv(p["stop"])}" channel="{ch_esc}">'
            )
            parts.append(f'    <title lang="en">{xml_escape(p["title"])}</title>')
            if p['episode']:
                parts.append(f'    <sub-title lang="en">{xml_escape(p["episode"])}</sub-title>')
            if p['desc']:
                parts.append(f'    <desc lang="en">{xml_escape(p["desc"])}</desc>')
            if p['season'] and p['epnum']:
                try:
                    s, e = int(p['season']), int(p['epnum'])
                    parts.append(f'    <episode-num system="onscreen">S{s:02d}E{e:02d}</episode-num>')
                    parts.append(f'    <episode-num system="xmltv_ns">{s-1}.{e-1}.0/1</episode-num>')
                except (ValueError, TypeError):
                    pass
            elif p['epnum']:
                try:
                    parts.append(f'    <episode-num system="onscreen">E{int(p["epnum"]):02d}</episode-num>')
                except (ValueError, TypeError):
                    pass
            for g in p['genres']:
                parts.append(f'    <category lang="en">{xml_escape(g)}</category>')
            if p['movie']:
                parts.append('    <category lang="en">Movie</category>')
            if p['year']:
                parts.append(f'    <date>{xml_escape(str(p["year"]))}</date>')
            if p['live']:
                parts.append('    <live/>')
            if p['rating']:
                parts.append(f'    <rating system="AUS"><value>{xml_escape(p["rating"])}</value></rating>')
            parts.append('  </programme>')

    parts.append('</tv>')
    return '\n'.join(parts)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    print(f'[{now.strftime("%Y-%m-%d %H:%M:%S UTC")}] Foxtel EPG generator (DAZN rail) starting...')

    session = cffi_requests.Session()

    print('  Fetching live schedule (today + 3 days)...')
    new_ch, new_pr = fetch_schedule(session)
    fresh_total = sum(len(v) for v in new_pr.values())
    print(f'  Fetched {len(new_ch)} channels, {fresh_total} fresh programmes')

    print('  Merging with committed history...')
    old_ch, old_pr = load_previous()
    print(f'  Previous file: {len(old_ch)} channels, {sum(len(v) for v in old_pr.values())} programmes')

    # Channel metadata: prefer fresh (has live name/number), keep old-only entries.
    channels = dict(old_ch)
    channels.update(new_ch)

    programmes = merge(old_pr, new_pr, now)
    # Only emit channels that carry programmes or are in the fresh lineup; this drops
    # stale channel nodes inherited from an older file that no longer have listings.
    keep = set(programmes) | set(new_ch)
    channels = {t: channels.get(t, {'name': t, 'logo': _FOXTEL_LOGO.format(c=t)})
                for t in keep}

    print('  Building XMLTV...', end=' ', flush=True)
    content = build_xml(channels, programmes)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

    total = sum(len(v) for v in programmes.values())
    kb = len(content) // 1024
    print(f'done.  {len(channels)} channels, {total} programmes, {kb} KB')
    print(f'  Written: {OUT_FILE}')

    if total == 0:
        sys.exit('ERROR: no programmes produced — refusing to publish empty EPG')


if __name__ == '__main__':
    main()
