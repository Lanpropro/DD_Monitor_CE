"""Bundled-to-single provider migration, disable persistence and failed load cleanup."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm.plugins import PluginManager

LEGACY = '''from ddm.plugins import Plugin, Platform
class Demo(Platform):
    def __init__(self, kind): self.kind=kind
    def matches(self, room_id): return room_id.startswith(self.kind+':')
class Bundle(Plugin):
    def on_load(self, context):
        for kind in ('alpha','beta'):
            if not context.platform_replaced(kind): context.register_platform(Demo(kind))
plugin=Bundle()
'''


class ReplacementTests(unittest.TestCase):
    def test_store_install_migrates_settings_on_main_thread_and_preserves_disable(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from unittest.mock import patch
        import zipfile
        from PySide6.QtWidgets import QApplication
        from ddm import plugin_updates
        from ddm.online_ui import PluginStorePage
        app = QApplication.instance() or QApplication([])
        self.provider('single_alpha', 'alpha')
        archive = self.root / 'provider.zip'
        with zipfile.ZipFile(archive, 'w') as package:
            for name in ('plugin.py', 'plugin.json'):
                package.write(self.root / 'single_alpha' / name, 'single_alpha/' + name)
        target = self.root / 'installed'
        target.mkdir()
        manager = PluginManager(plugins_dir=str(target), enabled=['bundle'])
        manager.plugin_settings = {'bundle': {'logo': False}}
        saved_on = []
        manager._save_settings = lambda: saved_on.append(threading.get_ident())
        with ThreadPoolExecutor(max_workers=1) as worker:
            installed = worker.submit(plugin_updates.install, manager, str(archive),
                {'id': 'single_alpha', 'version': '1.0'}).result(timeout=10)
        self.assertEqual(manager.plugin_settings, {'bundle': {'logo': False}})
        self.assertEqual(manager.enabled, {'bundle'})
        self.assertEqual(saved_on, [])
        with patch('ddm.online.load_plugin_cache', return_value=None), patch('ddm.online_ui.show_result'):
            page = PluginStorePage(manager)
            try:
                page._installed((installed, True))
                self.assertEqual(manager.plugin_settings['single_alpha'], {'logo': False})
                self.assertIn('single_alpha', manager.enabled)
                self.assertEqual(saved_on, [threading.get_ident()])
            finally:
                page.close()
                app.processEvents()
        manager.enabled.remove('single_alpha')
        restarted = PluginManager(plugins_dir=str(target), enabled=list(manager.enabled))
        restarted.plugin_settings = manager.plugin_settings
        try:
            restarted.load()
            self.assertNotIn('alpha', restarted.platforms)
            self.assertNotIn('single_alpha', restarted.enabled)
        finally:
            restarted.unload()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.make('bundle', LEGACY, platforms=['alpha', 'beta'])

    def make(self, name, source, **manifest):
        path = self.root / name
        path.mkdir()
        (path / 'plugin.py').write_text(source, encoding='utf-8')
        (path / 'plugin.json').write_text(json.dumps(dict(id=name, name=name, description='fixture',
            version='1.0', **manifest)), encoding='utf-8')
        if manifest.get('replaces'):
            (path / '.ddm-plugin-files.txt').write_text('plugin.py\nplugin.json\n', encoding='utf-8')

    def provider(self, name, kind, *, fail=False):
        self.make(name, '''from ddm.plugins import Plugin, Platform
class Demo(Platform):
    kind=%r
    def matches(self, room_id): return room_id.startswith(self.kind+':')
class Single(Plugin):
    def on_load(self, context):
        context.register_platform(Demo())
        %s
plugin=Single()
''' % (kind, "raise RuntimeError('fixture failed after registration')" if fail else 'pass'),
            replaces='bundle', platforms=[kind], inherit_settings=['logo', 'mapping'])

    def manager(self, enabled, settings=None):
        manager = PluginManager(plugins_dir=str(self.root), enabled=enabled)
        manager.plugin_settings = settings if settings is not None else {}
        manager.load()
        self.addCleanup(manager.unload)
        return manager

    def test_partial_replacement_keeps_other_legacy_platform(self):
        self.provider('single_alpha', 'alpha')
        settings = {'bundle': {'logo': False, 'mapping': {'room': 'owner'}, 'unrelated': 'keep'}}
        manager = self.manager(['bundle'], settings)
        self.assertEqual(manager._platform_owner, {'alpha': 'single_alpha', 'beta': 'bundle'})
        self.assertFalse(manager.plugin_settings['single_alpha']['logo'])
        self.assertNotIn('unrelated', manager.plugin_settings['single_alpha'])
        manager.plugin_settings['single_alpha']['mapping']['room'] = 'new'
        self.assertEqual(settings['bundle']['mapping']['room'], 'owner')
        self.assertEqual(manager.platform_for('alpha:existing').kind, 'alpha')

    def test_complete_replacement_hides_bundle_but_preserves_settings(self):
        self.provider('single_alpha', 'alpha')
        self.provider('single_beta', 'beta')
        manager = self.manager(['bundle'], {'bundle': {'logo': False}})
        self.assertEqual(set(manager._platform_owner.values()), {'single_alpha', 'single_beta'})
        self.assertNotIn('bundle', {row['id'] for row in manager.catalog()})
        self.assertIn('bundle', manager.plugin_settings)

    def test_disabled_replacement_is_not_restored_by_legacy_or_restart(self):
        self.provider('single_alpha', 'alpha')
        first = self.manager(['bundle'])
        first.enabled.remove('single_alpha')
        second = self.manager(list(first.enabled), first.plugin_settings)
        self.assertNotIn('alpha', second.platforms)
        self.assertEqual(second._platform_owner, {'beta': 'bundle'})
        self.assertNotIn('single_alpha', second.enabled)

    def test_explicit_new_settings_take_precedence(self):
        self.provider('single_alpha', 'alpha')
        manager = self.manager(['bundle'], {'bundle': {'logo': False}, 'single_alpha': {'logo': True}})
        self.assertEqual(manager.plugin_settings['single_alpha'], {'logo': True})
        self.assertNotIn('alpha', manager.platforms)

    def test_failed_provider_does_not_leave_registered_platform(self):
        self.provider('single_alpha', 'alpha', fail=True)
        manager = self.manager(['bundle'])
        self.assertNotIn('alpha', manager.platforms)
        self.assertNotIn('alpha', manager._platform_owner)
        self.assertEqual(manager.platforms['beta'].kind, 'beta')
        self.assertIn('single_alpha', dict(manager.skipped))

    def test_invalid_replacement_manifest_keeps_original_and_reports_error(self):
        self.make('invalid', 'raise AssertionError("must not execute")', replaces='bundle', platforms=[])
        manager = self.manager(['bundle', 'invalid'])
        self.assertEqual(set(manager.platforms), {'alpha', 'beta'})
        self.assertIn('invalid', dict(manager.skipped))

    def test_uninstalled_source_template_does_not_take_over_bundle(self):
        self.provider('single_alpha', 'alpha')
        (self.root / 'single_alpha/.ddm-plugin-files.txt').unlink()
        manager = self.manager(['bundle'])
        self.assertEqual(manager._platform_owner, {'alpha': 'bundle', 'beta': 'bundle'})
        self.assertNotIn('single_alpha', manager.enabled)

    def old_bundle(self):
        manifest = self.root / 'bundle/plugin.json'
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data.pop('platforms')
        manifest.write_text(json.dumps(data), encoding='utf-8')
        (self.root / 'bundle/plugin.py').write_text(LEGACY.replace(
            'if not context.platform_replaced(kind): ', ''), encoding='utf-8')

    def test_partial_replacement_preserves_old_bundle_without_query_api(self):
        self.old_bundle()
        self.provider('single_alpha', 'alpha')
        path = self.root / 'single_alpha/plugin.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['replaces_platforms'] = ['alpha', 'beta']
        path.write_text(json.dumps(data), encoding='utf-8')
        manager = self.manager(['bundle'])
        self.assertEqual(manager._platform_owner, {'alpha': 'bundle', 'beta': 'bundle'})
        self.assertIn('single_alpha', dict(manager.skipped))

    def test_complete_replacement_handles_old_bundle_without_query_api(self):
        self.old_bundle()
        for kind in ('alpha', 'beta'):
            self.provider('single_' + kind, kind)
            path = self.root / ('single_' + kind) / 'plugin.json'
            data = json.loads(path.read_text(encoding='utf-8'))
            data['replaces_platforms'] = ['alpha', 'beta']
            path.write_text(json.dumps(data), encoding='utf-8')
        manager = self.manager(['bundle'])
        self.assertEqual(set(manager._platform_owner.values()), {'single_alpha', 'single_beta'})
        self.assertFalse(manager.skipped)

    def test_new_platform_can_coexist_with_old_bundle_without_query_api(self):
        self.old_bundle()
        self.provider('single_gamma', 'gamma')
        path = self.root / 'single_gamma/plugin.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['replaces_platforms'] = ['alpha', 'beta']
        path.write_text(json.dumps(data), encoding='utf-8')
        manager = self.manager(['bundle'])
        self.assertEqual(manager._platform_owner, {'gamma': 'single_gamma', 'alpha': 'bundle', 'beta': 'bundle'})
        self.assertFalse(manager.skipped)


if __name__ == '__main__':
    unittest.main()
