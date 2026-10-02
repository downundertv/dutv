import arrow

from slyguy import plugin, gui, settings, userdata, signals, inputstream
from slyguy.exceptions import PluginError
from slyguy.constants import LIVE_HEAD

from .api import API
from .language import _
from .constants import *

api = API()


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
        folder.add_item(label=_(_.LIVE_TV,           _bold=True), path=plugin.url_for(live))
        folder.add_item(label=_(_.TV_SHOWS,          _bold=True), path=plugin.url_for(tv_shows))
        folder.add_item(label=_(_.MOVIES,            _bold=True), path=plugin.url_for(movies))
        folder.add_item(label=_(_.SPORTS,            _bold=True), path=plugin.url_for(sports))
        folder.add_item(label=_(_.SEARCH,            _bold=True), path=plugin.url_for(search))

        if settings.getBool('bookmarks', True):
            folder.add_item(label=_(_.BOOKMARKS, _bold=True),
                            path=plugin.url_for(plugin.ROUTE_BOOKMARKS), bookmark=False)

        folder.add_item(label=_(_.LOGOUT,   _bold=False), path=plugin.url_for(logout),          bookmark=False)
        folder.add_item(label=_(_.SETTINGS, _bold=False), path=plugin.url_for(plugin.ROUTE_SETTINGS), bookmark=False)

    return folder


# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------

@plugin.route()
def login(**kwargs):
    options = [
        [u'Email + Password', _login_password],
        [u'Email + OTP Code', _login_otp],
    ]
    index = gui.context_menu([x[0] for x in options])
    if index == -1:
        return
    if options[index][1]():
        gui.refresh()


def _login_password():
    email = gui.input(_.ASK_EMAIL, default=userdata.get('email', '')).strip()
    if not email:
        return False
    password = gui.input(_.ASK_PASSWORD, hide_input=True).strip()
    if not password:
        return False

    nickname = gui.input(_(_.DEVICE_NICKNAME) + u' (shared name = shared device slot)',
                         default=settings.get('device_nickname', 'Kodi')).strip()
    if nickname:
        try:
            import xbmcaddon
            xbmcaddon.Addon('plugin.video.foxtel.go').setSetting('device_nickname', nickname)
        except Exception:
            pass

    try:
        api.login(email=email, password=password)
    except Exception as e:
        raise PluginError(str(e))
    return True


def _login_otp():
    email = gui.input(_.ASK_EMAIL, default=userdata.get('email', '')).strip()
    if not email:
        return False

    nickname = gui.input(_(_.DEVICE_NICKNAME) + u' (shared name = shared device slot)',
                         default=settings.get('device_nickname', 'Kodi')).strip()
    if nickname:
        try:
            import xbmcaddon
            xbmcaddon.Addon('plugin.video.foxtel.go').setSetting('device_nickname', nickname)
        except Exception:
            pass

    try:
        api.login_otp_request(email)
    except Exception as e:
        raise PluginError(str(e))

    gui.ok(_(_.OTP_SENT))

    code = gui.input(_(_.OTP_CODE)).strip()
    if not code:
        return False

    try:
        api.login_otp_validate(email, code)
    except Exception as e:
        raise PluginError(str(e))
    return True


@plugin.route()
@plugin.login_required()
def logout(**kwargs):
    if not gui.yes_no(_.LOGOUT_YES_NO):
        return
    api.logout()
    gui.refresh()


# ------------------------------------------------------------------
# Live TV
# ------------------------------------------------------------------

@plugin.route()
@plugin.login_required()
def live(**kwargs):
    folder    = plugin.Folder(_.LIVE_TV)
    show_epg  = settings.getBool('show_epg', True)
    hide_lock = settings.getBool('hide_locked', False)

    channel_data = api.channel_data()
    if not channel_data:
        folder.add_item(label='[No channel data — check connection]')
        return folder

    now = arrow.now()

    for ch_code, ch in sorted(channel_data.items(), key=lambda x: x[1].get('chno', 999)):
        chno = ch.get('chno')
        epg  = ch.get('epg', [])
        logo = ch.get('logo', '')
        name = ch.get('name', ch_code)

        label = u'[{}] {}'.format(chno, name) if chno else name

        plot = u''
        if show_epg and epg:
            count = 0
            for index, row in enumerate(epg):
                start = arrow.get(row[0])
                try:
                    stop = arrow.get(epg[index + 1][0])
                except Exception:
                    stop = start.shift(hours=1)
                if now < stop:
                    plot += u'[{}] {}\n'.format(start.to('local').format('h:mma'), row[1])
                    count += 1
                    if count >= EPG_EVENTS_COUNT:
                        break

        folder.add_items(plugin.Item(
            label=label,
            art={'thumb': logo},
            info={'plot': plot.strip(), 'mediatype': 'video'},
            path=plugin.url_for(play_live, channel=ch_code, _is_live=True),
            playable=True,
        ))

    return folder


# ------------------------------------------------------------------
# VOD browsing (Rail-based)
# ------------------------------------------------------------------

@plugin.route()
@plugin.login_required()
def tv_shows(**kwargs):
    return _rail_folder(_.TV_SHOWS, rail_id='AllGenreShows', page_type='Show')


@plugin.route()
@plugin.login_required()
def movies(**kwargs):
    return _rail_folder(_.MOVIES, rail_id='AllGenreMovies', page_type='Movie')


@plugin.route()
@plugin.login_required()
def sports(**kwargs):
    return _rails_page_folder(_.SPORTS, group_id='sports', content_type='sports')



def _rails_page_folder(title, group_id, content_type=None, raw_params=None):
    """Fetch a page's section list via multi-rails and display as a folder."""
    folder = plugin.Folder(title)
    try:
        sections = api.rails_page(group_id, content_type=content_type, raw_params=raw_params)
    except Exception as e:
        folder.add_item(label=u'[Error loading sections: {}]'.format(str(e)[:80]))
        return folder

    if not sections:
        folder.add_item(label=u'[No sections found]')
        return folder

    for sec in sections:
        p = _parse_rail_params(sec.get('params', ''))
        folder.add_item(
            label=sec['title'],
            path=plugin.url_for(rail,
                                rail_id=sec['id'],
                                page_type=p.get('PageType', ''),
                                content_type=p.get('ContentType', ''),
                                content_id=p.get('ContentId', ''),
                                title=sec['title']),
        )
    return folder


@plugin.route()
@plugin.login_required()
def genre_rails(navigate_to, content_id='', title='', **kwargs):
    """Show rails for a genre/category (e.g. Action movies, Crime shows)."""
    raw_params = _build_rail_params(navigate_to, 'Genre', content_id)
    return _rails_page_folder(title or navigate_to, group_id=navigate_to, raw_params=raw_params)


def _parse_rail_params(params_str):
    """Parse 'PageType:X;ContentType:Y;ContentId:Z' into a dict."""
    result = {}
    for part in (params_str or '').split(';'):
        if ':' in part:
            k, v = part.split(':', 1)
            result[k.strip()] = v.strip()
    return result


def _build_rail_params(page_type='', content_type='', content_id=''):
    """Build a DAZN params string from safe URL-friendly components."""
    parts = []
    if page_type:
        parts.append('PageType:{}'.format(page_type))
    if content_type:
        parts.append('ContentType:{}'.format(content_type))
    if content_id:
        parts.append('ContentId:{}'.format(content_id))
    return ';'.join(parts)


def _extract_tiles(data):
    """Return the tiles list from a Rail API response regardless of wrapper."""
    if 'Rail' in data or 'rail' in data:
        rail_data = data.get('Rail') or data.get('rail') or {}
        return rail_data.get('Tiles') or rail_data.get('tiles') or []
    return data.get('Tiles') or data.get('tiles') or []


def _rail_folder(title, rail_id, page_type=None):
    """Fetch and display a DAZN content rail."""
    folder = plugin.Folder(title)
    try:
        data = api.rail(rail_id, page_type=page_type)
    except Exception as e:
        folder.add_item(label=u'[Error loading content: {}]'.format(str(e)[:80]))
        return folder

    for tile in _extract_tiles(data):
        item = _tile_to_item(tile)
        if item:
            folder.add_items(item)

    return folder


@plugin.route()
@plugin.login_required()
def rail(rail_id, page_type='', content_type='', content_id='', title='', **kwargs):
    """Generic rail browser — navigable from within the plugin."""
    folder = plugin.Folder(title or rail_id)
    raw_params = _build_rail_params(page_type, content_type, content_id) or None
    try:
        data = api.rail(rail_id, raw_params=raw_params)
    except Exception as e:
        folder.add_item(label=u'[Error: {}]'.format(str(e)[:80]))
        return folder

    for tile in _extract_tiles(data):
        item = _tile_to_item(tile)
        if item:
            folder.add_items(item)

    return folder


_tile_logged = False
def _img_from_id(img_id):
    """Build a DAZN image CDN URL from a foxtelgnc image Id string."""
    if img_id and isinstance(img_id, str):
        return 'https://image.discovery.indazn.com/jp/v3/jp/none/{}?imwidth=480'.format(img_id)
    return ''


def _extract_tile_image(tile):
    """Extract a thumbnail URL from a DAZN foxtelgnc Rail tile.

    foxtelgnc Rail tiles store image *IDs* (not URLs) in typed image objects.
    The actual image is at DAZN_IMG_BASE/image/{Id}.
    Priority: HeroImage.Landscape (16:9) → Image.Id → PortraitImage.Id
    """
    # 1. HeroImage.Landscape — 16:9 landscape ID, best for Kodi thumbnails
    hero = tile.get('HeroImage') or {}
    if isinstance(hero, dict):
        url = _img_from_id(hero.get('Landscape') or hero.get('Id') or hero.get('id'))
        if url:
            return url

    # 2. Image.Id (image-header type)
    img = tile.get('Image') or tile.get('image') or {}
    if isinstance(img, str) and img.startswith('http'):
        return img
    if isinstance(img, dict):
        # Check for a direct URL sub-key first (other DAZN brands)
        direct = (img.get('ImageUrl') or img.get('Url') or img.get('Uri') or
                  img.get('imageUrl') or img.get('url') or img.get('uri') or '')
        if direct and direct.startswith('http'):
            return direct
        # foxtelgnc: build URL from Id
        url = _img_from_id(img.get('Id') or img.get('id'))
        if url:
            return url

    # 3. PortraitImage.Id
    portrait = tile.get('PortraitImage') or {}
    if isinstance(portrait, dict):
        url = _img_from_id(portrait.get('Id') or portrait.get('id'))
        if url:
            return url

    # 4. Images dict (other DAZN brands / legacy format)
    images = tile.get('Images') or tile.get('images') or {}
    for key in ('Landscape', 'Tile', 'Thumbnail', 'Poster', 'Background', 'Hero',
                'landscape', 'tile', 'thumbnail', 'poster', 'background', 'hero'):
        img2 = images.get(key)
        if img2 is None:
            continue
        if isinstance(img2, str):
            return img2.replace('${WIDTH}', '512')
        if isinstance(img2, dict):
            u = img2.get('Uri') or img2.get('uri') or img2.get('url') or img2.get('URL') or ''
            if u:
                return u.replace('${WIDTH}', '512')

    # 5. contentDisplay.images (Kayo/DAZN discovery API format)
    for key in ('tile', 'Tile', 'landscape', 'Landscape', 'hero-default', 'hero'):
        v = tile.get('contentDisplay', {}).get('images', {}).get(key, '')
        if v:
            return v.replace('${WIDTH}', '512')

    return ''


def _tile_to_item(tile):
    """Convert a DAZN rail tile dict to a slyguy plugin.Item."""
    global _tile_logged
    tile_type  = tile.get('Type') or tile.get('type') or ''
    asset_id   = tile.get('AssetId') or tile.get('assetId') or tile.get('Id') or ''
    title      = tile.get('Title') or tile.get('title') or asset_id
    subtitle   = tile.get('Subtitle') or tile.get('subtitle') or ''
    is_live    = tile.get('IsLive') or tile.get('isLive') or False

    thumb = _extract_tile_image(tile)

    if not thumb and not _tile_logged:
        _tile_logged = True
        try:
            import json as _json, xbmc
            xbmc.log('FoxtelGo tile structure (first): ' + _json.dumps(tile)[:1500], xbmc.LOGINFO)
        except Exception:
            pass

    plot = subtitle

    if tile_type.lower() in ('rail', 'group', 'category', 'navigation'):
        navigate_to = tile.get('NavigateTo') or tile.get('navigateTo') or ''
        if navigate_to and asset_id:
            # Genre tile — drill into multi-rails by content_id (no special chars in URL)
            return plugin.Item(
                label=title,
                art={'thumb': thumb},
                info={'plot': plot},
                path=plugin.url_for(genre_rails, navigate_to=navigate_to,
                                    content_id=asset_id, title=title),
            )
        sub_rail_id = tile.get('RailId') or tile.get('railId') or asset_id
        return plugin.Item(
            label=title,
            art={'thumb': thumb},
            info={'plot': plot},
            path=plugin.url_for(rail, rail_id=sub_rail_id, title=title),
        )

    if asset_id:
        return plugin.Item(
            label=title,
            art={'thumb': thumb},
            info={'plot': plot, 'mediatype': 'video'},
            path=plugin.url_for(play, id=asset_id, is_live='1' if is_live else '0'),
            playable=True,
        )

    return None


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------

@plugin.route()
@plugin.login_required()
def search(**kwargs):
    query = gui.input(_.SEARCH_FOR, '').strip()
    if not query:
        return

    folder = plugin.Folder(_(_.SEARCH_FOR, query=query))
    try:
        data = api.search(query)
    except Exception as e:
        folder.add_item(label=u'[Search error: {}]'.format(str(e)[:80]))
        return folder

    results = data.get('Results') or data.get('results') or []
    for result in results:
        item = _tile_to_item(result)
        if item:
            folder.add_items(item)

    if not results:
        folder.add_item(label=u'[No results for "{}"]'.format(query))

    return folder


# ------------------------------------------------------------------
# Playback
# ------------------------------------------------------------------

@plugin.route()
@plugin.login_required()
def play_live(channel, **kwargs):
    """Play a live channel by channel code.

    Asks the relay to find the current live event's asset ID for this
    channel and return stream details.  The relay queries the DAZN EPG
    and looks up the Foxtel linear channel asset ID.
    """
    import requests as _req
    try:
        resp = _req.get(
            get_relay_url() + '/foxtel/live',
            params={'channel': channel},
            headers={'ngrok-skip-browser-warning': 'true', 'User-Agent': UA_ANDROID},
            timeout=20,
        )
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            raise Exception(u'relay returned non-JSON response')
        if resp.status_code != 200 or data.get('status') != 'success':
            raise Exception(data.get('message', u'relay error {}'.format(resp.status_code)))
        asset_id = data['asset_id']
    except PluginError:
        raise
    except Exception as e:
        raise PluginError(u'Could not get live stream for channel {}: {}'.format(channel, str(e)))

    return _play_asset(asset_id, is_live=True)


@plugin.route()
@plugin.login_required()
def play(id, is_live='0', **kwargs):
    """Play a VOD or live asset by DAZN asset ID."""
    return _play_asset(id, is_live=(is_live == '1'))


def _play_asset(asset_id, is_live=False):
    try:
        stream = api.stream(asset_id, quality='4k', is_live=is_live)
    except Exception as e:
        raise PluginError(str(e))

    # Relay's /foxtel/mpd_kodi proxies segments and handles CDN auth transparently.
    # License URL comes from the relay (already includes DRM auth).
    return plugin.Item(
        path=stream['manifest_url'],
        inputstream=inputstream.Widevine(
            license_key=stream.get('license_url', ''),
        ),
        resume_from=LIVE_HEAD if is_live else 0,
    )


# ------------------------------------------------------------------
# Playlist (for IPTV Manager / external playlist export)
# ------------------------------------------------------------------

@plugin.route()
@plugin.merge()
def playlist(output, **kwargs):
    import codecs
    epg_url = EPG_URL
    channel_data = api.channel_data()
    with codecs.open(output, 'w', encoding='utf8') as f:
        f.write(u'#EXTM3U x-tvg-url="{}"\n'.format(epg_url))
        for ch_code, ch in sorted(channel_data.items(), key=lambda x: x[1].get('chno', 999)):
            chno  = ch.get('chno', '')
            logo  = ch.get('logo', '')
            name  = ch.get('name', ch_code)
            group = CHANNEL_GROUPS.get(ch_code, 'Foxtel')
            play_url = plugin.url_for(play_live, channel=ch_code)
            tvg_id   = ch_code
            f.write(u'#EXTINF:-1 tvg-id="{}" tvg-chno="{}" tvg-logo="{}" group-title="{}",{}\n'.format(
                tvg_id, chno, logo, group, name))
            f.write(play_url + u'\n')
