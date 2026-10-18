"""Off-screen public live video + real danmaku comparison, without user credentials.

Uses the normal MainWindow message handler and libmpv player. Only aggregate
counts/scene coordinates are reported; no chat content, usernames or stream URLs.
Requires network access and a currently live, publicly accessible Bilibili room.
"""
import argparse
import ctypes
from contextlib import nullcontext
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ddm import bili, config, theme
from ddm.app import MainWindow
from ddm.danmaku import _Client
from ddm.player import TilePlayer
from selfcheck_danmaku_render_thread import MotionProbe, settle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", required=True)
    parser.add_argument("--backend", choices=("animator", "timer", "timer-legacy"), required=True)
    args = parser.parse_args()
    os.environ["DDM_QTQUICK_DANMAKU"] = "1"
    os.environ["DDM_QTQUICK_ANIMATOR"] = "1" if args.backend == "animator" else "0"
    assert not bili.SESSION_DATA, "Live test must not use account credentials"
    url, quality, profile, headers = bili.play_url(args.room, 80)
    app = QApplication([])
    assert app.platformName() == "windows"
    app.setStyleSheet(theme.qss())
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x4000)
    room = {"room_id": args.room, "uname": "公开直播测试", "live": True}
    wire_commands = {}
    original_command = _Client._handle_command

    def receive_command(client, command):
        name = str(command.get("cmd", "")).split(":", 1)[0]
        wire_commands[name] = wire_commands.get(name, 0) + 1
        original_command(client, command)

    with patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch.object(_Client, "_handle_command", receive_command), \
            (patch("ddm.video_danmaku.perf_counter", time.monotonic)
             if args.backend == "timer-legacy" else nullcontext()):
        window = MainWindow([room], [dict(room)], layout_id="1x1",
                            state={"plugins_enabled": [], "settings": dict(config.DEFAULT_SETTINGS)})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.setGeometry(-20000, -20000, 1000, 700)
        window.show()
        tile = window.wall.tiles[0]
        overlay = tile.video_danmaku
        overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False,
                                    video_danmaku_size=28, video_danmaku_area=100))
        counts = {"messages": 0, "accepted": 0}
        original_add = overlay.add_event

        def receive(event):
            counts["messages"] += (event.get("kind") or "danmaku") == "danmaku"
            accepted = original_add(event)
            counts["accepted"] += bool(accepted)
            return accepted

        overlay.add_event = receive
        player = TilePlayer(tile.video, tile)
        player.muted, player.volume = True, 0
        window.players[tile] = player
        frames, probe, layer = [], None, None
        ui_thread = threading.get_ident()

        def sample():
            x = probe.scene_x()
            if x is not None:
                frames.append((time.perf_counter(), x, threading.get_ident()))

        try:
            player.play(url, profile, headers, options=("audio=no",))
            tile.set_video_active(True)
            tile.danmaku_button.setChecked(True)
            window.sync_danmaku()
            deadline = time.perf_counter() + 35
            comment = None
            while time.perf_counter() < deadline:
                settle(app, .05)
                comment = next((item for item in overlay.comments
                                if 100 < item.x < overlay.width() - 100), None)
                if comment is not None and float(player._prop("time-pos", 0) or 0) > 0:
                    break
            assert comment is not None and counts["accepted"], \
                (f"No real live comments received: status={window._danmaku_status} "
                 f"counts={counts} wire_commands={wire_commands}")
            assert float(player._prop("time-pos", 0) or 0) > 0, "Live video must be playing"
            layer = window.wall._quick_danmaku_layer
            probe = MotionProbe(layer.items[comment.render_id]["item"])
            layer.window.afterRendering.connect(sample, Qt.DirectConnection)
            cpu_start, started = time.process_time(), time.perf_counter()
            video_start = float(player._prop("time-pos", 0) or 0)
            settle(app, 3)
            assert frames, "Live comment must have rendered scene nodes"
            normal = list(frames)
            before = normal[-1][1]
            frames.clear()
            block_start = time.perf_counter()
            time.sleep(.35)
            blocked = time.perf_counter() - block_start
            stalled = list(frames)
            distance = before - (stalled[-1][1] if stalled else before)
            unique = len({round(frame[1], 2) for frame in stalled})
            if args.backend == "animator":
                assert unique >= 3 and distance > comment.speed * blocked * .5
                assert all(frame[2] != ui_thread for frame in stalled)
            else:
                assert distance < 2, "Timer baseline must reproduce stalled visual motion"
            settle(app, .2)
            assert float(player._prop("time-pos", 0) or 0) > video_start
            assert window.geometry().right() < 0, "Live test must stay off-screen"
            positions = []
            for frame in normal:
                if not positions or abs(frame[1] - positions[-1][1]) > .01:
                    positions.append(frame)
            intervals = sorted((b[0] - a[0]) * 1000
                               for a, b in zip(positions, positions[1:]))
            print(json.dumps({"room_id": args.room, "backend": args.backend,
                              "python_clock_resolution_ms": time.get_clock_info(
                                  "monotonic" if args.backend == "timer-legacy" else "perf_counter").resolution * 1000,
                              "quality": quality, "video_width": player._prop("width"),
                              "video_height": player._prop("height"),
                              "video_fps": player._prop("container-fps"),
                              "decoder": player._prop("hwdec-current"),
                              **counts,
                              "wire_commands": dict(wire_commands),
                              "normal_scene_updates": len(intervals),
                              "normal_scene_gap_p50_ms": round(statistics.median(intervals), 2) if intervals else None,
                              "normal_scene_gap_p95_ms": round(intervals[min(len(intervals) - 1,
                                                                            int(len(intervals) * .95))], 2) if intervals else None,
                              "blocked_gui_ms": round(blocked * 1000),
                              "unique_positions_during_block": unique,
                              "distance_during_block_px": round(distance, 2),
                              "expected_distance_px": round(comment.speed * blocked, 2),
                              "cpu_percent_one_core": round((time.process_time() - cpu_start) /
                                                             (time.perf_counter() - started) * 100, 1),
                              "measurement": "public live stream; off-screen scene graph, not DWM presentation"}), flush=True)
        finally:
            if layer is not None and probe is not None:
                layer.window.afterRendering.disconnect(sample)
            window.close()
            app.processEvents()
            app.aboutToQuit.emit()


if __name__ == "__main__":
    main()
