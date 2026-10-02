"""虎牙离线自检：取流适配、真实拖入格子链路、持久化与旧卡片迁移。"""
import os
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from PySide6.QtCore import QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import bili, config, plugins  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import AddRoomDialog  # noqa: E402
from ddm.widgets import ROOM_MIME  # noqa: E402


def settle(app, condition):
    deadline = time.monotonic() + 4
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition(), "后台任务未按预期完成"


def main():
    app = QApplication.instance() or QApplication([])
    manager = plugins.PluginManager(enabled=["huya_watch"])
    manager.load()
    platform = manager.platforms["huya"]
    module = sys.modules[type(platform).__module__]
    for raw in ("huya:660000", "https://www.huya.com/660000",
                "https://m.huya.com/660000/?from=share", "http://huya.com/660000#share"):
        assert platform.matches(raw)
        assert platform.normalize(raw) == "huya:660000", raw
    assert platform.normalize("huya:godv") == "huya:godv"
    assert not platform.matches("660000"), "纯数字仍属于 B 站"
    for raw in ("huya:", "huya:../secret", "huya:a/b", "https://www.huya.com/%2Fsecret",
                "https://www.huya.com.evil.test/660000", "https://evil.test/660000",
                "https://user:pass@www.huya.com/660000", "https://www.huya.com:1234/660000"):
        try:
            platform.normalize(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(raw)
    print("PASS: canonical IDs and official URL validation")

    session = SimpleNamespace(http=Mock(headers={"User-Agent": "test-agent"}))
    parser = SimpleNamespace(author="测试虎牙主播", title="测试直播")
    streams = {"best": Mock(to_url=Mock(return_value="https://cdn.test/live.flv?token=test")),
               "tx_source": Mock(to_url=Mock(return_value="https://backup.test/live.flv"))}
    response = Mock(url="http://backup.test/live.flv")
    response.iter_content.return_value = iter([b"FLV"])
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    with patch.object(type(platform), "_streams", return_value=(session, parser, streams)):
        info = platform.room_info("huya:660000").as_dict()
        assert info["live"] and info["uname"] == parser.author
        with patch.object(module.requests, "get", side_effect=[
                module.requests.ConnectionError("first CDN failed"), response]) as get:
            url, qn, profile, headers = platform.play_url("huya:660000")
            assert (url, qn, profile) == (response.url, 10000, "huya")
            assert headers["Referer"] == "https://www.huya.com/"
            assert get.call_count == 2 and "cookies" not in get.call_args.kwargs
    with patch.object(type(platform), "_streams", return_value=(session, parser, {})):
        assert not platform.room_info("huya:660000").live
        try:
            platform.play_url("huya:660000")
        except RuntimeError:
            pass
        else:
            raise AssertionError("未开播不能生成播放地址")
    session.http.close.assert_called()
    resolver = bili.StreamResolver("huya:660000", platform=platform)
    resolved = []
    resolver.resolved.connect(lambda *args: resolved.append(args))
    with patch.object(platform, "play_url", return_value=(url, qn, profile, headers)), \
            patch.object(bili, "play_url", side_effect=AssertionError("误用 B 站")):
        resolver.run()
        assert resolved[0][1] == url and resolver.headers == headers
        resolved.clear()
        resolver.cancel()
        resolver.run()
        assert not resolved
    poller = bili.StatusPoller(["9001", "huya:660000"], platforms={"huya": platform})
    status = []
    poller.updated.connect(status.append)
    with patch.object(bili, "rooms_status", return_value={"9001": {}}) as bili_status, \
            patch.object(platform, "rooms_status", return_value={"huya:660000": info}):
        poller.run()
        bili_status.assert_called_once_with(["9001"])
        assert status[0]["huya:660000"]["live"]
    with patch.object(platform, "rooms_status", side_effect=RuntimeError("network")), \
            patch.object(bili, "rooms_status", return_value={"9001": {}}):
        status.clear()
        poller.run()
        assert "huya:660000" not in status[0], "网络错误不能标记下播"
    print("PASS: stream/CDN fallback, offline state, headers, cancellation, platform polling")

    state = {"plugins_enabled": ["huya_watch"], "settings": {
        "recording_enabled": False, "recording_replay_enabled": False, "preview_on_hover": False}}
    with patch("ddm.app.QTimer.singleShot"), \
            patch.object(bili, "room_info", side_effect=AssertionError("误用 B 站")), \
            patch.object(bili, "play_url", side_effect=AssertionError("误用 B 站")), \
            patch("ddm.app.webbrowser.open") as browser:
        window = MainWindow([], [], state=state, layout_id="1x2")
        hp = window.plugins.platforms["huya"]
        played = []
        def capture(tile, address, *_args, **kwargs):
            played.append((tile, address, kwargs["headers"]))
            tile.set_live(True)
        try:
            record = plugins.RoomInfo(room_id="huya:660000", uname=parser.author,
                title=parser.title, live=True, platform="huya",
                extra={"playback_mode": "stream", "live_known": True})
            with patch.object(hp, "room_info", return_value=record), \
                    patch.object(hp, "play_url", return_value=(url, qn, profile, headers)), \
                    patch.object(window, "_play_on", side_effect=capture), \
                    patch.object(window, "refresh_status"), patch.object(window, "refresh_stats"):
                def accept_huya(dialog):
                    dialog.edit.setText("https://www.huya.com/660000")
                    dialog.accept()
                    return dialog.result()
                with patch.object(AddRoomDialog, "exec", accept_huya):
                    window.open_add_room()
                settle(app, lambda: bool(played))
                window._add_room_id("huya:660000")
                assert len(window.sidebar.rooms()) == 1
                item = window.sidebar.items()[0]
                assert item.badge.text() == "直播中"
                assert "加入画面墙" in [a.text() for a in item._context_menu().actions()]
                item.clicked.emit(item.room)
                target = next(t for t in window.wall.tiles if not t.room.get("room_id"))
                before = len(played)
                mime = QMimeData()
                mime.setData(ROOM_MIME, b"huya:660000")
                event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                target.dropEvent(event)
                settle(app, lambda: len(played) > before)
                assert event.isAccepted() and played[-1][0] is target
                assert played[-1][1:] == (url, headers)
                browser.assert_not_called()
                window.start_danmaku("huya:660000")
                assert window._danmaku is None
                window.hover_preview.on_hover(item.room)
                assert window.hover_preview._resolver is None
                saved_state = window.current_state()
            with tempfile.TemporaryDirectory() as root, \
                    patch.object(config, "CONFIG_PATH", os.path.join(root, "config.json")), \
                    patch.dict(os.environ):
                os.environ.pop("DDM_NO_SAVE", None)
                config.save(saved_state)
                saved = config.load()
            sidebar, wall = config.build_rooms(saved)
            assert sidebar[0]["uname"] == parser.author
            assert sidebar[0]["playback_mode"] == "stream" and not sidebar[0]["live_known"]
            assert any(r.get("room_id") == "huya:660000" for r in wall)
            old = {"rooms": ["huya:660000"], "browser_rooms": {"huya:660000": {
                "platform": "huya", "playback_mode": "browser", "uname": "虎牙 · 660000"}}}
            assert config.build_rooms(old)[0][0]["playback_mode"] == "stream"
            saved["plugins_enabled"] = []
            disabled = MainWindow(sidebar, wall, state=saved)
            try:
                tile = next(t for t in disabled.wall.tiles if t.room.get("room_id"))
                disabled.start_tile(tile)
                assert "启用" in tile._status_text
                assert not disabled._resolvers_running
                disabled.remove_room(disabled.sidebar.rooms()[0])
                assert disabled.current_state()["platform_rooms"] == {}
            finally:
                disabled.close()
            print("PASS: dialog/drop-to-tile flow, no browser/Bili, save/restart, migration, disable")
        finally:
            window.close()
    app.processEvents()
    print("Huya tile playback selfcheck passed")


if __name__ == "__main__":
    main()
