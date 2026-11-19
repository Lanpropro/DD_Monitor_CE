"""Release ZIP discovery and verified catalog caching; synthetic requests and temporary packages only."""
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import online
from ddm.plugin_catalog_api import ICON_MAX_BYTES, decode_catalog_icon
from selfcheck_online import Response, asset


CATALOG_LOGO = ('iVBORw0KGgoAAAANSUhEUgAAACgAAAAUCAYAAAD/Rn+7AAAANElEQVR4nO3OMQ0AAAjAMLyg'
                'A/9OsAEqyDh29G901nwWdMCgQTpg0CAdMGiQDhg0SAcMXlugKBgKZpq8swAAAABJRU5ErkJggg==')


def package(plugin_id='new_plugin', version='1.0', *, files=None, **changes):
    manifest = dict(id=plugin_id, name='新插件', description='来自包内清单', version=version,
                    min_app_version='0.7.3', author='community-author')
    manifest.update(changes)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr(f'{plugin_id}/plugin.json', json.dumps(manifest))
        archive.writestr(f'{plugin_id}/plugin.py', "raise RuntimeError('must not execute')")
        for name, content in (files or {}).items():
            archive.writestr(f'{plugin_id}/{name}', content)
    return output.getvalue()


def release(plugin_id='new_plugin', version='1.0', content=None, **changes):
    item = dict(tag_name=f'{plugin_id}-v{version}', body='公开更新说明',
                html_url=f'https://github.com/{online.PLUGIN_REPOSITORY}/releases/tag/{plugin_id}-v{version}',
                assets=[asset(f'{plugin_id}-{version}.zip', content or package(plugin_id, version))])
    item.update(changes)
    return item


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


def published(items, etag='first'):
    response = Response(payload=items)
    response.headers = {'ETag': etag}
    return response


class DiscoveryTests(unittest.TestCase):
    def test_new_plugin_metadata_and_compatibility_without_execution(self):
        content = package()
        offer, = online.plugin_catalog(Client([published([release(content=content)]), Response(content)]), '0.7.2')
        self.assertEqual((offer['id'], offer['name'], offer['description'], offer['author']),
                         ('new_plugin', '新插件', '来自包内清单', 'community-author'))
        self.assertFalse(offer['available'])
        self.assertIn('0.7.3', offer['reason'])
        self.assertTrue(online._compatible_offers([offer], '0.7.3')[0]['available'])

    def test_highest_version_ignores_manifest_attachments_drafts_and_previews(self):
        content = package(version='1.10')
        latest = release(version='1.10', content=content)
        latest['assets'] += [asset('plugin-catalog.json', b'invalid'), asset('source.zip')]
        client = Client([published([release(version='1.9'), latest,
                                   release(version='2.0', draft=True), release(version='3.0', prerelease=True)]),
                         Response(content)])
        offer, = online.plugin_catalog(client, '0.7.3')
        self.assertEqual(offer['version'], '1.10')
        self.assertTrue(offer['available'])
        self.assertEqual(len(client.calls), 2)

    def test_discover_a_plugin_that_replaces_a_bundle(self):
        content = package('youtube_live', version='0.1', min_app_version='0.8',
                          replaces='global_live', platforms=['youtube'],
                          inherit_settings=['show_platform_logo'])
        item = release('youtube_live', version='0.1', content=content)
        client = Client([published([item]), Response(content)])
        offer, = online.plugin_catalog(client, '0.8')
        self.assertEqual(offer['id'], 'youtube_live')
        self.assertEqual(offer['min_app_version'], '0.8')
        self.assertTrue(offer['available'])

    def test_optional_logo_comes_from_the_verified_zip(self):
        png = base64.b64decode(CATALOG_LOGO)
        logo = 'assets/logo.png'
        oversized = png + b'\x00' * ICON_MAX_BYTES
        dimensions = png[:16] + (4096).to_bytes(4, 'big') + png[20:]
        for path, image, expected in ((logo, png, CATALOG_LOGO),
                ('../assets/logo.png', png, ''), ('https://example.com/logo.png', png, ''),
                ('missing.png', png, ''), (logo, b'not an image', ''),
                (logo, oversized, ''), (logo, dimensions, ''), (None, png, '')):
            with self.subTest(icon=path, size=len(image)):
                content = package(files={logo: image}, icon=path)
                offer, = online.plugin_catalog(Client([published([release(content=content)]), Response(content)]), '0.8')
                self.assertTrue(offer['available'])
                self.assertEqual(offer['icon_png'], expected)
        self.assertEqual(decode_catalog_icon(CATALOG_LOGO), png)
        self.assertEqual(decode_catalog_icon(base64.b64encode(dimensions).decode('ascii')), b'')
        self.assertEqual(decode_catalog_icon('not base64!'), b'')

    def test_bad_candidate_does_not_hide_other_plugins(self):
        wrong = package('other_id')
        valid = package('valid_plugin')
        offers = online.plugin_catalog(Client([published([
            release(content=wrong), release('valid_plugin', content=valid)]), Response(wrong), Response(valid)]), '0.7.3')
        self.assertFalse(offers[0]['available'])
        self.assertIn('ID', offers[0]['reason'])
        self.assertTrue(offers[1]['available'])

    def test_invalid_hash_url_version_and_package_are_unavailable(self):
        cases = []
        missing = release()
        missing['assets'][0].pop('digest')
        cases.append((missing, []))
        external = release()
        external['assets'][0]['browser_download_url'] = 'https://example.com/plugin.zip'
        cases.append((external, []))
        cases.append((release(), [Response(b'bad')]))
        content = package(version='2.0')
        cases.append((release(content=content), [Response(content)]))
        broken = b'not a ZIP'
        cases.append((release(content=broken), [Response(broken)]))
        for item, downloads in cases:
            with self.subTest(item=item):
                offer, = online.plugin_catalog(Client([published([item]), *downloads]), '9.0')
                self.assertFalse(offer['available'])
                self.assertIn('核验失败', offer['reason'])

    def test_path_validation_reuses_installer(self):
        content = io.BytesIO(package())
        with zipfile.ZipFile(content, 'a') as archive:
            archive.writestr('new_plugin/../../escape.py', 'unsafe')
        data = content.getvalue()
        offer, = online.plugin_catalog(Client([published([release(content=data)]), Response(data)]), '0.7.3')
        self.assertFalse(offer['available'])
        self.assertIn('不安全路径', offer['reason'])

    def test_plugins_beyond_first_release_page_are_discovered(self):
        pages = [release(version='0.9')] * 30
        content = package()
        client = Client([published(pages), published([release(content=content)]), Response(content)])
        cache = {}
        offer, = online.plugin_catalog(client, '0.7.3', cache=cache)
        self.assertEqual(offer['version'], '1.0')
        self.assertEqual(client.calls[1][1]['params']['page'], 2)
        self.assertTrue(cache['releases']['paginated'])

    def test_no_offline_builtin_catalog_or_placeholders(self):
        with self.assertRaises(online.requests.ConnectionError):
            online.plugin_catalog(Client([online.requests.ConnectionError('offline')]), '0.7.3')
        self.assertEqual(online.plugin_catalog(Client([published([])]), '0.7.3'), [])


class CacheTests(unittest.TestCase):
    def test_old_cache_backfills_logo_and_keeps_it_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'catalog.json'
            content = package(icon='icon.png', files={'icon.png': base64.b64decode(CATALOG_LOGO)})
            online.cached_plugin_catalog(Client([published([release(content=content)]), Response(content)]), '0.8', path)
            old = json.loads(path.read_text(encoding='utf-8'))
            old['offers'][0].pop('icon_png')
            path.write_text(json.dumps(old), encoding='utf-8')
            self.assertNotIn('icon_png', online.load_plugin_cache(path)['offers'][0])
            client = Client([Response(status_code=304), Response(content)])
            offer, = online.cached_plugin_catalog(client, '0.8', path, force=True)
            self.assertEqual(offer['icon_png'], CATALOG_LOGO)
            self.assertEqual(len(client.calls), 2)
            offline = Client([online.requests.ConnectionError('offline')])
            offer, = online.cached_plugin_catalog(offline, '0.8', path, force=True)
            self.assertEqual(offer['icon_png'], CATALOG_LOGO)

    def test_fresh_conditional_cache_and_offline_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'catalog.json'
            content = package()
            first = Client([published([release(content=content)]), Response(content)])
            offers = online.cached_plugin_catalog(first, '0.7.2', path)
            fresh = Client([])
            self.assertEqual(online.cached_plugin_catalog(fresh, '0.7.2', path), offers)
            self.assertFalse(fresh.calls)
            conditional = Client([Response(status_code=304)])
            self.assertEqual(online.cached_plugin_catalog(conditional, '0.7.2', path, force=True), offers)
            self.assertEqual(conditional.calls[0][1]['headers'], {'If-None-Match': 'first'})
            refreshed = Client([published([release(content=content, body='修正后的发布说明')])])
            updated = online.cached_plugin_catalog(refreshed, '0.7.2', path, force=True)
            self.assertEqual(updated[0]['notes'], '修正后的发布说明')
            self.assertEqual(len(refreshed.calls), 1, 'Unchanged ZIPs must not be downloaded again')
            self.assertTrue(online.cached_plugin_catalog(Client([]), '0.7.3', path)[0]['available'])
            offline = Client([online.requests.ConnectionError('offline')])
            cached = online.cached_plugin_catalog(offline, '0.7.2', path, force=True)
            self.assertTrue(cached[0]['cached'])
            self.assertEqual(cached[0]['version'], '1.0')
            removed = online.cached_plugin_catalog(Client([published([])]), '0.7.3', path, force=True)
            self.assertEqual(removed, [])

    def test_changed_package_reverified_and_old_cache_migrates(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'catalog.json'
            content = package()
            online.cached_plugin_catalog(Client([published([release(content=content)]), Response(content)]), '0.7.3', path)
            changed = package(name='修改后的包名')
            offer, = online.cached_plugin_catalog(Client([published([release(content=changed)]), Response(changed)]),
                                                    '0.7.3', path, force=True)
            self.assertEqual(offer['name'], '修改后的包名')
            data = json.loads(path.read_text(encoding='utf-8'))
            data.pop('catalog_version')
            path.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(online.load_plugin_cache(path), {})

    def test_untrusted_or_corrupt_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'catalog.json'
            content = package()
            online.cached_plugin_catalog(Client([published([release(content=content)]), Response(content)]), '0.7.3', path)
            data = json.loads(path.read_text(encoding='utf-8'))
            data['offers'][0]['url'] = 'https://example.com/plugin.zip'
            path.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(online.load_plugin_cache(path), {})
            path.write_text('broken', encoding='utf-8')
            self.assertEqual(online.load_plugin_cache(path), {})


def check_discovery():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DiscoveryTests)
    if not unittest.TextTestRunner().run(suite).wasSuccessful():
        raise AssertionError('Release catalog discovery checks failed')


if __name__ == '__main__':
    unittest.main()
