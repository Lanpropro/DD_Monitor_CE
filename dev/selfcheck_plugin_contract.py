"""插件装载、事件、平台注册与卸载契约；只使用临时插件和内存设置。"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import plugins as api


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
