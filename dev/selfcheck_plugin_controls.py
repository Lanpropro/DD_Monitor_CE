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
from PySide6.QtWidgets import QApplication, QLineEdit
from ddm import plugins as api
from ddm.widgets import Tile, WallGrid

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

    def test_existing_new_and_initially_empty_tiles_receive_one_control(self):
        first = self.tile()
        self.register()
        self.manager.attach_tile(first)
        second = self.tile({'room_id': '12'})
        self.assertEqual(len(self.controls), 2)
        first.set_room({'room_id': '11'})
        self.assertEqual(self.controls[0].rooms, [{}, {'room_id': '11'}])
        self.assertFalse(self.controls[0].widget.isHidden())

    def test_every_assignment_is_delivered_as_a_copy(self):
        self.register()
        tile = self.tile({'room_id': '12'})
        for room in (None, {'room_id': '12', 'title': 'new'}, {'room_id': '13'}, {'room_id': '12'}):
            tile.set_room(room)
            self.assertNotIn('mutated', tile.room)
            self.assertEqual(self.controls[0].rooms[-1].get('room_id'), (room or {}).get('room_id'))
            self.assertEqual(self.controls[0].ctx.room.get('room_id'), (room or {}).get('room_id'))
        self.assertEqual(len(self.controls), 1)

    def test_room_change_notifies_plugins_after_restoring_room_audio(self):
        tile = self.tile({'room_id': '12', 'volume': 17, 'muted': True})
        snapshots = []

        class Observer(api.TileControl):
            def __init__(self, context):
                super().__init__(QLineEdit(context.parent))

            def set_room(self, room):
                snapshots.append((room.get('room_id'), tile.volume, tile.muted))

        self.manager.register_tile_control('observer', 'audio', Observer)
        tile.set_room({'room_id': '13', 'volume': 0, 'muted': False})
        self.assertEqual(snapshots[-1], ('13', 0, False))
        self.assertEqual((tile.volume_slider.value(), tile.vertical_volume.value()), (0, 0))
        self.assertFalse(tile.volume_button.muted)

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
        tile.resize(400, 260)
        APP.processEvents()
        entries = tile._plugin_controls.entries
        self.assertEqual(entries[0].owner, 'high')
        self.assertFalse(entries[0].wrapper.isHidden())
        self.assertTrue(entries[1].wrapper.isHidden())
        # The compact volume icon frees enough room for both minima at 480px.
        tile.resize(480, 260)
        APP.processEvents()
        self.assertTrue(all(e.wrapper.isVisible() and e.wrapper.width() >= 90 for e in entries))
        tile.resize(900, 400)
        APP.processEvents()
        self.assertTrue(all(not e.wrapper.isHidden() for e in entries))
        self.assertEqual([e.wrapper.width() for e in entries], [240, 165])
        tile.set_room({'room_id': 'demo:12'})
        tile.resize(950, 400)
        APP.processEvents()
        self.assertTrue(all(e.control.widget.isHidden() for e in entries))

    def test_compact_controls_fit_200_320_360_900(self):
        self.register()
        tile = self.tile({'room_id': '12'})
        for width in (200, 320, 360, 900, 1600):
            tile.resize(width, 260)
            APP.processEvents()
            control = self.controls[0].widget
            self.assertEqual(control.parentWidget().isVisible(), width >= 360)
            if width >= 360:
                self.assertGreaterEqual(control.width(), 90)
            self.assertTrue(tile.volume_button.isVisible())
            self.assertTrue(tile.fullscreen_button.isVisible())
            self.assertLess(tile.fullscreen_button.geometry().right(), width)
            self.assertTrue(tile.recording_button.isVisible())
            if control.parentWidget().isVisible():
                region = tile._plugin_controls.widget.geometry()
                self.assertTrue(tile.bottom.rect().contains(region))
                self.assertGreater(region.left(), tile.volume_button.geometry().right())
                self.assertLess(region.right(), tile.danmaku_button.x())

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
