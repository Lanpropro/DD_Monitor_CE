"""插件目录缓存、条件查询、版本变化和离线保留。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import online
from selfcheck_online import Response


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(data, etag):
    result = Response(data=json.dumps(data).encode())
    result.headers = {'ETag': etag}
    return result


def main():
    manifest = {'plugins': [{'id': 'global_live', 'name': '海外直播平台', 'description': 'Twitch / YouTube',
        'version': '1.1', 'min_app_version': '0.3', 'asset_name': 'global_live-1.1.zip',
        'url': f'https://github.com/{online.PLUGIN_REPOSITORY}/releases/download/v1.1/global_live-1.1.zip',
        'size': 3, 'sha256': hashlib.sha256(b'zip').hexdigest()}]}
    with tempfile.TemporaryDirectory(prefix='ddm-plugin-cache-') as temporary:
        path = Path(temporary) / 'plugin-catalog.json'
        first = Client([response(manifest, 'first')])
        offers = online.cached_plugin_catalog(first, '0.3', path)
        assert offers[0]['name'] == '海外直播平台', 'asset filename must not replace the display name'
        assert len(first.calls) == 1 and online.load_plugin_cache(path)['offers'] == offers
        fresh = Client([])
        assert online.cached_plugin_catalog(fresh, '0.3', path) == offers and not fresh.calls
        unchanged = Client([Response(status_code=304)])
        assert online.cached_plugin_catalog(unchanged, '0.3', path, force=True) == offers
        assert unchanged.calls[0][1]['headers'] == {'If-None-Match': 'first'}
        later = online.load_plugin_cache(path)['checked_at'] + online.CATALOG_CHECK_SECONDS + 1
        with patch.object(online.time, 'time', return_value=later):
            stale = Client([Response(status_code=304)])
            assert online.cached_plugin_catalog(stale, '0.3', path) == offers and len(stale.calls) == 1
        updated = json.loads(json.dumps(manifest))
        updated['plugins'][0].update(version='1.2', min_app_version='0.4')
        changed = Client([response(updated, 'second')])
        latest = online.cached_plugin_catalog(changed, '0.3', path, force=True)
        assert latest[0]['version'] == '1.2' and not latest[0]['available']
        assert online.cached_plugin_catalog(Client([]), '0.4', path)[0]['available']
        offline = Client([online.requests.ConnectionError('offline'), online.requests.ConnectionError('offline')])
        assert online.cached_plugin_catalog(offline, '0.3', path, force=True) == latest
        assert online.load_plugin_cache(path)['offers'] == latest, 'network failure must retain the newer cached catalog'
        retry = Client([])
        assert online.cached_plugin_catalog(retry, '0.3', path) == latest and not retry.calls, \
            'offline reopenings must also respect the check interval'
        corrupted = online.load_plugin_cache(path)
        corrupted['offers'][0]['url'] = 'https://example.com/untrusted.zip'
        path.write_text(json.dumps(corrupted), encoding='utf-8')
        assert not online.load_plugin_cache(path)
        path.write_text('broken json', encoding='utf-8')
        assert not online.load_plugin_cache(path)
        # 旧仓库没有目录附件时，也可对 Release API 使用条件查询。
        release = [{'assets': [{'name': 'global_live-1.1.zip', 'size': 3,
            'digest': 'sha256:' + hashlib.sha256(b'zip').hexdigest(),
            'browser_download_url': manifest['plugins'][0]['url']}]}]
        api_response = Response(payload=release)
        api_response.headers = {'ETag': 'releases'}
        api = Client([Response(status_code=404), api_response])
        old_offers = online.cached_plugin_catalog(api, '0.3', path)
        conditional = Client([Response(status_code=404), Response(status_code=304)])
        assert online.cached_plugin_catalog(conditional, '0.3', path, force=True) == old_offers
        assert conditional.calls[1][1]['headers'] == {'If-None-Match': 'releases'}
    print('PASS: persistent plugin cache, no repeat requests, conditional checks, changed versions and offline retention')


if __name__ == '__main__':
    main()
