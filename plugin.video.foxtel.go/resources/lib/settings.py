from slyguy.settings import CommonSettings
from slyguy.settings.types import Bool, Text, Action

from .language import _


class Settings(CommonSettings):
    DEVICE_NAME = Text('device_name', _.DEVICE_NAME, default='{iPad')
    DEVICE_ID = Text('device_id', _.DEVICE_ID, default='iPad')
    SAVE_PASSWORD = Bool('save_password', _.SAVE_PASSWORD, default=True)
    HIDE_LOCKED = Bool('hide_locked', _.HIDE_LOCKED, default=False)
    SHOW_EPG = Bool('show_epg', _.SHOW_EPG, default=True)


settings = Settings()