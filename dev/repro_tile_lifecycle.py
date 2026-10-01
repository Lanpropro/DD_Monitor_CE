"""遍历格子创建/填入/复用路径，验证一次操作只处理一次。不联网。

--expect-baseline 用于修复前版本的故障基线；默认检查修复后的行为。
"""
import json
import os
import sys
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.app import MainWindow  # noqa: E402


def room(index):
    return {"room_id": str(index), "uname": f"repro{index}", "live": True,
            "quality": 250, "muted": True, "volume": 42}


class SpyPlayer:
    volume = 42
    paused = False
    pause_calls = 0

    def set_volume(self, value):
        self.volume = value

    def set_paused(self, value):
        self.paused = value
        self.pause_calls += 1

    def release(self):
        pass


CASES = [
    # 名称、初始播放数、初始布局、预期操作处理次数（当前未修复实现）
    ("boot_five", 5, "3x2", 1),
    ("boot_six", 6, "3x2", 1),
    ("boot_nine", 9, "3x3", 1),
    ("fill_add", 4, "3x2", 2),
    ("fill_drag", 4, "3x2", 1),
    ("expand_add", 4, "2x2", 1),
    ("expand_drag", 4, "2x2", 0),
    ("expand_swap", 4, "2x2", 0),
    ("expand_ninth", 4, "2x2", 0),
    ("expand_dialog", 4, "2x2", 1),
    ("close_add", 5, "3x2", 2),
    ("close_drag", 5, "3x2", 1),
    ("reuse_add_twice", 4, "3x2", 3),
    ("replace_drag", 5, "3x2", 1),
    ("shrink_expand", 5, "3x2", 1),
    ("portrait_expand", 4, "2x2", 0),
    ("fullscreen_return", 5, "3x2", 1),
]


def main():
    app = QApplication(sys.argv)
    expect_fixed = "--expect-baseline" not in sys.argv
    results = []
    with patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), \
            patch.object(MainWindow, "refresh_stats"), \
            patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "load_avatars_for"):
        for case, count, layout, expected in CASES:
            if expect_fixed:
                expected = 1
            window = MainWindow([room(i) for i in range(1, 10)],
                                [room(i) for i in range(1, count + 1)], layout_id=layout,
                                state={"settings": {"auto_quality": False,
                                                    "preview_on_hover": False}})
            try:
                if case.startswith("expand_"):
                    window._on_layout_changed("3x3" if case == "expand_ninth" else "3x2")
                if case == "portrait_expand":
                    window._on_layout_changed("portrait_main6")
                target = window.wall.tiles[8 if case == "expand_ninth" else 4]
                if case in ("fill_add", "expand_add", "reuse_add_twice"):
                    window.add_to_wall(room(5))
                    if case == "reuse_add_twice":
                        target.closeRequested.emit(target.room)
                        window.add_to_wall(room(5))
                elif case in ("fill_drag", "expand_drag", "expand_ninth", "portrait_expand"):
                    window._on_room_dropped(target, str(9 if case == "expand_ninth" else 5))
                elif case == "expand_swap":
                    window._on_tile_swapped("1", target)
                elif case == "expand_dialog":
                    window._on_room_added(room(5))
                elif case in ("close_add", "close_drag"):
                    target.closeRequested.emit(target.room)
                    if case == "close_add":
                        window.add_to_wall(room(5))
                    else:
                        window._on_room_dropped(target, "5")
                elif case == "replace_drag":
                    window._on_room_dropped(target, "7")
                elif case == "shrink_expand":
                    window._on_layout_changed("2x2")
                    window._on_layout_changed("3x2")
                elif case == "fullscreen_return":
                    window.wall.set_fullscreen_tile(target)
                    window.wall.set_fullscreen_tile(None)
                player = SpyPlayer()
                window.players[target] = player
                with patch.object(window, "start_tile") as start:
                    target.set_quality(10000)
                    quality_count = start.call_count
                    start.reset_mock()
                    target.reloadRequested.emit(target.room)
                    reload_count = start.call_count
                QTest.mouseClick(target.pause_button, Qt.LeftButton)
                target.volume_slider.setValue(65)
                menu = target.build_menu()
                with patch.object(window, "start_tile") as start:
                    quality_menu = next(a.menu() for a in menu.actions() if a.text() == "画质")
                    next(a for a in quality_menu.actions() if a.text() == "流畅").trigger()
                    menu_count = start.call_count
                next(a for a in menu.actions() if a.text() == "关闭这一路").trigger()
                closed = not target.room.get("room_id") and target not in window.players
                result = {"case": case, "quality_calls": quality_count,
                          "reload_calls": reload_count, "context_quality_calls": menu_count,
                          "pause_calls": player.pause_calls, "paused": player.paused,
                          "volume": player.volume, "closed": closed}
                assert quality_count == reload_count == menu_count == player.pause_calls == expected
                assert player.paused == bool(expected % 2)
                assert player.volume == (65 if expected else 42)
                assert closed == bool(expected)
                results.append(result)
                print("RESULT", json.dumps(result), flush=True)
            finally:
                window.close()
                window.deleteLater()
                app.processEvents()
    print("Lifecycle reproduction checks passed:", len(results), flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
