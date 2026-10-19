"""Compare raster and opt-in Qt Quick danmaku cadence and process CPU time.

Qt paint/frame callbacks measure submitted rendering work, not final DWM presentation.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--backend", choices=("raster", "quick"), required=True)
parser.add_argument("--seconds", type=float, default=4)
args = parser.parse_args()
if not 2 <= args.seconds <= 6:
    parser.error("--seconds must be between 2 and 6")

os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ["DDM_QTQUICK_DANMAKU"] = "1" if args.backend == "quick" else "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ddm import config, theme
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from ddm.video_danmaku import VideoDanmaku
from selfcheck_video_danmaku import Client


def stats(frames):
    intervals = sorted((b - a) / 1e6 for a, b in zip(frames, frames[1:]))
    if not intervals:
        return {"frames": len(frames), "p50_ms": None, "p95_ms": None, "max_ms": None}
    return {
        "frames": len(frames),
        "p50_ms": round(statistics.median(intervals), 3),
        "p95_ms": round(intervals[min(len(intervals) - 1, int(len(intervals) * .95))], 3),
        "max_ms": round(max(intervals), 3),
    }


def main():
    app = QApplication(sys.argv)
    if app.platformName() != "windows":
        print(json.dumps({"skipped": "Windows native window backend required"}))
        return
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": str(1000 + i), "uname": f"本地视频 {i}", "live": True}
             for i in range(4)]
    paint_frames = {}
    original_paint = VideoDanmaku.paintEvent

    def record_paint(overlay, event):
        paint_frames.setdefault(overlay, []).append(time.perf_counter_ns())
        original_paint(overlay, event)

    with tempfile.TemporaryDirectory(prefix="ddm-video-dm-benchmark-") as temp, \
            patch("ddm.app.DanmakuClient", Client), patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch.object(VideoDanmaku, "paintEvent", record_paint):
        source = str(Path(temp) / "blue.mp4")
        subprocess.run([ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30",
                        "-t", "30", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", source], check=True)
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="2x2",
                            state={"plugins_enabled": []})
        window.setGeometry(40, 60, 1200, 800)
        window.show()
        window.activateWindow()
        try:
            for tile in window.wall.tiles:
                player = TilePlayer(tile.video, tile, silent=True)
                window.players[tile] = player
                player.play(source)
                tile.set_video_active(True)
                tile.danmaku_button.setChecked(True)
                tile.video_danmaku.apply_settings(dict(config.DEFAULT_SETTINGS,
                                                       video_danmaku_scale=False,
                                                       video_danmaku_size=24,
                                                       video_danmaku_area=100))
                for index in range(8):
                    assert tile.video_danmaku.add_event({"text": f"弹幕渲染节奏与资源测试 {index}"})

            settle_end = time.monotonic() + 2
            while time.monotonic() < settle_end:
                app.processEvents()
                time.sleep(.005)
            if args.backend == "quick":
                layer = window.wall._quick_danmaku_layer
                if layer is None:
                    raise RuntimeError("Qt Quick shared layer did not initialize")
                frames = []
                layer.window.frameSwapped.connect(lambda: frames.append(time.perf_counter_ns()))
                graphics_api = layer.window.rendererInterface().graphicsApi().name
            else:
                paint_frames.clear()
                frames = None
                graphics_api = None

            wall_start = time.monotonic()
            cpu_start = time.process_time()
            QTimer.singleShot(round(args.seconds * 1000), app.quit)
            app.exec()
            wall_seconds = time.monotonic() - wall_start
            cpu_seconds = time.process_time() - cpu_start
            if args.backend == "quick":
                cadence = {"shared_window": stats(frames)}
            else:
                cadence = {f"tile_{index}": stats(paint_frames.get(tile.video_danmaku, []))
                           for index, tile in enumerate(window.wall.tiles)}
            print(json.dumps({
                "backend": args.backend,
                "graphics_api": graphics_api,
                "screen_hz": round(window.wall.tiles[0].screen().refreshRate()),
                "wall_seconds": round(wall_seconds, 3),
                "process_cpu_seconds": round(cpu_seconds, 3),
                "process_cpu_percent_one_core": round(cpu_seconds / wall_seconds * 100, 1),
                "cadence": cadence,
                "measurement": "Qt paintEvent/frameSwapped callbacks; not final DWM presentation",
            }, ensure_ascii=False, indent=2))
        finally:
            window.close()


if __name__ == "__main__":
    main()
