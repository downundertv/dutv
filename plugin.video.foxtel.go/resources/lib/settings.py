from slyguy.settings import CommonSettings
from slyguy.settings.types import Bool, Text

from .language import _


class Settings(CommonSettings):
    DEVICE_NICKNAME = Text('device_nickname', _.DEVICE_NICKNAME, default='Kodi')
    SHOW_EPG        = Bool('show_epg',        _.SHOW_EPG,        default=True)
    HIDE_LOCKED     = Bool('hide_locked',      _.HIDE_LOCKED,     default=False)
    RELAY_URL       = Text('relay_url',        _.RELAY_URL,       default='')


settings = Settings()
