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
from ddm import config, layouts, room_presets
from ddm.app import MainWindow
from ddm.widgets import WallGrid
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
        menu = panes.create_menu(1)
        self.addCleanup(menu.deleteLater)
        sources = next(action.menu() for action in menu.actions() if action.menu())
        next(action for action in sources.actions() if action.text().startswith('1 ·')).trigger()
        panel = panes.panels[1]
        self.assertTrue(panel.isVisible())
        self.assertTrue(backing.isHidden())
        self.assertIs(panes.target(panel), source)
        self.assertEqual(panel._linked_room_id, '1001')
        self.assertEqual((backing.room, backing.volume, backing.muted), original)
        menu = panes.create_menu(1)
        self.addCleanup(menu.deleteLater)
        next(action for action in menu.actions() if action.text() == '恢复直播画面').trigger()
        self.assertFalse(panes.panels)
        self.assertTrue(backing.isVisible())
        self.assertEqual((backing.room, backing.volume, backing.muted), original)
        source.setProperty('pictureInPicture', True)
        menu = source.build_menu()
        self.addCleanup(menu.deleteLater)
        self.assertNotIn('格子内容…', [action.text() for action in menu.actions()])
        source.setProperty('pictureInPicture', False)

    def test_multiple_panes_share_clients_and_route_messages_status_and_sc(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        first, second = wall.tiles[:2]
        window.configure_wall_panes({2: first, 3: first})
        panels = list(panes.panels.values())
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
