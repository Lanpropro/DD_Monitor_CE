"""联网验收：直播卡片拖入 VLC 格子，解码画面/音频、静音、恢复配置。

运行：python dev/selfcheck_huya_live.py [房间号] [持续秒数]。只保存测试截图，不改用户配置。
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(REPO / "libvlc.dll"))

import vlc  # noqa: E402
from PySide6.QtCore import QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import config  # noqa: E402
from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import ROOM_MIME  # noqa: E402


def wait_for(app, predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("真实直播验收超时")


def stats(player):
    result = vlc.MediaStats()
    player.player.get_media().get_stats(result)
    return result


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else "660000"
    room_id = raw if ":" in raw else "huya:" + raw
    kind = room_id.split(":", 1)[0]
    label = {"huya": "虎牙", "douyu": "斗鱼", "douyin": "抖音", "twitch": "Twitch", "youtube": "YouTube"}[kind]
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    state = {"plugins_enabled": ["huya_watch", "global_live"], "settings": {
        "recording_enabled": False, "recording_replay_enabled": False,
        "preview_on_hover": False, "freeze_watch": True, "auto_quality": False}}
    with patch("ddm.app.QTimer.singleShot"):
        window = MainWindow([], [], state=state, layout_id="1x2")
    window.resize(1280, 720)
    window.show()
    output = REPO / "work" / (kind + "-live")
    output.mkdir(parents=True, exist_ok=True)
    try:
        # 暂停添加后自动上墙，用真实拖放事件从关注卡片开始播放。
        with patch.object(window, "add_to_wall"), patch("ddm.app.QMessageBox.warning", return_value=0):
            window._add_room_id(room_id)
            wait_for(app, lambda: bool(window.sidebar.rooms()))
        item = window.sidebar.items()[0]
        assert item.room["live"], "验收需要正在直播的房间"
        item.room["quality"] = 10000  # 自动调档另有自检；这里验收固定档连续播放
        wait_for(app, lambda: item.thumb._face_source is not None and item.thumb._cover_source is not None)
        assert not item.thumb._face_source.isNull() and not item.thumb._cover_source.isNull()
        assert item.platform_badge.text() == "" and item.platform_badge.toolTip() == label
        assert not item.platform_badge.pixmap().isNull()
        assert item.platform_badge.isHidden(), "单平台关注栏不显示平台图标"
        target = window.wall.tiles[1]
        mime = QMimeData()
        mime.setData(ROOM_MIME, room_id.encode())
        event = QDropEvent(QPointF(50, 50), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        started = []
        original_start = window.start_tile
        def tracked_start(*args, **kwargs):
            started.append(time.monotonic())
            return original_start(*args, **kwargs)
        window.start_tile = tracked_start
        target.dropEvent(event)
        assert event.isAccepted()
        wait_for(app, lambda: target in window.players and
                 stats(window.players[target]).decoded_video > 30)
        player = window.players[target]
        wait_for(app, lambda: stats(player).decoded_audio > 10)
        first = stats(player).decoded_video
        assert player.player.get_hwnd() == int(target.video.winId()), "必须绑定软件格子的原生窗口"
        target.set_volume(42)
        target.set_muted(False)
        # 本体使用每格 PCM 输出，VLC 原生音量值不能代表实际音量。
        wait_for(app, lambda: player._audio_output.enabled and
                 player._audio_output._stream is not None and player._audio_output._stream.active)
        assert player._audio_output.volume == 42
        wait_for(app, lambda: stats(player).decoded_video > first + 60)
        target.set_muted(True)
        assert not player._audio_output.enabled
        result = stats(player)
        assert result.displayed_pictures > 30
        assert not target.stream_badge.viewers
        started[:] = [time.monotonic()]  # 首帧及音频就绪后开始连续播放验收。
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            before = stats(player).displayed_pictures
            wait_for(app, lambda: stats(player).displayed_pictures > before,
                     seconds=20 if kind in ("twitch", "youtube") else 12)
            assert len(started) == 1, "持续播放期间不应自动刷新/重取流"
            time.sleep(0.1)
        result = stats(player)
        window.raise_()
        window.activateWindow()
        app.processEvents()
        bounds = window.frameGeometry()
        app.primaryScreen().grabWindow(0, bounds.x(), bounds.y(), bounds.width(), bounds.height()).save(
            str(output / "window.png"))
        print(f"PASS: {room_id}, video={result.decoded_video}, displayed={result.displayed_pictures}, "
              f"audio={result.decoded_audio}, {duration}s no refresh, avatars/covers/platform badge, "
              "native tile handle, volume/mute", flush=True)
        saved = window.current_state()
        relay = player._relay
    finally:
        window.close()
        app.processEvents()
    assert relay._process.poll() is not None and not relay._thread.is_alive(), "关闭后不能留下转封装进程"
    sidebar, wall = config.build_rooms(saved)
    with patch("ddm.app.QTimer.singleShot"):
        restored = MainWindow(sidebar, wall, state=saved, layout_id="1x2")
    restored.resize(1280, 720)
    restored.show()
    try:
        restored.start_all()
        tile = next(t for t in restored.wall.tiles if t.room.get("room_id") == room_id)
        wait_for(app, lambda: tile in restored.players and stats(restored.players[tile]).decoded_video > 30)
        assert restored.players[tile].muted
        print("PASS: restored follow card and wall slot resume real playback", flush=True)
        active_player = restored.players[tile]
        active_relay = active_player._relay
        restored.plugins.enabled = set()
        restored._sync_platform_rooms()
        assert not restored.sidebar.rooms() and not tile.room.get("room_id")
        assert active_player._released and active_relay._process.poll() is not None
        assert not active_relay._thread.is_alive()
        assert restored.current_state()["suspended_platform_rooms"][kind]["rooms"]
        print("PASS: disabling platform suspends rooms and stops real VLC/FFmpeg playback", flush=True)
    finally:
        restored.close()
        app.processEvents()


if __name__ == "__main__":
    main()
