"""复现横屏六分布局：四路原画后加入第五路并切换原画。

参数：低清本地视频路径、原画本地视频路径、解码方式（默认 d3d11va）；
最后加 saved 可对比启动时已经存在五路原画的情况。
取流接口替换成本地文件，播放器、格子和操作接线保持本体实现。
"""
import json
import os
import sys
import time
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QMenu

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def room(index, quality=10000):
    return {"room_id": str(index), "uname": f"repro{index}", "live": True,
            "quality": quality, "muted": True, "volume": 42}


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Usage: repro_d3d_quality.py LOW_VIDEO ORIGINAL_VIDEO [DECODE_MODE]")
    low, original = (os.path.abspath(p) for p in sys.argv[1:3])
    assert os.path.isfile(low) and os.path.isfile(original)
    mode = sys.argv[3] if len(sys.argv) > 3 else "d3d11va"
    saved = len(sys.argv) > 4 and sys.argv[4] == "saved"
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    def settle(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def resolve(_room, quality=250, **_kwargs):
        return original if quality == 10000 else low, quality, "web", {}

    state = {"settings": {"decode_mode": mode, "auto_quality": False,
                          "preview_on_hover": False, "recording_enabled": False,
                          "recording_replay_enabled": False}}
    with patch.object(bili, "play_url", resolve), \
            patch.object(bili, "room_quality_options", return_value=[]), \
            patch.object(MainWindow, "refresh_status"), \
            patch.object(MainWindow, "refresh_stats"), \
            patch.object(MainWindow, "sync_danmaku"):
        window = MainWindow([room(i) for i in range(1, 7)],
                            [room(i) for i in range(1, 6 if saved else 5)],
                            layout_id="3x2", state=state)
        window.setGeometry(-9000, -9000, 1600, 900)
        window.show()
        settle(3)
        assert len(window.players) == (5 if saved else 4), "Initial players did not start"
        print("START", mode, "RESTORED" if saved else "ADDED", flush=True)
        target = window.wall.tiles[4]
        if not saved:
            window.add_to_wall(room(5, 250))
        settle(2)
        spy = QSignalSpy(target.qualityChanged)

        def snapshot(stage):
            states = [{"slot": index + 1, "state": player.state,
                       "time": player.player.get_time(),
                       "size": player.player.video_get_size(0),
                       "quality": tile.quality, "paused": tile.paused}
                      for index, tile in enumerate(window.wall.tiles)
                      if (player := window.players.get(tile)) is not None]
            print(stage, json.dumps(states), flush=True)

        class OriginalMenu(QMenu):
            def exec(self, _pos):
                next(a for a in self.actions() if a.text() == "原画").trigger()

        snapshot("BEFORE_QUALITY")
        target.set_controls_visible(True)
        with patch("ddm.widgets.QMenu", OriginalMenu), \
                patch.object(window, "start_tile", wraps=window.start_tile) as start:
            QTest.mouseClick(target.quality_button, Qt.LeftButton)
            print("QUALITY", "signals", spy.count(), "start_requests", start.call_count,
                  flush=True)
        settle(3)
        snapshot("AFTER_QUALITY")
        paused_before = target.paused
        QTest.mouseClick(target.pause_button, Qt.LeftButton)
        print("PAUSE", "before", paused_before, "after", target.paused, flush=True)
        target.volume_slider.setValue(65)
        print("VOLUME", target.volume, window.players[target].volume, flush=True)
        with patch.object(window, "start_tile", wraps=window.start_tile) as start:
            QTest.mouseClick(target.reload_button, Qt.LeftButton)
            print("RELOAD", "start_requests", start.call_count, flush=True)
        settle(2)
        snapshot("AFTER_RELOAD")
        QTest.mouseClick(target.close_button, Qt.LeftButton)
        print("CLOSE", "room", target.room.get("room_id"),
              "player_exists", target in window.players, flush=True)
        window.close()
        print("REPRO_END", flush=True)
        # 保留 Qt 局部对象到进程退出，避免诊断脚本在析构阶段干扰结果。
        os._exit(0)


if __name__ == "__main__":
    main()
