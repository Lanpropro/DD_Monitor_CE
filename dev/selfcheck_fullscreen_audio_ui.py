"""离线 Qt/VLC 集成：真实按钮、快捷键、格子信号及播放器音频状态。

check_window 也可在便携版进程内调用，以验证冻结程序的兼容性。
不会播放直播或写入用户配置。
"""
import os
from pathlib import Path
import sys

os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from ddm.player import TilePlayer


def check_window(window):
    tiles = window.wall.tiles
    assert len(tiles) >= 3
    assert any(p.context.name == "fullscreen_audio" for p in window.plugins.plugins)
    window._hold_fullscreen_frame = lambda: None
    for index, tile in enumerate(tiles):
        tile.set_room({"room_id": str(9000 + index), "uname": f"test {index}",
                       "live": False, "muted": False, "volume": 35})
        window.players[tile] = TilePlayer(tile.video, window)
        # 正常播放时由 play() 安装回调；这里不取流，只启用同一音频路径。
        window.players[tile]._enable_pcm_routing()
        tile.set_volume(35)
        tile.set_muted(False)
    order = list(tiles)
    layout = window.wall.layout_id

    def verify(target):
        assert window._fullscreen_tile is target
        for tile in tiles:
            expected = tile is not target
            assert tile.muted == expected
            assert tile.room["muted"] == expected
            assert tile.volume_button.muted == expected
            player = window.players[tile]
            assert player.muted == expected, "Qt signal must reach the owning player"
            assert player._audio_output.enabled == (not expected)
            assert player.volume == tile.volume

    def key(code):
        QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, code, Qt.NoModifier))

    tiles[1].set_muted(True)
    tiles[1].fullscreen_button.click()
    verify(tiles[1])
    assert all(tile.isHidden() for tile in tiles if tile is not tiles[1])
    key(Qt.Key_Escape)
    assert window._fullscreen_tile is None
    assert window.wall.tiles == order and window.wall.layout_id == layout
    assert [t.muted for t in tiles] == [t is not tiles[1] for t in tiles]

    # 固定鼠标命中结果，验证 F 的分发而不移动用户的真实鼠标。
    window._tile_under_cursor = lambda: tiles[2]
    key(Qt.Key_F)
    verify(tiles[2])
    key(Qt.Key_F)
    assert window._fullscreen_tile is None

    # 右键全屏菜单发出同一个信号；音量 0 时也必须打开声音。
    tiles[0].set_volume(0)
    tiles[0].set_muted(True)
    window.settings["default_volume"] = 57
    tiles[0].fullscreenRequested.emit(tiles[0])
    verify(tiles[0])
    assert tiles[0].volume == 57
    assert window.players[tiles[0]]._audio_output.volume == 57
    key(Qt.Key_Escape)
    assert window._fullscreen_tile is None
    assert window.wall.tiles == order and window.wall.layout_id == layout
    return "PASS: button, F, Esc, menu signal, hidden tiles, Qt/VLC audio, zero volume"


def main():
    from unittest.mock import patch
    from ddm.app import MainWindow

    app = QApplication.instance() or QApplication([])
    with patch.object(MainWindow, "start_all", lambda self: None), \
            patch.object(MainWindow, "refresh_status", lambda self: None), \
            patch.object(MainWindow, "refresh_stats", lambda self: None):
        window = MainWindow([], [], layout_id="corner",
                            state={"plugins_enabled": ["fullscreen_audio"]})
        window.resize(1400, 900)
        window.show()
        try:
            print(check_window(window))
        finally:
            window.close()
    app.quit()


if __name__ == "__main__":
    main()
