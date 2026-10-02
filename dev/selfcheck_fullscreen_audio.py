"""全屏独占声音：恢复静音状态，保存配置不写入临时状态，开关可关闭。"""
import os
import sys
from unittest.mock import patch

os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QDialog
from ddm import app as app_module, config
from ddm.app import MainWindow
from ddm.dialogs import GeneralSettingsPage


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, *args):
        super().__init__(args[-1])

    def run(self):
        pass


class Player:
    def __init__(self, tile):
        self.muted = tile.muted

    def set_muted(self, muted):
        self.muted = muted

    def release(self):
        pass


def main():
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication([])
    page = GeneralSettingsPage({})
    assert config.DEFAULT_SETTINGS["fullscreen_solo_audio"] is True
    assert page.values()["fullscreen_solo_audio"] is True
    page._checks["fullscreen_solo_audio"].setChecked(False)
    assert GeneralSettingsPage(page.values()).values()["fullscreen_solo_audio"] is False
    page.reset()
    assert page.values()["fullscreen_solo_audio"] is True

    original = [False, True, False, True, False, True]
    rooms = [{"room_id": str(1000 + i), "live": False,
              "muted": muted, "volume": 20 + i, "audio_channel": i % 5}
             for i, muted in enumerate(original)]
    window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="corner",
                        state={"plugins_enabled": []})
    window.start_tile = lambda _tile: None
    window._grab_fullscreen_frame = lambda: None
    window.show()
    app.processEvents()
    tiles = list(window.wall.tiles)
    for tile in tiles:
        window.players[tile] = Player(tile)
    volumes = [tile.volume for tile in tiles]
    channels = [tile.audio_channel for tile in tiles]

    def check(expected):
        assert [tile.muted for tile in tiles] == expected
        assert [window.players[tile].muted for tile in tiles] == expected
        assert [tile.volume for tile in tiles] == volumes
        assert [tile.audio_channel for tile in tiles] == channels

    def set_switch(enabled):
        class Dialog:
            Accepted = QDialog.Accepted

            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                return self.Accepted

            def settings(self):
                return {"fullscreen_solo_audio": enabled}

            def shortcuts(self):
                return window.shortcuts

            def enabled_plugins(self):
                return []

        with patch.object(app_module, "SettingsDialog", Dialog):
            assert window.open_settings()

    try:
        window._on_fullscreen(tiles[1])
        check([True, False, True, True, True, True])
        assert [slot["muted"] for slot in window.current_state()["wall"]] == original
        window._sync_fullscreen_audio()  # 重复应用不能覆盖原快照。
        window._exit_fullscreen()
        check(original)

        set_switch(False)
        assert window.current_state()["settings"]["fullscreen_solo_audio"] is False
        window._on_fullscreen(tiles[3])
        check(original)
        set_switch(True)  # 在全屏中开启立即独占声音。
        check([True, True, True, False, True, True])
        set_switch(False)  # 在全屏中关闭立即恢复。
        check(original)
        window._exit_fullscreen()
        check(original)

        set_switch(True)
        window._on_fullscreen(tiles[5])
        check([True, True, True, True, True, False])
        # 全屏直接关闭程序时也应保存进入前的各路静音状态。
        with patch.object(config, "save") as save:
            window.close()
            assert [slot["muted"] for slot in save.call_args.args[0]["wall"]] == original
    finally:
        if not window._closing:
            window.close()
        page.close()
        app.processEvents()
    print("PASS: fullscreen solo audio, restore, settings toggle and persistence")


if __name__ == "__main__":
    main()
