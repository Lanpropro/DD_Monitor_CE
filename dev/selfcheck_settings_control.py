"""Settings coordination with Qt signals and fake pages; no worker, window or accounts."""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Signal
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from ddm import app as app_module
from ddm.settings_control import SettingsControl


class AutoSave(QObject):
    requested = Signal(dict)

    def __init__(self, parent):
        super().__init__(parent)
        self.acknowledge = Mock()


class Dialog(QObject):
    Accepted, Rejected = 1, 0
    PAGES = (('general', ''), ('plugins', ''), ('updates', ''), ('danmaku', ''))
    PAGE_INDEX = {key: index for index, (key, _) in enumerate(PAGES)}
    pageCreated = Signal(int, object)
    updatesViewed = Signal(dict)
    appearanceChanged = Signal(str)

    def __init__(self, settings, shortcuts, parent, **options):
        super().__init__(parent)
        self.initial_settings, self.initial_shortcuts, self.options = settings, shortcuts, options
        self.seen_versions, self._loaded_pages = {}, {}
        self.nav, self.plugin_page, self._mark_update_page = Mock(), Mock(), Mock()
        self.exec = Mock(return_value=self.Rejected)
        self.settings = Mock(return_value={})
        self.shortcuts = Mock(return_value=shortcuts)
        self.enabled_plugins = Mock(return_value={'alpha'})
        self.restart_requested = False
        self.auto_save = AutoSave(self)
        self.general_page = SimpleNamespace(findChildren=lambda _type: [])


class Process(QObject):
    saved = Signal(dict)
    autoSaveRequested = Signal(dict)
    hostRequest = Signal(dict)
    closed = Signal()
    occlusionChanged = Signal()
    failed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.open = Mock()
        self._send = Mock()


class UpdatePage(QObject):
    releaseChecked = Signal(object)

    def __init__(self, settings, parent):
        super().__init__(parent)
        self.auto = Mock()


class Host(QObject):
    def __init__(self):
        super().__init__()
        self.settings = {'appearance_mode': 'dark', 'auto_update': False}
        self.shortcuts, self.state = {'focus': 'F'}, {}
        self.plugins = SimpleNamespace(enabled={'alpha'}, _platform_owner={'p': 'alpha'}, _removed=set())
        self.wall = SimpleNamespace(tiles=[], _quick_danmaku_layer=Mock())
        self.players, self._codec_dialogs = {}, {}
        self._available_update, self._update_notice = None, Mock()
        self._plugin_update_offers, self._plugin_catalog_offers = [], []
        self._closing, self._fullscreen_tile = False, None
        self._restart_requested, self._update_plan = False, ''
        for name in ('_startup_update_timer', '_poll_timer', '_sync_fullscreen_audio',
                     '_refresh_shortcuts', 'refresh_skin', '_sync_platform_rooms',
                     '_sync_recording_switch', '_sync_replay_scope', 'apply_danmaku_settings',
                     'apply_preview_settings', '_show_notice', '_set_app_update', '_set_plugin_updates',
                     '_remember_updates', '_mark_updates', 'set_appearance', 'close'):
            setattr(self, name, Mock())
        self.poll_interval_ms = lambda: 60000
        self.current_state = lambda: deepcopy(self.state)
        self.settings_control = SettingsControl(self)


for name in ('_open_sidebar_settings', '_sc_preview_context', '_get_settings_process',
             '_remote_settings_saved', '_settings_host_request', '_close_settings_host',
             '_get_update_page', '_create_settings_dialog', 'open_settings', '_apply_settings_dialog'):
    setattr(Host, name, getattr(app_module.MainWindow, name))


class SettingsControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host, self.stack = Host(), ExitStack()
        self.save = self.stack.enter_context(patch('ddm.settings_control.config_module.save'))
        self.stack.enter_context(patch.object(app_module, 'SettingsDialog', Dialog))

    def tearDown(self):
        children = self.host.children()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()
        self.assertTrue(all(not isValid(child) for child in children))

    def test_module_import_does_not_load_qt_app_dialogs_or_player(self):
        subprocess.run([sys.executable, '-c',
            "import sys; import ddm.settings_control; "
            "assert not {'PySide6','ddm.app','ddm.dialogs','ddm.player','mpv'}.intersection(sys.modules)"],
            cwd=ROOT, check=True, timeout=15)

    def test_sidebar_entry_preserves_normal_and_process_modes(self):
        host = self.host
        with patch.object(host, 'open_settings', return_value=True) as normal, \
                patch.dict('os.environ', {'DDM_SETTINGS_PROCESS': '0'}):
            self.assertTrue(host._open_sidebar_settings())
            normal.assert_called_once_with()
        with patch('ddm.settings_process.SettingsProcess', Process), \
                patch.object(host, '_sc_preview_context', return_value={'fixture': True}), \
                patch.dict('os.environ', {'DDM_SETTINGS_PROCESS': '1'}):
            self.assertFalse(host._open_sidebar_settings())
        host._settings_process.open.assert_called_once_with(host.settings, host.shortcuts, {'fixture': True})

    def test_process_is_reused_and_old_signal_entries_keep_host_parent(self):
        host = self.host
        with patch('ddm.settings_process.SettingsProcess', Process):
            process = host._get_settings_process()
            self.assertIs(host._get_settings_process(), process)
        self.assertIs(process.parent(), host)
        with patch.object(host, '_apply_settings_dialog') as apply:
            process.saved.emit({'shortcuts': {'focus': 'G'}})
            self.assertEqual(apply.call_args.args[0].shortcuts()['focus'], 'G')
        process.occlusionChanged.emit()
        host.wall._quick_danmaku_layer.show.assert_called_once_with()
        process.failed.emit('fixture error')
        self.assertEqual(host._show_notice.call_args.kwargs['on_click'], host.open_settings)
        session = host._settings_host = Mock()
        process.closed.emit()
        self.assertIsNone(host._settings_host)
        session.close.assert_called_once_with()

    def test_autosave_signals_apply_and_acknowledge_without_closing(self):
        host = self.host
        dialog = host._create_settings_dialog()
        with patch.object(host, '_apply_settings_dialog') as apply:
            dialog.auto_save.requested.emit({'settings': {'default_volume': 17}})
            adapter = apply.call_args.args[0]
            self.assertEqual(adapter.settings(), {'default_volume': 17})
            self.assertTrue(adapter.auto_saving)
            self.assertFalse(adapter.restart_requested)
            dialog.auto_save.acknowledge.assert_called_once_with()
            apply.side_effect = PermissionError('fixture write failure')
            dialog.auto_save.requested.emit({'settings': {'default_volume': 19}})
            dialog.auto_save.acknowledge.assert_called_with('fixture write failure')
        with patch('ddm.settings_process.SettingsProcess', Process):
            process = host._get_settings_process()
        with patch.object(host, '_apply_settings_dialog') as apply:
            process.autoSaveRequested.emit({'changes': {'settings': {'default_volume': 21}}})
            self.assertEqual(apply.call_args.args[0].settings(), {'default_volume': 21})
            process._send.assert_called_once_with({'kind': 'auto-saved', 'error': ''})
        host.close.assert_not_called()

    def test_remote_save_merges_current_shortcuts_and_ignores_empty_or_closing(self):
        host = self.host
        with patch.object(host, '_apply_settings_dialog') as apply:
            host._remote_settings_saved({'settings': {}})
            apply.assert_not_called()
            host._remote_settings_saved({'settings': {'freeze_watch': False}, 'shortcuts': {'mute': 'N'}})
            dialog, before = apply.call_args.args
            self.assertEqual(before, ({'alpha'}, {'p': 'alpha'}, set()))
            self.assertEqual(dialog.settings(), {'freeze_watch': False})
            host.shortcuts['focus'] = 'H'
            self.assertEqual(dialog.shortcuts(), {'focus': 'H', 'mute': 'N'})
            host._closing = True
            host._remote_settings_saved({'settings': {'freeze_watch': True}})
            self.assertEqual(apply.call_count, 1)

    def test_host_session_creation_gate_and_close_clear_before_callback(self):
        host = self.host
        host._settings_process = Mock()
        with patch('ddm.settings_host.SettingsHost') as factory:
            host._settings_host_request({'kind': 'host-save'})
            factory.assert_not_called()
            message = {'kind': 'host-page', 'page': 'plugins'}
            host._settings_host_request(message)
            session = factory.return_value
            factory.assert_called_once_with(host, host._settings_process, message)
            host._settings_host_request({'kind': 'host-save'})
            self.assertEqual(session.handle.call_count, 2)
            session.close.side_effect = lambda: self.assertIsNone(host._settings_host)
            host._close_settings_host()
            host._close_settings_host()
            session.close.assert_called_once_with()
            host._closing = True
            host._settings_host_request(message)
            self.assertEqual(factory.call_count, 1)

    def test_update_page_is_reused_and_release_signal_keeps_old_target(self):
        host = self.host
        with patch('ddm.online_ui.AppUpdatePage', UpdatePage):
            page = host._get_update_page({'auto_update': True})
            self.assertIs(page.parent(), host)
            page.auto.setChecked.assert_called_with(True)
            self.assertIs(host._get_update_page({'auto_update': False}), page)
            page.auto.setChecked.assert_called_with(False)
            page.releaseChecked.emit({'version': 'fixture'})
            host._set_app_update.assert_called_once_with({'version': 'fixture'})

    def test_dialog_factory_compatibility_entry_and_page_wiring(self):
        host = self.host
        host._available_update = {'version': '9.0'}
        host._plugin_update_offers = [{'id': 'alpha', 'version': '2'}]
        host._plugin_catalog_offers = [{'id': 'beta', 'version': '1'}]
        dialog = host._create_settings_dialog({'auto_update': True}, {'focus': 'G'})
        self.assertIsInstance(dialog, Dialog)
        self.assertIs(dialog.parent(), host)
        self.assertEqual(dialog.initial_shortcuts, {'focus': 'G'})
        self.assertEqual(host.settings['seen_update_entry_versions'], {'app': '9.0', 'alpha': '2'})
        self.save.assert_called_once()
        preview = Mock()
        with patch.object(host, '_sc_preview_context', return_value={'fixture': True}):
            dialog.pageCreated.emit(3, SimpleNamespace(super_chat_placement=preview))
        preview.set_preview_context.assert_called_once_with({'fixture': True})
        class Store(QObject):
            offersChanged = Signal(object)
        store = Store(host)
        store._catalog_ready = Mock()
        dialog.pageCreated.emit(1, SimpleNamespace(store_page=store))
        store._catalog_ready.assert_called_once_with(host._plugin_catalog_offers)
        store.offersChanged.emit([])
        host._set_plugin_updates.assert_called_once_with([])
        update = SimpleNamespace(jobs=[], plan_path='', _checked=False, offer=None,
                                 _release_ready=Mock(), _busy=Mock())
        dialog.pageCreated.emit(2, update)
        update._release_ready.assert_called_once_with(host._available_update)
        update.jobs = [object()]
        dialog.pageCreated.emit(2, update)
        self.assertEqual(update._release_ready.call_count, 1)
        dialog.updatesViewed.emit({'alpha': '2'})
        host._remember_updates.assert_called_once_with({'alpha': '2'})

    def test_accept_cancel_and_failure_always_release_dialog(self):
        host = self.host
        for outcome in ('cancel', 'accept', 'error'):
            with self.subTest(outcome=outcome):
                dialog = host._create_settings_dialog()
                dialog.exec.return_value = Dialog.Accepted if outcome == 'accept' else Dialog.Rejected
                if outcome == 'error':
                    dialog.exec.side_effect = RuntimeError('fixture error')
                with patch.object(host, '_create_settings_dialog', return_value=dialog), \
                        patch.object(host, '_apply_settings_dialog', return_value=True) as apply:
                    if outcome == 'error':
                        with self.assertRaisesRegex(RuntimeError, 'fixture error'):
                            host.open_settings('plugins')
                    else:
                        self.assertEqual(host.open_settings('plugins'), outcome == 'accept')
                    self.assertEqual(apply.call_count, int(outcome == 'accept'))
                    dialog.nav.setCurrentRow.assert_called_with(1)
                    dialog.plugin_page.tabs.setCurrentIndex.assert_called_with(1)
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.assertFalse(isValid(dialog))

    def test_apply_preserves_state_save_and_runtime_application_order(self):
        host = self.host
        dialog = host._create_settings_dialog()
        dialog.settings.return_value = {'freeze_watch': False, 'volume_normalization': True,
                                        'volume_normalization_curve': {'preset': 'spotify'}}
        dialog.shortcuts.return_value = {'focus': 'G'}
        player = Mock()
        host.players['fixture'] = player
        order = []
        self.save.side_effect = lambda _: order.append('save')
        for name in ('_sync_recording_switch', '_sync_replay_scope', 'apply_danmaku_settings', 'apply_preview_settings'):
            getattr(host, name).side_effect = lambda name=name: order.append(name)
        before = ({'alpha'}, {'p': 'alpha'}, set())
        self.assertTrue(host._apply_settings_dialog(dialog, before))
        self.assertEqual(order, ['save', '_sync_recording_switch', '_sync_replay_scope',
                                 'apply_danmaku_settings', 'apply_preview_settings'])
        self.assertFalse(player.freeze_watch)
        player.set_volume_normalization.assert_called_once_with(True, {'preset': 'spotify'})
        self.assertEqual(host.state['ui']['shortcuts'], {'focus': 'G'})
        host.refresh_skin.assert_not_called()
        host._sync_platform_rooms.assert_not_called()
        host._startup_update_timer.stop.assert_called_once_with()
        host._update_notice.dismiss.assert_called_once_with()
        self.assertEqual(vars(host.settings_control), {'host': host})

    def test_apply_plugin_change_and_restart_or_update_plan_keep_original_precedence(self):
        host = self.host
        dialog = host._create_settings_dialog()
        dialog.enabled_plugins.return_value = None
        dialog.restart_requested = True
        dialog._loaded_pages[2] = SimpleNamespace(install_requested=True)
        dialog.update_page = SimpleNamespace(plan_path='fixture-plan')
        host._apply_settings_dialog(dialog, ({'alpha'}, {'p': 'alpha'}, set()))
        self.assertIsNone(host.plugins.enabled)
        host.refresh_skin.assert_called_once_with()
        host._sync_platform_rooms.assert_called_once_with()
        self.assertEqual(host._update_plan, 'fixture-plan')
        self.assertFalse(host._restart_requested)
        host.close.assert_called_once_with()
        host.close.reset_mock()
        dialog._loaded_pages.clear()
        host._apply_settings_dialog(dialog, (None, {'p': 'alpha'}, set()))
        self.assertTrue(host._restart_requested)
        host.close.assert_called_once_with()

    def test_sc_preview_context_uses_current_surface_and_fullscreen_source(self):
        host = self.host
        viewport = Mock()
        viewport.width.return_value, viewport.height.return_value = 0, 80
        viewport.mapTo.return_value = QPoint(2, 3)
        panel = Mock()
        panel.body.viewport.return_value = viewport
        panel.width.return_value, panel.height.return_value = 100, 90
        panel.super_chats._events = []
        host.wall.danmaku = panel
        host.wall.danmaku_target_tile = Mock(return_value=None)
        context = host._sc_preview_context()
        self.assertEqual(context['panel'], {'size': [1, 80], 'cards': [{'message': '', 'collapsed': False}],
            'outer_size': [100, 90], 'viewport_rect': [2, 3, 0, 80]})
        video = Mock()
        video.width.return_value, video.height.return_value = 160, 90
        video.super_chat_overlay.chats = [{'text': 'fixture'}]
        video.super_chat_overlay.presentation.is_collapsed.return_value = True
        host._fullscreen_tile = SimpleNamespace(video_danmaku=video)
        self.assertEqual(host._sc_preview_context()['video']['cards'], [{'message': 'fixture', 'collapsed': True}])


if __name__ == '__main__':
    unittest.main()
