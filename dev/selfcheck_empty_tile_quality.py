"""关闭平台直播并重启后，空格子不能显示平台内部画质编号。仅使用替身数据。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from ddm import config
from ddm.app import MainWindow


def main():
    app = QApplication.instance() or QApplication([])
    state = {"plugins_enabled": [], "settings": {"auto_quality": False,
             "recording_enabled": False, "recording_replay_enabled": False,
             "danmaku_enabled": False, "preview_on_hover": False}}
    with patch("ddm.app.QTimer.singleShot"), patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch.object(MainWindow, "start_tile"):
        window = MainWindow([], [], layout_id="1x1", state=state)
        restored = None
        try:
            tile = window.wall.tiles[0]
            for kind, qn in (("huya", 1004000), ("douyu", 2000004), ("douyin", 3000001)):
                tile.set_room({"room_id": kind + ":123", "live": True, "quality": qn})
                tile.set_quality_options([{"qn": qn, "desc": "测试画质"}])
                tile.set_actual_quality(qn)
                assert tile.quality_button.text() == "测试画质"
                audio = (tile.volume, tile.muted, tile.audio_channel)
                tile.closeRequested.emit(tile.room)
                assert not tile.room.get("room_id")
                assert tile.quality == 250, (kind, tile.quality)
                assert tile.quality_button.text() == "超清 720P"
                assert tile.quality_button.toolTip() == "选择这一路的画质"
                assert not tile.quality_options and tile.actual_quality == 0
                assert (tile.volume, tile.muted, tile.audio_channel) == audio
                saved = window.current_state()
                assert saved["wall"][0]["quality"] == 250

            # 模拟旧版本已经保存的污染状态，不依赖修改用户配置。
            saved["wall"][0]["quality"] = 1004000
            sidebar, wall = config.build_rooms(saved)
            restored = MainWindow(sidebar, wall, layout_id="1x1", state=saved)
            empty = restored.wall.tiles[0]
            assert empty.quality == 250
            assert empty.quality_button.text() == "超清 720P"
            assert restored.current_state()["wall"][0]["quality"] == 250
            empty.set_room({"room_id": "huya:123", "live": True, "quality": 1004000})
            assert empty.quality == 1004000 and empty.quality_button.text() == "获取画质…"
            empty.set_quality_options([{"qn": 1004000, "desc": "蓝光4M"}])
            assert empty.quality_button.text() == "蓝光4M"
            empty.set_room({"room_id": "123", "quality": 80})
            assert empty.quality == 80 and "1004000" not in empty.quality_button.text()
        finally:
            if restored is not None:
                restored.close()
            window.close()
            app.processEvents()
    print("PASS: platform close/reset, audio preservation, state roundtrip, legacy empty slot, room quality retained")


if __name__ == "__main__":
    main()
