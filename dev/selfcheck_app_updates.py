"""Update coordination, real Qt sender dispatch and isolated offers; no network or windows."""
from contextlib import ExitStack, redirect_stderr
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from ddm import online_ui
from ddm.app import MainWindow
from ddm.app_updates import AppUpdates
from ddm.update_version import update_identity


class Host(QObject):
    def __init__(self):
        super().__init__()
        self._closing = False
        self.settings = {'auto_update': True}
        self.plugins = Mock()
        self.plugins.catalog.return_value = []
        self._available_update = self._startup_update_task = self._startup_plugin_task = None
        self._startup_update_checked = self._startup_plugin_checked = False
        self._plugin_update_offers, self._plugin_catalog_offers = [], []
        self._update_notice = None
        self.sidebar = Mock()
        self.open_settings, self.current_state = Mock(), Mock(return_value={'fixture': True})
        self.app_updates = AppUpdates(self)


# Exercise the actual old entry points, including QObject.sender() inside the delegate.
for name in ('_check_startup_update', '_startup_update_ready', '_set_app_update',
             '_set_plugin_updates', '_mark_updates', '_unread_app_update',
             '_unread_plugin_updates', '_remember_updates', '_check_startup_plugins',
             '_startup_plugins_ready', '_startup_plugins_finished', '_show_update_notice',
             '_startup_update_failed', '_startup_update_finished'):
    setattr(Host, name, getattr(MainWindow, name))


class Task(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, operation, callback, parent):
        super().__init__(parent)
        self.operation, self.callback = operation, callback
        self.start = Mock()


class Notice(QObject):
    activated = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.title, self.show_offer, self.track_history = Mock(), Mock(), Mock()


class AppUpdatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = Host()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(online_ui, 'OnlineTask', Task))
        self.dot = self.stack.enter_context(patch.object(online_ui, 'set_update_dot'))

    def tearDown(self):
        owned = self.host.children()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()
        self.assertTrue(all(not isValid(child) for child in owned))

    def test_module_import_does_not_load_qt_online_or_main_window(self):
        subprocess.run([sys.executable, '-c',
            "import sys; import ddm.app_updates; "
            "assert not {'PySide6','ddm.app','ddm.online','ddm.online_ui','mpv','requests'}.intersection(sys.modules)"],
            cwd=ROOT, check=True, timeout=15)

    def test_app_check_is_once_and_keeps_host_parent_callbacks_and_revision(self):
        host = self.host
        host._check_startup_update()
        task = host._startup_update_task
        self.assertIs(task.parent(), host)
        task.start.assert_called_once_with()
        host._check_startup_update()
        self.assertIs(host._startup_update_task, task)
        with patch('ddm.online.session') as session, \
                patch('ddm.app_updates.installed_revision', return_value=2), \
                patch('ddm.online.app_release', return_value={'version': '9.0'}) as release:
            client = session.return_value.__enter__.return_value
            self.assertEqual(task.operation(Mock(), Mock()), {'version': '9.0'})
            self.assertEqual(release.call_args.args[0], client)
            self.assertEqual(release.call_args.args[-1], 2)
        with patch.object(host, '_show_update_notice') as notice:
            task.succeeded.emit((task, {'version': '9.0'}))
            self.assertEqual(host._available_update, {'version': '9.0'})
            notice.assert_called_once_with()
            host.settings['auto_update'] = False
            task.succeeded.emit((task, {'version': '10.0'}))
            self.assertEqual(host._available_update, {'version': '9.0'})

    def test_plugin_check_still_runs_without_auto_app_update_and_uses_cache_path(self):
        host = self.host
        host.settings['auto_update'] = False
        host.plugins.catalog.return_value = [{'id': 'fixture', 'version': '1'}]
        with patch('ddm.app_updates.config_module.data_root', return_value='fixture-root'):
            host._check_startup_update()
        task = host._startup_plugin_task
        self.assertIsNone(host._startup_update_task)
        self.assertIs(task.parent(), host)
        with patch('ddm.online.session') as session, \
                patch('ddm.online.cached_plugin_catalog', return_value=[]) as catalog:
            self.assertEqual(task.operation(Mock(), Mock()), [])
            self.assertEqual(catalog.call_args.args[0], session.return_value.__enter__.return_value)
            self.assertEqual(catalog.call_args.args[-1], Path('fixture-root/cache/plugin-catalog.json'))
        with patch.object(host, '_set_plugin_updates') as updates, \
                patch.object(host, '_unread_plugin_updates', return_value=[{'id': 'fixture'}]), \
                patch.object(host, '_show_update_notice') as notice:
            task.succeeded.emit((task, [{'id': 'fixture'}]))
            updates.assert_called_once_with([{'id': 'fixture'}])
            notice.assert_called_once_with()
            host._closing = True
            task.succeeded.emit((task, []))
            self.assertEqual(updates.call_count, 1)

    def test_finished_sender_deletes_old_task_without_clearing_replacement(self):
        host = self.host
        for field, callback in (('_startup_update_task', host._startup_update_finished),
                                ('_startup_plugin_task', host._startup_plugins_finished)):
            with self.subTest(field=field):
                old, current = Task(None, None, host), Task(None, None, host)
                setattr(host, field, current)
                old.finished.connect(callback)
                old.finished.emit()
                self.assertIs(getattr(host, field), current)
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.assertFalse(isValid(old))
                current.finished.connect(callback)
                QTimer.singleShot(0, current.finished.emit)
                self.app.processEvents()
                self.assertIsNone(getattr(host, field))
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.assertFalse(isValid(current))

    def test_closing_and_disabled_checks_do_not_start_tasks(self):
        host = self.host
        host._closing = True
        host._check_startup_update()
        self.assertIsNone(host._startup_update_task)
        self.assertIsNone(host._startup_plugin_task)
        self.assertFalse(host._startup_update_checked)
        self.assertFalse(host._startup_plugin_checked)
        host._closing = False
        host.settings['auto_update'] = False
        host._check_startup_update()
        self.assertFalse(host._startup_update_checked)
        self.assertTrue(host._startup_plugin_checked)

    def test_catalog_and_installed_offers_keep_separate_meanings(self):
        host = self.host
        host.plugins.catalog.return_value = [{'id': 'installed', 'version': '1'}]
        offers = [{'id': 'installed', 'version': '2', 'available': True},
                  {'id': 'new', 'version': '2', 'available': True}]
        with patch('ddm.plugin_updates.pending_versions', return_value={}):
            host._set_plugin_updates(offers)
        self.assertEqual(host._plugin_catalog_offers, offers)
        self.assertEqual(host._plugin_update_offers, offers[:1])
        self.assertIsNot(host._plugin_catalog_offers, offers)

    def test_read_state_and_entry_dot_use_current_host_settings(self):
        host = self.host
        offer = {'version': '9.0', 'revision': 2}
        host._set_app_update(offer)
        self.dot.assert_called_with(host.sidebar.settings_button, True)
        host.settings = {'seen_update_entry_versions': {'app': update_identity(offer)}}
        host._mark_updates()
        self.dot.assert_called_with(host.sidebar.settings_button, False)
        self.assertIs(host._unread_app_update(), offer)
        host.settings['seen_update_versions'] = {'app': update_identity(offer)}
        self.assertIsNone(host._unread_app_update())
        host._plugin_update_offers = [{'id': 'fixture', 'version': '2'}]
        self.assertEqual(len(host._unread_plugin_updates()), 1)
        versions = {'app': update_identity(offer), 'fixture': '2'}
        with patch('ddm.app_updates.config_module.save') as save:
            host._remember_updates(versions)
            save.assert_called_once_with({'fixture': True})
        versions['fixture'] = '3'
        self.assertEqual(host.settings['seen_update_versions']['fixture'], '2')
        self.assertEqual(host._unread_plugin_updates(), [])
        self.assertEqual(vars(host.app_updates), {'host': host})

    def test_notice_reuse_and_actions_resolve_current_unread_target(self):
        host = self.host
        host._available_update = {'version': '9.0', 'revision': 2}
        host._plugin_update_offers = [{'id': 'fixture', 'version': '2'}]
        with patch.object(online_ui, 'UpdateNotice', Notice):
            host._show_update_notice()
            notice = host._update_notice
            host._show_update_notice()
        self.assertIs(host._update_notice, notice)
        self.assertIs(notice.parent(), host)
        self.assertEqual(notice.show_offer.call_count, 2)
        self.assertIn('1 个插件可更新', notice.title.setText.call_args.args[0])
        center = host.sidebar.notification_button.center
        key = center.add.call_args.kwargs['key']
        self.assertEqual(key, ('update', update_identity(host._available_update), (('fixture', '2'),)))
        notice.activated.emit()
        host.open_settings.assert_called_with('updates')
        host.settings['seen_update_versions'] = {'app': update_identity(host._available_update)}
        center.add.call_args.kwargs['callback']()
        host.open_settings.assert_called_with('plugins')
        notice.track_history.assert_called_with((center, center.add.return_value))

    def test_failure_is_silent_during_close(self):
        output = io.StringIO()
        with redirect_stderr(output):
            self.host._startup_update_failed((None, 'fixture error'))
            self.host._closing = True
            self.host._startup_update_failed((None, 'must be ignored'))
        self.assertIn('fixture error', output.getvalue())
        self.assertNotIn('must be ignored', output.getvalue())


if __name__ == '__main__':
    unittest.main()
