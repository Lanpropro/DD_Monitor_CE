"""Isolated data migration, settings entry, and protected-install update checks."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from ddm import config, data_paths, update_install


class DataPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ddm-data-paths-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.program = self.root / 'program'
        self.program.mkdir()
        self.home = self.root / 'local-appdata'
        self.target = self.root / '新的数据目录'
        self.values = {'utils/config.json': b'{"version":1,"rooms":[{"id":"synthetic"}]}',
                       'utils/accounts/bilibili.bin': b'encrypted synthetic account',
                       'utils/skins/background.png': b'skin',
                       'utils/folder-icons/folder.png': b'folder icon',
                       'plugins_user/custom/state.json': b'plugin state',
                       'cache/covers/test.png': b'cover', 'logs/test.log': b'log'}
        for name, contents in self.values.items():
            path = self.program / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        (self.program / 'unrelated.txt').write_bytes(b'keep')
        (self.program / 'recordings').mkdir()
        (self.program / 'recordings/video.mp4').write_bytes(b'recording')

    def assert_copied(self, target):
        for name, contents in self.values.items():
            self.assertEqual((target / name).read_bytes(), contents)
            self.assertEqual((self.program / name).read_bytes(), contents)
        self.assertFalse((target / 'unrelated.txt').exists())
        self.assertFalse((target / 'recordings').exists())

    def test_portable_stays_adjacent_and_creates_no_locator(self):
        self.assertEqual(data_paths.resolve(self.program, self.home), (self.program, ''))
        self.assertFalse(self.home.exists())

    def test_installed_legacy_data_is_copied_once_without_deleting_source(self):
        (self.program / data_paths.INSTALL_MARKER).write_text('{}')
        target, error = data_paths.resolve(self.program, self.home)
        self.assertFalse(error)
        self.assert_copied(target)
        (target / 'utils/config.json').write_bytes(b'latest')
        self.assertEqual(data_paths.resolve(self.program, self.home), (target, ''))
        self.assertEqual((target / 'utils/config.json').read_bytes(), b'latest')

    def test_old_installer_registration_also_uses_external_data(self):
        folder = self.program / '.ddm-uninstall'
        folder.mkdir()
        (folder / 'unins000.dat').write_bytes(b'registration')
        target, _ = data_paths.resolve(self.program, self.home)
        self.assertNotEqual(target, self.program)
        self.assert_copied(target)

    def test_migration_waits_for_exit_and_copies_final_saved_state(self):
        data_paths.schedule_migration(self.program, self.program, self.target, self.home)
        self.assertFalse(self.target.exists())
        self.values['utils/config.json'] = b'latest state saved during shutdown'
        (self.program / 'utils/config.json').write_bytes(self.values['utils/config.json'])
        with patch.object(update_install, 'wait_parent') as wait:
            self.assertEqual(data_paths.resolve(self.program, self.home), (self.target, ''))
            wait.assert_called_once_with(os.getpid())
        self.assert_copied(self.target)

    def test_failed_copy_keeps_source_and_rolls_back_location(self):
        data_paths.schedule_migration(self.program, self.program, self.target, self.home)
        with patch.object(update_install, 'wait_parent'), patch.object(data_paths.shutil, 'copytree', side_effect=OSError('disk full')):
            current, error = data_paths.resolve(self.program, self.home)
        self.assertEqual(current, self.program)
        self.assertIn('disk full', error)
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.root.glob('.ddm-migrate-*')))
        self.assertEqual(data_paths.resolve(self.program, self.home), (self.program, ''))
        for name, contents in self.values.items():
            self.assertEqual((self.program / name).read_bytes(), contents)

    def test_nested_nonempty_and_unwritable_targets_are_rejected(self):
        nonempty = self.root / 'nonempty'
        nonempty.mkdir()
        (nonempty / 'keep').write_bytes(b'keep')
        for target in (self.program, self.program / 'nested', self.root, nonempty, Path(self.root.anchor)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                data_paths.validate_target(self.program, target, self.program)
        with patch.object(data_paths, 'writable', return_value=False), self.assertRaisesRegex(ValueError, '不可写'):
            data_paths.validate_target(self.program, self.target, self.program)
        self.assertEqual((nonempty / 'keep').read_bytes(), b'keep')

    def test_target_populated_after_scheduling_is_not_overwritten(self):
        data_paths.schedule_migration(self.program, self.program, self.target, self.home)
        self.target.mkdir()
        (self.target / 'keep').write_bytes(b'keep')
        with patch.object(update_install, 'wait_parent'):
            current, error = data_paths.resolve(self.program, self.home)
        self.assertEqual(current, self.program)
        self.assertTrue(error)
        self.assertEqual((self.target / 'keep').read_bytes(), b'keep')

    def test_missing_custom_location_does_not_reset_user_configuration(self):
        location = data_paths.location_file(self.program, self.home)
        data_paths._write_location(location, {'root': str(self.target)})
        with self.assertRaisesRegex(OSError, '数据目录不存在'):
            data_paths.resolve(self.program, self.home)

    def test_configuration_accounts_and_personal_art_use_data_root(self):
        from ddm.account_store import AccountStore
        from ddm import skins
        with patch.object(config, 'REPO', str(self.program)), patch.object(config, 'DATA_ROOT', str(self.target)):
            self.assertEqual(AccountStore('bilibili').path, self.target / 'utils/accounts/bilibili.bin')
            with patch.object(skins, 'validate_asset', side_effect=lambda path: Path(path)):
                source = self.root / 'background.png'
                source.write_bytes(b'skin')
                relative = skins.import_asset(source)
            self.assertEqual((self.target / relative).read_bytes(), b'skin')
            self.assertTrue(relative.startswith('utils/skins/'))

    def test_bootstrap_sets_configuration_path_without_changing_program_resources(self):
        (self.program / data_paths.INSTALL_MARKER).write_text('{}')
        with patch.object(config, 'REPO', str(self.program)), patch.object(config, 'DATA_ROOT', None), patch.object(config, 'CONFIG_PATH', ''), patch.object(config, 'DATA_MIGRATION_ERROR', ''), patch.object(data_paths, 'user_home', return_value=self.home), patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
            config.initialize_paths()
            self.assertEqual(config.REPO, str(self.program))
            self.assertNotEqual(config.data_root(), str(self.program))
            self.assertEqual(Path(config.CONFIG_PATH).read_bytes(), self.values['utils/config.json'])
            self.assertEqual(config.load()['version'], 1)

    def test_linked_data_is_rejected_without_touching_source(self):
        with patch.object(Path, 'is_junction', side_effect=lambda: True):
            with self.assertRaisesRegex(ValueError, '链接'):
                data_paths.copy_data(self.program, self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual((self.program / 'utils/config.json').read_bytes(), self.values['utils/config.json'])

    def test_storage_settings_only_schedule_after_save(self):
        from PySide6.QtWidgets import QApplication
        from ddm.dialogs import SettingsDialog
        app = QApplication.instance() or QApplication([])
        with patch.object(config, 'REPO', str(self.program)), patch.object(config, 'DATA_ROOT', None), patch.object(data_paths, 'user_home', return_value=self.home):
            dialog = SettingsDialog({}, {})
            dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['updates'])
            page = dialog.update_page.data_page
            self.assertNotIn('storage', SettingsDialog.PAGE_INDEX)
            self.assertEqual(page.path.text(), str(self.program))
            self.assertTrue(page.set_target(self.target))
            self.assertEqual(dialog.confirm_button.text(), '保存并重启')
            self.assertFalse(data_paths.location_file(self.program, self.home).exists())
            dialog.reject()
            self.assertFalse(data_paths.location_file(self.program, self.home).exists())
            dialog = SettingsDialog({}, {})
            page = dialog.update_page.data_page
            self.assertTrue(page.set_target(self.target))
            dialog._save()
            self.assertTrue(dialog.restart_requested)
            self.assertTrue(data_paths.location_file(self.program, self.home).exists())
            self.assertFalse(self.target.exists())
            dialog.deleteLater()
            app.processEvents()

    def test_update_page_cancel_discards_migration_when_reused(self):
        from PySide6.QtWidgets import QApplication
        from ddm.dialogs import SettingsDialog
        from ddm.online_ui import AppUpdatePage
        app = QApplication.instance() or QApplication([])
        with patch.object(config, 'REPO', str(self.program)), patch.object(config, 'DATA_ROOT', None), patch.object(data_paths, 'user_home', return_value=self.home):
            cached = AppUpdatePage({})
            factory = lambda _settings: cached
            first = SettingsDialog({}, {}, update_page_factory=factory)
            self.assertTrue(first.update_page.data_page.set_target(self.target))
            first.reject()
            self.assertIsNone(cached.data_page.target)
            second = SettingsDialog({}, {}, update_page_factory=factory)
            second.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['updates'])
            self.assertEqual(second.confirm_button.text(), '保存')
            second._save()
            self.assertFalse(second.restart_requested)
            self.assertFalse(data_paths.location_file(self.program, self.home).exists())
            first.deleteLater()
            second.deleteLater()
            cached.deleteLater()
            app.processEvents()

    def test_web_login_cache_follows_selected_data_folder(self):
        from ddm import web_login
        with patch.object(config, 'DATA_ROOT', str(self.target)), patch.object(web_login, '_profile', None), patch.object(web_login, 'QWebEngineProfile') as profile:
            web_login._shared_profile()
            profile.return_value.setCachePath.assert_called_once_with(str(self.target / 'cache/web-login'))

    def test_plugin_installs_and_updates_record_only_package_files(self):
        from ddm.plugins import PluginManager, PLUGIN_INVENTORY
        from ddm import plugin_updates
        manager = PluginManager(plugins_dir=str(self.root / 'plugins'))
        def package(version, asset):
            archive = self.root / (version + '.zip')
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('sample/plugin.py', 'synthetic plugin')
                output.writestr('sample/plugin.json', json.dumps({'id': 'sample', 'name': 'test',
                    'description': 'fixture', 'version': version}))
                output.writestr('sample/' + asset, 'packaged asset')
            return archive
        manager.install_zip(str(package('1.0', 'old.txt')))
        folder = Path(manager.plugins_dir) / 'sample'
        (folder / 'user-recording.mp4').write_bytes(b'user recording')
        plugin_updates.stage(manager, str(package('2.0', 'new.txt')), 'sample', '2.0')
        plugin_updates.apply_pending(manager)
        owned = (folder / PLUGIN_INVENTORY).read_text(encoding='utf-8-sig').splitlines()
        self.assertEqual(set(owned), {'plugin.py', 'plugin.json', 'old.txt', 'new.txt'})
        self.assertEqual((folder / 'user-recording.mp4').read_bytes(), b'user recording')

    def test_update_elevation_success_and_cancel_preserve_normal_restart(self):
        stage = self.root / 'stage'
        stage.mkdir()
        old = self.program / 'old.exe'
        old.write_bytes(b'old')
        marker = self.program / data_paths.INSTALL_MARKER
        marker.write_bytes(b'installer-owned marker')
        data = self.root / 'data'
        data.mkdir()
        plan = {'root': str(self.program), 'stage': str(stage), 'files': ['new.exe'],
                'old_exe': 'old.exe', 'new_exe': 'new.exe', 'parent_pid': 1,
                'elevate': True, 'result_root': str(data)}
        path = stage / 'update-plan.json'
        path.write_text(json.dumps(plan))
        (stage / 'new.exe').write_bytes(b'new')
        with patch.object(update_install, 'wait_parent'), patch.object(update_install.subprocess, 'Popen') as launch:
            with patch('ddm.windows_elevation.run_elevated', side_effect=OSError('UAC cancelled')):
                self.assertEqual(update_install.run_helper(path), 1)
            self.assertEqual(old.read_bytes(), b'old')
            launch.assert_called_once_with([str(old)], cwd=self.program)
        def elevated(exe, args, directory):
            self.assertEqual(args[0], '--apply-update-elevated')
            return update_install.run_elevated_helper(args[1])
        with patch.object(update_install, 'wait_parent'), patch.object(update_install.subprocess, 'Popen') as launch, patch('ddm.windows_elevation.run_elevated', side_effect=elevated):
            self.assertEqual(update_install.run_helper(path), 0)
            launch.assert_called_once_with([str(self.program / 'new.exe')], cwd=self.program)
        self.assertEqual((self.program / 'new.exe').read_bytes(), b'new')
        self.assertEqual(marker.read_bytes(), b'installer-owned marker')
        self.assertTrue(json.loads((data / update_install.RESULT).read_text(encoding='utf-8'))['ok'])
        self.assertFalse((self.program / update_install.RESULT).exists())


if __name__ == '__main__':
    unittest.main()
