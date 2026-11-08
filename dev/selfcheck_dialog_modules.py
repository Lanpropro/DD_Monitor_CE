"""Dialog page ownership, old factories and import order; isolated Qt, no accounts or workers."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

MODULES = {
    'settings_general': ('CodecSettingsPanel', 'CodecSettingsDialog', 'GeneralSettingsPage', 'TraySettingsPage'),
    'settings_notifications': ('NotificationSwitch', 'NoticeBlurPreview', 'NotificationSettingsPage'),
    'settings_shortcuts': ('ShortcutSettingsPage',),
    'settings_danmaku': ('DanmakuSettingsPage',),
    'settings_recording': ('RecordingSettingsPage',),
    'settings_plugins': ('PluginRemovePrompt', 'PluginSettingsPage'),
    'settings_appearance': ('AppearanceSettingsPage',),
    'room_dialogs': ('AddRoomDialog', 'FollowImportDialog'),
}


class DialogModulesTests(unittest.TestCase):
    def child(self, code):
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_owned_pages_import_without_aggregate_main_window_or_player(self):
        for module in MODULES:
            with self.subTest(module=module):
                self.child(f"import sys; import ddm.{module}; "
                    "assert not {'ddm.dialogs','ddm.app','ddm.widgets','ddm.player','mpv'}.intersection(sys.modules)")

    def test_legacy_exports_and_shortcut_contract_keep_identity(self):
        import importlib
        from ddm import dialogs, shortcut_actions, settings_shortcuts
        for module, names in MODULES.items():
            owned = importlib.import_module('ddm.' + module)
            for name in names:
                self.assertIs(getattr(dialogs, name), getattr(owned, name))
        self.assertIs(dialogs.SHORTCUT_ACTIONS, shortcut_actions.SHORTCUT_ACTIONS)
        self.assertIs(settings_shortcuts.SHORTCUT_ACTIONS, shortcut_actions.SHORTCUT_ACTIONS)
        self.assertIs(dialogs.QFileDialog, importlib.import_module('ddm.settings_plugins').QFileDialog)
        self.assertIs(dialogs.QMessageBox, importlib.import_module('ddm.settings_plugins').QMessageBox)

    def test_legacy_import_preserves_qt_subclass_definition_order(self):
        expected = [name for module, names in MODULES.items() if module != 'room_dialogs' for name in names]
        expected += ['SettingsDialog', 'AddRoomDialog', 'FollowImportDialog']
        self.child(f'''
import builtins
expected = {expected!r}
original, seen = builtins.__build_class__, []
def record(function, name, *bases, **kwargs):
    if name in expected:
        seen.append(name)
    return original(function, name, *bases, **kwargs)
builtins.__build_class__ = record
try:
    import ddm.dialogs
finally:
    builtins.__build_class__ = original
assert seen == expected, seen
''')

    def test_room_helpers_and_account_import_share_the_owned_dialogs(self):
        from ddm import dialogs, room_dialogs
        self.assertIs(dialogs._add_folder_option, room_dialogs._add_folder_option)
        self.assertIs(dialogs._create_folder_for_dialog, room_dialogs._create_folder_for_dialog)
        self.child("import sys; import ddm.account_dialog; assert 'ddm.dialogs' not in sys.modules")

    def test_codec_action_keeps_old_factory_replacement_and_saved_values(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication, QDialog
        from ddm import dialogs
        app = QApplication.instance() or QApplication([])
        page = dialogs.GeneralSettingsPage({'bili_codec': 'avc', 'decode_mode': 'auto'})
        try:
            with patch('ddm.dialogs.CodecSettingsDialog') as factory:
                factory.return_value.exec.return_value = QDialog.Accepted
                factory.return_value.controls.values.return_value = {'bili_codec': 'hevc', 'decode_mode': 'none'}
                page._edit_codecs()
                self.assertEqual(page.values()['bili_codec'], 'hevc')
                self.assertEqual(page.values()['decode_mode'], 'none')
                factory.return_value.deleteLater.assert_called_once_with()
        finally:
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_lazy_plugin_page_keeps_the_old_factory_entry(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        from ddm import dialogs
        app = QApplication.instance() or QApplication([])
        with patch('ddm.dialogs.PluginSettingsPage', side_effect=RuntimeError('fixture lazy page')) as factory:
            dialog = dialogs.SettingsDialog({}, {})
            try:
                factory.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, 'fixture lazy page'):
                    _ = dialog.plugin_page
                factory.assert_called_once()
            finally:
                dialog.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
