"""横竖屏切换只进行一次最终墙面布局，保留原生窗口和正在播放的媒体。"""
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import theme
from ddm.app import MainWindow
from ddm.player import TilePlayer


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": str(9000 + i), "uname": "测试", "live": False} for i in range(16)]
    with patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow(rooms, rooms, layout_id="4x4", state={"plugins_enabled": []})
        window.resize(1400, 800)
        window.show()
        app.processEvents()
        media = Path("logs/control-edge-test.mp4").resolve()
        assert media.is_file(), "Local VLC test video is required"
        players = {}
        for tile in window.wall.tiles[:6]:
            player = TilePlayer(tile.video, window)
            player.set_muted(True)
            player.play(str(media))
            players[tile] = player
        window.players.update(players)
        QTest.qWait(1000)
        hwnds = {tile: int(tile.video.winId()) for tile in players}
        timings = []
        try:
            for size in ((700, 1600), (1400, 800), (700, 1600), (1400, 800)):
                with patch.object(window.wall, "relayout", wraps=window.wall.relayout) as layout:
                    before = time.perf_counter()
                    window.resize(*size)
                    app.processEvents()
                    elapsed = (time.perf_counter() - before) * 1000
                    calls = layout.call_count
                timings.append({"size": size, "ms": round(elapsed, 1), "layouts": calls})
                print(timings[-1], flush=True)
                assert window.orientation == ("portrait" if size[0] < size[1] else "landscape")
                assert calls <= 1, "方向切换不应反复清空、重新插入原生视频格子"
                app.processEvents()
                assert window.players == players
                assert all(int(tile.video.winId()) == hwnds[tile] for tile in players)
                assert all(not player._released for player in players.values())
                QTest.qWait(100)
            assert all(player._picture_signature()[1] > 0 for player in players.values())
        finally:
            window.close()
        print("PASS: one final orientation layout, native HWNDs and six real VLC players preserved")


if __name__ == "__main__":
    main()
