"""离线自检：禁用平台暂存、跨重启保存恢复、格子冲突和单平台图标隐藏。"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import app as app_module, config  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import SettingsDialog  # noqa: E402
from ddm.widgets import Sidebar  # noqa: E402


def main():
    app = QApplication([])
    state = {"version": config.STATE_VERSION, "plugins_enabled": ["huya_watch"],
        "rooms": ["1001", "huya:eslcs", "huya:660000", "1002"],
        "platform_rooms": {rid: {"uname": rid, "title": "test", "platform": "huya",
            "playback_mode": "stream"} for rid in ["huya:eslcs", "huya:660000"]},
        "wall": [{"room_id": "1001", "volume": 30}, {"room_id": "huya:eslcs",
            "volume": 61, "muted": False, "quality": 10000, "audio_channel": -1}],
        "pinned": ["huya:eslcs", "1001"], "import_order": ["1002", "huya:eslcs", "1001", "huya:660000"],
        "custom_order": ["1001", "huya:660000", "huya:eslcs", "1002"],
        "settings": {"recording_enabled": False, "recording_replay_enabled": False,
                     "preview_on_hover": False}, "sort": "custom"}
    original = json.loads(json.dumps(state))
    suspended = config.sync_platform_rooms(state, set())
    assert state == original, "转换不能修改调用方原配置"
    assert suspended["rooms"] == ["1001", "1002"] and not suspended["platform_rooms"]
    assert suspended["wall"][1]["room_id"] == "" and suspended["wall"][1]["volume"] == 61
    assert config.sync_platform_rooms(suspended, set()) == suspended, "多次禁用保存不能重复暂存"
    recovered = config.sync_platform_rooms(suspended, {"huya"})
    for key in ("rooms", "wall", "pinned", "import_order", "custom_order", "platform_rooms"):
        assert recovered[key] == original[key], key
    assert not recovered["suspended_platform_rooms"]
    conflict = json.loads(json.dumps(suspended))
    conflict["wall"][1]["room_id"] = "1002"
    assert config.sync_platform_rooms(conflict, {"huya"})["wall"][1]["room_id"] == "1002"
    mixed = {"rooms": ["1001", "huya:a", "douyu:b", "huya:c", "1002"]}
    both_hidden = config.sync_platform_rooms(mixed, set())
    assert config.sync_platform_rooms(both_hidden, {"huya", "douyu"})["rooms"] == mixed["rooms"]
    print("PASS: pure config suspension, idempotence, full restore, occupied slot preserved")

    windows = []
    with patch("ddm.app.QTimer.singleShot"), patch("ddm.app.StatusPoller") as poller, \
            patch("ddm.app.StreamResolver") as resolver:
        def window_for(saved):
            rooms, wall = config.build_rooms(saved)
            window = MainWindow(rooms, wall, state=saved, layout_id="1x2")
            windows.append(window)
            return window
        try:
            enabled = window_for(state)
            assert len(enabled.sidebar.rooms()) == 4
            huya_tile = enabled.wall.tiles[1]
            player = Mock()
            enabled.players[huya_tile] = player
            pending = Mock()
            enabled._resolvers[huya_tile] = pending
            class DisableDialog(SettingsDialog):
                def exec(self):
                    self.plugin_page.checks["huya_watch"].setChecked(False)
                    self.confirm_button.click()
                    return self.result()
            with patch.object(app_module, "SettingsDialog", DisableDialog), patch.object(config, "save") as save:
                assert enabled.open_settings()
                player.release.assert_called_once()
                pending.cancel.assert_called_once()
                disabled_state = save.call_args.args[0]
                assert enabled._restart_requested and enabled._closing
            assert disabled_state["rooms"] == ["1001", "1002"]
            assert disabled_state["suspended_platform_rooms"]["huya"]["wall"]
            disabled = window_for(disabled_state)
            assert [r["room_id"] for r in disabled.sidebar.rooms()] == ["1001", "1002"]
            assert not disabled.wall.tiles[1].room.get("room_id")
            disabled.refresh_status()
            assert "huya:eslcs" not in poller.call_args.args[0]
            assert "huya:660000" not in poller.call_args.args[0]
            assert all(item.platform_badge.isHidden() for item in disabled.sidebar.items())
            with tempfile.TemporaryDirectory() as root, patch.dict(os.environ), \
                    patch.object(config, "CONFIG_PATH", str(Path(root) / "config.json")):
                os.environ.pop("DDM_NO_SAVE")
                config.save(disabled.current_state())
                saved = config.load()
            again = window_for(saved)
            assert again.current_state()["suspended_platform_rooms"] == saved["suspended_platform_rooms"]
            class EnableDialog(SettingsDialog):
                def exec(self):
                    self.plugin_page.checks["huya_watch"].setChecked(True)
                    self.confirm_button.click()
                    return self.result()
            with patch.object(app_module, "SettingsDialog", EnableDialog), patch.object(config, "save") as save:
                assert again.open_settings()
                resumed_state = save.call_args.args[0]
            resumed = window_for(resumed_state)
            assert {r["room_id"] for r in resumed.sidebar.rooms()} == set(original["rooms"])
            assert resumed.wall.tiles[1].room["room_id"] == "huya:eslcs"
            assert resumed.wall.tiles[1].volume == 61 and not resumed.wall.tiles[1].muted
            assert resumed.wall.tiles[1].quality == 10000 and resumed.wall.tiles[1].audio_channel == -1
            assert resumed.sidebar.pinned == original["pinned"]
            assert resumed.sidebar.custom_order == original["custom_order"]
            assert resumed.sidebar.import_order == original["import_order"]
            assert not resumed.current_state()["suspended_platform_rooms"]
            resolver.assert_not_called()
            print("PASS: real plugin settings disable/enable, save/restart, no hidden polling, slot preferences")
        finally:
            for window in windows:
                window._poller = None
                window.close()
    sidebar = Sidebar([{"room_id": "huya:eslcs", "live": True}])
    sidebar.show()
    app.processEvents()
    first = sidebar.items()[0]
    assert first.platform_badge.isHidden()
    first.set_card_mode(False)
    first.set_portrait_strip(True)
    first.thumb.stop()
    assert first.platform_badge.isHidden()
    first.set_portrait_strip(False)
    first.set_card_mode(True)
    for compact in (True, False, True, False):
        first.set_compact(compact)
        app.processEvents()
        assert first.platform_badge.isHidden()
    sidebar.add_room({"room_id": "huya:660000"})
    assert all(item.platform_badge.isHidden() for item in sidebar.items())
    sidebar.add_room({"room_id": "1001"})
    assert all(not item.platform_badge.isHidden() for item in sidebar.items())
    for item in sidebar.items():
        item.set_compact(True)
        assert not item.platform_badge.isHidden()
    sidebar.remove_room({"room_id": "1001"})
    assert all(item.platform_badge.isHidden() for item in sidebar.items())
    sidebar.close()
    app.processEvents()
    print("PASS: one-platform icons hidden, mixed-platform icons restored, compact mode preserved")


if __name__ == "__main__":
    main()
