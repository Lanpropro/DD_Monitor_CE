"""Window layout coordination and Qt ownership with synthetic panes; no media or accounts."""
from pathlib import Path
import os
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtWidgets import QApplication, QBoxLayout, QWidget
from shiboken6 import isValid
from ddm import layouts
from ddm.app import MainWindow
from ddm.window_layout import WindowLayout


class Tile:
    def __init__(self, room_id, live, volume=40, muted=True, audio_channel=0):
        self.room = dict(room_id=room_id, live=live)
        self.volume, self.muted, self.audio_channel = volume, muted, audio_channel
        self.sync_audio_ui = Mock()


class Host:
    _layout_fits = staticmethod(MainWindow._layout_fits)

    def __init__(self):
        self.orientation, self._layout_by_orientation, self._pending_layout = 'landscape', {}, ''
        self.state, self._applying_room_preset, self._settling_resize = {}, False, False
        self.picture_in_picture = Mock(active=False)
        self._root_layout, self._content, self.sidebar = Mock(), Mock(), Mock()
        self._root_layout.isEnabled.return_value = True
        self._root_layout.indexOf.side_effect = lambda widget: 0 if widget is self.sidebar else 1
        self.wall = SimpleNamespace(layout_id='2x2', tiles=[], _capacity=lambda: 4,
            pane_danmaku=SimpleNamespace(settings={}, reset_preset=Mock(return_value=False)),
            relayout=Mock(), reset_layout_ratios=Mock(), setMinimumSize=Mock(),
            set_interactive_resize=Mock())
        self.wall.set_layout = Mock(side_effect=lambda identifier, **_: setattr(self.wall, 'layout_id', identifier))
        self.players, self.hover_preview = {}, Mock()
        for name in ('_cancel_interactive_resize', 'apply_quality_policy', '_sync_tile_playback',
                     '_refresh_meta', '_save_timer', '_resize_idle_timer', '_clear_tile_room'):
            setattr(self, name, Mock())
        self.is_portrait = Mock(return_value=False)
        self._resize_orientation = Mock(return_value='landscape')
        self.window_layout = WindowLayout(self)


for name in ('_build_arrangement', '_saved_layout', '_apply_orientation', '_clear_expanded_slots',
             '_prioritize_live_tiles', '_on_layout_changed', '_reshape_window'):
    setattr(Host, name, getattr(MainWindow, name))


class WindowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_import_does_not_load_main_window_player_or_owned_widgets(self):
        subprocess.run([sys.executable, '-c',
            "import sys; import ddm.window_layout; "
            "assert not {'ddm.app','ddm.widgets','ddm.wall_widgets','ddm.tile_widgets','ddm.player','mpv'}.intersection(sys.modules)"],
            cwd=ROOT, check=True, timeout=15)

    def test_saved_layout_defaults_invalid_value_and_current_host_state(self):
        host = Host()
        self.assertEqual(host._saved_layout('landscape'), layouts.FIRST_LAYOUT)
        self.assertEqual(host._saved_layout('portrait'), layouts.PORTRAIT_AUTO)
        host.state = {'ui': {'layout_landscape': 'auto', 'layout_portrait': 'portrait_dm4'}}
        self.assertEqual(host._saved_layout('landscape'), layouts.DEFAULT_LAYOUT)
        self.assertEqual(host._saved_layout('portrait'), 'portrait_dm4')
        self.assertEqual(vars(host.window_layout), {'host': host})

    def test_arrangement_keeps_qt_parents_and_native_child_identity(self):
        root = QWidget()
        root.setGeometry(-20000, -20000, 1200, 800)
        sidebar, content = QWidget(root), QWidget(root)
        video = QWidget(content)
        layout = QBoxLayout(QBoxLayout.LeftToRight, root)
        layout.addWidget(sidebar)
        layout.addWidget(content)
        sidebar.set_side, sidebar._sync_top_mode = Mock(), Mock()
        host = Host()
        host._root_layout, host.sidebar, host._content = layout, sidebar, content
        handle = int(video.winId())
        try:
            for orientation, direction in (('portrait', QBoxLayout.TopToBottom),
                                            ('landscape', QBoxLayout.LeftToRight)):
                host._build_arrangement(orientation)
                self.assertEqual(layout.direction(), direction)
                self.assertEqual(layout.count(), 2)
                self.assertIs(sidebar.parentWidget(), root)
                self.assertIs(content.parentWidget(), root)
                self.assertIs(video.parentWidget(), content)
                self.assertEqual(int(video.winId()), handle)
        finally:
            root.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(video))

    def test_pending_first_choice_and_orientation_memory_preserve_selection(self):
        host = Host()
        host.orientation = ''
        host._pending_layout = 'corner'
        host._apply_orientation('landscape')
        self.assertEqual(host.wall.layout_id, 'corner')
        self.assertEqual(host._pending_layout, '')
        host._apply_orientation('portrait')
        self.assertEqual(host._layout_by_orientation['landscape'], 'corner')
        portrait = host.wall.layout_id
        self.assertTrue(layouts.is_portrait_layout(portrait))
        host._apply_orientation('landscape')
        self.assertEqual(host.wall.layout_id, 'corner')
        self.assertEqual(host._layout_by_orientation['portrait'], portrait)
        host.sidebar.set_collapsed.assert_called_with(False, animate=False)

    def test_guard_and_exception_restore_root_layout_enabled_state(self):
        host = Host()
        for applying, pip in ((True, False), (False, True)):
            host._applying_room_preset, host.picture_in_picture.active = applying, pip
            host._apply_orientation('portrait')
            host._root_layout.setEnabled.assert_not_called()
        host._applying_room_preset = host.picture_in_picture.active = False
        for enabled in (True, False):
            host.orientation = 'landscape'
            host._root_layout.isEnabled.return_value = enabled
            host._root_layout.setEnabled.reset_mock()
            with patch.object(host, '_build_arrangement', side_effect=RuntimeError('fixture layout error')):
                with self.assertRaisesRegex(RuntimeError, 'fixture layout error'):
                    host._apply_orientation('portrait')
            self.assertEqual(host._root_layout.setEnabled.call_args.args, (enabled,))
        host.wall.relayout.assert_not_called()

    def test_expansion_clears_only_hidden_rooms_and_never_starts_them(self):
        host = Host()
        current, hidden, empty = Tile('current', True), Tile('hidden', True), Tile('', False)
        host.wall.tiles, host.wall._capacity = [current, hidden, empty], lambda: 1
        host._clear_expanded_slots('2x2')
        host._clear_tile_room.assert_called_once_with(hidden)
        host._clear_tile_room.reset_mock()
        host._clear_expanded_slots('1x1')
        host._clear_tile_room.assert_not_called()

    def test_shrinking_keeps_sound_at_position_and_preserves_player_identity(self):
        host = Host()
        offline, live, other = Tile('off', False, 20, True, 3), Tile('live', True, 75, False, 0), Tile('other', True)
        host.wall.tiles, host.wall._capacity = [offline, live, other], lambda: 3
        first_player, live_player = Mock(), Mock()
        host.players = {offline: first_player, live: live_player}
        host._prioritize_live_tiles('1x1')
        self.assertEqual(host.wall.tiles, [live, offline, other])
        self.assertIs(host.players[live], live_player)
        self.assertEqual((live.volume, live.muted, live.audio_channel), (20, True, 3))
        self.assertEqual((offline.volume, offline.muted, offline.audio_channel), (75, False, 0))
        live_player.set_volume.assert_called_once_with(20)
        first_player.set_volume.assert_called_once_with(75)
        live_player.reapply_audio_channel.assert_called_once_with()
        live_player.release.assert_not_called()
        self.assertEqual(live.room['audio_channel'], 3)

    def test_current_layout_reset_only_refreshes_playback_when_panes_changed(self):
        host = Host()
        host._on_layout_changed('2x2')
        host.wall.reset_layout_ratios.assert_called_once_with()
        host.wall.relayout.assert_not_called()
        host.wall.pane_danmaku.reset_preset.return_value = True
        host._on_layout_changed('2x2')
        host.wall.relayout.assert_called_once_with(force=True)
        host._sync_tile_playback.assert_called_once_with(start_visible=True)
        host._save_timer.start.assert_called_once_with()

    def test_explicit_cross_orientation_layout_survives_reshape_and_old_memory(self):
        host = Host()
        host._layout_by_orientation['portrait'] = 'portrait_main2'
        with patch.object(host, '_reshape_window') as reshape, \
                patch.object(host, '_apply_orientation') as apply:
            reshape.side_effect = lambda portrait: self.assertEqual(host.wall.layout_id, 'portrait_dm4')
            apply.side_effect = lambda direction: setattr(host, 'orientation', direction)
            host._on_layout_changed('portrait_dm4')
        reshape.assert_called_once_with(True)
        self.assertEqual(host._layout_by_orientation['landscape'], '2x2')
        self.assertEqual(host.state['ui']['layout_portrait'], 'portrait_dm4')
        self.assertEqual(host.wall.layout_id, 'portrait_dm4')
        self.assertEqual(host._pending_layout, 'portrait_dm4')
        host._resize_idle_timer.stop.assert_called_once_with()

    def test_reshape_clamps_to_screen_and_releases_old_minimum_before_resize(self):
        host = Host()
        host.isMaximized, host.showNormal = Mock(return_value=True), Mock()
        host.screen = Mock(return_value=SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080)))
        host.width, host.height = Mock(return_value=1600), Mock(return_value=900)
        host.x, host.y = Mock(return_value=1900), Mock(return_value=1070)
        host.move, host.resize = Mock(), Mock()
        order = []
        host.wall.setMinimumSize.side_effect = lambda *_: order.append('minimum')
        host.resize.side_effect = lambda *_: order.append('resize')
        with patch.object(host, '_build_arrangement') as arrange:
            arrange.side_effect = lambda _: order.append('arrange')
            host._reshape_window(True)
        host.showNormal.assert_called_once_with()
        host.move.assert_called_once_with(1312, 0)
        host.resize.assert_called_once_with(607, 1080)
        self.assertEqual(order, ['minimum', 'arrange', 'resize'])


if __name__ == '__main__':
    unittest.main()
