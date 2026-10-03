"""真实直播预览验收：横屏封面、竖屏简洁卡片和头像浮层，静音及进程清理。"""
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(REPO / "libvlc.dll"))
import vlc  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import bili, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def wait_for(app, predicate, seconds=40):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError("Live preview timed out")


def stats(player):
    result = vlc.MediaStats()
    media = player.player.get_media()
    if media is not None:
        media.get_stats(result)
    return result


def relay_stopped(relay):
    assert relay._process is not None and relay._process.poll() is not None
    assert not relay._thread.is_alive()


def main():
    room_id = sys.argv[1]
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    state = {"plugins_enabled": ["domestic_live", "global_live"], "settings": {"preview_on_hover": True,
             "recording_enabled": False, "recording_replay_enabled": False, "auto_quality": False}}
    with patch("ddm.app.QTimer.singleShot"):
        window = MainWindow([], [], state=state, layout_id="2x2")
    window.resize(1200, 700)
    window.show()
    window._poll_timer.stop()
    window._stats_timer.stop()
    output = REPO / "work" / (room_id.split(":", 1)[0] + "-preview-live")
    output.mkdir(parents=True, exist_ok=True)
    try:
        platform = window.plugins.platform_for(room_id)
        room = platform.room_info(room_id).as_dict()
        assert room["live"], "验收需要正在直播的房间"
        room["quality"] = 10000  # 主格手选固定档，独立验收悬停不触发重取流
        window.sidebar.add_room(room)
        item = window.sidebar.items()[0]
        hp = window.hover_preview
        # 用悬停入口驱动真实计时；避免用户鼠标或其他验收窗口干扰连续播放。
        window.sidebar.previewHovered.disconnect(hp.on_hover)
        window.sidebar.previewUnhovered.disconnect(hp.on_unhover)
        hp._cursor_on_item = lambda _item: True
        wall_starts = []
        original_start = window.start_tile
        def tracked_start(*args, **kwargs):
            wall_starts.append(time.monotonic())
            return original_start(*args, **kwargs)
        window.start_tile = tracked_start
        tile = window.wall.tiles[0]
        tile.set_room(dict(room))
        tile.set_muted(True)
        window.start_tile(tile)
        wait_for(app, lambda: tile in window.players and stats(window.players[tile]).displayed_pictures > 30)
        wall_player = window.players[tile]
        wall_relay = wall_player._relay
        wall_starts[:] = [time.monotonic()]  # 连续播放从首帧验收开始；起播时的网络重试单独处理。
        with patch.object(bili, "play_url", side_effect=AssertionError("Plugin preview called Bili")):
            for mode, width, height, card, collapsed in (
                    ("landscape-card", 1200, 700, True, False),
                    ("portrait-card", 520, 850, True, False),
                    ("portrait-list", 520, 850, False, False),
                    ("portrait-avatars", 520, 850, True, True)):
                hp.cancel()
                window.resize(width, height)
                app.processEvents()
                window.sidebar.set_card_mode(card)
                window.sidebar.set_collapsed(collapsed, animate=False)
                layout_deadline = time.monotonic() + .4
                while time.monotonic() < layout_deadline:
                    app.processEvents()
                    time.sleep(.02)
                hp.on_hover(item.room)             # 保留真实 1 秒悬停计时
                popup = collapsed or not card
                def current_player():
                    return hp._popup_player if popup else item.thumb._player
                wait_for(app, lambda: current_player() is not None and
                         current_player()._relay is not None and
                         stats(current_player()).displayed_pictures > 30)
                player = current_player()
                relay = player._relay
                target = hp._popup_video if popup else item.thumb.video
                assert player.player.get_hwnd() == int(target.winId())
                assert player.silent and player.muted and player.volume == 0
                assert not player._audio_output.enabled and player._audio_output._stream is None
                if popup:
                    assert hp._popup.isVisible() and window.rect().contains(hp._popup.geometry())
                    assert not item.thumb.video.isVisible()
                deadline = time.monotonic() + duration
                wall_before = stats(wall_player).displayed_pictures
                while time.monotonic() < deadline:
                    before = stats(player).displayed_pictures
                    wait_for(app, lambda: stats(player).displayed_pictures > before + 10, 15)
                    assert player._relay is relay and relay._process.poll() is None
                    if collapsed:
                        window.sidebar.resort(animate=False)
                        assert hp._popup.isVisible(), "Status refresh must keep avatar preview"
                result = stats(player)
                assert stats(wall_player).displayed_pictures > wall_before + 30
                assert len(wall_starts) == 1 and wall_player._relay is wall_relay, "Preview must not refresh wall"
                window.raise_()
                app.processEvents()
                bounds = window.frameGeometry()
                app.primaryScreen().grabWindow(0, bounds.x(), bounds.y(), bounds.width(), bounds.height()).save(
                    str(output / (mode + ".png")))
                print(f"PASS: {room_id} {mode}, displayed={result.displayed_pictures}, "
                      f"audio={result.decoded_audio}, {duration}s continuous, native handle, silent", flush=True)
                if mode == "portrait-avatars":
                    window.plugins.enabled = set()
                    window._sync_platform_rooms()
                    assert not window.sidebar.rooms() and not hp._popup.isVisible()
                    assert window.current_state()["suspended_platform_rooms"]
                    relay_stopped(wall_relay)
                elif mode == "landscape-card":
                    window.resize(520, 850)
                    app.processEvents()
                    assert hp._item is None, "Rotation must stop active preview"
                else:
                    hp.on_unhover(item.room)
                    wait_for(app, lambda: hp._item is None)
                relay_stopped(relay)
                print("PASS: wall keeps playing without refresh; leave/rotate/disable cleans up preview", flush=True)
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()
