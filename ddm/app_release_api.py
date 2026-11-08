"""Application release selection, revision matching and published notes."""
from pathlib import Path
import json
import tempfile
import requests
from .update_version import app_tag, update_key, version_key
from .release_repository import APP_REPOSITORY, releases, asset_info, latest_manifest, manifest_offer


def release_notes(client, release_version, release_tag=None):
    from . import online as api
    version_key(release_version)
    tag = release_tag or 'v' + release_version.removeprefix('v')
    if version_key(app_tag(tag)[0]) != version_key(release_version):
        raise ValueError('发布说明标签与版本不一致')
    with client.get(f'https://api.github.com/repos/{api.APP_REPOSITORY}/releases/tags/{tag}',
                    timeout=(5, 15)) as response:
        response.raise_for_status()
        release = response.json()
    if (release.get('tag_name') != tag or release.get('draft') or release.get('prerelease')
            or not isinstance(release.get('body'), str) or not release['body'].strip()):
        raise ValueError('正式版本的在线发布说明无效')
    return release['body'].replace('\r\n', '\n').rstrip() + '\n'


def app_release(client, current_version, current_revision=0):
    from . import online as api
    current = update_key(current_version, current_revision)
    try:
        manifest = api.latest_manifest(client, api.APP_REPOSITORY, 'app-update.json')
    except requests.RequestException:
        manifest = None
    if manifest is not None:
        offer = api.manifest_offer(manifest, api.APP_REPOSITORY)
        if update_key(offer['version'], offer['revision']) <= current:
            return None
        offer.setdefault('notes', '暂无更新说明')
        try:
            offer['notes'] = api.release_notes(client, offer['version'], offer['release_tag'])
        except (requests.RequestException, ValueError):
            pass
        return offer
    candidates = []
    for release in api.releases(api.APP_REPOSITORY, client):
        try:
            base, number = app_tag(release.get('tag_name', ''))
            key = version_key(base)
        except ValueError:
            continue
        if key >= current[0]:
            candidates.append((key, base, number, release))
    if not candidates:
        return None
    latest_base = max(candidate[0] for candidate in candidates)
    best, best_offer = current, None
    for key, base, number, release in sorted(candidates, key=lambda entry: (entry[0], entry[2]), reverse=True):
        if key != latest_base:
            continue
        if number and (key, number) <= best:
            continue
        metadata = next((asset for asset in release.get('assets', []) if asset.get('name') == 'app-update.json'), None)
        if metadata is not None:
            info = api.asset_info(metadata, api.APP_REPOSITORY)
            if info['size'] > 1024 * 1024:
                raise ValueError('本体更新清单超过大小限制')
            with tempfile.TemporaryDirectory(prefix='ddm-app-manifest-') as temporary:
                path = api.download(info, Path(temporary)/'app-update.json', client)
                data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            data.setdefault('release_tag', release['tag_name'])
            offer = api.manifest_offer(data, api.APP_REPOSITORY)
            if version_key(offer['version']) != key or (number and offer['revision'] != number):
                raise ValueError('更新清单与正式发布记录不一致')
        else:
            if (key, number) <= best:
                continue
            offer = {'version': base, 'revision': number, 'release_tag': release['tag_name']}
            assets = [asset for asset in release.get('assets', [])
                      if asset.get('name', '').lower().endswith('-exe.zip')]
            if len(assets) != 1:
                raise ValueError('新版尚未提供唯一的 Windows EXE 更新包')
            offer.update(api.asset_info(assets[0], api.APP_REPOSITORY))
        offer.update(notes=release.get('body') or offer.get('notes') or '暂无更新说明',
                     release_url=release.get('html_url', ''))
        candidate = update_key(offer['version'], offer['revision'])
        if candidate > best:
            best, best_offer = candidate, offer
    return best_offer
