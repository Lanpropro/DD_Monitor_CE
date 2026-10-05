"""离线验证全屏最高画质、自动画质保留及迟到档位处理。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import bili
from ddm.app import MainWindow
from ddm.auto_quality import AUTO_QUALITY
from ddm.player import TilePlayer
from selfcheck_live_platforms import settle


BILI_OPTIONS = [{"qn": qn, "desc": label} for qn, label in
                ((25000, "2K 原画"), (10000, "原画"), (400, "蓝光"), (250, "720P"))]
GLOBAL_OPTIONS = [{"qn": AUTO_QUALITY, "desc": "自动"},
                  {"qn": 10000, "desc": "1080p60"},
                  {"qn": 5000001, "desc": "720p"}]


def check_resolver(app, state):
    room = {"room_id": "1000", "live": False, "quality": 250}
    def source(room_id, quality, **kwargs):
        return "https://cdn.test/live.flv", quality, "app", {}
    with patch("ddm.app.QTimer.singleShot"), patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch.object(MainWindow, "_grab_fullscreen_frame", return_value=None), \
            patch.object(bili, "play_url", side_effect=source) as get, \
            patch.object(bili, "room_quality_options", return_value=BILI_OPTIONS), \
            patch.object(TilePlayer, "play") as play:
        window = MainWindow([room], [dict(room)], layout_id="1x1", state=state)
        window.show()
        app.processEvents()
        tile = window.wall.tiles[0]
        try:
            for known in (True, False):
                window._stop_tile(tile)
                tile.set_room(dict(room, live=True))
                if known:
                    tile.set_quality_options(BILI_OPTIONS)
                get.reset_mock()
                play.reset_mock()
                window._on_fullscreen(tile)
                settle(app, lambda: tile.actual_quality == 25000 and tile not in window._resolvers)
                assert tile.quality == tile.actual_quality == 25000
                assert [call.args[1] for call in get.call_args_list] == ([25000] if known else [10000, 25000])
                assert play.call_count == 1
                assert window.current_state()["wall"][0]["quality"] == 25000
                window._exit_fullscreen()
                window._on_fullscreen(tile)
                assert get.call_count == (1 if known else 2), "最高档再次全屏不能重新取流"
                window._exit_fullscreen()
        finally:
            window.close()
            app.processEvents()
    print("PASS: real Qt resolver switches to the highest tier once and persists the selected quality")


def main():
    app = QApplication([])
    state = {"plugins_enabled": [], "settings": {"auto_quality": False,
             "recording_enabled": False, "recording_replay_enabled": False,
             "preview_on_hover": False, "danmaku_enabled": False}}
    rooms = [{"room_id": str(1000 + i), "live": False, "quality": 250}
             for i in range(4)]
    requests = []
    with patch("ddm.app.QTimer.singleShot"), patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch.object(MainWindow, "_grab_fullscreen_frame", return_value=None), \
            patch.object(MainWindow, "start_tile", side_effect=lambda tile:
                         requests.append((tile, tile.quality))), patch.object(TilePlayer, "play") as play:
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="2x2", state=state)
        window.resize(1200, 800)
        window.show()
        app.processEvents()
        target, other, *_ = window.wall.tiles
        target.room["live"] = True
        try:
            # 真正点击全屏按钮，只升级目标格子，并走现有 qualityChanged 取流/保存接线。
            target.set_quality_options(BILI_OPTIONS)
            QTest.mouseClick(target.fullscreen_button, Qt.LeftButton)
            app.processEvents()
            assert window._fullscreen_tile is target
            assert target.quality == target.room["quality"] == 25000
            assert requests == [(target, 25000)] and other.quality == 250
            assert window._save_timer.isActive()
            QTest.mouseClick(target.fullscreen_button, Qt.LeftButton)
            assert window._fullscreen_tile is None and target.quality == 25000
            assert requests == [(target, 25000)], "退出全屏不应重复取流"
            window._on_fullscreen(target)
            assert len(requests) == 1, "已是最高档时不能重连"
            window._exit_fullscreen()

            # 平台编号不是画质大小，跳过自动并沿用平台从高到低的顺序。
            target.set_room({"room_id": "twitch:test", "live": True, "quality": 5000001})
            target.set_quality_options(GLOBAL_OPTIONS)
            requests.clear()
            window._on_fullscreen(target)
            assert target.quality == 10000 and requests == [(target, 10000)]
            target.set_quality(5000001)
            assert target.quality == 5000001, "进入后仍可手动调整画质"
            window._exit_fullscreen()

            # 自动画质的选项、当前播放档和网络策略都原样保留。
            target.set_quality(AUTO_QUALITY)
            window._play_on(target, "https://cdn.test/auto.m3u8", 5000001, "twitch",
                            GLOBAL_OPTIONS, room_id="twitch:test", requested_quality=AUTO_QUALITY)
            player = window.players[target]
            controller = player.auto_quality
            assert controller is not None
            requests.clear()
            calls = play.call_count
            window._on_fullscreen(target)
            assert target.quality == AUTO_QUALITY and target.actual_quality == 5000001
            assert player.auto_quality is controller and play.call_count == calls and not requests
            window._exit_fullscreen()

            # 初次取流还没返回档位时，先请求最高可用，再按迟到的真实档位补升2K。
            target.set_room({"room_id": "1000", "live": True, "quality": 250})
            requests.clear()
            window._on_fullscreen(target)
            assert target.quality == 10000 and requests == [(target, 10000)]
            calls = play.call_count
            window._play_on(target, "https://cdn.test/old.flv", 250, "app", BILI_OPTIONS,
                            room_id="1000", requested_quality=250)
            assert not target.quality_options and play.call_count == calls, "旧低档回调不能覆盖新请求"
            window._play_on(target, "https://cdn.test/original.flv", 10000, "app", BILI_OPTIONS,
                            room_id="1000", requested_quality=10000)
            assert target.quality == 25000 and requests[-1] == (target, 25000)
            assert play.call_count == calls, "不能先播放较低档再补一次重连"
            window._play_on(target, "https://cdn.test/2k.flv", 25000, "app", BILI_OPTIONS,
                            room_id="1000", requested_quality=25000)
            assert target.actual_quality == 25000 and play.call_count == calls + 1
            window._exit_fullscreen()

            # 主动选低档/退出/切自动后，迟到的档位不能强制升级。
            for action in ("manual", "exit", "auto"):
                target.set_room({"room_id": "1000", "live": True, "quality": 250})
                window._on_fullscreen(target)
                if action == "manual":
                    target.set_quality(400)
                elif action == "exit":
                    window._exit_fullscreen()
                else:
                    target.set_quality(AUTO_QUALITY)
                requested = target.quality
                requests.clear()
                window._play_on(target, "https://cdn.test/chosen.flv", 400, "app", BILI_OPTIONS,
                                room_id="1000", requested_quality=requested)
                assert target.quality == requested and not requests, action
                window._exit_fullscreen()

            # 录制原画锁定不能因全屏被切断或改档。
            target.set_room({"room_id": "1000", "live": True, "quality": 10000})
            target.set_quality_options(BILI_OPTIONS)
            target.quality_locked = True
            window._capture_quality[target] = ("1000", 250)
            requests.clear()
            window._on_fullscreen(target)
            assert target.quality == 10000 and not requests
            window._exit_fullscreen()
            window._capture_quality.clear()
            target.quality_locked = False

            # 空格子、其他全屏格子正在播放时不能触发额外画质切换。
            other.set_quality_options(BILI_OPTIONS)
            window._on_fullscreen(target)
            requests.clear()
            window._on_fullscreen(other)
            assert window._fullscreen_tile is target and other.quality == 250 and not requests
            window._exit_fullscreen()
            other.set_room(None)
            window._on_fullscreen(other)
            assert window._fullscreen_tile is None and not requests
        finally:
            window._exit_fullscreen()
            window.close()
            app.processEvents()
    print("PASS: fullscreen highest platform tier, auto/controller unchanged, late tiers, manual override and recording lock")
    check_resolver(app, state)


if __name__ == "__main__":
    main()
