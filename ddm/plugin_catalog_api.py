"""Official plugin offers, compatibility and persistent catalog cache."""
import os
from pathlib import Path
import re
import json
import tempfile
import time
import requests
from .update_version import version_key
from .release_repository import PLUGIN_REPOSITORY, releases, asset_info, latest_manifest, manifest_offer


KNOWN_PLUGINS = {
    'bili_live': ('B站直播互动', '逐格发送弹幕、表情与直播礼物；使用本体登录'),
    'domestic_live': ('国内直播平台', '虎牙、斗鱼、抖音的直播与关注接入'),
    'global_live': ('海外直播平台', 'Twitch、YouTube 的直播与账号授权'),
    'match_sync': ('比赛二路同步', '多主播比赛画面同步、声音和弹幕合并'),
}


PUBLISHED_PLUGINS = (
    ('domestic_live', '1.0', 22886, 'fd0ee1403903bf7e75a4aefeaa626f31aa638a6a4a787203f7878eb7d2914030'),
    ('global_live', '1.0', 18061, '5d71e1e1658842ca16af66ad49e6531354f1bda85b0e94d400d92f8a149f8807'),
)


CATALOG_CHECK_SECONDS = 15 * 60


def plugin_catalog(client, current_version, cache=None):
    from . import online as api
    offers = {}
    try:
        catalog = api.latest_manifest(client, api.PLUGIN_REPOSITORY, 'plugin-catalog.json', cache=cache)
        if catalog is not None:
            for entry in catalog['plugins']:
                if entry['id'] not in api.KNOWN_PLUGINS:
                    continue
                offer = api.manifest_offer(entry, api.PLUGIN_REPOSITORY)
                offer['available'] = version_key(current_version) >= version_key(entry['min_app_version'])
                if not offer['available']:
                    offer['reason'] = '请先更新本体至 ' + entry['min_app_version']
                offers[entry['id']] = offer
    except requests.RequestException:
        pass
    try:
        published = api.releases(api.PLUGIN_REPOSITORY, client, cache=cache)
    except requests.RequestException:
        for cached_offer in api._compatible_offers((cache or {}).get('offers', []), current_version):
            plugin_id = cached_offer['id']
            if (plugin_id not in offers or cached_offer.get('version') and
                    version_key(cached_offer['version']) > version_key(offers[plugin_id]['version'])):
                offers[plugin_id] = dict(cached_offer, cached=True)
        if offers:
            return list(offers.values())
        # 公开 API 额度用尽或离线时仍能展示已核实的官方安装包。
        published = [{'assets': [
            {'name': f'{plugin_id}-{plugin_version}.zip', 'size': size, 'digest': 'sha256:' + digest,
             'browser_download_url': f'https://github.com/{api.PLUGIN_REPOSITORY}/releases/download/v1.0/{plugin_id}-{plugin_version}.zip'}
            for plugin_id, plugin_version, size, digest in api.PUBLISHED_PLUGINS]}]
        cached = True
    else:
        cached = False
    for release in published:
        candidates = []
        for asset in release.get('assets', []):
            match = re.fullmatch(r'(domestic_live|global_live|match_sync|match-sync|bili_live)-v?(\d+(?:\.\d+){0,3})\.zip',
                                 asset.get('name', ''))
            if not match:
                continue
            plugin_id, plugin_version = match.groups()
            plugin_id = plugin_id.replace('-', '_')
            if plugin_id in offers and version_key(offers[plugin_id]['version']) >= version_key(plugin_version):
                continue
            candidates.append((plugin_id, plugin_version, asset))
        if not candidates:
            continue
        metadata = {}
        catalog_asset = next((asset for asset in release.get('assets', [])
                              if asset.get('name') == 'plugin-catalog.json'), None)
        if catalog_asset:
            info = api.asset_info(catalog_asset, api.PLUGIN_REPOSITORY)
            if info['size'] > 1024 * 1024:
                raise ValueError('插件目录清单超过限制')
            with tempfile.TemporaryDirectory(prefix='ddm-catalog-') as temporary:
                path = api.download(info, Path(temporary) / 'catalog.json', client)
                data = json.loads(Path(path).read_text(encoding='utf-8'))
            metadata = {entry['id']: entry for entry in data['plugins'] if entry['id'] in api.KNOWN_PLUGINS}
        for plugin_id, plugin_version, asset in candidates:
            if plugin_id in offers and version_key(offers[plugin_id]['version']) >= version_key(plugin_version):
                continue
            name, description = api.KNOWN_PLUGINS[plugin_id]
            details = metadata.get(plugin_id, {})
            offer = {'id': plugin_id, 'name': name, 'description': description,
                     'version': plugin_version, 'min_app_version': details.get('min_app_version', '0.3'),
                     'notes': details.get('notes') or release.get('body', ''),
                     'author': details.get('author', ''),
                     'release_url': release.get('html_url', ''), 'available': True, 'cached': cached}
            try:
                offer.update(api.asset_info(asset, api.PLUGIN_REPOSITORY))
                offer['name'] = name
            except ValueError as error:
                offer.update(available=False, reason=str(error))
            if version_key(current_version) < version_key(offer['min_app_version']):
                offer.update(available=False, reason='请先更新本体至 ' + offer['min_app_version'] + ' 或更高版本')
            offers[plugin_id] = offer
    for plugin_id, (name, description) in api.KNOWN_PLUGINS.items():
        offers.setdefault(plugin_id, {'id': plugin_id, 'name': name, 'description': description,
                                     'version': '', 'available': False, 'reason': '官方仓库暂未发布安装包'})
    if cache is not None:
        cache['source'] = 'combined'
    return list(offers.values())


def _compatible_offers(offers, current_version):
    result = []
    for offer in offers:
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
                or not isinstance(data['checked_at'], (int, float)) or not isinstance(data['offers'], list)):
            return {}
        for offer in data['offers']:
            if (not isinstance(offer, dict) or offer['id'] not in api.KNOWN_PLUGINS
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
    cache = api.load_plugin_cache(path)
    now = time.time()
    if not force and cache and 0 <= now - cache['checked_at'] < api.CATALOG_CHECK_SECONDS:
        return api._compatible_offers(cache['offers'], current_version)
    offers = api.plugin_catalog(client, current_version, cache=cache)
    cache.update(repository=api.PLUGIN_REPOSITORY, offers=offers, checked_at=now)
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.plugin-catalog-', dir=path.parent)
        os.close(descriptor)
        try:
            Path(temporary).write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    except OSError:
        pass
    return offers
