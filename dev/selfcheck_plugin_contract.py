"""插件装载、事件、平台注册与卸载契约；只使用临时插件和内存设置。"""
from pathlib import Path
import json
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import plugins as api
from ddm import plugin_updates


SOURCE = '''from ddm.plugins import Plugin, Platform
class DemoPlatform(Platform):
    kind = 'smoke'
    label = '测试平台'
    def matches(self, room_id):
        return room_id.startswith('smoke:')
class Demo(Plugin):
    name = '测试插件'
    def on_load(self, context):
        self.events = []
        context.register_platform(DemoPlatform())
    def on_event(self, event, payload):
        self.events.append((event, payload))
    def on_unload(self):
        self.unloaded = True
plugin = Demo()
'''


class PluginContractTests(unittest.TestCase):
    def test_settings_presentation_is_a_normalized_snapshot_of_display_preferences(self):
        settings = dict(settings_glass_enabled=True, settings_glass_opacity=40,
                        settings_no_shadows=True, settings_wheel_speed=4,
                        settings_card_layout='horizontal', recording_dir='private')
        manager = SimpleNamespace(window=SimpleNamespace(settings=settings), _unloaded=False, _contexts=set())
        context = api.PluginContext(manager, 'smoke')
        result = context.settings_presentation()
        self.assertEqual(result['settings_glass_opacity'], 40)
        self.assertEqual(result['settings_wheel_speed'], 4)
        self.assertTrue(result['settings_glass_enabled'])
        self.assertTrue(result['settings_no_shadows'])
        self.assertNotIn('settings_card_layout', result)
        self.assertNotIn('recording_dir', result)
        result['settings_glass_opacity'] = 100
        self.assertEqual(settings['settings_glass_opacity'], 40)
        settings['settings_wheel_speed'] = 0
        self.assertEqual(context.settings_presentation()['settings_wheel_speed'], 1)

    def test_documented_recording_example_preserves_all_headers(self):
        reference = (Path(__file__).resolve().parents[1] / 'docs/plugins.md').read_text(encoding='utf-8')
        example = next(block for block in re.findall(r'```python\n(.*?)```', reference, re.S)
                       if block.startswith('import subprocess\n'))
        namespace = {'api': api}
        exec(compile(example, 'docs/plugins.md', 'exec'), namespace)
        source = api.StreamSource('smoke:42', 'https://example.test/live',
                                  headers={'Referer': 'https://example.test/', 'User-Agent': 'fixture'})
        with patch('subprocess.Popen') as launch:
            namespace['on_event'](None, api.EVENT_STARTED, {})
            launch.assert_not_called()
            namespace['on_event'](None, api.EVENT_STREAM_RESOLVED, {'source': source})
        launch.assert_called_once()
        arguments = launch.call_args.args[0]
        self.assertEqual(arguments.count('-headers'), 1)
        self.assertEqual(arguments[arguments.index('-headers') + 1],
                         'Referer: https://example.test/\r\nUser-Agent: fixture\r\n')
        self.assertEqual(arguments[-1], 'smoke_42.flv')

    def test_manual_import_and_loading_do_not_enforce_store_version_gate(self):
        with tempfile.TemporaryDirectory(prefix='ddm-contract-') as directory:
            root = Path(directory)
            manifest = dict(id='version_probe', name='版本契约', description='fixture',
                            version='1.0', min_app_version='999.0')
            archive = root / 'plugin.zip'
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('version_probe/plugin.json', json.dumps(manifest))
                package.writestr('version_probe/plugin.py', SOURCE)
            manager = api.PluginManager(plugins_dir=str(root / 'installed'))
            try:
                manager.install_zip(str(archive))
                self.assertNotIn('ddm_plugin_version_probe', sys.modules)
                self.assertEqual(manager.catalog()[0]['status'], '待重启')
                with self.assertRaises(ValueError):
                    manager.install_zip(str(archive))
                with self.assertRaisesRegex(ValueError, '999.0'):
                    plugin_updates.check_compatibility(manifest)
                manager.load()
                self.assertEqual(len(manager.plugins), 1)
                self.assertIn('smoke', manager.platforms)
            finally:
                manager.unload()

    def test_temporary_plugin_load_event_registration_and_unload(self):
        with tempfile.TemporaryDirectory(prefix='ddm-contract-') as directory:
            root = Path(directory)
            for name, source in (('smoke', SOURCE), ('broken', 'raise RuntimeError("fixture")'),
                                 ('_template', 'raise AssertionError("must not load")')):
                folder = root / name
                folder.mkdir()
                (folder / 'plugin.py').write_text(source, encoding='utf-8')
            manager = api.PluginManager(plugins_dir=directory, enabled=['smoke', 'broken'])
            try:
                manager.load()
                self.assertEqual(len(manager.plugins), 1)
                plugin = manager.plugins[0]
                self.assertEqual(plugin.name, '测试插件')
                self.assertEqual({name for name, _ in manager.skipped}, {'broken'})
                self.assertIn('smoke', manager.platforms)
                with self.assertRaises(ValueError):
                    manager.register_platform('duplicate', manager.platforms['smoke'])
                manager.emit(api.EVENT_STARTED, fixture=True)
                self.assertEqual(plugin.events, [(api.EVENT_STARTED, {'fixture': True})])
                self.assertEqual({item['id'] for item in manager.catalog()}, {'smoke', 'broken'})
            finally:
                manager.unload()
            self.assertTrue(plugin.unloaded)


if __name__ == '__main__':
    unittest.main()
