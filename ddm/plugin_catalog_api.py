"""Discover official Release ZIPs, inspect their manifests and cache verified offers."""
from pathlib import Path
import re
import json
import tempfile
import time
import zipfile
from types import SimpleNamespace
import requests
from . import image_cache
from .cache_cleanup import store_catalog
from .update_version import version_key
from .plugin_manifest import PLUGIN_ID, RETIRED_BUNDLED_PLUGINS, read_manifest
from .plugin_icons import package_icon
from .plugin_packages import PluginPackages
from .file_ops import replace_directory


CATALOG_CHECK_SECONDS = 15 * 60
CATALOG_CACHE_VERSION = 2
PLUGIN_ARCHIVE = re.compile(r'([a-z][a-z0-9_-]*)-v?(\d+(?:\.\d+){0,3})\.zip')
_PACKAGE_METADATA = ('name', 'description', 'min_app_version', 'author', 'icon_png')


def _package_metadata(path, plugin_id, plugin_version):
    # Reuse the installer's package/path limits without loading plugin code.
    with tempfile.TemporaryDirectory(prefix='ddm-catalog-check-') as temporary:
        host = SimpleNamespace(plugins_dir=temporary, enabled=None, plugin_settings={})
        installed = PluginPackages(host).install_zip(
            path, manifest_reader=read_manifest, directory_replace=replace_directory)
        if installed != plugin_id:
            raise ValueError('安装包 ID 与附件文件名不一致')
        folder = Path(temporary) / installed
        manifest = read_manifest(str(folder), installed)
        if manifest['version'] != plugin_version:
            raise ValueError('安装包版本与附件文件名不一致')
        version_key(manifest['version'])
        minimum = manifest.get('min_app_version', '0.3')
        version_key(minimum)
        author = manifest.get('author', '')
        if not isinstance(author, str):
            raise ValueError('插件作者必须是字符串')
        return {key: manifest[key] for key in ('name', 'description')} | {
            'min_app_version': minimum, 'author': author,
            'icon_png': package_icon(folder, manifest.get('icon'))}


def plugin_catalog(client, current_version, cache=None):
    from . import online as api
    try:
        published = api.releases(api.PLUGIN_REPOSITORY, client, cache=cache)
    except requests.RequestException:
        saved = (cache or {}).get('offers', [])
        if not saved:
            raise
        return [dict(offer, cached=True) for offer in _compatible_offers(saved, current_version)]
    candidates = {}
    for release in published:
        if release.get('draft') or release.get('prerelease'):
            continue
        for asset in release.get('assets', []):
            match = PLUGIN_ARCHIVE.fullmatch(asset.get('name', ''))
            if not match:
                continue
            plugin_id, plugin_version = match.groups()
            plugin_id = plugin_id.replace('-', '_')
            if plugin_id in RETIRED_BUNDLED_PLUGINS:
                continue
            previous = candidates.get(plugin_id)
            if previous is None or version_key(plugin_version) > version_key(previous[0]):
                candidates[plugin_id] = (plugin_version, asset, release)
    saved = {offer['id']: offer for offer in (cache or {}).get('offers', [])}
    offers = []
    for plugin_id, (plugin_version, asset, release) in candidates.items():
        offer = {'id': plugin_id, 'name': plugin_id, 'description': '',
                 'version': plugin_version, 'min_app_version': '0.3',
                 'notes': release.get('body') or '', 'author': '', 'icon_png': '',
                 'release_url': release.get('html_url', ''), 'available': True, 'cached': False}
        try:
            info = api.asset_info(asset, api.PLUGIN_REPOSITORY)
            previous = saved.get(plugin_id, {})
            if (previous.get('version') == plugin_version and
                    all(previous.get(key) == info[key] for key in ('url', 'sha256', 'size')) and
                    all(key in previous for key in _PACKAGE_METADATA) and
                    (previous.get('available') or previous.get('reason', '').startswith('请先更新本体至 '))):
                offer.update({key: previous[key] for key in _PACKAGE_METADATA})
            else:
                with tempfile.TemporaryDirectory(prefix='ddm-catalog-') as temporary:
                    path = api.download(info, Path(temporary) / 'plugin.zip', client)
                    offer.update(_package_metadata(path, plugin_id, plugin_version))
            # Asset names are filenames, not the plugin's display name.
            offer.update({key: info[key] for key in ('url', 'sha256', 'size')})
            if version_key(current_version) < version_key(offer['min_app_version']):
                offer.update(available=False, reason='请先更新本体至 ' + offer['min_app_version'])
        except (requests.RequestException, OSError, ValueError, zipfile.BadZipFile, KeyError, TypeError) as error:
            offer.update(available=False, reason='插件包核验失败：' + str(error))
        offers.append(offer)
    if cache is not None:
        cache['source'] = 'releases'
    return offers


def _compatible_offers(offers, current_version):
    result = []
    for offer in offers:
        if offer['id'] in RETIRED_BUNDLED_PLUGINS:
            continue
        offer = dict(offer)
        minimum = offer.get('min_app_version', '0.3')
        if offer.get('reason', '').startswith('请先更新本体至 '):
            offer.pop('reason')
            offer['available'] = True
        if offer.get('available') and version_key(current_version) < version_key(minimum):
            offer.update(available=False, reason='请先更新本体至 ' + minimum)
        result.append(offer)
    return result


def load_plugin_cache(path):
    from . import online as api
    try:
        path = Path(path)
        if path.stat().st_size > 4 * 1024 * 1024:
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('repository') != api.PLUGIN_REPOSITORY
                or data.get('catalog_version') != CATALOG_CACHE_VERSION
                or not isinstance(data['checked_at'], (int, float)) or not isinstance(data['offers'], list)):
            return {}
        for offer in data['offers']:
            if (not isinstance(offer, dict) or not isinstance(offer.get('id'), str) or not PLUGIN_ID.fullmatch(offer['id'])
                    or not isinstance(offer['name'], str) or not isinstance(offer['description'], str)):
                return {}
            version_key(offer.get('min_app_version', '0.3'))
            if offer.get('version'):
                version_key(offer['version'])
            if offer.get('available') or offer.get('url'):
                api.asset_info({'browser_download_url': offer['url'], 'digest': 'sha256:' + offer['sha256'],
                            'size': offer['size'], 'name': offer['name']}, api.PLUGIN_REPOSITORY)
        for key, kind in (('manifest', dict), ('releases', list)):
            if key in data and (not isinstance(data[key], dict) or not isinstance(data[key].get('data'), kind)
                                or not isinstance(data[key].get('etag', ''), str)):
                return {}
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def cached_plugin_catalog(client, current_version, path, force=False):
    from . import online as api
    stamp = image_cache.ticket()
    cache = api.load_plugin_cache(path)
    now = time.time()
    if not force and cache and 0 <= now - cache['checked_at'] < api.CATALOG_CHECK_SECONDS:
        return api._compatible_offers(cache['offers'], current_version)
    offers = api.plugin_catalog(client, current_version, cache=cache)
    cache.update(repository=api.PLUGIN_REPOSITORY, catalog_version=CATALOG_CACHE_VERSION,
                 offers=offers, checked_at=now)
    path = Path(path)
    try:
        store_catalog(path, json.dumps(cache, ensure_ascii=False).encode('utf-8'), stamp)
    except OSError:
        pass
    return offers
