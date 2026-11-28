"""Numeric motion capture must not touch render-thread nodes or message data."""
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from ddm.danmaku_diagnostics import _LayeredPaintTrace, _QuickCadence
from ddm.danmaku_float_window import DanmakuFloatWindow
from ddm.video_danmaku import VideoDanmaku
from ddm.video_danmaku_quick import QuickDanmakuLayer
from ddm.danmaku_diagnostics import MotionTrace
from dev.match_gui_dispatch import install as install_match_gui_dispatch
from dev.match_quick_trial import install_plugin_source


class MotionDiagnosticsTests(unittest.TestCase):
    def test_match_source_override_leaves_other_plugins_on_their_normal_paths(self):
        class Manager:
            def _load_module(self, name, path):
                return name, path

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'plugin.py'
            source.touch()
            install_plugin_source(Manager, source)
            manager = Manager()
            self.assertEqual(manager._load_module('match_sync', 'installed.py'), ('match_sync', str(source)))
            self.assertEqual(manager._load_module('other', 'other.py'), ('other', 'other.py'))

    def test_native_raster_trial_uses_configured_motion_interval(self):
        app = QApplication.instance() or QApplication([])
        overlay = VideoDanmaku()
        try:
            with patch.dict(os.environ, DDM_QTQUICK_DANMAKU='1'), \
                    patch.object(overlay, '_native_layered', return_value=True):
                overlay.set_native_video(True, allow_quick=False)
                overlay.set_raster_frame_interval(16)
                self.assertTrue(overlay.native_video)
                self.assertFalse(overlay._quick_requested)
                self.assertEqual(overlay._motion_interval(), 16)
                overlay.set_native_video(True)
                self.assertTrue(overlay._quick_requested)
        finally:
            overlay.close()
            overlay.deleteLater()
            app.processEvents()

    def test_main_update_separates_first_paint_canvas_and_tail(self):
        class Application:
            @staticmethod
            def instance():
                return None

            def notify(self, _receiver, event):
                return event.dispatch()

        class MainWindow:
            pass

        class Canvas:
            paint_probe = None

        class Timeline:
            now = 0

            def __init__(self):
                self.events = []

            def begin(self):
                return self.now, self.now

            def end(self, label, start, value=None):
                self.events.append((label, start[0], self.now, value))

        module = SimpleNamespace(QApplication=Application)
        with patch.dict(os.environ, DDM_MATCH_GUI_DISPATCH='0'):
            install_match_gui_dispatch(module)
            self.assertIs(module.QApplication, Application)
        install_match_gui_dispatch(module)
        app = module.QApplication()
        timeline = app.match_gui_timeline = Timeline()

        def notify(receiver, kind, dispatch):
            return app.notify(receiver, SimpleNamespace(type=lambda: kind, dispatch=dispatch))

        def advance(step):
            timeline.now += step
            return True

        def update():
            advance(3)
            notify(Canvas(), QEvent.Paint, lambda: advance(4))
            advance(2)
            main = Canvas()
            main.paint_probe = object()
            notify(main, QEvent.Paint, lambda: advance(1))
            notify(object(), QEvent.Paint, lambda: advance(2))
            return advance(5)

        self.assertTrue(notify(MainWindow(), QEvent.UpdateRequest, update))
        self.assertIsNone(app._match_window_update)
        events = {label: (start, end) for label, start, end, _value in timeline.events}
        self.assertEqual(events['qt.main_update_before_first_paint'], (0, 3))
        self.assertEqual(events['qt.main_update_before_canvas_paint'], (0, 9))
        self.assertEqual(events['qt.main_update_after_last_paint'], (12, 17))
        timeline.events.clear()
        notify(MainWindow(), QEvent.UpdateRequest, lambda: advance(1))
        self.assertFalse(any(label.startswith('qt.main_update_') for label, *_rest in timeline.events))

    def test_quick_swap_timestamps_are_batched_separately_from_raster_paints(self):
        class Window(QObject):
            frameSwapped = Signal()

            def isExposed(self):
                return True

            def winId(self):
                return 123

            def devicePixelRatio(self):
                return 1.25

        overlay = Mock(comments=[object()])
        overlay.y.return_value = 10
        overlay.height.return_value = 900
        overlay.lane_height.return_value = 30
        overlay.lane_count.return_value = 12
        layer = SimpleNamespace(window=Window(), _active_groups={1},
                                parent=SimpleNamespace(video_danmaku=overlay))
        emit = Mock()
        cadence = _QuickCadence(layer, emit)
        with patch('ddm.danmaku_diagnostics.time.perf_counter', side_effect=[1, 1.020, 1.100, 2]):
            layer.window.frameSwapped.emit()
            layer.window.frameSwapped.emit()
            layer.window.frameSwapped.emit()
            emit.assert_not_called()
            cadence.sample()
            cadence.stop()
            layer.window.frameSwapped.emit()
        stage, = emit.call_args.args
        row = emit.call_args.kwargs
        self.assertEqual(stage, 'quick-cadence')
        self.assertEqual((row['swaps'], row['over_50_ms'], row['over_100_ms']), (3, 1, 0))
        self.assertEqual(row['gap_count'], 2)
        self.assertEqual(row['scroll_bottom'], 370)
        self.assertEqual(row['swap_gap_ms']['max'], 80)
        self.assertEqual(len(cadence.timestamps), 0)
        with patch.dict(os.environ, DDM_MATCH_DESKTOP_CADENCE='1'):
            desktop = _QuickCadence(layer, emit)
            layer.window.frameSwapped.emit()
            desktop.sample()
            self.assertIsNone(desktop.connection)
            self.assertEqual(len(desktop.timestamps), 0)
            self.assertEqual(emit.call_args.args, ('quick-window-state',))
            self.assertNotIn('swaps', emit.call_args.kwargs)
            desktop.stop()

    def test_match_arrivals_check_projected_lane_without_an_extra_tick(self):
        app = QApplication.instance() or QApplication([])
        overlay = VideoDanmaku()
        try:
            overlay.set_native_video(False)
            overlay.raster_control.enable_motion_coalescing()
            overlay.resize(400, 200)
            overlay.active = overlay.enabled = True
            overlay._last_tick = 10.
            item = SimpleNamespace(lane=0, held=False, right=377., speed=100., motion_speed=100.)
            overlay.comments.append(item)
            self.assertFalse(overlay._lane_available(0, 0))
            with patch.object(overlay, 'isVisible', return_value=True), \
                    patch.object(overlay, 'lane_count', return_value=1), \
                    patch.object(overlay.timer, 'isActive', return_value=True), \
                    patch.object(overlay, '_tick') as tick, \
                    patch('ddm.video_danmaku.perf_counter', return_value=10.014):
                self.assertTrue(overlay.add_event({'text': 'fixture'}))
                tick.assert_not_called()
                self.assertEqual(len(overlay._pending_comments), 1)
                self.assertEqual(item.right, 377.)
                image = QImage(16, 8, QImage.Format_ARGB32)
                image.fill(Qt.white)
                self.assertTrue(overlay._admit_comment(image, (), 'fixture', Qt.white, [], False, {}))
                self.assertEqual(overlay.comments[-1].x, 400.)
        finally:
            overlay._comment_resize_timer.stop()
            overlay.comments.clear()
            overlay.close()
            overlay.deleteLater()
            app.processEvents()

    def test_match_raster_update_joins_video_or_flushes_on_timeout(self):
        app = QApplication.instance() or QApplication([])
        overlay = VideoDanmaku()
        try:
            overlay.set_native_video(False)
            raster = overlay.raster_control
            first, second = QRect(0, 0, 40, 20), QRect(0, 0, 40, 35)
            with patch.object(overlay, 'update') as update:
                raster.queue_motion_update(first)
                update.assert_called_once_with(first)
                update.reset_mock()
                join = raster.enable_motion_coalescing()
                raster.queue_motion_update(first)
                raster.queue_motion_update(second)
                update.assert_not_called()
                join()
                update.assert_called_once_with(second)
                QTest.qWait(25)
                self.assertEqual(update.call_count, 1)
                self.assertEqual(raster.joined_motion_updates, 1)
                update.reset_mock()
                raster.queue_motion_update(first)
                QTest.qWait(25)
                update.assert_called_once_with(first)
                self.assertEqual(raster.standalone_motion_updates, 1)
        finally:
            overlay.close()
            overlay.deleteLater()
            app.processEvents()

    def test_float_group_emits_one_summary_per_drag(self):
        emit = Mock()
        trace = MotionTrace('unused.jsonl', emit=emit)
        floating = Mock(_move_followers={object(): QPoint()}, property=Mock(return_value=True))
        with patch.object(QuickDanmakuLayer, '__init__'), patch.object(QuickDanmakuLayer, 'move'), \
                patch.object(trace, 'install_raster'), \
                patch.object(DanmakuFloatWindow, '_move_group') as move, \
                patch.object(DanmakuFloatWindow, '_finish_move') as finish:
            trace.install()
            DanmakuFloatWindow._move_group(floating, QPoint(10, 2))
            DanmakuFloatWindow._move_group(floating, QPoint(11, 3))
            emit.assert_not_called()
            DanmakuFloatWindow._finish_move(floating)
            self.assertEqual(move.call_count, 2)
            finish.assert_called_once_with(floating)
        emit.assert_called_once()
        self.assertEqual(emit.call_args.args, ('float-group-move',))
        row = emit.call_args.kwargs
        self.assertEqual((row['windows'], row['pointerUpdates'], row['glass']), (2, 2, True))
        self.assertGreaterEqual(row['maxMoveMs'], 0)

    def test_raster_tick_and_paint_are_counted_independently(self):
        emit = Mock()
        trace = MotionTrace('unused.jsonl', emit=emit)
        overlay = Mock(native_video=False, _quick_requested=False, _last_tick=9.984,
                       comments=[Mock(message='private')])
        overlay.timer.interval.return_value = 4
        overlay.timer.isActive.return_value = True
        clock = Mock(return_value=10)
        with patch('ddm.danmaku_diagnostics.time.perf_counter', clock), \
                patch.object(VideoDanmaku, '_tick'), patch.object(VideoDanmaku, 'paintEvent'), \
                patch.object(VideoDanmaku, 'set_native_video', VideoDanmaku.set_native_video), \
                patch.object(VideoDanmaku, '_stop_timer'):
            trace.install_raster()
            VideoDanmaku._tick(overlay)
            for offset in (.020, .050):
                clock.return_value = 10 + offset
                VideoDanmaku.paintEvent(overlay, object())
            VideoDanmaku._stop_timer(overlay)
            clock.return_value = 10.9
            VideoDanmaku.paintEvent(overlay, object())
            clock.return_value = 11.02
            overlay._last_tick = 11
            VideoDanmaku._tick(overlay)
        emit.assert_called_once()
        stage, = emit.call_args.args
        row = emit.call_args.kwargs
        self.assertEqual(stage, 'raster-cadence')
        self.assertEqual((row['ticks'], row['paints']), (2, 3))
        self.assertEqual(row['paint_gap_ms']['max'], 30)
        self.assertEqual(row['tick_gap_ms']['max'], 20)
        self.assertNotIn('private', str(row))

    def test_layered_upload_completion_and_fallback_have_separate_counts(self):
        emit = Mock()
        trace = MotionTrace('unused.jsonl', emit=emit)
        layer = _LayeredPaintTrace(trace, object())
        clock = Mock(return_value=10)
        with patch('ddm.danmaku_diagnostics.time.perf_counter', clock):
            for offset in (0, .020):
                clock.return_value = 10 + offset
                layer.queue()
                clock.return_value += .002
                self.assertIs(layer.begin(), layer)
                layer.set_size(400, 300, 1.25)
                for name in ('image_prepare_ms', 'draw_ms', 'dib_prepare_ms', 'copy_ms', 'upload_ms'):
                    clock.return_value += .001
                    layer.mark(name)
                clock.return_value += .001
                layer.finish(True, False, 12)
            clock.return_value += .010
            layer.begin()
            layer.finish(False, True, 13)
        emit.assert_called_once()
        self.assertEqual(emit.call_args.args, ('layered-cadence',))
        row = emit.call_args.kwargs
        self.assertEqual((row['attempts'], row['uploads'], row['fallbacks']), (3, 2, 1))
        self.assertEqual((row['comments_min'], row['comments_max']), (12, 13))
        self.assertEqual(row['sizes'], [(400, 300, 1.25)])
        self.assertEqual(row['queue_ms']['max'], 2)
        self.assertEqual(row['upload_ms']['max'], 1)
        self.assertEqual(row['refresh_gap_ms']['max'], 20)
        self.assertEqual(row['total_ms']['max'], 6)

    def test_layered_pixel_copy_preserves_premultiplied_alpha_and_clears(self):
        app = QApplication.instance() or QApplication([])
        overlay = VideoDanmaku()
        image = QImage(3, 2, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        image.setPixelColor(1, 0, QColor(90, 140, 230, 127))
        image.setPixelColor(2, 1, QColor(20, 45, 70, 255))
        destination = ctypes.create_string_buffer(image.sizeInBytes())
        try:
            overlay._copy_layered_pixels(image, destination)
            self.assertEqual(destination.raw, bytes(image.constBits()))
            image.fill(Qt.transparent)
            overlay._copy_layered_pixels(image, destination)
            self.assertEqual(destination.raw, bytes(image.sizeInBytes()))
        finally:
            overlay.deleteLater()
            app.processEvents()

    def test_live_layer_sampling_is_bounded_and_preserves_items(self):
        app = QApplication.instance() or QApplication([])
        if app.platformName() != 'windows':
            self.skipTest('Native Quick window requires Windows')
        import PySide6
        qt_dir = Path(PySide6.__file__).parent
        with os.add_dll_directory(str(qt_dir)):
            ctypes.WinDLL(str(qt_dir / 'Qt6QuickEffects.dll'))
        with tempfile.TemporaryDirectory() as directory:
            parent = QWidget()
            parent.setAttribute(Qt.WA_ShowWithoutActivating)
            parent.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
            parent.setGeometry(-14000, -14000, 800, 500)
            parent.show()
            parent.winId()
            layer = QuickDanmakuLayer(parent)
            trace = MotionTrace(Path(directory) / 'motion.jsonl')
            trace.LIMIT = 10
            group = layer.create_group(0, 0, 800, 500)
            image = QImage(100, 30, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.white)
            identifier = layer.add(group, image, 600, 30, 100, 30, 80)
            item = layer.items[identifier]['item']
            children = list(item.childItems())
            trace.attach(layer)
            try:
                QTest.qWait(150)
                layer.set_group_active(group, False)
                layer.window.hide()
                QTest.qWait(150)
                layer.set_group_active(group, True)
                layer.show()
                QTest.qWait(150)
                self.assertEqual(item.childItems(), children, 'No render-thread probes may be attached')
                self.assertEqual(set(layer.items), {identifier})
                self.assertIs(layer.items[identifier]['item'], item)
                timer = layer.findChildren(QTimer)[-1]
                for _ in range(30):
                    timer.timeout.emit()
                rows = [json.loads(line) for line in trace.path.read_text().splitlines()]
                self.assertEqual(len(rows), trace.LIMIT)
                self.assertTrue(any(row['stage'] == 'sample' for row in rows))
                self.assertTrue(all(row['session'] == trace.session for row in rows))
                self.assertFalse(timer.isActive())
                for row in rows:
                    self.assertFalse({'text', 'message', 'cookie', 'frames'} & row.keys())
                trace.arm()
                self.assertTrue(timer.isActive(), 'A later user marker must restart bounded sampling')
                for _ in range(30):
                    timer.timeout.emit()
                self.assertFalse(timer.isActive())
                self.assertEqual(len(trace.path.read_text().splitlines()), trace.LIMIT * 2)
            finally:
                layer.remove_group(group)
                layer.window.hide()
                parent.close()
                layer.window.destroy()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
