"""官方仓库的版本查询和校验下载；不使用直播账号的网络会话。"""
import hashlib
import os
from pathlib import Path
import re
import json
import tempfile
import time
from urllib.parse import urlsplit

import requests
from .update_version import app_tag, revision, update_key, version_key

from .release_repository import (APP_REPOSITORY, PLUGIN_REPOSITORY, session, releases, _conditional_headers, _remember_response, asset_info, latest_manifest, manifest_offer)
from .plugin_catalog_api import (KNOWN_PLUGINS, PUBLISHED_PLUGINS, CATALOG_CHECK_SECONDS, plugin_catalog, _compatible_offers, load_plugin_cache, cached_plugin_catalog)


from .app_release_api import (release_notes, app_release)


from .verified_download import (download)
