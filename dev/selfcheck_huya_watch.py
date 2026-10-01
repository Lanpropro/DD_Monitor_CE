"""虎牙网页观看：链接校验、关注卡片、浏览器路由、保存重启和插件禁用。"""
import os
import sys
import tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import config, plugins  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import AddRoomDialog  # noqa: E402


def main():
    app = QApplication.instance() or QApplication([])
    manager = plugins.PluginManager(enabled=["huya_watch"])
    manager.load()
    platform = manager.platforms["huya"]
    for raw in ("huya:660000", "https://www.huya.com/660000",
                "https://m.huya.com/660000/?from=share", "http://huya.com/660000#share"):
        assert platform.matches(raw)
        assert platform.normalize(raw) == "huya:660000", raw
    assert platform.normalize("huya:godv") == "huya:godv"
    assert platform.normalize("huya:https://www.huya.com/godv") == "huya:godv"
    assert not platform.matches("660000"), "纯数字仍属于 B 站"
    for raw in ("huya:", "huya:../secret", "huya:a/b", "https://www.huya.com/%2Fsecret",
                "https://www.huya.com.evil.test/660000", "https://evil.test/www.huya.com/660000",
                "https://user:pass@www.huya.com/660000", "https://www.huya.com:1234/660000",
                "file:///660000"):
        try:
            platform.normalize(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(f"必须拒绝非法房间输入：{raw}")
    assert platform.room_url("huya:660000") == "https://www.huya.com/660000"
    print("PASS: Huya official URLs and canonical room IDs")

    # 跳过启动定时网络任务，只验证本次功能实际使用的界面和配置链路。
    with patch("ddm.app.QTimer.singleShot"), patch("ddm.app.bili.room_info") as bili_info:
        window = MainWindow([], [], state={"plugins_enabled": ["huya_watch"]})
        try:
            for raw, expected in (("https://www.huya.com/660000?from=share", "huya:660000"),
                                  ("9001", "9001"), ("https://live.bilibili.com/9001", "9001")):
                dialog = AddRoomDialog(window, room_id_resolver=window._normalize_room_input)
                dialog.edit.setText(raw)
                dialog.accept()
                assert dialog.result() == AddRoomDialog.DialogCode.Accepted
                assert dialog.room_id == expected
                dialog.deleteLater()
            dialog = AddRoomDialog(window, room_id_resolver=window._normalize_room_input)
            dialog.edit.setText("https://www.huya.com.evil.test/660000")
            dialog.accept()
            assert dialog.result() != AddRoomDialog.DialogCode.Accepted and not dialog.room_id
            dialog.deleteLater()

            before_wall = len(window.wall.tiles)
            def accept_huya(dialog):
                dialog.edit.setText("https://www.huya.com/660000")
                dialog.accept()
                return dialog.result()
            with patch.object(AddRoomDialog, "exec", accept_huya):
                window.open_add_room()
            window._add_room_id(platform.normalize("https://www.huya.com/660000/"))
            assert len(window.sidebar.rooms()) == 1, "重复链接只能有一张卡片"
            assert len(window.wall.tiles) == before_wall, "网页房间不会创建 VLC 格子"
            item = window.sidebar.items()[0]
            assert item.room["room_id"] == "huya:660000"
            assert item.badge.text() == "网页观看", "不得把未知状态显示成未开播"
            assert not item.room["live"] and item.room["live_known"] is False
            with patch("ddm.app.webbrowser.open", return_value=True) as opened:
                item.clicked.emit(item.room)
                assert opened.call_args.args == ("https://www.huya.com/660000",)
                actions = {action.text(): action for action in item._context_menu().actions()}
                assert "观看直播" in actions and "加入画面墙" not in actions
                actions["观看直播"].trigger()
                window._on_room_dropped(None, "huya:660000")
                assert opened.call_count == 3
            with patch("ddm.app.webbrowser.open", return_value=False), \
                    patch("ddm.app.QMessageBox.warning") as warning:
                item.clicked.emit(item.room)
                warning.assert_called_once()
            with patch("ddm.app.StatusPoller") as poller, \
                    patch("ddm.app.CachedCoverLoader") as covers, \
                    patch("ddm.app.CachedAvatarLoader") as avatars:
                window.refresh_status()
                window.load_cached_covers()
                window.load_cached_avatars()
                poller.assert_not_called()
                covers.assert_not_called()
                avatars.assert_not_called()
            bili_info.assert_not_called()
            print("PASS: card add/deduplicate, click/menu/drop, browser failure, no Bili requests")

            state = window.current_state()
            with tempfile.TemporaryDirectory() as root, \
                    patch.object(config, "CONFIG_PATH", os.path.join(root, "config.json")), \
                    patch.dict(os.environ):
                os.environ.pop("DDM_NO_SAVE", None)
                config.save(state)
                saved = config.load()
            sidebar, wall = config.build_rooms(saved)
            assert sidebar[0]["uname"] == "虎牙 · 660000"
            assert sidebar[0]["playback_mode"] == "browser"
            restored = MainWindow(sidebar, wall, state=saved)
            try:
                with patch("ddm.app.webbrowser.open", return_value=True) as opened:
                    restored.sidebar.items()[0].clicked.emit(restored.sidebar.rooms()[0])
                    opened.assert_called_once_with("https://www.huya.com/660000")
                restored.remove_room(restored.sidebar.rooms()[0])
                assert restored.current_state()["rooms"] == []
                assert restored.current_state()["browser_rooms"] == {}
            finally:
                restored.close()

            saved["plugins_enabled"] = []
            sidebar, wall = config.build_rooms(saved)
            disabled = MainWindow(sidebar, wall, state=saved)
            try:
                with patch("ddm.app.webbrowser.open") as opened, \
                        patch("ddm.app.QMessageBox.information") as notice:
                    disabled.sidebar.items()[0].clicked.emit(disabled.sidebar.rooms()[0])
                    opened.assert_not_called()
                    notice.assert_called_once()
                try:
                    disabled._normalize_room_input("https://www.huya.com/660000")
                except ValueError:
                    pass
                else:
                    raise AssertionError("禁用插件后不能把虎牙链接解析成 B 站数字房间")
            finally:
                disabled.close()
            print("PASS: disk save/restart, deletion, disabled plugin preserves cards")
        finally:
            window.close()
    app.processEvents()
    print("Huya watch selfcheck passed")


if __name__ == "__main__":
    main()
