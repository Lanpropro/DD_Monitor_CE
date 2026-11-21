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
from ddm.plugins import RoomInfo, RoomList
from ddm.room_add_batch import RoomAddBatch
from ddm.room_catalog import RoomCatalog
from ddm.room_dialogs import FollowImportDialog
from ddm.room_navigation import RoomNavigation
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
        column_center = sidebar._column.width() / 2
        for control in (sidebar.toggle_button, button):
            center = control.mapTo(sidebar._column, control.rect().center()).x() + .5
            self.assertAlmostEqual(center, column_center, delta=1)
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
        for control in (sidebar.toggle_button, button):
            center = control.mapTo(sidebar._column, control.rect().center()).x() + .5
            self.assertAlmostEqual(center, sidebar._column.width() / 2, delta=1)
        sidebar.set_collapsed(False, animate=False)
        self.assertTrue(button.isHidden())

    def test_slot_button_routes_empty_and_offline_targets_and_hides_during_playback(self):
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
        self.assertTrue(tile.add_room_button.isVisible())
        self.assertEqual(tile.add_room_button.text(), '替换直播间')
        self.assertEqual(tile.cover.text(), '未开播')
        tile.add_room_button.click()
        self.assertEqual(targets, [tile, tile, tile])
        tile.set_live(True)
        self.assertTrue(tile.add_room_button.isHidden())
        tile.set_offline()
        self.assertEqual(tile.cover.text(), '已下播')
        self.assertTrue(tile.add_room_button.isVisible())
        tile.set_video_active(True)
        self.assertTrue(tile.add_room_button.isHidden())
        tile.set_room(dict(room_id='1001', live=False, live_known=False))
        self.assertTrue(tile.add_room_button.isHidden())
        tile.set_room(None)
        self.assertTrue(tile.add_room_button.isVisible())
        self.assertEqual(tile.add_room_button.text(), '＋ 添加直播间')

    def host(self):
        host = self.own(QWidget())
        host._closing = False
        host._platform_info_running = set()
        host.sidebar = SimpleNamespace(rooms=lambda: [dict(room_id='old')])
        host.plugins = SimpleNamespace(platform_for=lambda _rid: None)
        host._on_room_added = Mock()
        return host

    def test_playlist_input_uses_channel_picker_and_normal_follow_cards(self):
        host = self.host()
        host.resize(900, 600)
        host.sidebar = Sidebar([], host, auto_compact=False)
        store = Mock()
        sports = RoomInfo('test:5plus', 'CCTV-5+', '体育', True, platform='test',
                          extra={'import_group': '体育'})
        news = RoomInfo('test:news', '新闻', '资讯', True, platform='test',
                        extra={'import_group': '资讯'})
        plugin = SimpleNamespace(normalize=lambda value: value,
                                 room_input_file_filter='播放列表 (*.m3u *.m3u8)',
                                 room_list=lambda _source, _cancelled: RoomList([sports, news], store=store))
        host.plugins = SimpleNamespace(platforms={'test': plugin}, platform_for=lambda _value: plugin)
        host._normalize_room_input = RoomNavigation(host).normalize_room_input
        def add(rooms, *, folder_id, on_complete):
            host.sidebar.add_rooms(rooms)
            on_complete()
        host._import_selected_follows = add
        catalog = RoomCatalog(host)
        host.show()
        catalog.open_add_room(resolver_type=Resolver)
        panel = catalog._add_panel
        self.assertTrue(panel.presets.isHidden())
        self.assertTrue(panel.preset_button.isVisible())
        self.assertTrue(panel.preset_button.isCheckable())
        panel.preset_button.click()
        self.assertTrue(panel.presets.file_button.isVisible())
        self.assertTrue(panel.presets.isAncestorOf(panel.presets.file_button))
        self.assertEqual(panel.presets.file_button.text(), '')
        self.assertEqual(panel.presets.file_button.kind, 'open_folder')
        self.assertEqual(panel.presets.file_button.accessibleName(), '选择本地播放列表')
        self.assertTrue(panel.presets.search.isHidden())
        observed = []
        def select(dialog):
            self.assertEqual(dialog.windowTitle(), '导入频道')
            dialog.search_edit.setText('CCTV')
            self.assertFalse(dialog.list.item(0).isHidden())
            self.assertTrue(dialog.list.item(1).isHidden())
            dialog.search_edit.clear()
            dialog.group_control.setCurrentIndex(dialog.group_control.findData('体育'))
            self.assertFalse(dialog.list.item(0).isHidden())
            self.assertTrue(dialog.list.item(1).isHidden())
            dialog.list.item(0).setCheckState(Qt.Checked)
            observed.append(dialog.selected())
            return QDialog.Accepted
        path = 'C:/播放列表/频道.m3u'
        with patch('ddm.room_add_panel.QFileDialog.getOpenFileNames',
                   side_effect=[([], ''), ([path], '')]) as chooser:
            panel.presets.file_button.click()
            self.assertTrue(panel.presets.isVisible())
            self.assertFalse(panel.entry.toPlainText())
            panel.presets.file_button.click()
        self.assertIn('*.m3u8', chooser.call_args.args[3])
        self.assertEqual(panel.entry.toPlainText(), path)
        with patch.object(FollowImportDialog, 'exec', select):
            panel.submit_button.click()
            for _ in range(100):
                QTest.qWait(10)
                if not panel.busy:
                    break
        self.assertEqual(len(observed), 1)
        store.assert_called_once_with(['test:5plus'])
        self.assertFalse(panel.busy)
        self.assertEqual([room['room_id'] for room in host.sidebar.rooms()], ['test:5plus'])
        self.assertFalse(host._platform_info_running)

    def test_direct_hls_uses_normal_add_and_target(self):
        host = self.host()
        room = RoomInfo('test:hls', '单条直播', live=True, platform='test')
        source = Mock(return_value=RoomList([room], choose=False))
        host.plugins.platform_for = lambda _value: SimpleNamespace(room_list=source)
        target = object()
        done = Mock()
        RoomCatalog(host).add_room_id('https://example.com/live.m3u8', resolver_type=Resolver,
                                      target_tile=target, on_complete=done)
        for _ in range(100):
            QTest.qWait(10)
            if done.called:
                break
        done.assert_called_once_with(True, '')
        host._on_room_added.assert_called_once_with(room.as_dict(), folder_id='', target_tile=target)

    def test_legacy_channel_restores_existing_card_and_wall_labels(self):
        from ddm.app import MainWindow
        from ddm.plugins import Platform, PluginManager

        room_id = 'test:preset:cctv5plus'

        class StationPlatform(Platform):
            kind = 'test'

            def matches(self, value):
                return value == room_id

            def restore_follow_rooms(self, rooms):
                for room in rooms:
                    room.update(uname='CCTV-5+', title='体育赛事', live_from_playback=True)

        def load(manager):
            manager.platforms['test'] = StationPlatform()
            manager._platform_owner['test'] = 'test'

        state = {'rooms': [room_id], 'wall': [{'room_id': room_id}], 'plugins_enabled': ['test']}
        rooms, wall = config.build_rooms(state)
        with patch.object(PluginManager, 'load', load), patch('ddm.app.QTimer.singleShot'):
            window = self.own(MainWindow(rooms, wall, layout_id='1x1', state=state))
        item = window.sidebar.items_control.items()[0]
        tile = window.wall.tiles[0]
        self.assertEqual(item.name_label._full_text, 'CCTV-5+')
        self.assertEqual(item.sub._full_text, '体育赛事')
        self.assertEqual(item.badge.text(), '待检测')
        self.assertEqual((tile.room['uname'], tile.room['title']), ('CCTV-5+', '体育赛事'))
        self.assertEqual(window.current_state()['platform_rooms'][room_id]['playback_mode'], 'stream')

    def test_iptv_poll_result_sorts_unwalled_card_and_preserves_local_playback(self):
        from ddm.room_status import RoomStatus

        room_id = 'm3u:preset:cctv5plus'
        offline = dict(room_id='1001', uname='离线主播', live=False)
        channel = dict(room_id=room_id, uname='CCTV-5+', live=False, live_known=False, live_from_playback=True)
        sidebar = self.own(Sidebar([offline, channel], auto_compact=False))
        sidebar.set_sort_mode('live')
        host = SimpleNamespace(sidebar=sidebar, wall=SimpleNamespace(tiles=[]), settings={},
                               hover_preview=Mock(**{'_room_id.return_value': ''}), _startup_status_complete=True,
                               _load_room_banners=Mock(), _sync_replay_scope=Mock(), sync_danmaku=Mock(),
                               _show_notice=Mock())
        status = RoomStatus(host)
        item = sidebar.items_control.items()[1]
        self.assertEqual(item.room['room_id'], room_id)
        status.apply_status({room_id: dict(live=True, live_known=True, title='', viewers='')})
        self.assertEqual(item.badge.text(), '直播中')
        self.assertIs(sidebar.items_control.items()[0], item)
        host._show_notice.assert_not_called()

        tile = Mock(room=dict(item.room), _player_active=True)
        host.wall.tiles = [tile]
        unknown = {room_id: dict(live=False, live_known=False, title='', viewers='')}
        status.apply_status(unknown)
        self.assertEqual(item.badge.text(), '直播中')
        tile.set_live.assert_not_called()
        host.wall.tiles = []
        status.apply_status(unknown)
        self.assertEqual((item.badge.text(), item.sub._full_text), ('待检测', '待检测'))
        self.assertEqual(sidebar.items_control.items()[0].room['room_id'], '1001')

    def test_plugin_preset_from_empty_tile_adds_follow_only_and_deduplicates(self):
        host = self.host()
        host.resize(760, 530)
        host.sidebar = Sidebar([], host, auto_compact=False)
        target = self.own(WallGrid([], '1x1')).tiles[0]
        room = RoomInfo('test:preset', '研讨会直播', '会议频道', True, platform='test')
        host.plugins.platforms = {'test': SimpleNamespace(room_input_presets=lambda: [room])}
        host._import_selected_follows = Mock(side_effect=lambda rooms, **_kw: host.sidebar.add_rooms(rooms))
        folder_id = host.sidebar.create_folder('电视')
        host.show()
        catalog = RoomCatalog(host)
        catalog.open_add_room(target_tile=target, resolver_type=Resolver)
        panel = catalog._add_panel
        self.assertTrue(panel.followed_toggle.isVisible())
        self.assertTrue(panel.preset_button.isVisible())
        self.assertEqual(panel.preset_button.text(), '')
        self.assertEqual(panel.preset_button.kind, 'tv')
        self.assertEqual(panel.preset_button.accessibleName(), '频道预设')
        self.assertEqual(panel.preset_button.size(), panel.followed_toggle.size())
        self.assertLess(panel.followed_toggle.x(), panel.preset_button.x())
        collapsed_height = panel.height()
        panel.followed_toggle.click()
        self.assertTrue(panel.followed.isVisible())
        panel.preset_button.click()
        self.assertTrue(panel.preset_button.isChecked())
        self.assertTrue(panel.followed.isHidden())
        self.assertTrue(panel.presets.isVisible())
        self.assertGreater(panel.height(), collapsed_height)
        self.assertGreater(panel.presets.y(), panel.preset_button.y())
        self.assertTrue(panel.presets.file_button.isHidden())
        self.assertIsNone(panel.preset_button.menu())
        panel.presets.search.setText('不存在')
        self.assertEqual(panel.presets.model.rowCount(), 0)
        panel.presets.search.setText('研讨会')
        self.pump()
        folder = next(action for action in panel.folder_button.menu().actions() if action.data() == folder_id)
        folder.trigger()
        preset = panel.presets.model.index(1, 0)
        self.assertEqual(preset.data(Qt.DisplayRole), '研讨会直播')
        self.assertEqual(preset.data(Qt.ToolTipRole), '研讨会直播')
        for _ in range(2):
            QTest.mouseClick(panel.presets.scroll.viewport(), Qt.LeftButton,
                             pos=panel.presets.scroll.visualRect(preset).center())
        host._import_selected_follows.assert_called_once_with([room.as_dict()], folder_id=folder_id, on_complete=None)
        self.assertIn('已在关注列表', panel.error.text())
        self.assertEqual([item['room_id'] for item in host.sidebar.rooms()], ['test:preset'])
        host._on_room_added.assert_not_called()
        self.assertFalse(target.room.get('room_id'))
        host.plugins.platforms.clear()
        catalog.open_add_room(resolver_type=Resolver)
        self.assertTrue(panel.preset_button.isHidden())
        self.assertTrue(panel.presets.isHidden())
        self.assertFalse(panel.presets.rooms)

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
