"""Inline add integration with real controls, isolated data and deferred fake room lookups."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QBoxLayout, QWidget
from ddm import config, images, motion
from ddm.sidebar_widgets import Sidebar
from ddm.room_catalog import RoomCatalog
from ddm.room_add_input import normalize_room_lines, normalize_room_text
from ddm.room_choice import RoomChoice
from ddm.room_placement import RoomPlacement
from ddm.wall_widgets import WallGrid
from selfcheck_room_add_entry import Resolver


class InlineRoomAddTests(unittest.TestCase):
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
        self.stack.enter_context(patch('ddm.online_ui.show_result'))
        self.host = QWidget()
        self.host.resize(1000, 800)
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self.host)
        self.host.sidebar = Sidebar([dict(room_id='old', uname='测试关注', live=False)], self.host, auto_compact=False)
        self.wall = QWidget()
        self.box.addWidget(self.host.sidebar)
        self.box.addWidget(self.wall, 1)
        self.host._closing = False
        self.host._platform_info_running = set()
        self.host.plugins = SimpleNamespace(platforms={}, platform_for=lambda _rid: None)
        self.host._normalize_room_input = lambda text: None
        self.host._on_room_added = Mock()
        self.catalog = RoomCatalog(self.host)
        self.host.show()
        Resolver.created = []
        self.pump()

    def tearDown(self):
        self.host._closing = True
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def pump(self):
        for _ in range(6):
            self.app.processEvents()

    def open(self, target=None):
        self.catalog.open_add_room(target_tile=target, resolver_type=Resolver)
        self.pump()
        return self.catalog._add_panel

    def portrait(self):
        self.box.setDirection(QBoxLayout.TopToBottom)
        self.host.resize(480, 900)
        self.host.sidebar.set_side('top')
        self.pump()

    def install_wall(self):
        host = self.host
        wall = WallGrid([], 'grid4', host)
        self.box.replaceWidget(self.wall, wall)
        self.wall.deleteLater()
        self.wall = host.wall = wall
        host.settings = {}
        host.recorder = Mock()
        host._stop_tile = Mock()
        host.start_tile = Mock()
        host.apply_quality_policy = Mock(return_value=[])
        host._refresh_meta = Mock()
        host._save_timer = Mock()
        host._tile_of = lambda rid: next((tile for tile in wall.tiles if tile.room.get('room_id') == rid), None)
        host.room_placement = RoomPlacement(host)
        host._prepare_room = host.room_placement.prepare_room
        host._on_room_added.side_effect = lambda room, **kwargs: self.catalog.on_room_added(
            room, max_tiles=4, **kwargs)
        wall.addRoomRequested.connect(lambda target: self.catalog.open_add_room(
            target_tile=target, resolver_type=Resolver))
        wall.show()
        self.pump()
        return wall

    def test_empty_slot_expands_grouped_follows_and_places_offline_room_without_lookup(self):
        wall = self.install_wall()
        occupied = dict(room_id='old', uname='测试关注', live=False)
        chosen = dict(room_id='huya:321', display_room_id='7654', uname='星空主播', live=False)
        self.host.sidebar.add_rooms([chosen, dict(room_id='1002', uname='路人', live=True)])
        folder = self.host.sidebar.create_folder('赛事')
        self.host.sidebar.move_to_folder([chosen['room_id']], folder)
        wall.tiles[0].set_room(dict(occupied))
        target = wall.tiles[3]
        panel = self.open()
        self.assertTrue(panel.followed_toggle.isHidden())
        panel.close_editor()
        QTest.mouseClick(target.add_room_button, Qt.LeftButton)
        self.pump()
        self.assertIs(self.catalog._add_target, target)
        self.assertTrue(panel.followed_toggle.isVisible())
        self.assertEqual(panel.followed_toggle.y(), panel.import_button.y())
        self.assertGreater(panel.followed_toggle.x(), panel.import_button.x())
        self.assertEqual(panel.followed_toggle.accessibleName(), '从关注列表选择')
        self.assertTrue(panel.followed.isHidden())
        panel.entry.setPlainText('https://live.bilibili.com/1003')
        collapsed = panel.geometry()
        QTest.mouseClick(panel.followed_toggle, Qt.LeftButton)
        self.pump()
        self.assertTrue(panel.followed.isVisible())
        self.assertEqual(panel.y(), collapsed.y())
        self.assertGreater(panel.height(), collapsed.height())
        self.assertTrue(self.host.rect().contains(panel.geometry()))
        cards = panel.followed.findChildren(RoomChoice)
        self.assertEqual({card.preview_name for card in cards}, {'星空主播', '路人'})
        panel.followed.search.setText('xkzb 赛事')
        self.assertEqual([card.preview_name for card in cards if card.isVisible()], ['星空主播'])
        QTest.mouseClick(panel.followed.live_only, Qt.LeftButton)
        self.assertFalse(any(card.isVisible() for card in cards))
        panel.followed.search.clear()
        self.assertEqual([card.preview_name for card in cards if card.isVisible()], ['路人'])
        stable_grid = next(grid for _holder, grid, entries in panel.followed.groups
                           if any(card.preview_name == '路人' for card, _terms, _room in entries))
        with patch.object(stable_grid, 'takeAt', wraps=stable_grid.takeAt) as removed:
            QTest.mouseClick(panel.followed.live_only, Qt.LeftButton)
        removed.assert_not_called()
        panel.followed.search.setText('7654')
        card = next(card for card in cards if card.isVisible())
        self.assertFalse(card.isCheckable())
        QTest.mouseClick(card, Qt.LeftButton)
        self.pump()
        self.assertFalse(panel.isVisible())
        self.assertEqual(target.room['room_id'], 'huya:321')
        self.assertFalse(wall.tiles[1].room.get('room_id'))
        self.assertFalse(Resolver.created)
        self.host.start_tile.assert_called_once_with(target)
        self.assertEqual(self.host.sidebar.folder_for('huya:321'), folder)
        self.assertEqual(panel.entry.toPlainText(), 'https://live.bilibili.com/1003')

    def test_followed_picker_scrolls_in_portrait_and_preserves_an_occupied_target(self):
        wall = self.install_wall()
        self.host.sidebar.add_rooms([dict(room_id=str(i), uname=f'关注 {i}', live=True) for i in range(100, 140)])
        self.portrait()
        target = wall.tiles[3]
        target.add_room_button.click()
        panel = self.catalog._add_panel
        panel.followed_toggle.click()
        self.pump()
        self.assertTrue(self.host.rect().contains(panel.geometry()))
        self.assertGreater(panel.followed.scroll.verticalScrollBar().maximum(), 0)
        search = panel.followed.search
        search.setText('139')
        self.pump()
        card = next(card for card in panel.followed.findChildren(RoomChoice) if card.isVisible())
        target.set_room(dict(room_id='other', uname='现有房间', live=False))
        QTest.mouseClick(card, Qt.LeftButton)
        self.assertEqual(target.room['room_id'], 'other')
        self.assertTrue(panel.error.isVisible())
        self.assertTrue(self.host.rect().contains(panel.geometry()))
        self.host._on_room_added.assert_not_called()
        search.setFocus()
        QTest.keyClick(search, Qt.Key_Escape)
        self.assertFalse(panel.isVisible())

    def test_no_dialog_and_sidebar_query_or_wall_geometry_changes(self):
        self.host.sidebar.search.setText('原搜索')
        query = self.host.sidebar.search.text()
        wall, side = self.wall.geometry(), self.host.sidebar.geometry()
        panel = self.open()
        self.assertTrue(panel.isVisible())
        self.assertFalse(panel.isWindow())
        self.assertIs(panel.parentWidget(), self.host)
        self.assertFalse(self.host.sidebar.search.isHidden())
        self.assertTrue(self.host.rect().contains(panel.geometry()))
        self.assertLessEqual(panel.submit_button.mapTo(panel, panel.submit_button.rect().bottomRight()).x(), panel.width())
        self.assertGreater(panel.x(), self.host.sidebar.geometry().right())
        panel.entry.setPlainText('1\n2\n3')
        self.pump()
        self.assertEqual(panel.submit_button.text(), '添加 3 个')
        self.assertEqual(self.wall.geometry(), wall)
        self.assertEqual(self.host.sidebar.geometry(), side)
        panel.close_button.click()
        self.assertFalse(panel.isVisible())
        self.assertEqual(self.host.sidebar.search.text(), query)
        self.assertEqual(self.wall.geometry(), wall)

    def test_portrait_keeps_search_follow_and_wall_for_many_inputs(self):
        self.portrait()
        wall, side = self.wall.geometry(), self.host.sidebar.geometry()
        panel = self.open()
        initial = panel.geometry()
        self.assertIs(panel.parentWidget(), self.host)
        self.assertFalse(self.host.sidebar.search.isHidden())
        self.assertFalse(self.host.sidebar.scroll.isHidden())
        panel.entry.setPlainText('\n'.join(str(number) for number in range(100)))
        self.pump()
        self.assertEqual(panel.geometry(), initial)
        self.assertEqual(self.wall.geometry(), wall)
        self.assertEqual(self.host.sidebar.geometry(), side)
        self.assertEqual(panel.entry.document().blockCount(), 100)
        self.assertGreater(panel.entry.verticalScrollBar().maximum(), 0)
        self.assertGreaterEqual(panel.height(), panel.minimumSizeHint().height())
        panel.close_editor()
        self.assertFalse(self.host.sidebar.search.isHidden())
        self.assertFalse(self.host.sidebar.scroll.isHidden())
        self.assertEqual(self.wall.geometry(), wall)

    def test_orientation_resize_and_collapsed_entry_preserve_draft(self):
        panel = self.open()
        panel.entry.setPlainText('1001\n1002')
        self.portrait()
        self.assertFalse(panel.isVisible())
        self.open()
        self.assertTrue(panel.isVisible())
        self.assertEqual(panel.entry.toPlainText(), '1001\n1002')
        self.assertTrue(self.host.rect().contains(panel.geometry()))
        self.host.sidebar.set_collapsed(True, animate=False)
        self.pump()
        self.assertTrue(self.host.sidebar.collapsed)
        self.assertFalse(panel.isVisible())
        self.open()
        self.assertTrue(panel.isVisible())
        self.assertIs(panel.parentWidget(), self.host)
        self.assertTrue(self.host.rect().contains(panel.geometry()))
        panel.close_editor()
        self.box.setDirection(QBoxLayout.LeftToRight)
        self.host.resize(1000, 800)
        self.host.sidebar.set_side('left')
        self.pump()
        wall = self.wall.geometry()
        self.open()
        self.assertTrue(self.host.sidebar.collapsed)
        self.assertEqual(self.wall.geometry(), wall)

    def test_invalid_line_is_inline_and_preserves_all_input(self):
        panel = self.open()
        draft = '1001\n\n无效输入\n1002'
        panel.entry.setPlainText(draft)
        panel.submit_button.click()
        self.assertIn('第 3 行', panel.error.toolTip())
        self.assertTrue(panel.error.isVisible())
        self.assertEqual(panel.entry.toPlainText(), draft)
        self.assertFalse(Resolver.created)
        self.assertFalse(panel.busy)

    def test_one_input_uses_existing_resolver_target_and_closes_on_success(self):
        target = object()
        panel = self.open(target)
        panel.entry.setPlainText('https://live.bilibili.com/1001')
        panel.submit_button.click()
        self.assertEqual(len(Resolver.created), 1)
        self.assertTrue(panel.busy)
        self.assertFalse(panel.submit_button.isEnabled())
        Resolver.created[-1].complete()
        self.assertFalse(panel.isVisible())
        self.assertEqual(panel.entry.toPlainText(), '')
        self.assertIs(self.host._on_room_added.call_args.kwargs['target_tile'], target)

    def test_failure_reason_preserves_draft_and_allows_retry(self):
        panel = self.open()
        panel.entry.setPlainText('1001')
        panel.submit_button.click()
        Resolver.created[-1].complete(fail=True)
        self.assertTrue(panel.isVisible())
        self.assertFalse(panel.busy)
        self.assertIn('网络请求超时', panel.error.toolTip())
        self.assertEqual(panel.entry.toPlainText(), '1001')
        self.assertTrue(panel.submit_button.isEnabled())

    def test_auto_batch_deduplicates_and_keeps_only_failures_for_retry(self):
        panel = self.open()
        panel.entry.setPlainText('1001\n1001\n1002')
        panel.submit_button.click()
        self.pump()
        self.assertEqual(len(Resolver.created), 1)
        Resolver.created[-1].complete(fail=True)
        self.pump()
        self.assertEqual(len(Resolver.created), 2)
        Resolver.created[-1].complete()
        self.pump()
        self.assertTrue(panel.isVisible())
        self.assertFalse(panel.busy)
        self.assertEqual(panel.entry.toPlainText(), '1001')
        self.assertIn('网络请求超时', panel.error.toolTip())
        self.assertEqual(self.host._on_room_added.call_count, 1)

    def test_folder_selection_import_and_escape_reuse_original_actions(self):
        folder = self.host.sidebar.create_folder('赛事')
        panel = self.open()
        action = next(a for a in panel.folder_button.menu().actions() if a.data() == folder)
        action.trigger()
        self.assertEqual(panel.folder_id, folder)
        imports = []
        self.host.sidebar.importFollowsClicked.connect(lambda: imports.append(True))
        panel.import_button.click()
        self.assertEqual(imports, [True])
        self.assertFalse(panel.isVisible())
        self.open()
        QTest.keyClick(panel.entry, Qt.Key_Escape)
        self.assertFalse(panel.isVisible())

    def test_input_validation_is_shared_and_preserves_original_line_numbers(self):
        normalize = lambda text: normalize_room_text(text, None)
        self.assertEqual(normalize_room_lines('1001\nhttps://live.bilibili.com/1001\n1002', normalize), ['1001', '1002'])
        with self.assertRaisesRegex(ValueError, '第 3 行'):
            normalize_room_lines('1001\n\n无效输入', normalize)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(InlineRoomAddTests, __file__))
    unittest.main()
