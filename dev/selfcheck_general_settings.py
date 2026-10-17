"""后台检查常规设置顺序、隐藏选项保留和固定开启的卡死检测。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QLabel, QCheckBox
from ddm import app as app_module, config
from ddm.dialogs import GeneralSettingsPage, RecordingSettingsPage, SettingsDialog
from ddm.plugins import Platform
from dev.selfcheck_tile_fullscreen import SilentPoller


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
        "自动切换紧凑列表", "自动切换数量", "关注栏直播预览", "开播提醒（顶部提示与关注栏动效）",
        "B站直播编码", "视频解码方式", "新建格子的初始音量"]
    assert {"auto_quality", "freeze_watch", "sidebar_card_mode"}.isdisjoint(page._checks)
    values = page.values()
    assert values["auto_quality"] is False and values["sidebar_card_mode"] is False
    assert values["freeze_watch"] is True and values["default_volume"] == 21
    # 直播源编码在上，解码方式在下。
    assert values["bili_codec"] == config.DEFAULT_SETTINGS["bili_codec"]
    page._checks["sidebar_auto_compact"].setChecked(False)
    assert not page.compact_threshold_spin.isEnabled()
    page.reset()
    assert page.compact_threshold_spin.isEnabled()
    assert all(page.values()[key] == config.DEFAULT_SETTINGS[key] for key in page.values())
    class FixturePlatform(Platform):
        kind, label = "fixture", "测试平台"
        video_codec_options = (("avc", "H.264"), ("av1", "AV1"))
        def video_codec(self):
            return saved.get(self.kind, "avc")
        def set_video_codec(self, codec):
            saved[self.kind] = codec
    saved = {}
    platform = FixturePlatform()
    manager = SimpleNamespace(platforms={platform.kind: platform, "legacy": Platform()})
    page = GeneralSettingsPage({}, plugin_manager=manager)
    assert len(page._platform_codecs) == 1, "旧插件不应出现无效编码选项"
    combo = page._platform_codecs[0][1]
    combo.setCurrentIndex(combo.findData("av1"))
    page.values()
    assert not saved, "修改控件、读取设置或取消窗口不能保存插件偏好"
    grid = page.layout().itemAt(1).layout()
    def row_of(widget):
        return grid.getItemPosition(grid.indexOf(widget))[0]
    assert row_of(page.bili_codec) < row_of(combo) < row_of(page.decode_mode)
    assert page.apply_platform_codecs() == {"fixture"} and saved == {"fixture": "av1"}
    assert page.apply_platform_codecs() == set(), "重复保存不应重新取流"
    page.reset()
    assert saved == {"fixture": "av1"}, "恢复控件默认也需等待保存"
    assert page.apply_platform_codecs() == {"fixture"} and saved["fixture"] == "avc"
    dialog = SettingsDialog({}, {}, plugin_manager=manager, preview=True)
    assert len(dialog.general_page._platform_codecs) == 1
    dialog.general_page._platform_codecs[0][1].setCurrentIndex(1)
    dialog.reject()
    assert saved == {"fixture": "avc"}
    recording = RecordingSettingsPage({"recording_enabled": True, "recording_codec": "copy"})
    assert not recording.encoder.isEnabled() and "直存无需编码器" in recording.encoder_hint.text()
    recording.codec.setCurrentIndex(recording.codec.findData("h264"))
    assert recording.encoder.isEnabled()
    recording.recording_enabled.setChecked(False)
    assert not recording.encoder.isEnabled() and "先开启" in recording.encoder_hint.text()
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
    print("PASS: general settings, startup/default volume, new-slot inheritance, saved slot volumes, boundaries and always-on freeze detection")


if __name__ == "__main__":
    main()
