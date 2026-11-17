"""Issue 223: real input widgets and sequential fake lookups; no account, media or network."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, QCoreApplication, QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QWidget
from ddm import config, images, motion
from ddm.add_room_dialog import AddRoomDialog
from ddm.room_add_batch import RoomAddBatch
from ddm.room_catalog import RoomCatalog
from ddm.sidebar_widgets import Sidebar
from ddm.wall_widgets import WallGrid


class Resolver(QObject):
    resolved = Signal(dict)
    failed = Signal(str)
    finished = Signal()
    created = []

    def __init__(self, room_id, parent, **options):
        super().__init__(parent)
        self.room_id = room_id
        self.error_message = '网络请求超时'
        self.created.append(self)

    def start(self):
        pass

    def complete(self, canonical=None, fail=False):
        if fail:
            self.failed.emit(self.room_id)
        else:
            self.resolved.emit(dict(room_id=canonical or self.room_id, uname='测试', live=False))
        self.finished.emit()


class AddRoomEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(config, 'DATA_ROOT', directory))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')))
        self.stack.enter_context(patch.object(images, 'REPO', directory))
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.widgets = []
        Resolver.created = []

    def tearDown(self):
        for widget in self.widgets:
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def own(self, widget):
        self.widgets.append(widget)
        return widget

    def pump(self):
        for _ in range(5):
            self.app.processEvents()

    def test_multiline_deduplicates_and_reports_original_line_without_partial_accept(self):
        dialog = self.own(AddRoomDialog())
        dialog.show()
        dialog.batch_button.click()
        self.assertTrue(dialog.batch_edit.isVisible())
        dialog.batch_edit.setPlainText('1001\n\nhttps://live.bilibili.com/1001\n无效输入\n1002')
        dialog.accept()
        self.assertIn('第 4 行', dialog.hint.text())
        self.assertEqual(dialog.room_ids, [])
        self.assertEqual(dialog.result(), QDialog.Rejected)
        dialog.batch_edit.setPlainText('1001\n\nhttps://live.bilibili.com/1001\n1002')
        dialog.accept()
        self.assertEqual(dialog.room_ids, ['1001', '1002'])
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_single_input_enter_and_mixed_platform_resolver(self):
        dialog = self.own(AddRoomDialog(room_id_resolver=lambda text:
            'huya:abc' if 'huya' in text else None))
        dialog.batch_button.click()
        dialog.batch_edit.setPlainText('1001\nhttps://www.huya.com/abc')
        dialog.accept()
        self.assertEqual(dialog.room_ids, ['1001', 'huya:abc'])
        single = self.own(AddRoomDialog())
        single.edit.setText('1002')
        QTest.keyClick(single.edit, Qt.Key_Return)
        self.assertEqual(single.room_ids, ['1002'])

    def test_collapsed_sidebar_has_direct_add_connected_to_original_signal(self):
        sidebar = self.own(Sidebar([], auto_compact=False))
        sidebar.show()
        sidebar.set_collapsed(True, animate=False)
        self.pump()
        button = sidebar.navigation.collapsed_add_button
        self.assertTrue(button.isVisible())
        self.assertGreater(button.mapTo(sidebar, button.rect().topLeft()).y(),
                           sidebar.toggle_button.mapTo(sidebar, sidebar.toggle_button.rect().bottomLeft()).y())
        calls = []
        sidebar.addRoomClicked.connect(lambda: calls.append('add'))
        button.click()
        self.assertEqual(calls, ['add'])
        sidebar.set_collapsed(False, animate=False)
        self.assertTrue(button.isHidden())

    def test_collapsed_add_survives_orientation_changes(self):
        sidebar = self.own(Sidebar([], auto_compact=False))
        sidebar.show()
        sidebar.set_collapsed(True, animate=False)
        sidebar.set_side('top')
        self.pump()
        button = sidebar.navigation.collapsed_add_button
        self.assertTrue(button.isVisible())
        self.assertIs(button.parentWidget(), sidebar._bar_row)
        sidebar.set_side('left')
        self.pump()
        self.assertTrue(button.isVisible())
        self.assertIs(button.parentWidget(), sidebar._column)
        sidebar.set_collapsed(False, animate=False)
        self.assertTrue(button.isHidden())

    def test_empty_slot_button_and_context_menu_route_target_and_hide_when_occupied(self):
        wall = self.own(WallGrid([], 'grid4'))
        wall.resize(900, 650)
        wall.show()
        self.pump()
        tile = wall.tiles[-1]
        targets = []
        wall.addRoomRequested.connect(targets.append)
        self.assertTrue(tile.add_room_button.isVisible())
        tile.add_room_button.click()
        self.assertEqual(targets, [tile])
        def choose():
            menu = QApplication.activePopupWidget()
            self.assertEqual(menu.actions()[0].text(), '添加直播间…')
            menu.actions()[0].trigger()
            menu.close()
        QTimer.singleShot(50, choose)
        point = tile.rect().center()
        tile.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse, point, tile.mapToGlobal(point)))
        self.assertEqual(targets, [tile, tile])
        tile.set_room(dict(room_id='1001', uname='测试', live=False))
        self.assertTrue(tile.add_room_button.isHidden())
        tile.set_room(None)
        self.assertTrue(tile.add_room_button.isVisible())

    def host(self):
        host = self.own(QWidget())
        host._closing = False
        host._platform_info_running = set()
        host.sidebar = SimpleNamespace(rooms=lambda: [dict(room_id='old')])
        host.plugins = SimpleNamespace(platform_for=lambda _rid: None)
        host._on_room_added = Mock()
        return host

    def test_batch_queries_serially_skips_duplicates_continues_after_failure_and_summarizes(self):
        host = self.host()
        target = object()
        batch = RoomAddBatch(host, ['old', '1', '2', '3', '3'], 'folder',
                             target_tile=target, resolver_type=Resolver)
        with patch('ddm.online_ui.show_result') as notice, patch('ddm.room_add_batch.QMessageBox.exec'):
            batch.start()
            self.pump()
            self.assertEqual([r.room_id for r in Resolver.created], ['1'])
            self.assertEqual(len(host._platform_info_running), 1)
            self.assertEqual(host._on_room_added.call_args.kwargs['target_tile'], target)
            Resolver.created[-1].complete(fail=True)
            self.pump()
            self.assertEqual([r.room_id for r in Resolver.created], ['1', '2'])
            Resolver.created[-1].complete()
            self.pump()
            Resolver.created[-1].complete()
            self.pump()
            self.assertFalse(host._platform_info_running)
            self.assertIn('已添加 2', notice.call_args.args[1])
            self.assertIn('失败 1', notice.call_args.args[1])
            self.assertEqual(batch.failures, [('1', '网络请求超时')])

    def test_single_target_reuses_original_query_and_preserves_target_on_completion(self):
        host = self.host()
        target = object()
        catalog = RoomCatalog(host)
        catalog.add_room_id('1001', resolver_type=Resolver, target_tile=target)
        Resolver.created[-1].complete()
        self.assertEqual(host._on_room_added.call_args.kwargs['target_tile'], target)
        self.assertFalse(host._platform_info_running)

    def test_close_stops_next_lookup(self):
        host = self.host()
        batch = RoomAddBatch(host, ['1', '2'], resolver_type=Resolver)
        batch.start()
        self.pump()
        host._closing = True
        Resolver.created[-1].complete()
        self.pump()
        self.assertEqual(len(Resolver.created), 1)
        host._on_room_added.assert_not_called()

    def test_added_room_fills_target_even_when_slot_count_at_limit_and_never_overwrites(self):
        host = self.host()
        target = SimpleNamespace(room={})
        host.sidebar.add_room = Mock(return_value=False)
        host.wall = SimpleNamespace(tiles=[target])
        host._tile_of = Mock(return_value=None)
        host.room_placement = SimpleNamespace(drop_room=Mock())
        host.add_to_wall = Mock()
        host._refresh_meta = Mock()
        host._save_timer = Mock()
        room = dict(room_id='new', uname='测试')
        catalog = RoomCatalog(host)
        catalog.on_room_added(room, max_tiles=1, target_tile=target, notify=False)
        host.room_placement.drop_room.assert_called_once_with(target, 'new', room=room)
        target.room = dict(room_id='occupied')
        catalog.on_room_added(room, max_tiles=1, target_tile=target, notify=False)
        host.add_to_wall.assert_called_once_with(room)
        host.room_placement.drop_room.assert_called_once()


if __name__ == '__main__':
    unittest.main()
