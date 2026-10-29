"""Public tile extensions: attachment, isolation, layout and disposal."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
import shiboken6

os.environ.setdefault('DDM_NO_SAVE', '1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QPushButton, QWidget
from PySide6.QtGui import QPalette
from ddm import plugins as api
from ddm.widgets import Tile, WallGrid
from ddm import theme

APP = QApplication.instance() or QApplication([])


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(api, 'TileControl'), 'public tile extension API is missing')
        self.manager = api.PluginManager()
        self.tiles = []
        self.controls = []

    def tearDown(self):
        self.manager.unload()
        for tile in self.tiles:
            tile.close()
            tile.deleteLater()
        APP.processEvents()

    def tile(self, room=None):
        tile = Tile(room or {})
        self.tiles.append(tile)
        tile.show()
        self.manager.attach_tile(tile)
        return tile

    def register(self, owner='demo', priority=0, broken=False):
        controls = self.controls
        class Control(api.TileControl):
            def __init__(self, ctx):
                super().__init__(QLineEdit(ctx.parent), minimum_width=90)
                self.ctx, self.rooms, self.stops = ctx, [], 0
                controls.append(self)
            def set_room(self, room):
                self.rooms.append(dict(room))
                room['mutated'] = True
                self.widget.setVisible(str(room.get('room_id', '')).isdigit())
                if broken:
                    raise ValueError('test update failure')
            def shutdown(self):
                self.stops += 1
        self.manager.register_tile_control(owner, 'edit', Control, priority=priority)

    def test_focus_dispatch_skips_hidden_disabled_and_removed_controls(self):
        class Input(api.TileControl):
            def __init__(self, context):
                super().__init__(QLineEdit(context.parent), minimum_width=90)
            def focus_input(self):
                self.widget.setFocus(Qt.ShortcutFocusReason)
                return True
        self.manager.register_tile_control('input', 'edit', Input)
        tile = self.tile({'room_id': '12'})
        tile.resize(900, 400)
        APP.processEvents()
        edit = tile._plugin_controls.entries[0].control.widget
        self.assertTrue(tile._plugin_controls.focus_input())
        self.assertTrue(edit.hasFocus())
        edit.clearFocus()
        edit.setEnabled(False)
        self.assertFalse(tile._plugin_controls.focus_input())
        edit.setEnabled(True)
        tile.resize(200, 240)
        APP.processEvents()
        self.assertFalse(tile._plugin_controls.focus_input())
        self.manager.detach_tile(tile)
        tile.focus_danmaku_input()  # No provider is a safe no-op.

    def test_existing_new_and_initially_empty_tiles_receive_one_control(self):
        first = self.tile()
        self.register()
        self.manager.attach_tile(first)
        second = self.tile({'room_id': '12'})
        self.assertEqual(len(self.controls), 2)
        first.set_room({'room_id': '11'})
        self.assertEqual(self.controls[0].rooms, [{}, {'room_id': '11'}])
        self.assertFalse(self.controls[0].widget.isHidden())

    def test_danmaku_layout_moves_existing_editor_and_restores_it(self):
        self.register()
        wall = WallGrid([{'room_id': '12'}, {'room_id': '13'}], layout_id='dm_main2')
        self.addCleanup(wall.deleteLater)
        self.addCleanup(wall.close)
        wall.resize(1200, 700)
        wall.show()
        for tile in wall.tiles:
            self.manager.attach_tile(tile)
        APP.processEvents()
        main, small = wall.tiles
        controls = main._plugin_controls
        edit = controls.entries[0].control.widget
        edit.setText('unsent draft')
        panel = wall.danmaku
        self.assertIs(controls.widget.parentWidget(), panel.composer_bar)
        self.assertTrue(panel.composer_bar.isVisible())
        self.assertTrue(panel.composer_bar.rect().contains(controls.widget.geometry()))
        self.assertGreater(panel.composer_bar.y(), panel.body.geometry().bottom())
        self.assertIs(small._plugin_controls.widget.parentWidget(), small.bottom)
        wall.resize(600, 480)
        APP.processEvents()
        self.assertTrue(panel.composer_bar.rect().contains(controls.widget.geometry()))
        wall.set_fullscreen_tile(main)
        APP.processEvents()
        self.assertIs(controls.widget.parentWidget(), main.bottom)
        self.assertTrue(panel.composer_bar.isHidden())
        wall.set_fullscreen_tile(None)
        APP.processEvents()
        self.assertIs(controls.widget.parentWidget(), panel.composer_bar)
        self.assertEqual(edit.text(), 'unsent draft')
        main.set_room({'room_id': 'other:12'})
        APP.processEvents()
        self.assertTrue(panel.composer_bar.isHidden())
        main.set_room({'room_id': '14'})
        APP.processEvents()
        self.assertTrue(panel.composer_bar.isVisible())
        self.assertEqual(controls.entries[0].context.room['room_id'], '14')
        wall.set_layout('1x2')
        APP.processEvents()
        self.assertIs(controls.widget.parentWidget(), main.bottom)
        self.assertEqual(edit.text(), 'unsent draft')
        wall.set_layout('dm_main2')
        APP.processEvents()
        self.manager.detach_tile(main)
        APP.processEvents()
        self.assertIsNone(panel._tile_controls)
        self.assertTrue(panel.composer_bar.isHidden())

    def test_destroyed_wall_disposes_docked_controls_once(self):
        self.register()
        wall = WallGrid([{'room_id': '12'}], layout_id='dm_pair')
        tile = wall.tiles[0]
        self.manager.attach_tile(tile)
        wall.show()
        APP.processEvents()
        control = tile._plugin_controls.entries[0].control
        wall.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertNotIn(tile, self.manager._tiles)
        self.assertEqual(control.stops, 1)

    def test_docked_composer_and_bottom_icon_follow_light_dark_theme(self):
        previous = theme.mode()
        self.addCleanup(theme.apply, previous)
        theme.apply('dark')
        def factory(context):
            widget = QWidget(context.parent)
            widget.setObjectName('DanmakuComposer')
            widget.setStyleSheet('#DanmakuComposer {background: transparent; border: none;}')
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(widget)
            edit.setPlaceholderText('输入弹幕，Enter 发送')
            layout.addWidget(edit)
            send = QPushButton('发送', widget)
            send.setObjectName('TileCtrl')
            send.setEnabled(False)
            layout.addWidget(send)
            return api.TileControl(widget, minimum_width=90)
        self.manager.register_tile_control('synthetic', 'interaction', factory)
        wall = WallGrid([{'room_id': '12'}], layout_id='dm_pair')
        self.addCleanup(wall.deleteLater)
        self.addCleanup(wall.close)
        wall.resize(900, 600)
        wall.show()
        self.manager.attach_tile(wall.tiles[0])
        panel = wall.danmaku
        for i in range(100):
            panel.add_message('Viewer', str(i))
        APP.processEvents()
        panel.body.verticalScrollBar().setValue(0)
        panel._on_user_scroll()
        composer = panel._tile_controls.entries[0].control.widget
        edit = composer.findChild(QLineEdit)
        for mode in ('light', 'dark', 'light'):
            theme.apply(mode)
            APP.processEvents()
            self.assertEqual(panel.header.property('appearanceLight'), mode == 'light')
            self.assertEqual(panel.composer_bar.property('appearanceLight'), mode == 'light')
            for bar in (panel.header, panel.composer_bar):
                pixel = panel.grab().toImage().pixelColor(bar.x() + 2, bar.y() + 8)
                self.assertEqual(pixel.lightness() > 200, mode == 'light')
            self.assertEqual(edit.palette().color(QPalette.Text).lightness() < 128, mode == 'light')
            image = edit.grab().toImage()
            ink = [image.pixelColor(x, y).lightness()
                   for y in range(6, image.height() - 6) for x in range(10, min(100, image.width() - 10))]
            self.assertGreater(max(ink) - min(ink), 60)
            self.assertEqual(edit.palette().color(QPalette.PlaceholderText).lightness() < 128, mode == 'light')
            send = composer.findChild(QPushButton)
            self.assertEqual(send.palette().color(QPalette.ButtonText).lightness() < 160, mode == 'light')
            button = panel.bottom_button
            self.assertTrue(button.isVisible())
            pixel = button.grab().toImage().pixelColor(3, 16)
            self.assertEqual(pixel.lightness() > 200, mode == 'light',
                             (mode, pixel.name(), pixel.alpha(), button.styleSheet()))

    def test_danmaku_target_switch_and_late_registration(self):
        wall = WallGrid([{'room_id': '12'}, {'room_id': '13'}], layout_id='dm_pair')
        self.addCleanup(wall.deleteLater)
        self.addCleanup(wall.close)
        wall.resize(1200, 700)
        wall.show()
        for tile in wall.tiles:
            self.manager.attach_tile(tile)
        APP.processEvents()
        self.assertTrue(wall.danmaku.composer_bar.isHidden())
        self.register()
        APP.processEvents()
        first, second = wall.tiles
        self.assertIs(wall.danmaku._tile_controls, first._plugin_controls)
        first.set_room(None)
        APP.processEvents()
        self.assertIs(wall.danmaku._tile_controls, second._plugin_controls)
        self.assertIs(first._plugin_controls.widget.parentWidget(), first.bottom)
        self.manager._remove_tile_owner('demo')
        APP.processEvents()
        self.assertTrue(wall.danmaku.composer_bar.isHidden())

    def test_every_assignment_is_delivered_as_a_copy(self):
        self.register()
        tile = self.tile({'room_id': '12'})
        for room in (None, {'room_id': '12', 'title': 'new'}, {'room_id': '13'}, {'room_id': '12'}):
            tile.set_room(room)
            self.assertNotIn('mutated', tile.room)
            self.assertEqual(self.controls[0].rooms[-1].get('room_id'), (room or {}).get('room_id'))
            self.assertEqual(self.controls[0].ctx.room.get('room_id'), (room or {}).get('room_id'))
        self.assertEqual(len(self.controls), 1)

    def test_failed_load_rolls_back_controls(self):
        self.tile({'room_id': '12'})
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'bad'
            folder.mkdir()
            (folder / 'plugin.py').write_text('from ddm.plugins import *\n'
                'from PySide6.QtWidgets import QLineEdit\n'
                'class Bad(Plugin):\n'
                ' def on_load(self, c):\n'
                '  c.register_tile_control("bad", lambda x: TileControl(QLineEdit(x.parent)))\n'
                '  raise ValueError("intentional")\nplugin=Bad()\n', encoding='utf-8')
            self.manager.plugins_dir = root
            self.manager.load()
        self.assertEqual(len(self.manager.plugins), 0)
        self.assertEqual(self.tiles[0]._plugin_controls.entries, [])

    def test_provider_exceptions_do_not_block_others(self):
        self.register('bad', broken=True)
        self.register('good')
        tile = self.tile({'room_id': '12'})
        tile.set_room({'room_id': '13'})
        self.assertEqual(self.controls[-1].rooms[-1]['room_id'], '13')

    def test_remove_and_unload_shutdown_once(self):
        self.register()
        tile = self.tile({'room_id': '12'})
        self.manager.detach_tile(tile)
        self.manager.detach_tile(tile)
        self.manager.unload()
        self.assertEqual(self.controls[0].stops, 1)

    def test_dropped_wall_tile_does_not_break_later_registration(self):
        self.register()
        wall = WallGrid([], layout_id='1x1')
        self.addCleanup(wall.deleteLater)
        self.addCleanup(wall.close)
        dropped = wall.tiles[0]
        self.manager.attach_tile(dropped)
        old_control = self.controls[0]
        wall._drop_tile(dropped)
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(shiboken6.isValid(dropped))
        live = self.tile({'room_id': '13'})
        self.register('next')
        self.assertNotIn(dropped, self.manager._tiles)
        self.assertEqual([entry.owner for entry in live._plugin_controls.entries], ['demo', 'next'])
        self.assertEqual(old_control.stops, 1)

    def test_destroyed_tile_unregisters_with_a_retained_python_wrapper(self):
        self.register()
        tile = self.tile({'room_id': '12'})
        self.tiles.remove(tile)
        control = self.controls[0]
        tile.close()
        tile.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(shiboken6.isValid(tile))
        self.register('next')
        self.assertNotIn(tile, self.manager._tiles)
        self.assertEqual(control.stops, 1)

    def test_no_extension_layout_is_preserved(self):
        tile = self.tile({'room_id': '12'})
        tile.resize(360, 240)
        APP.processEvents()
        self.assertTrue(tile.volume_slider.isHidden())
        self.assertFalse(tile.danmaku_settings_button.isHidden())
        self.assertLess(tile.fullscreen_button.geometry().right(), tile.width())

    def test_priority_overflow_recovers_on_widening(self):
        self.register('low', priority=0)
        self.register('high', priority=100)
        tile = self.tile({'room_id': '12'})
        tile.resize(480, 260)
        APP.processEvents()
        entries = tile._plugin_controls.entries
        self.assertEqual(entries[0].owner, 'high')
        self.assertFalse(entries[0].wrapper.isHidden())
        self.assertTrue(entries[1].wrapper.isHidden())
        tile.resize(900, 400)
        APP.processEvents()
        self.assertTrue(all(not e.wrapper.isHidden() for e in entries))
        self.assertEqual([e.wrapper.width() for e in entries], [240, 165])
        tile.set_room({'room_id': 'demo:12'})
        tile.resize(950, 400)
        APP.processEvents()
        self.assertTrue(all(e.control.widget.isHidden() for e in entries))

    def test_compact_controls_fit_200_360_900(self):
        self.register()
        tile = self.tile({'room_id': '12'})
        for width in (200, 360, 900, 1600):
            tile.resize(width, 260)
            APP.processEvents()
            control = self.controls[0].widget
            self.assertEqual(control.parentWidget().isVisible(), width >= 360)
            if width >= 900:
                self.assertGreaterEqual(control.width(), 90)
            self.assertTrue(tile.volume_button.isVisible())
            self.assertTrue(tile.fullscreen_button.isVisible())
            self.assertLess(tile.fullscreen_button.geometry().right(), width)
            self.assertTrue(tile.recording_button.isVisible())
            if control.parentWidget().isVisible():
                self.assertTrue(tile.bottom.rect().contains(tile._plugin_controls.widget.geometry()))

    def test_single_control_is_centered_bounded_and_stable_on_hover(self):
        self.register()
        tile = self.tile({'room_id': '12'})
        for width, cap in ((900, 405), (1600, 520)):
            tile.resize(width, 400)
            tile.set_status('Short')
            APP.processEvents()
            region = tile._plugin_controls.widget
            self.assertEqual(region.width(), cap)
            self.assertLessEqual(abs(region.geometry().center().x() - tile.bottom.width() / 2), 2)
            geometry = region.geometry()
            editor = self.controls[0].widget
            editor.setFocus()
            editor.setText('draft')
            APP.processEvents()
            focused = editor.hasFocus()
            for _ in range(5):
                tile.set_controls_visible(True)
                tile._layout_areas()
                APP.processEvents()
                self.assertEqual(region.geometry(), geometry)
                self.assertEqual(editor.hasFocus(), focused)
                self.assertEqual(editor.text(), 'draft')

    def test_layout_recovers_after_unsupported_room_and_recording_changes(self):
        self.register()
        tile = self.tile({'room_id': '12'})
        tile.resize(900, 400)
        APP.processEvents()
        region = tile._plugin_controls.widget
        tile.set_room({'room_id': 'other:12'})
        APP.processEvents()
        self.assertFalse(region.isVisible())
        tile.set_room({'room_id': '13'})
        APP.processEvents()
        self.assertTrue(region.isVisible())
        tile.set_recording_state('record')
        tile.set_recording_elapsed('123:45:56')
        APP.processEvents()
        self.assertLess(region.geometry().right(), tile.danmaku_button.x())
        self.assertTrue(tile.bottom.rect().contains(region.geometry()))
        tile.set_recording_elapsed('')
        APP.processEvents()
        self.assertEqual(region.width(), 405)

    def test_removed_callback_is_inert_and_shutdown_once(self):
        self.register()
        tile = self.tile({'room_id': '12'})
        control = self.controls[0]
        invalidate = control.ctx.invalidate_layout
        self.manager.detach_tile(tile)
        tile.set_room({'room_id': 'replacement'})
        invalidate()
        self.manager.unload()
        self.assertEqual(control.stops, 1)
        self.assertEqual(control.rooms, [{'room_id': '12'}])

    def test_detach_restores_ordinary_bar_without_a_resize(self):
        tile = self.tile({'room_id': '12'})
        tile.resize(900, 400)
        APP.processEvents()
        original = tile.fullscreen_button.geometry()
        self.register()
        APP.processEvents()
        self.manager.detach_tile(tile)
        APP.processEvents()
        self.assertEqual(tile.bottom.layout().stretch(
            tile.bottom.layout().indexOf(tile.status_label)), 1)
        self.assertEqual(tile.fullscreen_button.geometry(), original)

    def test_failed_factory_does_not_leave_a_region_or_block_next_provider(self):
        def bad(ctx):
            QLineEdit(ctx.parent)
            raise ValueError('intentional factory failure')
        self.manager.register_tile_control('bad', 'broken', bad)
        self.register('good')
        tile = self.tile({'room_id': '12'})
        tile.resize(900, 400)
        APP.processEvents()
        self.assertEqual([e.owner for e in tile._plugin_controls.entries], ['good'])
        self.assertTrue(self.controls[0].widget.isVisible())


if __name__ == '__main__':
    unittest.main()
