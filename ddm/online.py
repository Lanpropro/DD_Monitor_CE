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

APP_REPOSITORY = 'Lanpropro/DD_Monitor_CE'
PLUGIN_REPOSITORY = 'Lanpropro/DD_Monitor_Plugins'
KNOWN_PLUGINS = {
    'domestic_live': ('国内直播平台', '虎牙、斗鱼、抖音的直播与关注接入'),
    'global_live': ('海外直播平台', 'Twitch、YouTube 的直播与账号授权'),
    'match_sync': ('比赛二路同步', '多主播比赛画面同步、声音和弹幕合并'),
}
PUBLISHED_PLUGINS = (
    ('domestic_live', '1.0', 22886, 'fd0ee1403903bf7e75a4aefeaa626f31aa638a6a4a787203f7878eb7d2914030'),
    ('global_live', '1.0', 18061, '5d71e1e1658842ca16af66ad49e6531354f1bda85b0e94d400d92f8a149f8807'),
)
CATALOG_CHECK_SECONDS = 15 * 60


def version_key(value):
    text = str(value).removeprefix('v')
    if not re.fullmatch(r'\d+(?:\.\d+){0,3}', text):
        raise ValueError('版本号必须使用数字，例如 0.3 或 0.3.1')
    parts = tuple(map(int, text.split('.')))
    return parts + (0,) * (4 - len(parts))


def session():
    client = requests.Session()
    client.headers['User-Agent'] = 'DD-Monitor-CE-Updater'
    client.headers['Accept'] = 'application/vnd.github+json'
    return client


def releases(repository, client, cache=None):
    if repository not in (APP_REPOSITORY, PLUGIN_REPOSITORY):
        raise ValueError('不支持的更新仓库')
    with client.get(f'https://api.github.com/repos/{repository}/releases',
                    params={'per_page': 30}, timeout=(5, 15),
                    headers=_conditional_headers(cache, 'releases')) as response:
        if response.status_code == 304 and cache is not None and 'releases' in cache:
            cache['unchanged'] = True
            return cache['releases']['data']
        if response.status_code in (403, 429) and getattr(response, 'headers', {}).get('X-RateLimit-Remaining') == '0':
            raise requests.HTTPError('GitHub 查询额度暂时用尽，请稍后重试或打开发布页面')
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list):
        raise ValueError('仓库版本列表格式无效')
    data = [release for release in data if not release.get('draft') and not release.get('prerelease')]
    _remember_response(cache, 'releases', response, data)
    return data


def _conditional_headers(cache, key):
    entry = (cache or {}).get(key, {})
    return {'If-None-Match': entry['etag']} if entry.get('etag') else {}


def _remember_response(cache, key, response, data):
    if cache is not None:
        cache['unchanged'] = data == cache.get(key, {}).get('data')
        cache[key] = {'etag': getattr(response, 'headers', {}).get('ETag', ''), 'data': data}


def asset_info(asset, repository):
    url = asset.get('browser_download_url', '')
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc != 'github.com'
            or not parts.path.startswith(f'/{repository}/releases/download/')):
        raise ValueError('安装包必须来自官方仓库 Release')
    digest = str(asset.get('digest') or '')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        raise ValueError('安装包缺少 SHA-256 校验值，请维护者重新发布')
    size = asset.get('size')
    if not isinstance(size, int) or not 0 < size <= 1024 * 1024 * 1024:
        raise ValueError('安装包大小无效')
    return {'url': url, 'sha256': digest[7:].lower(), 'size': size, 'name': asset['name']}


def latest_manifest(client, repository, name, cache=None):
    with client.get(f'https://github.com/{repository}/releases/latest/download/{name}',
                    timeout=(5, 15), stream=True,
                    headers=_conditional_headers(cache, 'manifest')) as response:
        if response.status_code == 304 and cache is not None and 'manifest' in cache:
            cache['unchanged'] = True
            return cache['manifest']['data']
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise ValueError('在线目录超过大小限制')
    data = json.loads(body.decode('utf-8-sig'))
    _remember_response(cache, 'manifest', response, data)
    return data


def manifest_offer(entry, repository):
    entry = dict(entry)
    version_key(entry['version'])
    if not entry['asset_name'].endswith('-exe.zip' if repository == APP_REPOSITORY else '.zip'):
        raise ValueError('在线目录必须指向对应的 ZIP 安装包')
    info = asset_info({'browser_download_url': entry['url'], 'name': entry['asset_name'],
                       'digest': 'sha256:' + entry['sha256'], 'size': entry['size']}, repository)
    entry.update(info)
    if repository == PLUGIN_REPOSITORY:
        entry['name'] = KNOWN_PLUGINS.get(entry.get('id'), (entry['name'], ''))[0]
    return entry


def plugin_catalog(client, current_version, cache=None):
    try:
        catalog = latest_manifest(client, PLUGIN_REPOSITORY, 'plugin-catalog.json', cache=cache)
        if catalog is not None:
            if cache and cache.get('source') == 'manifest' and cache.get('unchanged') and cache.get('offers'):
                return _compatible_offers(cache['offers'], current_version)
            offers = []
            for entry in catalog['plugins']:
                if entry['id'] not in KNOWN_PLUGINS:
                    continue
                offer = manifest_offer(entry, PLUGIN_REPOSITORY)
                offer['available'] = version_key(current_version) >= version_key(entry['min_app_version'])
                if not offer['available']:
                    offer['reason'] = '请先更新本体至 ' + entry['min_app_version']
                offers.append(offer)
            if cache is not None:
                cache['source'] = 'manifest'
            return offers
    except requests.RequestException:
        pass
    offers = {}
    try:
        published = releases(PLUGIN_REPOSITORY, client, cache=cache)
        if cache and cache.get('source') == 'releases' and cache.get('unchanged') and cache.get('offers'):
            return _compatible_offers(cache['offers'], current_version)
    except requests.RequestException:
        if cache and cache.get('offers'):
            return _compatible_offers(cache['offers'], current_version)
        # 公开 API 额度用尽或离线时仍能展示已核实的官方安装包。
        published = [{'assets': [
            {'name': f'{plugin_id}-{plugin_version}.zip', 'size': size, 'digest': 'sha256:' + digest,
             'browser_download_url': f'https://github.com/{PLUGIN_REPOSITORY}/releases/download/v1.0/{plugin_id}-{plugin_version}.zip'}
            for plugin_id, plugin_version, size, digest in PUBLISHED_PLUGINS]}]
        cached = True
    else:
        cached = False
    for release in published:
        metadata = {}
        catalog_asset = next((asset for asset in release.get('assets', [])
                              if asset.get('name') == 'plugin-catalog.json'), None)
        if catalog_asset:
            info = asset_info(catalog_asset, PLUGIN_REPOSITORY)
            if info['size'] > 1024 * 1024:
                raise ValueError('插件目录清单超过限制')
            with tempfile.TemporaryDirectory(prefix='ddm-catalog-') as temporary:
                path = download(info, Path(temporary) / 'catalog.json', client)
                data = json.loads(Path(path).read_text(encoding='utf-8'))
            metadata = {entry['id']: entry for entry in data['plugins'] if entry['id'] in KNOWN_PLUGINS}
        for asset in release.get('assets', []):
            match = re.fullmatch(r'(domestic_live|global_live|match_sync|match-sync)-v?(\d+(?:\.\d+){0,3})\.zip',
                                 asset.get('name', ''))
            if not match:
                continue
            plugin_id, plugin_version = match.groups()
            plugin_id = plugin_id.replace('-', '_')
            if plugin_id in offers and version_key(offers[plugin_id]['version']) >= version_key(plugin_version):
                continue
            name, description = KNOWN_PLUGINS[plugin_id]
            details = metadata.get(plugin_id, {})
            offer = {'id': plugin_id, 'name': name, 'description': description,
                     'version': plugin_version, 'min_app_version': details.get('min_app_version', '0.3'),
                     'notes': details.get('notes') or release.get('body', ''),
                     'release_url': release.get('html_url', ''), 'available': True, 'cached': cached}
            try:
                offer.update(asset_info(asset, PLUGIN_REPOSITORY))
                offer['name'] = name
            except ValueError as error:
                offer.update(available=False, reason=str(error))
            if version_key(current_version) < version_key(offer['min_app_version']):
                offer.update(available=False, reason='请先更新本体至 ' + offer['min_app_version'] + ' 或更高版本')
            offers[plugin_id] = offer
    for plugin_id, (name, description) in KNOWN_PLUGINS.items():
        offers.setdefault(plugin_id, {'id': plugin_id, 'name': name, 'description': description,
                                     'version': '', 'available': False, 'reason': '官方仓库暂未发布安装包'})
    if cache is not None:
        cache['source'] = 'releases'
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
    try:
        path = Path(path)
        if path.stat().st_size > 4 * 1024 * 1024:
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('repository') != PLUGIN_REPOSITORY
                or not isinstance(data['checked_at'], (int, float)) or not isinstance(data['offers'], list)):
            return {}
        for offer in data['offers']:
            if (not isinstance(offer, dict) or offer['id'] not in KNOWN_PLUGINS
                    or not isinstance(offer['name'], str) or not isinstance(offer['description'], str)):
                return {}
            version_key(offer.get('min_app_version', '0.3'))
            if offer.get('version'):
                version_key(offer['version'])
            if offer.get('available') or offer.get('url'):
                asset_info({'browser_download_url': offer['url'], 'digest': 'sha256:' + offer['sha256'],
                            'size': offer['size'], 'name': offer['name']}, PLUGIN_REPOSITORY)
        for key, kind in (('manifest', dict), ('releases', list)):
            if key in data and (not isinstance(data[key], dict) or not isinstance(data[key].get('data'), kind)
                                or not isinstance(data[key].get('etag', ''), str)):
                return {}
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def cached_plugin_catalog(client, current_version, path, force=False):
    cache = load_plugin_cache(path)
    now = time.time()
    if not force and cache and 0 <= now - cache['checked_at'] < CATALOG_CHECK_SECONDS:
        return _compatible_offers(cache['offers'], current_version)
    offers = plugin_catalog(client, current_version, cache=cache)
    cache.update(repository=PLUGIN_REPOSITORY, offers=offers, checked_at=now)
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


def app_release(client, current_version):
    try:
        manifest = latest_manifest(client, APP_REPOSITORY, 'app-update.json')
    except requests.RequestException:
        manifest = None
    if manifest is not None:
        if version_key(manifest['version']) <= version_key(current_version):
            return None
        offer = manifest_offer(manifest, APP_REPOSITORY)
        offer.setdefault('notes', '暂无更新说明')
        return offer
    candidates = []
    for release in releases(APP_REPOSITORY, client):
        try:
            key = version_key(release.get('tag_name', ''))
        except ValueError:
            continue
        if key > version_key(current_version):
            candidates.append((key, release))
    if not candidates:
        return None
    _, release = max(candidates, key=lambda candidate: candidate[0])
    offer = {'version': release['tag_name'].removeprefix('v'),
             'notes': release.get('body') or '暂无更新说明', 'release_url': release.get('html_url', '')}
    assets = [asset for asset in release.get('assets', [])
              if asset.get('name', '').lower().endswith('-exe.zip')]
    if len(assets) != 1:
        raise ValueError('新版尚未提供唯一的 Windows EXE 更新包')
    offer.update(asset_info(assets[0], APP_REPOSITORY))
    return offer


def download(offer, destination, client, cancelled=lambda: False, progress=lambda *_: None):
    """完整下载并校验后才交付文件；取消或失败清理半成品。"""
    destination = Path(destination)
    partial = destination.with_suffix(destination.suffix + '.part')
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest, received = hashlib.sha256(), 0
    try:
        with client.get(offer['url'], stream=True, timeout=(5, 15)) as response:
            response.raise_for_status()
            with partial.open('wb') as output:
                for chunk in response.iter_content(128 * 1024):
                    if cancelled():
                        raise InterruptedError('下载已取消')
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > offer['size']:
                        raise ValueError('下载大小超过发布包记录')
                    output.write(chunk)
                    digest.update(chunk)
                    progress(received, offer['size'])
        if cancelled():
            raise InterruptedError('下载已取消')
        if received != offer['size'] or digest.hexdigest() != offer['sha256']:
            raise ValueError('安装包完整性校验失败，请重新下载')
        os.replace(partial, destination)
        return str(destination)
    finally:
        partial.unlink(missing_ok=True)
