from slyguy.language import BaseLanguage


class Language(BaseLanguage):
    LOGIN_ERROR        = 30003
    LIVE_TV            = 30005
    PLAYBACK_ERROR     = 30006
    NO_STREAM_ERROR    = 30007
    TV_SHOWS           = 30010
    TOKEN_ERROR        = 30011
    SPORTS             = 30012
    MOVIES             = 30013
    SEASON             = 30014
    EPISODE_MENU_TITLE = 30015
    KIDS               = 30017
    HIDE_LOCKED        = 30018
    CHANNEL            = 30019
    LOCKED             = 30020
    DEVICE_NICKNAME    = 30021
    RECOMMENDED        = 30023
    SEARCH             = 30025
    SEARCH_FOR         = 30026
    CONTINUE_WATCHING  = 30027
    WATCHLIST          = 30028
    SHOW_EPG           = 30029
    SEE_ALL            = 30030
    OTP_LOGIN          = 30031
    OTP_CODE           = 30032
    OTP_SENT           = 30033
    NEWS               = 30034
    QUALITY            = 30035
    RELAY_URL          = 30036


_ = Language()
