"""发布版本、官方插件目录、下载完整性、取消和插件升级事务。"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import online, plugin_updates
from ddm.plugins import PluginManager, read_manifest


class Response:
    def __init__(self, data=b'', payload=None, chunks=None, status_code=200):
        self.data, self.payload, self.chunks = data, payload, chunks
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload

    def iter_content(self, size):
        yield from self.chunks if self.chunks is not None else [self.data]


class Client:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, *args, **kwargs):
        if '/releases/latest/download/' in args[0]:
            return Response(status_code=404)
        return self.responses.pop(0)


def asset(name, data=b'zip', repository=online.PLUGIN_REPOSITORY):
    return {'name': name, 'size': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest(),
            'browser_download_url': f'https://github.com/{repository}/releases/download/v1/{name}'}


def package(path, plugin_id='global_live', version='1.0', minimum='0.3'):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(plugin_id + '/plugin.json', json.dumps({
            'id': plugin_id, 'name': plugin_id, 'description': 'test', 'version': version,
            'min_app_version': minimum}))
        archive.writestr(plugin_id + '/plugin.py', 'from ddm.plugins import Plugin\nplugin = Plugin()\n')
        archive.writestr(plugin_id + '/module.py', 'VERSION = ' + repr(version))


def rejected(operation):
    try:
        operation()
    except (ValueError, InterruptedError, OSError):
        return
    raise AssertionError('operation should have failed')


def main():
    assert online.version_key('0.3') == online.version_key('v0.3.0')
    assert online.version_key('0.3.10') > online.version_key('0.3.9')
    rejected(lambda: online.version_key('0.4-rc1'))
    releases = [
        {'tag_name': 'v0.4', 'draft': True}, {'tag_name': 'v0.5', 'prerelease': True},
        {'tag_name': 'v0.2'}, {'tag_name': 'v0.3.1', 'body': 'fix', 'assets': [
            asset('DD监控室CE-v0.3.1-exe.zip', repository=online.APP_REPOSITORY)]}]
    release = online.app_release(Client([Response(payload=releases)]), '0.3')
    assert release['version'] == '0.3.1' and release['notes'] == 'fix'
    assert online.app_release(Client([Response(payload=releases)]), '0.3.1') is None
    rejected(lambda: online.asset_info(asset('p.zip') | {'browser_download_url': 'https://example.com/p.zip'}, online.PLUGIN_REPOSITORY))
    rejected(lambda: online.asset_info(asset('p.zip') | {'digest': None}, online.PLUGIN_REPOSITORY))
    # 最新 Release 的固定附件清单可绕开 API 额度，仍限制官方下载源。
    manifest = {'version': '0.3.2', 'asset_name': 'DD监控室CE-v0.3.2-exe.zip',
                'url': f'https://github.com/{online.APP_REPOSITORY}/releases/download/v0.3.2/DD监控室CE-v0.3.2-exe.zip',
                'size': 3, 'sha256': hashlib.sha256(b'zip').hexdigest(), 'notes': 'manifest update'}
    with patch.object(online, 'latest_manifest', return_value=manifest):
        assert online.app_release(Client([]), '0.3')['version'] == '0.3.2'
        assert online.app_release(Client([]), '0.3.2') is None
    with patch.object(online, 'latest_manifest', return_value=None), \
            patch.object(online, 'releases', side_effect=online.requests.HTTPError('rate limited')):
        fallback = online.plugin_catalog(Client([]), '0.3')
        assert len(fallback) == 3
        assert all(offer.get('cached') for offer in fallback if offer['available'])
    metadata = json.dumps({'plugins': [{'id': 'global_live', 'min_app_version': '0.4',
                                       'notes': 'plugin-specific fixes'}]}).encode()
    releases = [{'tag_name': 'v1', 'assets': [asset('global_live-1.0.zip'), asset('plugin-catalog.json', metadata)]},
                {'tag_name': 'older', 'assets': [asset('global_live-0.9.zip')]}]
    offers = online.plugin_catalog(Client([Response(payload=releases), Response(metadata)]), '0.3')
    overseas = next(offer for offer in offers if offer['id'] == 'global_live')
    assert overseas['version'] == '1.0' and not overseas['available'] and '0.4' in overseas['reason']
    assert overseas['notes'] == 'plugin-specific fixes'
    assert not next(offer for offer in offers if offer['id'] == 'match_sync')['available']
    with tempfile.TemporaryDirectory(prefix='ddm-online-test-') as temporary:
        root = Path(temporary)
        info = online.asset_info(asset('a.zip', b'123456'), online.PLUGIN_REPOSITORY)
        progress = []
        result = online.download(info, root / 'download.zip', Client([Response(chunks=[b'123', b'456'])]),
                                 progress=lambda *value: progress.append(value))
        assert Path(result).read_bytes() == b'123456' and progress[-1] == (6, 6)
        for content in (b'123', b'654321', b'1234567'):
            rejected(lambda: online.download(info, root / 'bad.zip', Client([Response(content)])))
            assert not (root / 'bad.zip').exists() and not (root / 'bad.zip.part').exists()
        rejected(lambda: online.download(info, root / 'cancel.zip', Client([Response(b'123456')]), cancelled=lambda: True))
        assert not (root / 'cancel.zip.part').exists()
        manager = PluginManager(plugins_dir=str(root / 'plugins'), enabled=[])
        first, second, incompatible = root / 'first.zip', root / 'second.zip', root / 'incompatible.zip'
        package(first)
        package(second, version='1.1')
        package(incompatible, version='1.2', minimum='9.0')
        plugin_updates.install(manager, first, {'id': 'global_live', 'version': '1.0'})
        assert manager.enabled == set(), 'background installation must not save UI state'
        installed = root / 'plugins' / 'global_live'
        (installed / 'data.json').write_text('original data')
        manager.plugin_settings['global_live'] = {'choice': 'keep'}
        plugin_updates.install(manager, second, {'id': 'global_live', 'version': '1.1'})
        assert read_manifest(str(installed), 'global_live')['version'] == '1.0'
        assert plugin_updates.pending_versions(manager) == {'global_live': '1.1'}
        (installed / 'data.json').write_text('data written after download')
        manager.load()
        assert read_manifest(str(installed), 'global_live')['version'] == '1.1'
        assert (installed / 'data.json').read_text() == 'data written after download'
        assert manager.plugin_settings['global_live'] == {'choice': 'keep'}
        assert manager.enabled == set() and not manager.plugins, 'disabled plugin must remain disabled'
        rejected(lambda: plugin_updates.install(manager, incompatible, {'id': 'global_live', 'version': '1.2'}))
        rejected(lambda: plugin_updates.install(manager, second, {'id': 'domestic_live', 'version': '1.1'}))
        assert not (root / 'plugins' / 'domestic_live').exists()
        # 模拟替换失败：旧代码和数据恢复，更新包仍可重试。
        package(second, version='1.3')
        plugin_updates.install(manager, second, {'id': 'global_live', 'version': '1.3'})
        replace = os.replace
        def fail_new(source, target):
            if '.merge-' in str(source):
                raise OSError('simulated sharing violation')
            return replace(source, target)
        with patch.object(plugin_updates.os, 'replace', side_effect=fail_new):
            plugin_updates.apply_pending(manager)
        assert read_manifest(str(installed), 'global_live')['version'] == '1.1'
        assert (installed / 'data.json').read_text() == 'data written after download'
        assert plugin_updates.pending_versions(manager) == {'global_live': '1.3'}
        manager.remove_plugin('global_live')
        assert not plugin_updates.pending_versions(manager)
    print('PASS: release selection, official catalog, compatibility, checksums/cancel, staged plugin upgrades and rollback')


if __name__ == '__main__':
    main()
