"""离线回归：取流失败后重试，恢复、关闭和下播时取消重试。"""
import os
import sys
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.app import MainWindow  # noqa: E402


def main():
    app = QApplication(sys.argv)
    room = {"room_id": "1001", "uname": "retry-test", "live": True,
            "quality": 250, "muted": True, "volume": 42}
    with patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), \
            patch.object(MainWindow, "refresh_stats"), \
            patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "load_avatars_for"):
        window = MainWindow([dict(room)], [dict(room)], layout_id="1x1",
                            state={"settings": {"preview_on_hover": False}})
        try:
            tile = window.wall.tiles[0]
            window._on_resolve_failed(tile, "CDN unavailable", requested_quality=250)
            assert tile in window._retry_timers, "首次取流失败后必须继续尝试连接"
            first = window._retry_timers[tile]
            assert first.isActive()
            window._on_resolve_failed(tile, "CDN unavailable", requested_quality=250)
            assert not first.isActive(), "重复失败不能留下多个重连定时器"
            window._on_player_state(tile, "playing")
            assert tile not in window._retry_timers
            window._on_resolve_failed(tile, "stale result", requested_quality=10000)
            assert tile not in window._retry_timers, "旧画质请求失败不能干扰新流"
            window._on_resolve_failed(tile, "CDN unavailable", requested_quality=250)
            window._offline_tile(tile)
            assert tile not in window._retry_timers, "下播后不能继续重连"
            tile.room["live"] = True
            window._on_resolve_failed(tile, "CDN unavailable", requested_quality=250)
            tile.closeRequested.emit(tile.room)
            assert tile not in window._retry_timers, "关闭格子后不能继续重连"
            window._closing = True
            window._on_resolve_failed(tile, "late result", requested_quality=250)
            assert tile not in window._retry_timers
        finally:
            window._closing = False
            window.close()
            app.processEvents()
        rooms = [dict(room, room_id=str(1001 + i)) for i in range(6)]
        window = MainWindow(rooms, [dict(item) for item in rooms], layout_id="3x2",
                            state={"settings": {"preview_on_hover": False}})
        try:
            window.setGeometry(-9000, -9000, 1200, 800)
            window.show()
            app.processEvents()
            retry_tile, resolving_tile = window.wall.tiles[4:6]
            window._on_resolve_failed(retry_tile, "CDN unavailable", requested_quality=250)
            resolver = Mock()
            window._resolvers[resolving_tile] = resolver
            window._on_layout_changed("2x2")
            assert retry_tile not in window._retry_timers, "隐藏格子即使没有播放器也要取消重连"
            assert resolving_tile not in window._resolvers
            resolver.cancel.assert_called_once()
        finally:
            window.close()
            app.processEvents()
    print("取流失败重试及恢复/下播/关闭清理：通过", flush=True)


if __name__ == "__main__":
    main()
