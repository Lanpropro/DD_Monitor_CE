"""Compare rendered scene-graph motion during a GUI stall, entirely off-screen.

Samples native transform nodes, not QML x (which XAnimator updates only at its end).
This does not measure final desktop presentation or live-stream performance.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtQuick import QQuickItem, QSGNode
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from ddm import config
from ddm.video_danmaku import VideoDanmaku
from ddm.video_danmaku_quick import QuickDanmakuLayer


class MotionProbe(QQuickItem):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFlag(QQuickItem.ItemHasContents)
        self.setWidth(1)
        self.setHeight(1)
        self.node = None

    def updatePaintNode(self, old_node, data):
        self.node = old_node or QSGNode()
        return self.node

    def scene_x(self):
        node, x = self.node, 0.0
        if node is None or not isValid(node):
            return None
        while node is not None:
            matrix = node.matrix() if hasattr(node, "matrix") else None
            if matrix is not None:
                x += matrix.column(3).x()
            node = node.parent()
        return x


def settle(app, seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(.002)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("animator", "timer"), default="animator")
    parser.add_argument("--unthrottled", action="store_true",
                        help="Disable swap throttling to verify wall-clock animation speed")
    args = parser.parse_args()
    os.environ["DDM_QTQUICK_DANMAKU"] = "1"
    os.environ["DDM_QTQUICK_ANIMATOR"] = "0" if args.backend == "timer" else "1"
    app = QApplication([])
    if app.platformName() != "windows":
        print("SKIP: Windows native scene graph required")
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x4000)  # Below normal.
    parent = QWidget()
    parent.setAttribute(Qt.WA_NativeWindow)
    parent.setAttribute(Qt.WA_ShowWithoutActivating)
    parent.setGeometry(-20000, -20000, 400, 180)
    overlay = VideoDanmaku(parent)
    overlay.setGeometry(parent.rect())
    overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False,
                                video_danmaku_size=28, video_danmaku_area=100))
    parent.show()
    overlay.set_enabled(True)
    overlay.set_active(True)
    layer = QuickDanmakuLayer(parent)
    if args.unthrottled:
        surface = layer.window.format()
        surface.setSwapInterval(0)
        layer.window.setFormat(surface)
    overlay.attach_quick_layer(layer)
    layer.show()
    assert overlay.add_event({"text": "render thread motion"})
    assert overlay.add_event({"text": "second lane"})
    comment = overlay.comments[0]
    overlay.set_paused(True)
    comment.x, comment.speed = 280, 100
    layer.move(comment.render_id, comment.x, 40, comment.speed)
    probe = MotionProbe(layer.items[comment.render_id]["item"])
    samples = []
    ui_thread = threading.get_ident()

    def sample():
        x = probe.scene_x()
        if x is not None:
            samples.append((time.perf_counter(), x, threading.get_ident()))

    layer.window.afterRendering.connect(sample, Qt.DirectConnection)
    try:
        overlay.set_paused(False)
        settle(app, .08)  # Let initial scene-graph synchronization finish before measuring.
        samples.clear()
        settle(app, .25)
        assert samples and layer.window.isExposed()
        initial = list(samples)
        elapsed = initial[-1][0] - initial[0][0]
        measured_speed = (initial[0][1] - initial[-1][1]) / elapsed
        assert .8 < measured_speed / comment.speed < 1.2, \
            ("render animation must follow elapsed time", measured_speed, comment.speed)
        assert parent.geometry().right() < 0, "Test window must remain off-screen"
        before = samples[-1][1]
        samples.clear()
        started = time.perf_counter()
        time.sleep(.35)  # Deliberately stop all GUI event processing.
        blocked = time.perf_counter() - started
        stalled_samples = list(samples)
        after = stalled_samples[-1][1] if stalled_samples else before
        distance = before - after
        unique = len({round(frame[1], 2) for frame in stalled_samples})
        if args.backend == "animator":
            assert unique >= 3 and distance > 20, (unique, distance)
            assert all(frame[2] != ui_thread for frame in stalled_samples)
            assert overlay.timer.interval() == 50
            with patch.object(layer, "move", wraps=layer.move) as move:
                settle(app, .15)
                assert move.call_count == 0, "Housekeeping must not drive visual positions"
        else:
            assert distance < 2, "Timer baseline should reproduce the blocked motion"

        overlay.set_paused(True)
        settle(app, .08)
        overlay.apply_settings(dict(overlay.settings, video_danmaku_area=30))
        assert len(overlay.comments) == 1, "Area change should prune the second lane"
        assert overlay._quick_group not in layer._active_groups
        settle(app, .03)
        paused_x = comment.x
        paused_scene_x = samples[-1][1]
        samples.clear()
        layer.window.update()
        settle(app, .08)
        assert comment.x == paused_x and not overlay.timer.isActive()
        assert samples and abs(samples[-1][1] - paused_scene_x) < 1, \
            (len(samples), samples[-1][1] if samples else None, paused_scene_x, comment.x)
        if args.backend == "animator":
            assert layer.items[comment.render_id]["item"].property("motionPaused")
        overlay.apply_settings(dict(overlay.settings, video_danmaku_speed=200))
        overlay.set_paused(False)
        samples.clear()
        settle(app, .2)
        if args.backend == "animator":
            movement = samples[0][1] - samples[-1][1]
            duration = samples[-1][0] - samples[0][0]
            assert .6 < movement / duration / comment.speed < 1.4
        overlay.clear()
        settle(app, .1)
        samples.clear()
        settle(app, .2)
        assert not samples, "Empty scene must stop continuously rendering"
        print(json.dumps({"backend": args.backend, "blocked_gui_ms": round(blocked * 1000),
                          "unthrottled": args.unthrottled,
                          "measured_speed_px_s": round(measured_speed, 2),
                          "configured_speed_px_s": 100,
                          "render_frames_during_block": len(stalled_samples),
                          "unique_scene_positions": unique,
                          "distance_during_block_px": round(distance, 2),
                          "expected_distance_px": round(100 * blocked, 2),
                          "measurement": "off-screen scene graph; not DWM presentation"}))
    finally:
        layer.window.afterRendering.disconnect(sample)
        layer.window.hide()
        overlay.clear()
        parent.close()
        app.processEvents()


if __name__ == "__main__":
    main()
