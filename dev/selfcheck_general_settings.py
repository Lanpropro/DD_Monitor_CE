"""后台检查常规设置顺序、隐藏选项保留和固定开启的卡死检测。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QLabel, QCheckBox
from ddm import app as app_module, config
from ddm.dialogs import GeneralSettingsPage
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
        "自动切换紧凑列表", "自动切换数量", "关注栏直播预览", "开播气泡提醒",
        "视频解码方式", "新建格子的初始音量"]
    assert {"auto_quality", "freeze_watch", "sidebar_card_mode"}.isdisjoint(page._checks)
    values = page.values()
    assert values["auto_quality"] is False and values["sidebar_card_mode"] is False
    assert values["freeze_watch"] is True and values["default_volume"] == 21
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
    print("PASS: general setting order and labels, hidden values, defaults and always-on freeze detection")


if __name__ == "__main__":
    main()
