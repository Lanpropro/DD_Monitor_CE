"""Shared isolated platform browser profile registry and logout clearing."""
import os
from .account_store import AccountStore


_profiles = {}


def clear_platform_login(kind):
    from .platform_login import AccountStore
    if os.environ.get("DDM_NO_SAVE") != "1":
        AccountStore(kind).clear()
    profile = _profiles.get(kind)
    if profile is not None:
        profile.cookieStore().deleteAllCookies()
        profile.clearHttpCache()
