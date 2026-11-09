"""Official release HTTP transport, conditional responses and asset/manifest validation."""
import re
import json
from urllib.parse import urlsplit
import requests
from .update_version import app_tag, revision, version_key


APP_REPOSITORY = 'Lanpropro/DD_Monitor_CE'


PLUGIN_REPOSITORY = 'Lanpropro/DD_Monitor_Plugins'


def session():
    client = requests.Session()
    client.headers['User-Agent'] = 'DD-Monitor-CE-Updater'
    client.headers['Accept'] = 'application/vnd.github+json'
    return client


def releases(repository, client, cache=None):
    from . import online as api
    if repository not in (api.APP_REPOSITORY, api.PLUGIN_REPOSITORY):
        raise ValueError('不支持的更新仓库')
    with client.get(f'https://api.github.com/repos/{repository}/releases',
                    params={'per_page': 30}, timeout=(5, 15),
                    headers=api._conditional_headers(cache, 'releases')) as response:
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
    api._remember_response(cache, 'releases', response, data)
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
    from . import online as api
    with client.get(f'https://github.com/{repository}/releases/latest/download/{name}',
                    timeout=(5, 15), stream=True,
                    headers=api._conditional_headers(cache, 'manifest')) as response:
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
    api._remember_response(cache, 'manifest', response, data)
    return data


def manifest_offer(entry, repository):
    from . import online as api
    entry = dict(entry)
    version_key(entry['version'])
    if not entry['asset_name'].endswith('-exe.zip' if repository == api.APP_REPOSITORY else '.zip'):
        raise ValueError('在线目录必须指向对应的 ZIP 安装包')
    info = api.asset_info({'browser_download_url': entry['url'], 'name': entry['asset_name'],
                       'digest': 'sha256:' + entry['sha256'], 'size': entry['size']}, repository)
    entry.update(info)
    if repository == api.PLUGIN_REPOSITORY:
        entry['name'] = api.KNOWN_PLUGINS.get(entry.get('id'), (entry['name'], ''))[0]
    else:
        tag = entry.get('release_tag', 'v' + entry['version'].removeprefix('v'))
        base, tag_revision = app_tag(tag)
        entry['revision'] = revision(entry.get('revision', tag_revision))
        if version_key(base) != version_key(entry['version']) or (tag_revision and tag_revision != entry['revision']):
            raise ValueError('更新清单的标签、版本与修订号不一致')
        entry['release_tag'] = tag
    return entry
