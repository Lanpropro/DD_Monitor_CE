"""真实播放器回归：播放中通过画质菜单切换手动/自动并验证持续解码。"""
import faulthandler
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(REPO / "libvlc.dll"))
from PySide6.QtCore import QTimer, Qt, qInstallMessageHandler  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402
from ddm import config, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.auto_quality import AUTO_QUALITY  # noqa: E402
from selfcheck_platform_preview_live import stats, wait_for, relay_stopped  # noqa: E402


def main():
    faulthandler.enable()
    qInstallMessageHandler(lambda kind, context, message: print("QT:", kind, message, flush=True))
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    state = {"plugins_enabled": ["global_live"], "settings": {"recording_enabled": False,
        "recording_replay_enabled": False, "preview_on_hover": False, "danmaku_enabled": False}}
    with patch("ddm.app.QTimer.singleShot"), patch.object(MainWindow, "sync_danmaku"):
        window = MainWindow([], [], state=state, layout_id="dm_main2")
    window.resize(1100, 700)
    window.show()
    window._poll_timer.stop()
    window._stats_timer.stop()
    window._audio_audit_timer.stop()
    try:
        rid = sys.argv[1] if len(sys.argv) > 1 else "youtube:@LofiGirl"
        room = window.plugins.platform_for(rid).room_info(rid).as_dict()
        assert room["live"], "The supplied room is offline"
        room["quality"] = 10000
        tile = window.wall.tiles[0]
        tile.set_room(room)
        tile.set_muted(False)
        window.start_tile(tile)
        wait_for(app, lambda: tile in window.players and window.players[tile].state == "playing"
                 and stats(window.players[tile]).displayed_pictures > 30, 70)
        player = window.players[tile]
        print("PASS: manual playback", player.player.video_get_size(0), flush=True)

        def choose(qn):
            def select():
                menu = app.activePopupWidget()
                assert isinstance(menu, QMenu)
                action = next(a for a in menu.actions() if a.text() == tile._quality_name(qn))
                menu.setActiveAction(action)
                QTest.keyClick(menu, Qt.Key_Return)
            tile.set_controls_visible(True)
            QTimer.singleShot(150, select)
            QTest.mouseClick(tile.quality_button, Qt.LeftButton)

        for index in range(4):
            media, relay = player._media, player._relay
            before = stats(player).displayed_pictures
            choose(AUTO_QUALITY)
            if "--expect-fixed" in sys.argv:
                assert player._media is media and player._relay is relay
                assert tile.actual_quality == player.actual_quality
            wait_for(app, lambda: tile not in window._resolvers and stats(player).displayed_pictures > 60, 70)
            print("PASS: automatic menu switch", index, tile._quality_text(), flush=True)
            if "--expect-fixed" in sys.argv:
                wait_for(app, lambda: stats(player).displayed_pictures > before + 60, 15)
                assert player._media is media and player._relay is relay
            choose(player.actual_quality)
            if "--expect-fixed" in sys.argv:
                assert player._media is media and player._relay is relay
            wait_for(app, lambda: tile not in window._resolvers and stats(player).displayed_pictures > 60, 70)
            assert player.auto_quality is None
            print("PASS: current tier manual switch", index, flush=True)
        choose(AUTO_QUALITY)
        if "--expect-fixed" in sys.argv:
            # 策略启用后仍要能换档：只替换网络测量，保留真实取流和 VLC 解码。
            player.auto_quality.last_switch = 0
            player.auto_quality.has_played = True
            with patch.object(player._relay._hls_proxy, "network_speed", return_value=(1, 6)):
                player._check_auto_quality()
            wait_for(app, lambda: tile.actual_quality != 10000 and tile not in window._resolvers
                     and player.state == "playing" and stats(player).displayed_pictures > 60, 70)
            assert tile.quality == AUTO_QUALITY
            print("PASS: automatic downshift after in-place enable", tile._quality_text(), flush=True)
            player.auto_quality.last_switch = 0
            player.auto_quality.stable_since = time.monotonic() - 40
            with patch.object(player._relay._hls_proxy, "network_speed", return_value=(100000000, 6)):
                player._check_auto_quality()
            wait_for(app, lambda: tile.actual_quality == 10000 and tile not in window._resolvers
                     and player.state == "playing" and stats(player).displayed_pictures > 60, 70)
            assert tile.quality == AUTO_QUALITY
            print("PASS: automatic upshift and native playback after in-place enable", flush=True)
        saved = window.current_state()
        _, slots = config.build_rooms(saved)
        assert slots[0]["quality"] == AUTO_QUALITY
        relay = player._relay
    finally:
        window.close()
        app.processEvents()
    relay_stopped(relay)
    print("PASS: menu switches, native playback, automatic persistence and cleanup", flush=True)


if __name__ == "__main__":
    main()
