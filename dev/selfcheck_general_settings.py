"""后台检查常规设置顺序、隐藏选项保留和固定开启的卡死检测。"""
import gc
import os
from pathlib import Path
import sys
import weakref
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QLabel, QCheckBox
from PySide6.QtCore import QCoreApplication, QEvent, SIGNAL
from ddm import app as app_module, config
from ddm.dialogs import CodecSettingsPanel, GeneralSettingsPage, SettingsDialog
from dev.selfcheck_tile_fullscreen import SilentPoller


def check_volume_page_lifetime():
    """The volume signal must not retain its parent page until cyclic GC."""
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        page = GeneralSettingsPage({"default_volume": 21})
        for volume in (0, 17, 100):
            page.volume_slider.setValue(volume)
            assert page.volume_label.text() == str(volume)
            assert page.values()["default_volume"] == volume
        page_ref = weakref.ref(page)
        del page
        assert page_ref() is None, "Volume callback retains the settings page"
    finally:
        if gc_was_enabled:
            gc.enable()


def check_settings_lifetime(app):
    with patch('ddm.app.QTimer.singleShot'):
        window = app_module.MainWindow([], [], layout_id='1x1', state={'plugins_enabled': []})
    try:
        layer = window.skin_controller.layer
        receivers = layer.receivers(SIGNAL('frameReady()'))
        for result in (SettingsDialog.Rejected, SettingsDialog.Accepted, SettingsDialog.Rejected):
            def execute(dialog):
                dialog.nav.setCurrentRow(1)
                dialog.done(result)
                return result
            with patch.object(SettingsDialog, 'exec', execute):
                assert window.open_settings() == (result == SettingsDialog.Accepted)
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
            assert not window.findChildren(SettingsDialog), '关闭设置后必须释放整棵页面控件'
            assert layer.receivers(SIGNAL('frameReady()')) == receivers, '不能累积后台预览更新连接'
    finally:
        window.close()


def check_codecs(app):
    expected = ("auto", "d3d11va-copy", "none", "d3d11va", "dxva2")
    assert tuple(config.DECODE_LABELS) == expected
    assert config.DEFAULT_SETTINGS["bili_codec"] == "avc"
    assert config.codec_settings({})["bili_codec"] == "avc"
    basic = CodecSettingsPanel({})
    events = []
    basic.changed.connect(events.append)
    assert basic.values() == {"bili_codec": "avc", "decode_mode": "auto"}
    assert basic.bili_codec.accessibleName() == "直播源格式"
    assert "AV1（仅B站）" in basic.bili_codec.itemText(basic.bili_codec.findData("av1"))
    assert any(label.text() == "直播源格式" for label in basic.findChildren(QLabel))
    assert basic.decode_mode.count() == 5
    assert tuple(basic.decode_mode.itemData(i) for i in range(5)) == expected
    assert not hasattr(basic, "advanced_decode") and not events
    basic.decode_mode.setCurrentIndex(basic.decode_mode.findData("dxva2"))
    assert basic.values()["decode_mode"] == "dxva2"
    basic.decode_mode.setCurrentIndex(basic.decode_mode.findData("auto"))
    assert basic.decode_mode.count() == 5 and len(events) == 2
    for mode in expected:
        saved = {"bili_codec": "av1", "decode_mode": mode}
        restored = CodecSettingsPanel(config.codec_settings(saved))
        assert restored.values() == saved
        assert restored.decode_mode.count() == 5
    inherited = CodecSettingsPanel({}, defaults={"bili_codec": "avc", "decode_mode": "dxva2"})
    inherited.changed.connect(events.append)
    assert inherited.decode_mode.count() == 6
    assert inherited.values() == {} and "颜色" in inherited.decode_hint.text()
    inherited.set_defaults({"bili_codec": "av1", "decode_mode": "auto"})
    assert inherited.values() == {} and len(events) == 2
    assert "多窗" in inherited.decode_hint.text()
    assert config.codec_settings({"hw_decode": False})["decode_mode"] == "none"
    assert config.codec_overrides({"bili_codec": "bad", "decode_mode": "none", "x": 1}) == {
        "decode_mode": "none"}
    assert config.codec_overrides(None) == {}
    assert config.codec_overrides({"decode_mode": "d3d11va-copy"}) == {
        "decode_mode": "d3d11va-copy"}
    compatibility = CodecSettingsPanel({"bili_codec": "avc", "decode_mode": "d3d11va-copy"})
    assert compatibility.values()["decode_mode"] == "d3d11va-copy"
    compatibility_page = GeneralSettingsPage(compatibility.values())
    assert "兼容硬解" in compatibility_page.codec_button.text()
    panel = CodecSettingsPanel({"bili_codec": "av1", "decode_mode": "none"})
    assert panel.values() == {"bili_codec": "av1", "decode_mode": "none"}
    page = GeneralSettingsPage(panel.values())
    assert "AV1" in page.codec_button.text() and "CPU" in page.codec_button.text()
    for accepted in (False, True):
        with patch("ddm.dialogs.CodecSettingsDialog") as mocked:
            mocked.return_value.exec.return_value = int(accepted)
            mocked.return_value.controls.values.return_value = {
                "bili_codec": "hevc", "decode_mode": "d3d11va"}
            page._edit_codecs()
        assert page.values()["bili_codec"] == ("hevc" if accepted else "av1")
    rooms = [{"room_id": str(1001 + i), "uname": f"测试{i}", "live": True}
             for i in range(3)]
    settings = {"bili_codec": "av1", "recording_enabled": False,
                "recording_replay_enabled": False, "preview_on_hover": False,
                "danmaku_enabled": False, "auto_quality": False}
    with patch("ddm.app.QTimer.singleShot"), \
            patch.object(app_module.MainWindow, "sync_danmaku"), \
            patch.object(app_module.MainWindow, "refresh_status"), \
            patch.object(app_module.MainWindow, "refresh_stats"), \
            patch.object(app_module.StreamResolver, "start"):
        window = app_module.MainWindow(rooms, [dict(room) for room in rooms], layout_id="1x3",
            state={"plugins_enabled": [], "settings": settings})
        window.show()
        app.processEvents()
        first, other, plugin_tile = window.wall.tiles[:3]
        plugin = SimpleNamespace(kind="huya")
        with patch.object(window.plugins, "platform_for", side_effect=lambda rid:
                          plugin if rid == "1003" else None):
            try:
                with patch.object(window, "start_tile") as restart:
                    window._set_tile_codecs(first, {"bili_codec": "hevc", "decode_mode": "none"})
                    restart.assert_called_once_with(first)
                    assert other.codec_overrides == {}
                    restart.reset_mock()
                    window._set_tile_codecs(first, first.codec_overrides)
                    restart.assert_not_called()
                assert window.media_options(first) == ("hwdec=no",)
                assert window.media_options(other) == ()
                window.start_tile(first)
                assert window._resolvers[first].codec == "hevc"
                window.start_tile(other)
                assert window._resolvers[other].codec == "av1"
                assert "等待新流" in window._codec_status(first)
                window._resolvers.clear()
                with patch.object(app_module.TilePlayer, "play") as play:
                    window._play_on(first, "http://127.0.0.1:9/test", 250, "app")
                    assert play.call_args.kwargs["options"] == ("hwdec=no",)
                player = window.players[first]
                player.decode_mode = "none"
                assert "H.264" in window._codec_status(first)
                assert "首选 HEVC" in window._codec_status(first)
                first.codec_overrides["decode_mode"] = "d3d11va"
                assert "故障回退" in window._codec_status(first)
                player.decode_mode = "auto"
                first.codec_overrides["decode_mode"] = "auto"
                assert "实际：等待首帧" in window._codec_status(first)
                first.codec_overrides["decode_mode"] = "none"
                assert any("当前窗口编解码设置" in action.text()
                           for action in first.build_menu().actions())
                next(action for action in first.build_menu().actions()
                     if "当前窗口编解码设置" in action.text()).trigger()
                dialog = window._codec_dialogs[first]
                assert dialog.isVisible() and dialog._status_timer.isActive()
                window._open_tile_codecs(first)
                assert window._codec_dialogs[first] is dialog
                window._open_tile_codecs(plugin_tile)
                plugin_controls = window._codec_dialogs[plugin_tile].controls
                assert plugin_controls.bili_codec.isEnabled()
                assert "HEVC、H.264" in plugin_controls.hint.text()
                window._codec_dialogs[plugin_tile].close()
                with patch.object(window, "start_tile") as restart, \
                        patch.object(app_module, "SettingsDialog") as global_dialog:
                    global_dialog.Accepted = int(SettingsDialog.DialogCode.Accepted)
                    global_dialog.return_value.exec.return_value = int(SettingsDialog.DialogCode.Accepted)
                    global_dialog.return_value.settings.return_value = {"bili_codec": "avc"}
                    global_dialog.return_value.shortcuts.return_value = {}
                    global_dialog.return_value.enabled_plugins.return_value = []
                    global_dialog.return_value.restart_requested = False
                    global_dialog.return_value.update_page.install_requested = False
                    global_dialog.return_value._loaded_pages = {}
                    window.open_settings()
                    assert [call.args[0] for call in restart.call_args_list] == [other, plugin_tile], \
                        "全局格式变化应重连所有跟随窗口，保留独立设置"
                    assert "H.264" in dialog.controls.bili_codec.itemText(0)
                    restart.reset_mock()
                    global_dialog.return_value.settings.return_value = {"bili_codec": "av1"}
                    window.open_settings()
                    assert [call.args[0] for call in restart.call_args_list] == [other, plugin_tile]
                    assert "AV1（仅B站）" in dialog.controls.bili_codec.itemText(0)
                    restart.reset_mock()
                    global_dialog.return_value.settings.return_value = {"decode_mode": "dxva2"}
                    window.open_settings()
                    assert [call.args[0] for call in restart.call_args_list] == [other, plugin_tile], \
                        "全局解码变化应影响跟随的所有平台，保留独立窗口"
                first.set_paused(True)
                with patch.object(window, "start_tile") as restart:
                    dialog.controls.decode_mode.setCurrentIndex(
                        dialog.controls.decode_mode.findData("d3d11va"))
                    restart.assert_not_called()
                    assert first.codec_reconnect_pending
                    assert "恢复播放" in window._codec_status(first)
                    window._on_pause_toggled(first.room)
                    restart.assert_called_once_with(first)
                first.codec_reconnect_pending = False
                with patch.object(window, "start_tile") as restart:
                    dialog._reset_inheritance()
                    restart.assert_called_once_with(first)
                    assert first.codec_overrides == {}
                window._set_tile_codecs(first, {"bili_codec": "hevc"})
                first.set_room(dict(rooms[1]))
                assert first.codec_overrides == {"bili_codec": "hevc"}, "换台保留单窗设置"
                saved = window.current_state()
                _, restored = config.build_rooms(saved)
                assert restored[0]["codec_overrides"] == {"bili_codec": "hevc"}
                first.set_room(None)
                _, restored = config.build_rooms(window.current_state())
                assert restored[0]["codec_overrides"] == {"bili_codec": "hevc"}
                dialog.close()
                assert not dialog._status_timer.isActive() and first not in window._codec_dialogs
            finally:
                window.close()
                app.processEvents()


def main():
    app = QApplication([])
    page = GeneralSettingsPage({"auto_quality": False, "sidebar_card_mode": False,
                                "freeze_watch": False, "default_volume": 21})
    grid = page.layout().itemAt(1).layout()
    labels = []
    for index in range(grid.count()):
        item = grid.itemAt(index)
        widget = item.widget()
        if isinstance(widget, (QLabel, QCheckBox)):
            labels.append((grid.getItemPosition(index)[0], widget.text()))
    assert [text for _, text in sorted(labels)] == [
        "关注列表刷新间隔", "新建格子初始静音", "全屏只播放该路声音",
        "全屏时自动收起底部控制条",
        "自动切换紧凑列表", "自动切换数量", "关注栏直播预览", "显示关注栏平台 Logo",
        "关闭窗口时", "编解码设置", "新建格子的初始音量"]
    assert {"auto_quality", "freeze_watch", "sidebar_card_mode"}.isdisjoint(page._checks)
    values = page.values()
    assert values["auto_quality"] is False and values["sidebar_card_mode"] is False
    assert values["freeze_watch"] is True and values["default_volume"] == 21
    page._checks["sidebar_platform_logos"].setChecked(False)
    assert page.values()["sidebar_platform_logos"] is False
    # 直播编码跟着解码方式走：两档都是「B 站这一路怎么播」的选择。
    assert values["bili_codec"] == config.DEFAULT_SETTINGS["bili_codec"]
    page._checks["sidebar_auto_compact"].setChecked(False)
    assert not page.compact_threshold_spin.isEnabled()
    page.reset()
    assert page.compact_threshold_spin.isEnabled()
    assert all(page.values()[key] == config.DEFAULT_SETTINGS[key] for key in page.values())
    app_module.StatusPoller = app_module.StatsPoller = SilentPoller
    with patch("ddm.app.QTimer.singleShot"):
        window = app_module.MainWindow([], [], state={"plugins_enabled": [],
            "settings": {"freeze_watch": False, "auto_update": False}})
    assert window.settings["freeze_watch"] is True, "Old setting disabled always-on detection"
    window.close()
    app.processEvents()
    for default_volume in (40, 0, 100):
        state = {'plugins_enabled': [], 'settings': {
            'default_volume': default_volume, 'auto_update': False}}
        with patch('ddm.app.QTimer.singleShot'):
            window = app_module.MainWindow([], [], layout_id='1x1', state=state)
        try:
            first = window.wall.tiles[0]
            assert first.volume == default_volume, 'Startup empty slots must use the configured default volume'
            first.set_volume(17)
            window.settings['default_volume'] = 23
            window._on_layout_changed('2x2')
            assert [tile.volume for tile in window.wall.tiles] == [17, 23, 23, 23]
            assert all(tile.volume_slider.value() == tile.volume
                       and tile.volume_label.text() == str(tile.volume) for tile in window.wall.tiles)
            window.wall.tiles[1].set_room({'room_id': '1', 'uname': 'Fixture'})
            assert window.wall.tiles[1].volume == 23, 'Replacing a room must preserve slot volume'
            saved = window.current_state()
            _, wall = config.build_rooms(saved)
            assert [room['volume'] for room in wall] == [17, 23, 23, 23]
        finally:
            window.close()
    state = {'plugins_enabled': [], 'settings': {'default_volume': 40, 'auto_update': False},
             'wall': [{'room_id': '1', 'volume': 42}, {'room_id': '2', 'volume': 0},
                      {'room_id': '3'}, {'room_id': ''}, {'room_id': '', 'volume': 17}]}
    rooms, wall = config.build_rooms(state)
    assert [room['volume'] for room in wall] == [42, 0, 40, 40, 17], 'Only missing values should inherit the default'
    with patch('ddm.app.QTimer.singleShot'):
        window = app_module.MainWindow(rooms, wall, layout_id='corner', state=state)
    try:
        assert [tile.volume for tile in window.wall.tiles] == [42, 0, 40, 40, 17, 40]
    finally:
        window.close()
    check_volume_page_lifetime()
    check_settings_lifetime(app)
    check_codecs(app)
    print("PASS: unified codec settings, per-window overrides, general settings and default volumes")


if __name__ == "__main__":
    main()
