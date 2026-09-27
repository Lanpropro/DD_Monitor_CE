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

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from ddm.player import TilePlayer
from ddm import plugins as api


def check_window(window):
    tiles = window.wall.tiles
    assert len(tiles) >= 3
    assert any(p.context.name == "fullscreen_audio" for p in window.plugins.plugins)
    window._hold_fullscreen_frame = lambda: None

    def edit_setting(enabled, save=True, reset=False, capture=False):
        errors = []

        def edit():
            dialog = QApplication.activeModalWidget()
            try:
                page = dialog.general_page
                box = page._checks["fullscreen_audio_focus"]
                assert box.isChecked() == bool(window.settings.get("fullscreen_audio_focus", True))
                box.setChecked(enabled)
                if reset:
                    page.reset()
                    assert box.isChecked()
                if capture:
                    assert box.isVisible()
                    assert dialog.grab().save(str(Path(api.REPO) / "settings-preview.png"))
                if save:
                    dialog.accept()
                else:
                    dialog.reject()
            except Exception as error:
                errors.append(error)
                if dialog is not None:
                    dialog.reject()

        QTimer.singleShot(0, edit)
        accepted = window.open_settings()
        assert not errors, errors
        assert accepted == save

    edit_setting(False, save=False)
    assert window.settings.get("fullscreen_audio_focus", True)
    edit_setting(False)
    assert window.current_state()["settings"]["fullscreen_audio_focus"] is False

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

    # 保存关闭后，进出全屏不改变任何格子的声音。
    tiles[1].set_muted(True)
    before = [(t.muted, t.volume) for t in tiles]
    tiles[1].fullscreen_button.click()
    assert [(t.muted, t.volume) for t in tiles] == before
    window._exit_fullscreen()
    assert [(t.muted, t.volume) for t in tiles] == before
    # 重开设置可读回关闭状态；恢复默认并保存后重新启用。
    edit_setting(False, reset=True, capture=True)
    assert window.settings["fullscreen_audio_focus"] is True

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
    assert [(t.muted, t.volume) for t in tiles] == before
    for tile, (muted, volume) in zip(tiles, before):
        assert window.players[tile].muted == muted
        assert window.players[tile].volume == volume

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
    tiles[0].set_volume(80)
    tiles[2].set_volume(12)
    key(Qt.Key_Escape)
    assert window._fullscreen_tile is None
    assert tiles[0].volume == 0 and tiles[0].muted is True
    assert tiles[2].volume == 35
    assert window.players[tiles[0]].volume == 0
    assert window.wall.tiles == order and window.wall.layout_id == layout
    return "PASS: settings save/cancel/reset/reopen, disabled mode, button/F/Esc/menu, audio restore"


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
