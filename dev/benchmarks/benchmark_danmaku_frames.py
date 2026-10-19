"""可见四格弹幕绘制间隔测量；--baseline 对照未申请 Windows 定时精度的行为。

测量 QWidget 绘制回调，不代表 DWM 最终呈现帧率。运行时保持窗口可见。
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DDM_NO_SAVE", "1")
from ddm.video_danmaku import VideoDanmaku, _TimerResolution


class Probe(VideoDanmaku):
    def __init__(self, parent):
        self.frames = []
        self.costs = []
        super().__init__(parent)

    def paintEvent(self, event):
        start = time.perf_counter()
        self.frames.append(start)
        super().paintEvent(event)
        self.costs.append((time.perf_counter() - start) * 1000)


def run(app, seconds):
    window = QWidget()
    window.setWindowTitle("弹幕帧间隔测量")
    window.resize(1200, 720)
    window.show()
    overlays = []
    for index in range(4):
        overlay = Probe(window)
        overlay.setGeometry(index % 2 * 600, index // 2 * 360, 600, 360)
        overlay.apply_settings({"video_danmaku_scale": False,
                                "video_danmaku_size": 24, "video_danmaku_area": 100})
        overlay.set_enabled(True)
        overlay.set_active(True)
        for lane in range(8):
            assert overlay.add_event({"text": f"滚动弹幕性能测量 {lane}"})
        overlays.append(overlay)
    QTimer.singleShot(round(seconds * 1000), app.quit)
    app.exec()
    results = []
    for overlay in overlays:
        intervals = sorted((b - a) * 1000 for a, b in zip(overlay.frames[3:], overlay.frames[4:]))
        if not intervals:
            raise RuntimeError("没有足够的可见绘制帧")
        results.append({"screen_hz": overlay.screen().refreshRate(),
                        "timer_ms": overlay.timer.interval(),
                        "paint_fps": round(1000 / statistics.mean(intervals), 1),
                        "interval_p50_ms": round(statistics.median(intervals), 2),
                        "interval_p95_ms": round(intervals[int(len(intervals) * .95)], 2),
                        "interval_max_ms": round(max(intervals), 2),
                        "paint_mean_ms": round(statistics.mean(overlay.costs), 3)})
    window.close()
    assert all(overlay._timer_resolution._winmm is None for overlay in overlays)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--seconds", type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 6:
        parser.error("--seconds must be between 1 and 6 (before comments leave the screen)")
    app = QApplication(sys.argv[:1])
    if args.baseline:
        with patch.object(_TimerResolution, "acquire"):
            results = run(app, args.seconds)
    else:
        results = run(app, args.seconds)
    print(json.dumps({"baseline": args.baseline, "tiles": results}, ensure_ascii=False, indent=2))
