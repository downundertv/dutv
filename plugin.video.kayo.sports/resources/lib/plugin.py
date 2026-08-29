import codecs
import os

import arrow
import xbmcgui
from kodi_six import xbmc

from slyguy import plugin, gui, settings, userdata, signals, inputstream
from slyguy.log import log
from slyguy.exceptions import PluginError
from slyguy.constants import (
    PLAY_FROM_TYPES, PLAY_FROM_ASK, PLAY_FROM_LIVE, PLAY_FROM_START,
    ROUTE_RESUME_TAG, ROUTE_LIVE_TAG, LIVE_HEAD,
)

from .api import API
from .language import _
from .constants import *

# Set to False to restore Logout, Profile and Settings in the home menu
KIOSK_MODE = True

api = API()

# Addon root path derived from this file's location (resources/lib/plugin.py -> ../../..)
_ADDON_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ICON_PATH  = os.path.join(_ADDON_PATH, 'icon.png')

@signals.on(signals.BEFORE_DISPATCH)
def before_dispatch():
    try:
        api.new_session()
        plugin.logged_in = api.logged_in
    except Exception:
        plugin.logged_in = False


# ------------------------------------------------------------------
# Home
# ------------------------------------------------------------------

@plugin.route('')
def home(**kwargs):
    folder = plugin.Folder(cacheToDisc=False)

    if not api.logged_in:
        folder.add_item(label=_(_.LOGIN, _bold=True), path=plugin.url_for(login), bookmark=False)
    else:
        folder.add_item(label=u'[B]Live & Upcoming[/B]',  path=plugin.url_for(live_events))
        folder.add_item(label=u'[B]Fixtures[/B]',         path=plugin.url_for(fixtures))
        folder.add_item(label=u'[B]Shows[/B]',            path=plugin.url_for(dazn_shows))
        folder.add_item(label=u'[B]Sports[/B]',            path=plugin.url_for(sport_index))
        folder.add_item(label=u'[B]Recent Replays[/B]',  path=plugin.url_for(recent_replays_flat))
        folder.add_item(label=u'[B]Minis[/B]',           path=plugin.url_for(recent_minis_flat))
        folder.add_item(label=u'[B]Highlights[/B]',      path=plugin.url_for(recent_highlights_flat))
        folder.add_item(label=u'[B]Browse by Date[/B]',  path=plugin.url_for(recent_replays))
        folder.add_item(label=_(_.LIVE_CHANNELS,      _bold=True), path=plugin.url_for(live))
        folder.add_item(label=_(_.SEARCH,             _bold=True), path=plugin.url_for(search))

        if settings.getBool('bookmarks', True):
            folder.add_item(label=_(_.BOOKMARKS, _bold=True), path=plugin.url_for(plugin.ROUTE_BOOKMARKS), bookmark=False)

        if not KIOSK_MODE:
            folder.add_item(
                label=_.SELECT_PROFILE,
                path=plugin.url_for(select_profile),
                art={'thumb': userdata.get('avatar')},
                info={'plot': userdata.get('profile_name')},
                bookmark=False,
            )
            folder.add_item(label=_.LOGOUT, path=plugin.url_for(logout), bookmark=False)

    if not KIOSK_MODE:
        folder.add_item(label=_.SETTINGS, path=plugin.url_for(plugin.ROUTE_SETTINGS), bookmark=False)
    return folder


# ------------------------------------------------------------------
# Login / logout
# ------------------------------------------------------------------

@plugin.route()
def login(**kwargs):
    options = [
        [_.EMAIL_PASSWORD,    _email_password],
        [_.DEVICE_CODE,       _device_code],
        ['Enter DAZN Token',  _manual_dazn_token],
    ]
    index = gui.context_menu([x[0] for x in options])
    if index == -1 or not options[index][1]():
        return
    _select_profile()
    gui.refresh()


def _device_code():
    try:
        data = api.device_code()
    except Exception as e:
        gui.ok(_.LOGIN_ERROR, heading=_.DEVICE_CODE)
        return False

    monitor = xbmc.Monitor()
    start   = time.time()

    with gui.progress(_(_.DEVICE_LINK_STEPS, url=CODE_URL, code=data['user_code']), heading=_.DEVICE_CODE) as progress:
        while (time.time() - start) < data['expires_in']:
            for i in range(data['interval']):
                if progress.iscanceled() or monitor.waitForAbort(1):
                    return False
                progress.update(int(((time.time() - start) / data['expires_in']) * 100))
            if api.device_login(data['device_code']):
                return True
    return False


def _email_password():
    username = gui.input(_.ASK_EMAIL, default=userdata.get('username', '')).strip()
    if not username:
        return False
    userdata.set('username', username)

    password = gui.input(_.ASK_PASSWORD, hide_input=True).strip()
    if not password:
        return False

    try:
        api.login(username=username, password=password)
    except Exception as e:
        raise PluginError(str(e))

    return True


def _manual_dazn_token(skip_intro=False):
    if not skip_intro:
        gui.ok(
            'This option lets you paste a DAZN token obtained from your browser.\n\n'
            'Use this if email/password login cannot exchange the token automatically.',
            heading='Enter DAZN Token',
        )

    gui.ok(
        '1. On a PC or phone, go to kayosports.com.au and log in\n\n'
        '2. Press F12 (PC) or open browser DevTools\n\n'
        '3. Click the Console tab\n\n'
        '4. Paste this and press Enter:\n'
        "JSON.parse(localStorage.getItem('daznAuthAccessTokenStore'))?.data?.accessToken?.token\n\n"
        '5. Copy the long eyJ... value that appears\n\n'
        '6. Press OK and paste it below.',
        heading='How to Get Your DAZN Token',
    )

    token = gui.input('Paste DAZN Token (eyJ...)', '').strip()
    if not token:
        return False
    if not token.startswith('eyJ'):
        gui.ok('That does not look like a valid token (should start with eyJ). Try again.', heading='Invalid Token')
        return False

    api.set_dazn_token(token)
    return True


@plugin.route()
@plugin.login_required()
def logout(**kwargs):
    if not gui.yes_no(_.LOGOUT_YES_NO):
        return
    api.logout()
    gui.refresh()


# ------------------------------------------------------------------
# Profile
# ------------------------------------------------------------------

@plugin.route()
@plugin.login_required()
def select_profile(**kwargs):
    _select_profile()
    gui.refresh()


def _select_profile():
    try:
        profiles = api.profiles()
    except Exception:
        return

    avatars = {}
    try:
        for av in api.profile_avatars():
            avatars[av['id']] = av['url']
    except Exception:
        pass

    options = []
    values  = []
    default = -1

    for index, profile in enumerate(profiles):
        profile['avatar'] = avatars.get(profile.get('avatar_id', ''))
        values.append(profile)
        options.append(plugin.Item(label=profile['name'], art={'thumb': profile['avatar']}))
        if profile['id'] == userdata.get('profile_id'):
            default = index
            _set_profile(profile, notify=False)

    index = gui.select(_.SELECT_PROFILE, options=options, preselect=default, useDetails=True)
    if index < 0:
        return
    _set_profile(values[index])


def _set_profile(profile, notify=True):
    userdata.set('avatar',       profile.get('avatar'))
    userdata.set('profile_name', profile.get('name'))
    userdata.set('profile_id',   profile.get('id'))
    if notify:
        gui.notification(_.PROFILE_ACTIVATED, heading=profile.get('name'), icon=profile.get('avatar'))


# ------------------------------------------------------------------
# Live channels
# ------------------------------------------------------------------

def _get_live_channels():
    live_data = api.channel_data()
    channels  = []
    for name, asset_id in LIVE_CHANNELS.items():
        ch = {'id': asset_id, 'name': name, 'chno': None, 'epg': [], 'logo': None}
        if asset_id in live_data:
            ch['chno'] = live_data[asset_id].get('chno')
            ch['epg']  = live_data[asset_id].get('epg', [])
            ch['logo'] = live_data[asset_id].get('logo')
        # Fall back to our hardcoded logo map if mjh.nz has no logo
        if not ch['logo']:
            ch['logo'] = CHANNEL_LOGO_MAP.get(asset_id, '')
        channels.append(ch)
    return channels


def _get_4k_channels():
    """Return permanent 4K channel data enriched with current Rail events.

    Always returns one entry per PERMANENT_4K_CHANNELS regardless of whether
    a 4K game is live.  Each entry contains:
      channel_id, name, chno, logo, linear_asset, live_event, upcoming
    """
    try:
        events = api.events()
    except Exception:
        events = []

    # Build per-channel-id lookup: live and upcoming 4K events
    live_4k     = {}   # channel_id -> event dict
    upcoming_4k = {}   # channel_id -> [event, ...]
    for ev in events:
        if not ev.get('is_4k'):
            continue
        cid = ev.get('channel_id', '')
        if ev.get('type') == 'live':
            live_4k[cid] = ev
        else:
            upcoming_4k.setdefault(cid, []).append(ev)

    result = []
    for channel_id, display_name, chno in PERMANENT_4K_CHANNELS:
        linear_asset = CHANNEL_ID_TO_ASSET.get(channel_id, '')
        result.append({
            'channel_id':   channel_id,
            'name':         display_name,
            'chno':         chno,
            'logo':         CHANNEL_LOGO_MAP.get(linear_asset, ''),
            'linear_asset': linear_asset,
            'live_event':   live_4k.get(channel_id),       # None when no live 4K game
            'upcoming':     upcoming_4k.get(channel_id, []),
        })
    return result


@plugin.route()
def live(**kwargs):
    folder     = plugin.Folder(_.LIVE_CHANNELS)
    show_chnos = settings.getBool('show_chnos', True)
    show_epg   = settings.getBool('show_epg', True)

    # --- Permanent 4K channels (always shown at top, live or not) ---
    for ch4k in _get_4k_channels():
        ev = ch4k['live_event']
        if ev:
            label = u'[COLOR cyan][4K LIVE][/COLOR]  {} — {}'.format(ev.get('title', ''), ch4k['name'])
            plot  = u'[COLOR lime][LIVE NOW][/COLOR]\n{}\n{}'.format(ev.get('sport', ''), ev.get('channel', ''))
        else:
            label = u'[COLOR yellow][4K][/COLOR]  ' + ch4k['name']
            if ch4k['upcoming']:
                nxt = ch4k['upcoming'][0]
                try:
                    t = arrow.get(nxt['time']).to('local').format('h:mma')
                except Exception:
                    t = ''
                label += u'  — Next: {} [{}]'.format(nxt.get('title', ''), t)
            plot = u'\n'.join(
                u'[{}] {} [4K]'.format(
                    arrow.get(e['time']).to('local').format('h:mma') if e.get('time') else '',
                    e.get('title', ''))
                for e in ch4k['upcoming'][:4]
            ) if ch4k['upcoming'] else u'No 4K events scheduled'

        # Always play via the permanent linear channel slot so the stream continues
        # after the event ends. The relay upgrades to the live 4K event asset_id
        # transparently via _get_live_4k_event_for_channel when a match is on.
        play_id = ch4k['linear_asset']

        folder.add_items(plugin.Item(
            label=label,
            art={'thumb': ch4k['logo']},
            info={'plot': plot, 'mediatype': 'video'},
            path=plugin.url_for(play, id=play_id, channel_id=ch4k['channel_id'], upgrade_4k='1', _is_live=True),
            playable=True,
        ))

    if show_epg:
        now = arrow.now()

    for ch in _get_live_channels():
        label = ch['name']
        if ch['chno'] and show_chnos:
            label = _(_.LIVE_CHNO, chno=ch['chno'], label=label)

        plot = u''
        if show_epg and ch['epg']:
            count = 0
            for index, row in enumerate(ch['epg']):
                start = arrow.get(row[0])
                try:    stop = arrow.get(ch['epg'][index + 1][0])
                except: stop = start.shift(hours=1)
                if now < stop or start > now:
                    plot += u'[{}] {}\n'.format(start.to('local').format('h:mma'), row[1])
                    count += 1
                    if count == 5:
                        break

        item = plugin.Item(
            label=label,
            art={'thumb': ch['logo']},
            info={'plot': plot.strip() or None, 'mediatype': 'video'},
            path=plugin.url_for(play, id=ch['id'], play_type=PLAY_FROM_LIVE, _is_live=True),
            playable=True,
        )
        folder.add_items(item)

    return folder


# ------------------------------------------------------------------
# Live & Upcoming events (via relay DAZN Rail API)
# ------------------------------------------------------------------

@plugin.route()
@plugin.login_required()
def live_events(**kwargs):
    folder = plugin.Folder('Live & Upcoming')
    try:
        evts = api.events()

        now = arrow.utcnow()

        live_items     = []
        upcoming_items = []

        for ev in evts:
            asset_id = ev.get('asset_id', '')
            if not asset_id:
                continue

            try:
                start = arrow.get(ev['time'])
            except Exception:
                start = now

            sport      = ev.get('sport', '')
            channel    = ev.get('channel', '')
            channel_id = ev.get('channel_id', '')
            title      = ev.get('title', '')
            is_live    = ev.get('type') == 'live'

            # Channel logo: map channel_id → linear asset_id → logo URL
            linear_asset = CHANNEL_ID_TO_ASSET.get(channel_id, '')
            logo = CHANNEL_LOGO_MAP.get(linear_asset, '')

            badge = '[COLOR lime][LIVE][/COLOR]  ' if is_live else '[{}]  '.format(
                start.to('local').format('ddd h:mma')
            )
            label = '{}{} — {}'.format(badge, title, channel)
            if ev.get('is_4k'):
                label = u'[COLOR cyan][4K][/COLOR]  ' + label
            plot  = u'{sport}\n{channel}'.format(sport=sport, channel=channel)
            if ev.get('is_4k'):
                plot += u'\n[COLOR cyan]4K available[/COLOR]'

            thumb = ev.get('thumb') or logo
            if is_live:
                play_kwargs = dict(id=asset_id, start_from=1, play_type=PLAY_FROM_ASK, _is_live=True)
                if ev.get('is_4k'):
                    play_kwargs['upgrade_4k'] = '1'
                play_path = plugin.url_for(play, **play_kwargs)
            else:
                play_kwargs = dict(id=asset_id)
                if ev.get('is_4k'):
                    play_kwargs['upgrade_4k'] = '1'
                play_path = plugin.url_for(play, **play_kwargs)
            item = plugin.Item(
                label=label,
                art={'thumb': thumb, 'fanart': ev.get('fanart', ''), 'icon': logo},
                info={'plot': plot, 'mediatype': 'video'},
                path=play_path,
                playable=True,
            )

            if is_live:
                live_items.append(item)
            else:
                upcoming_items.append((start, item))

        folder.add_items(live_items)

        upcoming_items.sort(key=lambda x: x[0])
        folder.add_items([i for _, i in upcoming_items])
    except Exception:
        pass

    return folder


# ------------------------------------------------------------------
# Browse by Date — via DAZN EPG API
# ------------------------------------------------------------------

@plugin.route()
@plugin.login_required()
def recent_replays(**kwargs):
    folder = plugin.Folder('Browse by Date')
    now = arrow.utcnow()
    for days_ago in range(21):
        day   = now.shift(days=-days_ago)
        date  = day.format('YYYY-MM-DD')
        label = day.to('local').format('ddd D MMM')
        if days_ago == 0:
            label = u'Today — {}'.format(label)
        elif days_ago == 1:
            label = u'Yesterday — {}'.format(label)
        folder.add_item(
            label=label,
            path=plugin.url_for(epg_day, date=date),
        )
    return folder


# ------------------------------------------------------------------
# Sport & Competition browsing — DAZN EPG tiles organised by section
# ------------------------------------------------------------------

# Maps DAZN raw Sport.Title values to nice display labels.
_SPORT_LABELS = {
    'Australian Rules Football': 'AFL',
    'Rugby League':              'Rugby League',
    'Rugby Union':               'Rugby Union',
    'Cricket':                   'Cricket',
    'Basketball':                'Basketball',
    'Football':                  'Football',
    'Tennis':                    'Tennis',
    'Ice Hockey':                'Ice Hockey',
    'Motor Sport':               'Motorsport',
    'Motorsport':                'Motorsport',
    'Golf':                      'Golf',
    'Boxing':                    'Boxing',
    'Mixed Martial Arts':        'MMA',
    'MMA':                       'MMA',
    'Cycling':                   'Cycling',
    'Cycling BMX':               'Cycling',
    'Netball':                   'Netball',
    'Surfing':                   'Surfing',
    'Swimming':                  'Swimming',
    'Athletics':                 'Athletics',
    'Snooker':                   'Snooker',
    'Baseball':                  'Baseball',
    'American Football':         'American Football',
    'Darts':                     'Darts',
    'Bowls':                     'Bowls',
    'Equestrian':                'Equestrian',
    'Table Tennis':              'Table Tennis',
    'Squash':                    'Squash',
    'Sailing':                   'Sailing',
    'Pool':                      'Pool',
    'OTHER':                     'Other',
}

# Ordered section definitions: (id, display label)
_SECTIONS = [
    ('live_upcoming', u'Live & Upcoming'),
    ('replays',       u'Full Replays'),
    ('minis',         u'Minis'),
    ('highlights',    u'Highlights & Bites'),
]


def _filter_tiles(tiles, section):
    if section == 'live_upcoming':
        return [t for t in tiles if t.get('type') == 'UpComing']
    if section == 'replays':
        return [t for t in tiles if t.get('type') == 'CatchUp']
    if section == 'minis':
        return [t for t in tiles if t.get('type') == 'Highlights'
                and t.get('display_type') == 'MinisHighlights']
    if section == 'highlights':
        return [t for t in tiles if t.get('type') == 'Highlights'
                and t.get('display_type') != 'MinisHighlights']
    return tiles


def _sort_tiles(tiles, section):
    if section == 'live_upcoming':
        # Live (started) first, then upcoming ascending
        now = arrow.utcnow()
        def _live_key(t):
            try:
                s = arrow.get(t['start'])
                return (0 if s <= now else 1, t.get('start', ''))
            except Exception:
                return (1, t.get('start', ''))
        tiles.sort(key=_live_key)
    else:
        # Most recent first for replays/minis/highlights
        tiles.sort(key=lambda t: t.get('start', ''), reverse=True)
    return tiles


def _section_menu(folder, tiles, route_fn, **route_kwargs):
    """Add section sub-menu items to folder, showing only sections with content."""
    for sec_id, sec_label in _SECTIONS:
        count = len(_filter_tiles(tiles, sec_id))
        if count == 0:
            continue
        folder.add_item(
            label=u'{} ({})'.format(sec_label, count),
            path=plugin.url_for(route_fn, section=sec_id, **route_kwargs),
        )


def _render_tile(tile, section=''):
    """Build a plugin.Item from an EPG tile dict."""
    asset_id    = tile.get('asset_id', '')
    tile_type   = tile.get('type', '')
    title       = tile.get('title', '')
    is_upcoming = tile_type == 'UpComing'

    if section == 'live_upcoming':
        try:
            start = arrow.get(tile['start'])
            if start <= arrow.utcnow():
                badge = u'[COLOR lime][LIVE][/COLOR]  '
            else:
                badge = u'[COLOR gray][{}][/COLOR]  '.format(
                    start.to('local').format('ddd D MMM, h:mma'))
        except Exception:
            badge = u'[COLOR gray][UPCOMING][/COLOR]  '
    else:
        try:
            badge = u'[{}]  '.format(arrow.get(tile['start']).to('local').format('ddd D MMM'))
        except Exception:
            badge = u''

    lbl = badge + title
    if tile.get('is_4k'):
        lbl = u'[COLOR cyan][4K][/COLOR]  ' + lbl

    return plugin.Item(
        label=lbl,
        art={'thumb': tile.get('thumb', ''), 'fanart': tile.get('fanart', '')},
        info={'plot': tile.get('description') or title, 'mediatype': 'video'},
        path=plugin.url_for(play, id=asset_id),
        playable=not is_upcoming,
    )


# ── Sports ──────────────────────────────────────────────────────────

@plugin.route()
@plugin.login_required()
def sport_index(**kwargs):
    folder = plugin.Folder('Sports')
    try:
        sports = api.sports_list()
    except Exception as e:
        raise PluginError(str(e))
    for item in sports:
        raw   = item.get('raw', '')
        label = _SPORT_LABELS.get(raw, raw)
        count = item.get('count', 0)
        folder.add_item(
            label=u'{} ({})'.format(label, count),
            path=plugin.url_for(sport_menu, raw_sport=raw),
        )
    return folder


@plugin.route()
@plugin.login_required()
def sport_menu(raw_sport, **kwargs):
    label = _SPORT_LABELS.get(raw_sport, raw_sport)
    folder = plugin.Folder(label)
    try:
        tiles = api.sport_tiles(raw_sport)
    except Exception as e:
        raise PluginError(str(e))
    _section_menu(folder, tiles, sport_section, raw_sport=raw_sport)
    return folder


@plugin.route()
@plugin.login_required()
def sport_section(raw_sport, section, **kwargs):
    sport_label   = _SPORT_LABELS.get(raw_sport, raw_sport)
    section_label = dict(_SECTIONS).get(section, section)
    folder = plugin.Folder(u'{} — {}'.format(sport_label, section_label))
    try:
        tiles = api.sport_tiles(raw_sport)
    except Exception as e:
        raise PluginError(str(e))
    tiles = _sort_tiles(_filter_tiles(tiles, section), section)
    for tile in tiles:
        folder.add_items(_render_tile(tile, section))
    return folder


@plugin.route()
@plugin.login_required()
def sport_shows(raw_sport, **kwargs):
    label = _SPORT_LABELS.get(raw_sport, raw_sport)
    kayo_slug = SPORT_KAYO_SLUG.get(raw_sport)
    if not kayo_slug:
        raise PluginError(u'No shows available for {}'.format(label))

    folder = plugin.Folder(u'{} — Shows'.format(label))
    try:
        panels = api.landing(name='sport', sport=kayo_slug)['panels']
    except Exception as e:
        raise PluginError(u'Shows unavailable: {}'.format(str(e)))

    shows_panel = next((p for p in panels if p.get('title') == 'Shows'), None)
    if not shows_panel:
        raise PluginError(u'No shows panel found for {}'.format(label))

    href = (shows_panel.get('links') or {}).get('panels', '')
    if not href:
        raise PluginError(u'Shows panel has no URL for {}'.format(label))

    try:
        data = api.panel(href)
        folder.add_items(_parse_contents(data.get('contents', [])))
    except Exception as e:
        raise PluginError(u'Could not load shows: {}'.format(str(e)))

    return folder


# ── Competitions ─────────────────────────────────────────────────────

@plugin.route()
@plugin.login_required()
def competition_index(**kwargs):
    folder = plugin.Folder('Competitions')
    for label, sport_title in COMPETITIONS:
        folder.add_item(
            label=label,
            path=plugin.url_for(competition_menu, sport_title=sport_title, title=label),
        )
    return folder


@plugin.route()
@plugin.login_required()
def competition_menu(sport_title, title, **kwargs):
    folder = plugin.Folder(title)
    try:
        tiles = api.competition_tiles(sport_title)
    except Exception as e:
        raise PluginError(str(e))
    _section_menu(folder, tiles, competition_section, sport_title=sport_title, title=title)
    return folder


@plugin.route()
@plugin.login_required()
def competition_section(sport_title, title, section, **kwargs):
    section_label = dict(_SECTIONS).get(section, section)
    folder = plugin.Folder(u'{} — {}'.format(title, section_label))
    try:
        tiles = api.competition_tiles(sport_title)
    except Exception as e:
        raise PluginError(str(e))
    tiles = _sort_tiles(_filter_tiles(tiles, section), section)
    for tile in tiles:
        folder.add_items(_render_tile(tile, section))
    return folder


# Keep old routes alive so any saved bookmarks/history still resolve
@plugin.route()
@plugin.login_required()
def sport_content(raw_sport, **kwargs):
    return sport_menu(raw_sport=raw_sport)


@plugin.route()
@plugin.login_required()
def competition_content(sport_title, title, **kwargs):
    return competition_menu(sport_title=sport_title, title=title)


@plugin.route()
@plugin.login_required()
def fixtures(**kwargs):
    folder = plugin.Folder(u'Fixtures')
    try:
        resp = api._session.get(
            get_relay_url() +'/fixtures',
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        tiles = resp.json().get('tiles', [])

        now_perth = arrow.utcnow().to('Australia/Perth')
        today     = now_perth.format('YYYY-MM-DD')
        tomorrow  = now_perth.shift(days=1).format('YYYY-MM-DD')

        from collections import OrderedDict
        days = OrderedDict()
        for t in tiles:
            try:
                start     = arrow.get(t['start'])
                day_key   = start.to('Australia/Perth').format('YYYY-MM-DD')
                day_label = start.to('Australia/Perth').format('dddd D MMM')
            except Exception:
                day_key   = t['start'][:10]
                day_label = day_key
            if day_key not in days:
                days[day_key] = (day_label, 0)
            days[day_key] = (days[day_key][0], days[day_key][1] + 1)

        for day_key, (day_label, count) in days.items():
            if day_key == today:
                label = u'[B]Today — {}[/B]  ({} events)'.format(day_label, count)
            elif day_key == tomorrow:
                label = u'[B]Tomorrow — {}[/B]  ({} events)'.format(day_label, count)
            else:
                label = u'[B]{}[/B]  ({} events)'.format(day_label, count)
            folder.add_item(
                label=label,
                path=plugin.url_for(fixture_day, date=day_key),
            )
    except Exception:
        pass

    return folder


@plugin.route()
@plugin.login_required()
def fixture_day(date, **kwargs):
    folder = plugin.Folder(date, cacheToDisc=False)
    try:
        resp = api._session.get(
            get_relay_url() +'/fixtures',
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        tiles = resp.json().get('tiles', [])
    except Exception as e:
        raise PluginError(u'Could not load fixtures: {}'.format(str(e)))

    now_utc = arrow.utcnow()
    for t in tiles:
        try:
            start    = arrow.get(t['start'])
            day_key  = start.to('Australia/Perth').format('YYYY-MM-DD')
            time_str = start.to('Australia/Perth').format('h:mma')
        except Exception:
            day_key  = t['start'][:10]
            time_str = ''
            start    = now_utc
        if day_key != date:
            continue

        competition = t.get('competition', '')
        is_catchup  = t.get('catchup', False)
        started     = start < now_utc

        if is_catchup:
            # Already finished — play as VOD from the beginning
            play_path = plugin.url_for(play, id=t['asset_id'])
            badge = u'[COLOR gray][REPLAY][/COLOR]  '
        elif started:
            play_path = plugin.url_for(play, id=t['asset_id'], start_from=1,
                                       play_type=PLAY_FROM_ASK, _is_live=True)
            badge = u'[COLOR lime][LIVE][/COLOR]  '
        else:
            play_path = plugin.url_for(play, id=t['asset_id'])
            badge = u'[{}]  '.format(time_str)

        label = u'{}{} — {}'.format(badge, t['title'], competition)
        plot  = u'{}\n{}\n{}'.format(t.get('sport', ''), competition, time_str)

        folder.add_item(
            label=label,
            art={'thumb': t.get('thumb', ''), 'fanart': t.get('fanart', '')},
            info={'plot': plot, 'mediatype': 'video'},
            path=play_path,
            playable=True,
        )
    return folder


@plugin.route()
@plugin.login_required()
def dazn_shows(**kwargs):
    folder = plugin.Folder(u'Shows')
    try:
        resp = api._session.get(
            get_relay_url() +'/dazn/show_rails',
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=30,
        )
        resp.raise_for_status()
        rails = resp.json().get('rails', [])
    except Exception as e:
        raise PluginError(u'Could not load shows: {}'.format(str(e)))
    for rail in rails:
        folder.add_item(
            label=rail['title'],
            path=plugin.url_for(dazn_show_rail, rail_id=rail['id'], title=rail['title']),
        )
    return folder


@plugin.route()
@plugin.login_required()
def dazn_show_rail(rail_id, title, **kwargs):
    folder = plugin.Folder(title)
    try:
        resp = api._session.get(
            get_relay_url() +'/dazn/show_tiles',
            params={'rail_id': rail_id},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        tiles = resp.json().get('tiles', [])
    except Exception as e:
        raise PluginError(u'Could not load rail: {}'.format(str(e)))
    for t in tiles:
        if t.get('playable'):
            import arrow as _arrow
            try:
                start_str = u'[{}]  '.format(_arrow.get(t['start']).to('local').format('ddd D MMM'))
            except Exception:
                start_str = u''
            folder.add_item(
                label=start_str + t['title'],
                art={'thumb': t.get('thumb',''), 'fanart': t.get('fanart','')},
                info={'plot': t.get('description') or t['title'], 'mediatype': 'video'},
                path=plugin.url_for(play, id=t['asset_id']),
                playable=True,
            )
        else:
            folder.add_item(
                label=t['title'],
                art={'thumb': t.get('thumb',''), 'fanart': t.get('fanart','')},
                info={'plot': t.get('description') or t['title']},
                path=plugin.url_for(dazn_show_episodes, competition_id=t['asset_id'], title=t['title']),
            )
    return folder


@plugin.route()
@plugin.login_required()
def dazn_show_episodes(competition_id, title, **kwargs):
    folder = plugin.Folder(title)
    try:
        resp = api._session.get(
            get_relay_url() +'/dazn/show_episodes',
            params={'competition_id': competition_id},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        resp.raise_for_status()
        episodes = resp.json().get('episodes', [])
    except Exception as e:
        raise PluginError(u'Could not load episodes: {}'.format(str(e)))
    import arrow as _arrow
    for ep in episodes:
        try:
            start_str = u'[{}]  '.format(_arrow.get(ep['start']).to('local').format('ddd D MMM'))
        except Exception:
            start_str = u''
        folder.add_item(
            label=start_str + ep['title'],
            art={'thumb': ep.get('thumb',''), 'fanart': ep.get('fanart','')},
            info={'plot': ep.get('description') or ep['title'], 'mediatype': 'video'},
            path=plugin.url_for(play, id=ep['asset_id']),
            playable=True,
        )
    if not episodes:
        folder.add_item(label=u'No recent episodes found', path='')
    return folder


@plugin.route()
@plugin.login_required()
def shows_index(**kwargs):
    return sport_index()


# ------------------------------------------------------------------
# Browse by Date
# ------------------------------------------------------------------

def _normalise_sport(tile):
    raw = tile.get('sport') or ''
    if raw:
        return _SPORT_LABELS.get(raw, raw)
    title = tile.get('title', '').upper()
    if 'AFL' in title or 'AFLW' in title:       return 'AFL'
    if 'NRL' in title or 'NRLW' in title:       return 'Rugby League'
    if 'CRICKET' in title or 'BBL' in title:    return 'Cricket'
    if 'NBA' in title or 'NBL' in title:        return 'Basketball'
    if 'FORMULA 1' in title or ' F1 ' in title: return 'Motorsport'
    if 'UFC' in title or 'BOXING' in title:     return 'MMA'
    if 'TENNIS' in title or 'ATP' in title:     return 'Tennis'
    if 'GOLF' in title or 'PGA' in title:       return 'Golf'
    return 'Other'


def _epg_tiles_for_date(date):
    return [t for t in api.epg(date) if t.get('asset_id')]


@plugin.route()
@plugin.login_required()
def epg_day(date, **kwargs):
    folder = plugin.Folder(date)
    try:
        tiles = _epg_tiles_for_date(date)
    except Exception as e:
        raise PluginError(str(e))

    sports = {}
    for tile in tiles:
        sport = _normalise_sport(tile)
        sports.setdefault(sport, []).append(tile)

    for sport in sorted(sports.keys()):
        folder.add_item(
            label=u'{} ({})'.format(sport, len(sports[sport])),
            path=plugin.url_for(epg_sport, date=date, sport=sport),
        )
    return folder


@plugin.route()
@plugin.login_required()
def recent_replays_flat(**kwargs):
    folder = plugin.Folder('Recent Replays', cacheToDisc=False)
    try:
        tiles = api.recent_replays()
        for tile in tiles:
            title = tile.get('title', '')
            sport = _normalise_sport(tile)
            try:
                ts = arrow.get(tile['start']).to('local').format('ddd D MMM h:mma')
                label = u'[COLOR yellow]{}[/COLOR]  {} [{}]'.format(sport, title, ts)
            except Exception:
                label = u'[COLOR yellow]{}[/COLOR]  {}'.format(sport, title)
            if tile.get('is_4k'):
                label = u'[COLOR cyan][4K][/COLOR]  ' + label
            folder.add_item(
                label=label,
                art={'thumb': tile.get('thumb', ''), 'fanart': tile.get('fanart', '')},
                info={'plot': tile.get('description') or title, 'mediatype': 'video'},
                path=plugin.url_for(play, id=tile['asset_id']),
                playable=True,
            )
    except Exception:
        pass
    return folder


@plugin.route()
@plugin.login_required()
def recent_minis_flat(**kwargs):
    folder = plugin.Folder('Minis', cacheToDisc=False)
    try:
        tiles = api.recent_replays(tile_type='minis')
        for tile in tiles:
            title = tile.get('title', '')
            sport = _normalise_sport(tile)
            try:
                ts = arrow.get(tile['start']).to('local').format('ddd D MMM h:mma')
                label = u'[COLOR orange]{}[/COLOR]  {} [{}]'.format(sport, title, ts)
            except Exception:
                label = u'[COLOR orange]{}[/COLOR]  {}'.format(sport, title)
            if tile.get('is_4k'):
                label = u'[COLOR cyan][4K][/COLOR]  ' + label
            folder.add_item(
                label=label,
                art={'thumb': tile.get('thumb', ''), 'fanart': tile.get('fanart', '')},
                info={'plot': tile.get('description') or title, 'mediatype': 'video'},
                path=plugin.url_for(play, id=tile['asset_id']),
                playable=True,
            )
    except Exception:
        pass
    return folder


@plugin.route()
@plugin.login_required()
def recent_highlights_flat(**kwargs):
    folder = plugin.Folder('Highlights', cacheToDisc=False)
    try:
        tiles = api.recent_replays(tile_type='highlights')
        for tile in tiles:
            title = tile.get('title', '')
            sport = _normalise_sport(tile)
            try:
                ts = arrow.get(tile['start']).to('local').format('ddd D MMM h:mma')
                label = u'[COLOR orange]{}[/COLOR]  {} [{}]'.format(sport, title, ts)
            except Exception:
                label = u'[COLOR orange]{}[/COLOR]  {}'.format(sport, title)
            if tile.get('is_4k'):
                label = u'[COLOR cyan][4K][/COLOR]  ' + label
            folder.add_item(
                label=label,
                art={'thumb': tile.get('thumb', ''), 'fanart': tile.get('fanart', '')},
                info={'plot': tile.get('description') or title, 'mediatype': 'video'},
                path=plugin.url_for(play, id=tile['asset_id']),
                playable=True,
            )
    except Exception:
        pass
    return folder


@plugin.route()
@plugin.login_required()
def epg_sport(date, sport, **kwargs):
    folder = plugin.Folder(u'{} — {}'.format(sport, date))
    try:
        tiles = _epg_tiles_for_date(date)
    except Exception as e:
        raise PluginError(str(e))

    sport_tiles = [t for t in tiles if _normalise_sport(t) == sport]

    # Sort: upcoming/live first, then replays, then minis, then highlights
    order = {'UpComing': 0, 'CatchUp': 1}
    sport_tiles.sort(key=lambda t: (order.get(t.get('type', ''), 2), t.get('start', '')))

    for tile in sport_tiles:
        tile_type   = tile.get('type', '')
        display_type = tile.get('display_type', '')
        is_upcoming = tile_type == 'UpComing'

        if tile_type == 'UpComing':
            type_label = u'[COLOR gray]UPCOMING[/COLOR]'
        elif tile_type == 'CatchUp':
            type_label = u'[COLOR yellow]REPLAY[/COLOR]'
        elif display_type == 'MinisHighlights':
            type_label = u'[COLOR orange]MINI[/COLOR]'
        else:
            type_label = u'[COLOR orange]HIGHLIGHTS[/COLOR]'

        title = tile.get('title', '')
        try:
            ts = arrow.get(tile['start']).to('local').format('h:mma')
            label = u'{}  {} [{}]'.format(type_label, title, ts)
        except Exception:
            label = u'{}  {}'.format(type_label, title)

        if tile.get('is_4k'):
            label = u'[COLOR cyan][4K][/COLOR]  ' + label

        folder.add_item(
            label=label,
            art={'thumb': tile.get('thumb', ''), 'fanart': tile.get('fanart', '')},
            info={'plot': tile.get('description') or title, 'mediatype': 'video'},
            path=plugin.url_for(play, id=tile.get('asset_id', '')),
            playable=not is_upcoming,
        )
    return folder


# ------------------------------------------------------------------
# Content browsing (Kayo content API panels — used by Search/landing)
# ------------------------------------------------------------------

@plugin.route()
def landing(title, name, sport=None, series=None, team=None, **kwargs):
    folder = plugin.Folder(title)
    try:
        panels = api.landing(name, sport=sport, series=series, team=team)['panels']
    except Exception as e:
        raise PluginError(str(e))

    for index, row in enumerate(panels):
        is_hero = row['panelType'] == 'hero-carousel' and ('hero' in row['title'].lower() or index == 0)

        if 'id' not in row or (is_hero and not settings.getBool('show_hero_contents', True)):
            continue

        if 'live channels' in row['title'].lower():
            folder.add_item(label=row['title'], path=plugin.url_for(live))

        elif is_hero or row['panelType'] == 'nav-menu':
            row['contents'] = row.get('contents') or api.panel(row['links']['panels']).get('contents', [])
            folder.add_items(_parse_contents(row['contents']))

        elif row['panelType'] not in ('nav-menu-sticky',):
            folder.add_item(label=row['title'], path=plugin.url_for(panel, href=row['links']['panels']))

    return folder


@plugin.route()
def panel(href, **kwargs):
    data   = api.panel(href)
    folder = plugin.Folder(data['title'])
    folder.add_items(_parse_contents(data.get('contents', [])))
    return folder


@plugin.route()
def show(show_id, title, **kwargs):
    try:
        data = api.show(show_id=show_id)
    except Exception as e:
        msg = str(e)
        if '503' in msg or 'unavailable' in msg.lower() or 'upstream' in msg.lower():
            raise PluginError(u'{} — Kayo show API is temporarily unavailable. Try again later.'.format(title))
        raise PluginError(msg)
    folder = plugin.Folder(title)

    for row in data['panels']:
        if row['title'] == 'Seasons':
            if len(row.get('contents', [])) == 1:
                d = row['contents'][0]['data']
                return _season(show_id, d['id'], title)

            for row2 in row.get('contents', []):
                d = row2['data']
                folder.add_item(
                    label=d['contentDisplay']['title']['value'],
                    art={
                        'thumb':  _get_image(d, 'thumb'),
                        'fanart': _get_image(d, 'fanart'),
                    },
                    info={'plot': d['contentDisplay']['synopsis'] or None},
                    path=plugin.url_for(season, show_id=show_id,
                                        season_id=d['id'],
                                        title=d['contentDisplay']['title']['value']),
                )
    return folder


@plugin.route()
def season(show_id, season_id, title, **kwargs):
    return _season(show_id, season_id, title)


def _season(show_id, season_id, title):
    try:
        data = api.show(show_id=show_id, season_id=season_id)
    except Exception as e:
        msg = str(e)
        if any(x in msg for x in ('503', '502', 'unavailable', 'Unavailable', 'upstream')):
            raise PluginError(u'{} — Episodes temporarily unavailable. Try again later.'.format(title))
        raise PluginError(msg)
    folder = plugin.Folder(title)
    for row in data.get('panels', []):
        if row.get('title') == 'Episodes':
            folder.add_items(_parse_contents(row.get('contents', [])))
    return folder


@plugin.route()
@plugin.search()
def search(query, page, **kwargs):
    data = api.search(query=query, page=page)['panels'][0]
    return _parse_contents(data.get('contents', [])), data['resultCount'] > 250


# ------------------------------------------------------------------
# Stream playback — DAZN Playback API + direct Widevine
# ------------------------------------------------------------------

@plugin.route()
@plugin.login_required()
def play(id, start_from=0, play_type=PLAY_FROM_LIVE, **kwargs):
    start_from = int(start_from)
    play_type  = int(play_type)
    is_live    = ROUTE_LIVE_TAG in kwargs

    if is_live:
        if play_type == PLAY_FROM_LIVE:
            start_from = 0
        elif play_type == PLAY_FROM_ASK:
            start_from = plugin.live_or_start(start_from)
            if start_from == -1:
                return

    try:
        stream = api.stream(id, channel_id=kwargs.get('channel_id') or None, upgrade_4k=bool(kwargs.get('upgrade_4k')), is_live=is_live)
    except Exception as e:
        gui.notification(str(e), heading='Stream Error')
        return

    if not stream.get('manifest_url'):
        gui.notification(_.NO_STREAM, heading='Stream Error')
        return

    headers = {}
    if stream.get('cookie_name') and stream.get('cookie_value'):
        headers['Cookie'] = '{}={}'.format(stream['cookie_name'], stream['cookie_value'])

    # api.stream() already appends avc_only=1 for live non-4K plays.
    # Do not add it here — that would duplicate it for live non-4K and,
    # worse, incorrectly strip HEVC from VOD replays (which have upgrade_4k=False
    # but should still play HEVC at quality=4k).
    manifest_url = stream['manifest_url']

    log.debug('Kayo stream: manifest={} cdn={}'.format(
        manifest_url[:80], stream['cookie_name'],
    ))

    api.register_now_watching(id)

    item = plugin.Item(
        path=manifest_url,
        headers=headers,
        inputstream=inputstream.Widevine(
            license_key=stream['license_url'],
            license_headers={'Authorization': 'Bearer {}'.format(stream['dazn_token'])},
            wv_secure=stream.get('wv_secure', False),
        ),
    )

    if start_from and ROUTE_RESUME_TAG not in kwargs:
        item.resume_from = start_from

    # LIVE_HEAD (90000 s) far exceeds any DVR buffer depth so ISA clamps it
    # to the live edge.  Apply for all live plays including _restart=1 so the
    # stream always resumes at the live edge rather than the start of the buffer.
    if not item.resume_from and ROUTE_LIVE_TAG in kwargs:
        item.resume_from = LIVE_HEAD

    # KayoPlayer watchdog disabled — relay now uses body={} so DAZN never
    # inserts ad periods into the manifest. No ads = no watchdog needed.

    return item


# ------------------------------------------------------------------
# IPTV merge / playlist export
# ------------------------------------------------------------------

@plugin.route()
@plugin.merge()
def playlist(output, **kwargs):
    epg_url = settings.get('epg_url', '').strip() or EPG_URL
    with codecs.open(output, 'w', encoding='utf8') as f:
        f.write(u'#EXTM3U x-tvg-url="{}"'.format(epg_url))

        # Permanent 4K channels — always in the playlist.
        # Always use the linear channel slot, not the event-specific asset_id.
        # DAZN serves UHD quality from the linear slot when a 4K match is live,
        # and FHD otherwise — but the channel never stops when a match ends.
        for ch4k in _get_4k_channels():
            play_id = ch4k['linear_asset']
            if not play_id:
                continue
            f.write(u'\n#EXTINF:-1 tvg-id="4k-{cid}" channel-id="kayo-4k-{cid}" tvg-chno="{chno}" tvg-logo="{logo}",{name}\n{url}'.format(
                cid=ch4k['channel_id'],
                chno=ch4k['chno'],
                logo=ch4k['logo'],
                name=ch4k['name'],
                url=plugin.url_for(play, id=play_id, channel_id=ch4k['channel_id'], upgrade_4k='1', _is_live=True),
            ))

        for ch in _get_live_channels():
            f.write(u'\n#EXTINF:-1 tvg-id="{id}" channel-id="kayo-{id}" tvg-chno="{chno}" tvg-logo="{logo}",{name}\n{url}'.format(
                id=ch['id'], chno=ch['chno'] or '', logo=ch['logo'] or '',
                name=ch['name'],
                url=plugin.url_for(play, id=ch['id'], _is_live=True),
            ))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_contents(rows):
    items = []
    for row in rows:
        if row['contentType'] == 'video':
            item = _parse_video(row['data'])
            if item:
                items.append(item)
        elif row['contentType'] == 'section':
            items.append(_parse_section(row['data']))
    return items


def _parse_section(data):
    ct = data['clickthrough']
    if data['type'] == 'panel':
        path = plugin.url_for(landing,
            title=ct['title'], name=ct['type'],
            sport=ct['sportId'] or None, series=ct['seriesId'] or None, team=ct['teamId'] or None,
        )
    else:
        panel_href = (data.get('links') or {}).get('panels', '')
        if panel_href:
            path = plugin.url_for(panel, href=panel_href)
        else:
            path = plugin.url_for(show, show_id=data['id'], title=ct['title'])

    return plugin.Item(
        label=ct['title'],
        art={'thumb': _get_image(data, 'thumb'), 'fanart': _get_image(data, 'fanart')},
        info={'plot': data['contentDisplay']['synopsis'] or None},
        path=path,
    )


def _parse_video(data):
    clickthrough = data['clickthrough']
    content      = data['contentDisplay']

    channel_id   = clickthrough.get('channel', '').lower()
    is_streaming = clickthrough.get('isStreaming', False)
    if is_streaming and channel_id and channel_id in CHANNEL_ID_TO_ASSET:
        asset_id = CHANNEL_ID_TO_ASSET[channel_id]
    else:
        asset_id = clickthrough.get('foxtelCmsAssetId') or data['id']

    now    = arrow.now()
    start  = arrow.get(clickthrough['transmissionTime'])
    precheck = start

    if clickthrough.get('preCheckTime'):
        precheck = arrow.get(clickthrough['preCheckTime'])
        if precheck > start:
            precheck = start

    title    = clickthrough['title']
    headline = content.get('headline', '').strip()
    if headline:
        title += u' [' + headline \
            .replace('${DATE_HUMANISED}', _make_humanised(now, start).upper()) \
            .replace('${TIME}', _make_time(start)) + u']'
    elif not clickthrough.get('isStreaming') and data.get('type') not in ('live-linear',):
        title += u' | ' + start.format('D MMM YYYY')

    if not api.is_subscribed():
        is_free = content.get('isFreemium', False)
        if settings.getBool('hide_locked', False) and not is_free:
            return None
        elif not is_free:
            title = _(_.LOCKED, label=title)

    play_type     = settings.getEnum('live_play_type', PLAY_FROM_TYPES, default=PLAY_FROM_ASK)
    start_from    = max(1, (start - precheck).seconds)
    is_live       = False
    is_streaming  = False

    if now < start:
        is_live = True

    elif data['type'] == 'live-linear':
        is_live    = True
        start_from = 0
        play_type  = PLAY_FROM_LIVE

    elif data.get('playback', {}).get('info', {}).get('playbackType') == 'LIVE' \
            and clickthrough.get('isStreaming', False):
        is_live      = True
        is_streaming = True

    item = plugin.Item(
        label=title,
        art={'thumb': _get_image(data, 'thumb'), 'fanart': _get_image(data, 'fanart')},
        info={'plot': content['synopsis'] or None, 'mediatype': 'video',
              'aired': start.format('YYYY-MM-DD')},
        playable=True,
        path=plugin.url_for(play, id=asset_id, start_from=start_from, play_type=play_type, _is_live=is_live),
    )

    if is_streaming:
        item.context.append((_.PLAY_FROM_LIVE, 'PlayMedia({})'.format(
            plugin.url_for(play, id=asset_id, play_type=PLAY_FROM_LIVE, _is_live=True))))
        item.context.append((_.PLAY_FROM_START, 'PlayMedia({})'.format(
            plugin.url_for(play, id=asset_id, start_from=start_from, play_type=PLAY_FROM_START, _is_live=True))))

    return item


def _get_image(data, img_type='thumb', width=None):
    images = data.get('contentDisplay', {}).get('images', {})
    if img_type == 'thumb':
        for key in ('tile',):
            if key in images:
                return images[key].replace('${WIDTH}', width or '612')
    elif img_type == 'fanart':
        for key in ('hero-default', 'hero', 'heroPortrait'):
            if key in images:
                return images[key].replace('${WIDTH}', width or '1920')
    return None


def _make_time(start=None):
    return start.to('local').format('h:mmA') if start else ''


def _make_humanised(now, start=None):
    if not start:
        return ''
    n = now.to('local').replace(hour=0, minute=0, second=0, microsecond=0)
    s = start.to('local').replace(hour=0, minute=0, second=0, microsecond=0)
    days = (s - n).days
    if days == -1: return 'yesterday'
    if days == 0:  return 'today'
    if days == 1:  return 'tomorrow'
    if 1 < days <= 7: return s.format('dddd')
    return s.to('local').format('DD MMM')
