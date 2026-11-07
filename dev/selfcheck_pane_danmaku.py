"""Wall-only chat pane actions, shared subscriptions, identity and persistence."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

NATIVE = '--native' in sys.argv
if NATIVE:
    sys.argv.remove('--native')
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    os.environ['DDM_QTQUICK_DANMAKU'] = '1'

import selfcheck_main_notices as fixtures
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from ddm import config, layouts, room_presets, theme
from ddm.app import MainWindow
from ddm.widgets import DanmakuPanel, WallGrid
from selfcheck_video_danmaku import Client, Snapshot


REAL_SYNC = MainWindow.sync_danmaku


class PaneDanmakuTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MainNoticesTests.setUpClass.__func__)
    window = fixtures.MainNoticesTests.window
    close_window = fixtures.MainNoticesTests.close_window

    def setUp(self):
        fixtures.MainNoticesTests.setUp(self)
        self.stack.enter_context(patch.object(MainWindow, "sync_danmaku", REAL_SYNC))
        self.stack.enter_context(patch("ddm.app.bili._cookies", return_value={}))
        self.stack.enter_context(patch('ddm.app.DanmakuClient', Client))
        self.stack.enter_context(patch('ddm.app.SuperChatSnapshot', Snapshot))

    def wall_window(self):
        window = self.window([dict(room_id=str(1001 + i), uname=f'主播 {i + 1}',
                                 live=True, volume=20 + 10 * i, muted=bool(i % 2)) for i in range(4)], offscreen=True)
        window.settings["close_behavior"] = "exit"
        return window

    def test_wall_menu_converts_restores_and_preserves_room_and_sound(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        backing, source = wall.tiles[1], wall.tiles[0]
        original = deepcopy(backing.room), backing.volume, backing.muted
        menu = backing.build_menu()
        self.addCleanup(menu.deleteLater)
        self.assertNotIn('格子内容…', [action.text() for action in menu.actions()])
        next(action for action in menu.actions() if action.text() == '切换为弹幕').trigger()
        panel = panes.panels[1]
        self.assertTrue(panel.isVisible())
        self.assertTrue(backing.isHidden())
        self.app.processEvents()
        picker = panel.source_picker
        self.assertTrue(picker.expanded)
        self.assertEqual(set(picker.buttons), {wall.tiles[0], wall.tiles[2], wall.tiles[3]})
        self.assertIsNone(panes.target(panel))
        QTest.mouseClick(picker.buttons[source], Qt.LeftButton)
        self.assertFalse(picker.expanded)
        self.assertTrue(picker.tray.isHidden())
        self.assertTrue(picker.anchor.isVisible())
        self.assertFalse(panel.font_controls.isHidden())
        self.assertIs(panes.target(panel), source)
        self.assertEqual(panel._linked_room_id, '1001')
        self.assertLessEqual(picker.geometry().right(), panel.count.x())
        self.assertLess(panel.count.x() - picker.geometry().right(), 10)
        self.assertEqual((backing.room, backing.volume, backing.muted), original)
        menu = panes.create_menu(1)
        self.addCleanup(menu.deleteLater)
        self.assertEqual([action.text() for action in menu.actions()], ['恢复直播画面'])
        next(action for action in menu.actions() if action.text() == '恢复直播画面').trigger()
        self.assertFalse(panes.panels)
        self.assertTrue(backing.isVisible())
        self.assertEqual((backing.room, backing.volume, backing.muted), original)
        source.setProperty('pictureInPicture', True)
        menu = source.build_menu()
        self.addCleanup(menu.deleteLater)
        self.assertNotIn('切换为弹幕', [action.text() for action in menu.actions()])
        source.setProperty('pictureInPicture', False)

    def test_avatar_strip_reopens_scrolls_and_receives_late_cached_images(self):
        window = self.wall_window()
        wall = window.wall
        wall.set_layout('4x4')
        for index, tile in enumerate(wall.tiles[4:], 4):
            tile.set_room(dict(room_id=str(1001 + index), uname=f'主播 {index + 1}', live=False))
        window.configure_wall_panes({15: wall.tiles[0]})
        panel = wall.pane_danmaku.panels[15]
        picker = panel.source_picker
        QTest.mouseClick(picker.anchor, Qt.LeftButton)
        self.assertTrue(picker.expanded)
        self.assertEqual(len(picker.buttons), 15)
        positions = [button.x() for button in picker.buttons.values()]
        self.assertEqual(positions, sorted(positions, reverse=True))
        self.assertGreater(picker.scroll.horizontalScrollBar().maximum(), 0)
        # Every candidate remains reachable within the existing header height.
        bar = picker.scroll.horizontalScrollBar()
        bar.setValue(0)
        self.assertEqual(picker.buttons[wall.tiles[14]].x(), 0)
        height = panel.header.height()
        selected = wall.tiles[14]
        QTest.mouseClick(picker.buttons[selected], Qt.LeftButton)
        self.assertIs(wall.pane_danmaku.target(panel), selected)
        self.assertEqual(panel.header.height(), height)
        self.assertEqual(picker.anchor.identity[0], selected.room['room_id'])
        picker.set_expanded(True, animate=False)
        QTest.keyClick(picker.buttons[selected], Qt.Key_Escape)
        self.assertFalse(picker.expanded)
        self.assertTrue(picker.anchor.isVisible())
        # Avatar loading updates an already selected anchor without clearing its source.
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor('red'))
        target = wall.tiles[0]
        window.configure_wall_panes({15: target})
        window._on_room_avatar(target.room['room_id'], pixmap)
        self.assertEqual(picker.anchor.face_key, pixmap.cacheKey())
        self.assertEqual(picker.buttons[target].face_key, pixmap.cacheKey())
        self.assertIs(wall.pane_danmaku.target(panel), target)

    def test_avatar_header_only_compacts_when_candidates_do_not_fit(self):
        window = self.wall_window()
        window.configure_wall_panes({3: window.wall.tiles[0]})
        panel = window.wall.pane_danmaku.panels[3]
        picker = panel.source_picker
        panel.resize(700, 300)
        self.app.processEvents()
        picker.set_expanded(True, animate=False)
        self.assertTrue(panel.title.isVisible())
        self.assertTrue(panel.font_controls.isVisible())
        self.assertGreaterEqual(picker.tray.x(), panel.font_controls.geometry().right())
        self.assertLessEqual(picker.tray.geometry().right(), panel.count.x())
        panel.resize(210, 300)
        self.app.processEvents()
        self.assertTrue(picker.expanded)
        self.assertTrue(panel.title.isHidden())
        self.assertTrue(panel.font_controls.isHidden())
        self.assertEqual(picker.tray.x(), panel.header.layout().contentsMargins().left())
        panel.resize(700, 300)
        self.app.processEvents()
        self.assertTrue(panel.title.isVisible())
        self.assertTrue(panel.font_controls.isVisible())
        self.assertGreaterEqual(picker.tray.x(), panel.font_controls.geometry().right())
        picker.set_expanded(False, animate=False)
        self.assertTrue(panel.title.isVisible())
        self.assertTrue(panel.font_controls.isVisible())

    def test_lower_corners_are_continuous_with_and_without_send_bar(self):
        from ddm import continuous_corners
        host = QWidget()
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.close)
        host.setObjectName('PanelCornersFixture')
        host.setStyleSheet('#PanelCornersFixture {background: #ff00ff;}')
        host.setGeometry(-10000, -10000, 384, 304)
        panel = DanmakuPanel(host)
        panel.setGeometry(12, 12, 360, 280)
        panel.body.setPlainText('\n'.join('滚动消息 ' + str(index) for index in range(100)))
        host.show()
        for mode in ('dark', 'light'):
            theme.apply(mode)
            self.app.setStyleSheet(theme.qss())
            for sending in (False, True):
                with self.subTest(theme=mode, send_bar=sending):
                    panel.composer_bar.setVisible(sending)
                    self.app.processEvents()
                    panel.body.verticalScrollBar().setValue(panel.body.verticalScrollBar().maximum())
                    surface = panel.composer_bar if sending else panel.body
                    values = continuous_corners._filter.values(surface)
                    self.assertEqual(values['border-bottom-left-radius'], '10px')
                    self.assertEqual(values['border-bottom-right-radius'], '10px')
                    image = host.grab().toImage()
                    scale = image.devicePixelRatio()
                    for x in (12, 13, 370, 371):
                        self.assertEqual(image.pixelColor(round(x * scale), round(291 * scale)).name(), '#ff00ff')
                    self.assertNotEqual(image.pixelColor(round(180 * scale), round(291 * scale)).name(), '#ff00ff')

    def test_avatar_motion_is_right_anchored_interruptible_and_stops_when_hidden(self):
        from ddm import motion
        window = self.wall_window()
        window.configure_wall_panes({3: window.wall.tiles[1]})
        panel = window.wall.pane_danmaku.panels[3]
        picker = panel.source_picker
        with patch.object(motion, 'enabled', return_value=True):
            picker.set_expanded(True)
            picker.animation.setCurrentTime(60)
            progress = picker.progress
            self.assertGreater(progress, 0)
            self.assertLess(progress, 1)
            picker.set_expanded(False)
            self.assertAlmostEqual(picker.animation.startValue(), progress)
            picker.animation.setCurrentTime(picker.animation.duration())
            self.assertTrue(picker.tray.isHidden())
            self.assertTrue(picker.anchor.isVisible())
            picker.set_expanded(True)
            panel.hide()
            self.assertEqual(picker.animation.state(), QAbstractAnimation.Stopped)
            self.assertFalse(picker.expanded)
            self.assertTrue(picker.tray.isHidden())
        panel.show()
        with patch.object(motion, 'enabled', return_value=False):
            picker.set_expanded(True)
            self.assertEqual(picker.progress, 1)
            self.assertEqual(picker.animation.state(), QAbstractAnimation.Stopped)

    def test_multiple_panes_share_clients_and_route_messages_status_and_sc(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        first, second = wall.tiles[:2]
        window.configure_wall_panes({2: first, 3: first})
        panels = panes.rendered()
        self.assertEqual(len(panels), 1)
        self.assertEqual(set(window._danmaku_clients), {'1001', '1002'})  # visible SC sources too
        client = window._danmaku_clients['1001']
        client.message.emit(dict(kind='danmaku', text='共享消息', uname='测试'))
        for panel in panels:
            self.assertEqual(panel._blocks[-1]['text'], '共享消息')
        client.status.emit('已连接')
        self.assertTrue(all(panel._status == '已连接' for panel in panels))
        now = int(time.time())
        client.message.emit(dict(kind='super_chat', id='shared-sc', uid='1', uname='测试',
                                 price=30, message='共享 SC', start_time=now, end_time=now + 120))
        self.assertTrue(all(panel.super_chats._events for panel in panels))
        client.message.emit(dict(kind='super_chat_delete', ids=['shared-sc']))
        self.assertTrue(all(not panel.super_chats._events for panel in panels))
        window.configure_wall_panes({2: first, 3: second})
        panels = list(panes.panels.values())
        self.assertIs(window._danmaku_clients['1001'], client)
        client.message.emit(dict(kind='danmaku', text='只给第一栏'))
        self.assertEqual(panels[0]._blocks[-1]['text'], '只给第一栏')
        self.assertFalse(any(event.get('text') == '只给第一栏' for event in panels[1]._blocks))
        # Old clients queued after a source change must not route into the new pane.
        first.set_room(dict(room_id='2001', uname='新主播', live=True))
        window.sync_danmaku()
        client.message.emit(dict(kind='danmaku', text='旧房间排队消息'))
        self.assertFalse(any(event.get('text') == '旧房间排队消息' for event in panels[0]._blocks))
        self.assertEqual(panels[0]._linked_room_id, '2001')
        first.set_room(None)
        window.sync_danmaku()
        self.assertEqual(panels[0]._linked_room_id, '')
        self.assertEqual(panels[0].count.property("state"), "idle")
        self.assertIsNone(panes.target(panels[0]))

    def test_swap_and_move_keep_explicit_sources_and_recording_is_not_interrupted(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        first, second = wall.tiles[:2]
        window.configure_wall_panes({3: first})
        wall.tiles[0], wall.tiles[1] = second, first
        wall.relayout(force=True)
        window.sync_danmaku()
        self.assertIs(panes.target(panes.panels[3]), first)
        with patch.object(window, '_hot_swap', return_value=False):
            window._on_tile_swapped('1001', second)
        self.assertIs(panes.target(panes.panels[3]), second)
        self.assertEqual(panes.target(panes.panels[3]).room['room_id'], '1001')
        destination = panes.cell_for_tile(first)
        panes.move(3, first)
        self.assertIn(destination, panes.bindings())
        self.assertIs(panes.target(panes.panels[destination]), second)
        window.recorder.sessions[second] = Mock(recording=True, stopping=False)
        self.addCleanup(window.recorder.sessions.clear)
        with self.assertRaisesRegex(ValueError, '录制'):
            window.configure_wall_panes({panes.cell_for_tile(second): None})

    def test_explicit_layout_selection_resets_manual_panes_including_current_layout(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        window.configure_wall_panes({3: wall.tiles[0]})
        window._on_layout_changed('1x2')
        window._on_layout_changed('2x2')
        self.assertFalse(panes.bindings())
        self.assertTrue(all(tile.isVisible() for tile in wall.tiles[:4]))
        window.configure_wall_panes({3: wall.tiles[0]})
        window._on_layout_changed('2x2')
        self.assertFalse(panes.bindings())
        window._on_layout_changed('dm_main2')
        default = layouts.danmaku_cell('dm_main2')
        window.configure_wall_panes({0: -1})
        window._on_layout_changed('dm_main2')
        self.assertFalse(panes.custom)
        self.assertEqual(set(panes.bindings()), {default})
        self.assertIs(panes.panels[default], wall.danmaku)

    def test_adjacent_regions_merge_preserve_messages_and_restore_all_backing_cells(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        source = wall.tiles[0]
        window.configure_wall_panes({2: source})
        original = panes.panels[2]
        client = window._danmaku_clients['1001']
        client.message.emit(dict(kind='danmaku', text='合并前消息'))
        window.configure_wall_panes({2: source, 3: source})
        merged, = panes.rendered()
        self.assertIs(merged, original)
        self.assertEqual(merged._blocks[-1]['text'], '合并前消息')
        self.assertEqual(merged.geometry(), panes.rectangles[2].united(panes.rectangles[3]))
        self.assertEqual(set(panes.cells_for(2)), {2, 3})
        wall.set_fullscreen_tile(source)
        window.sync_danmaku()
        self.assertTrue(all(panel.isHidden() for panel in panes.all_panels()))
        wall.set_fullscreen_tile(None)
        window.sync_danmaku()
        self.assertIs(panes.rendered()[0], merged)
        self.assertEqual(merged._blocks[-1]['text'], '合并前消息')
        panes.room_dropped(merged, '1002')
        self.assertTrue(all(tile is wall.tiles[1] for tile in panes.bindings().values()))
        self.assertEqual(len(panes.rendered()), 1)
        menu = panes.create_menu(2)
        self.addCleanup(menu.deleteLater)
        self.assertEqual([a.text() for a in menu.actions()], ['恢复直播画面'])
        menu.actions()[0].trigger()
        self.assertFalse(panes.bindings())
        self.assertTrue(all(tile.isVisible() for tile in wall.tiles[:4]))

    def test_rectangular_merges_never_cover_unrelated_cells_and_follow_source_changes(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        window._on_layout_changed('3x3')
        first, second = wall.tiles[:2]
        cases = [({3: first, 4: first}, 1), ({3: first, 6: first}, 1),
                 ({3: first, 4: first, 6: first, 7: first}, 1),
                 ({3: first, 7: first}, 2), ({3: first, 4: second}, 2),
                 ({3: -1, 4: -1}, 2), ({3: first, 4: first, 6: first}, 2)]
        for bindings, count in cases:
            with self.subTest(cells=tuple(bindings), count=count):
                window.configure_wall_panes(bindings)
                self.assertEqual(len(panes.rendered()), count)
                for panel in panes.rendered():
                    for cell, rect in panes.rectangles.items():
                        if cell not in bindings:
                            self.assertFalse(panel.geometry().intersects(rect))
        window.configure_wall_panes({3: first, 4: second})
        second.set_room(dict(first.room))
        window.sync_danmaku()
        self.assertEqual(len(panes.rendered()), 1)
        second.set_room(dict(room_id='2002', uname='换台', live=True))
        window.sync_danmaku()
        self.assertEqual(len(panes.rendered()), 2)
        self.assertEqual({panel._linked_room_id for panel in panes.rendered()}, {'1001', '2002'})
        second.set_room(None)
        window.sync_danmaku()
        self.assertEqual(len(panes.rendered()), 2)
        self.assertEqual(panes.panels[4]._linked_room_id, '')

    def test_state_and_named_presets_restore_type_links_and_backing_slots(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        first, second = wall.tiles[:2]
        window.configure_wall_panes({2: first, 3: second})
        snapshot = window.room_preset_snapshot()
        self.assertEqual(snapshot['layout']['panels'], [dict(cell=2, source=0), dict(cell=3, source=1)])
        self.assertEqual(len(snapshot['slots']), 4)
        key = window.save_room_preset('双路弹幕')
        window.configure_wall_panes({})
        self.assertTrue(window.apply_room_preset(key))
        self.assertEqual(window.room_preset_snapshot(), snapshot)
        state = window.current_state()
        state["settings"]["danmaku_font_size"] = 18
        # A software restart creates a fresh QApplication in a new process.
        with tempfile.TemporaryDirectory(prefix='ddm-pane-state-') as directory:
            state_file = Path(directory) / 'state.json'
            state_file.write_text(json.dumps(state), encoding='utf-8')
            result = subprocess.run([sys.executable, str(Path(__file__).parent / 'checks/bootstrap.py'),
                str(Path(__file__).resolve()), '--restore-state', str(state_file)],
                capture_output=True, text=True, encoding='utf-8', timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS: fresh-process pane restoration', result.stdout)
        invalid = deepcopy(snapshot)
        invalid['layout']['panels'][0]['source'] = 3
        with self.assertRaises(ValueError):
            room_presets.validate(invalid)

    @unittest.skipUnless(NATIVE, 'Windows native local MP4 check')
    def test_native_playback_core_and_hwnd_survive_type_changes_and_hot_swap(self):
        from ddm.player import TilePlayer
        from selfcheck_mpv import ready, pump
        window = self.wall_window()
        source, empty = window.wall.tiles[:2]
        empty.set_room(None)
        with tempfile.TemporaryDirectory(prefix='ddm-chat-panes-') as directory:
            media = Path(directory) / 'silent.mp4'
            subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30', '-t', '10', '-c:v', 'libx264',
                '-preset', 'ultrafast', str(media)], check=True, timeout=30)
            player = TilePlayer(source.video, window, silent=True)
            window.players[source] = player
            try:
                player.play(str(media))
                ready(self.app, player)
                core, handle, generation = player.player, int(source.video.winId()), player.state_generation
                position = player._prop('time-pos') or 0
                window.configure_wall_panes({2: source, 3: source})
                self.assertTrue(window._hot_swap(source, empty))
                pump(self.app, .3)
                self.assertIs(player.player, core)
                self.assertEqual(int(source.video.winId()), handle)
                self.assertGreater(player._prop('time-pos') or 0, position)
                self.assertTrue(all(window.wall.pane_danmaku.target(panel) is source
                                    for panel in window.wall.pane_danmaku.panels.values()))
                window.picture_in_picture.start([window.wall.tiles.index(source)])
                self.assertTrue(all(panel.isHidden() for panel in window.wall.pane_danmaku.all_panels()))
                window.picture_in_picture.restore(activate=True)
                self.assertEqual(len(window.wall.pane_danmaku.rendered()), 1)
                self.assertTrue(window.wall.pane_danmaku.rendered()[0].isVisible())
                window.configure_wall_panes({})
                self.assertIs(player.player, core)
                self.assertEqual(int(source.video.winId()), handle)
                self.assertEqual(player.state_generation, generation)
            finally:
                window.players.pop(source, None)
                player.release()

    def test_every_preset_accepts_arbitrary_cells_including_portrait_and_corner(self):
        wall = WallGrid([], layout_id='2x2')
        self.addCleanup(wall.deleteLater)
        self.addCleanup(wall.close)
        wall.resize(1200, 900)
        wall.show()
        self.app.processEvents()
        for identifier in layouts.BY_ID:
            with self.subTest(layout=identifier):
                wall.set_layout(identifier)
                count = layouts.capacity(identifier)
                wall.pane_danmaku.apply({0: None, count - 1: None})
                self.app.processEvents()
                widgets = wall._preset_widgets()
                self.assertEqual(set(widgets), set(range(count)))
                self.assertEqual(set(wall.pane_danmaku.panels), {0, count - 1})
                self.assertTrue(all(panel.isVisible() for panel in wall.pane_danmaku.panels.values()))
                self.assertTrue(all(rect.width() > 0 and rect.height() > 0 for rect in
                                    (widget.geometry() for widget in widgets.values())))


def restore_state(path):
    state = json.loads(Path(path).read_text(encoding='utf-8'))
    case = PaneDanmakuTests('test_state_and_named_presets_restore_type_links_and_backing_slots')
    case.setUpClass()
    case.setUp()
    try:
        follows, rooms = config.build_rooms(state)
        window = MainWindow(follows, rooms, layout_id='2x2', state=state)
        window.settings['close_behavior'] = 'exit'
        case.addCleanup(case.close_window, window)
        window.move(-10000, -10000)
        window.show()
        case.app.processEvents()
        panes = window.wall.pane_danmaku
        case.assertEqual(set(panes.panels), {2, 3})
        case.assertTrue(all(panel.font_slider.value() == 18 for panel in panes.panels.values()))
        case.assertEqual([panes.target(panel).room['room_id'] for panel in panes.panels.values()], ['1001', '1002'])
        case.assertEqual(window.current_state()['ui']['pane_layouts'], state['ui']['pane_layouts'])
        print('PASS: fresh-process pane restoration', flush=True)
    finally:
        case.doCleanups()


if __name__ == '__main__':
    if '--restore-state' in sys.argv:
        restore_state(sys.argv[sys.argv.index('--restore-state') + 1])
    else:
        unittest.main(verbosity=2)
