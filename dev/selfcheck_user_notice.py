"""用户须知：确认或关闭后持久化、后续启动跳过、主窗口保存保留状态。"""
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, config, theme, user_notice


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    real_dialog = user_notice.UserNoticeDialog
    with tempfile.TemporaryDirectory(prefix="ddm-user-notice-") as temporary, \
            patch.object(config, "CONFIG_PATH", str(Path(temporary) / "config.json")):
        state = {"version": 1, "rooms": ["123"], "settings": {"default_volume": 30}}
        original = deepcopy(state)
        rejected = real_dialog()
        QTimer.singleShot(0, rejected.close)
        dismissed = deepcopy(state)
        with patch.object(user_notice, "UserNoticeDialog", return_value=rejected), \
                patch.dict(os.environ):
            os.environ.pop("DDM_NO_SAVE", None)
            assert user_notice.confirm_user_notice(dismissed)
        assert config.load() == dict(original, user_notice_accepted=True)
        with patch.object(user_notice, "UserNoticeDialog") as dialog:
            assert user_notice.confirm_user_notice(config.load())
            dialog.assert_not_called()

        accepted = real_dialog()
        assert accepted.content.isReadOnly() and accepted.content.openExternalLinks()
        text = accepted.content.toPlainText()
        for content in ("开源与免费", "GNU LGPL 2.1", "不收取", "第三方平台与插件", "使用与反馈"):
            assert content in text
        html = accepted.content.toHtml()
        for url in ("https://github.com/Lanpropro/DD_Monitor_CE/releases",
                    "https://github.com/Lanpropro/DD_Monitor_CE/issues",
                    "https://space.bilibili.com/193559518"):
            assert url in html
        QTimer.singleShot(0, lambda: QTest.mouseClick(accepted.confirm_button, Qt.LeftButton))
        with patch.object(user_notice, "UserNoticeDialog", return_value=accepted), \
                patch.dict(os.environ):
            os.environ.pop("DDM_NO_SAVE", None)
            assert user_notice.confirm_user_notice(state)
        loaded = config.load()
        assert loaded == dict(original, user_notice_accepted=True)
        with patch.object(user_notice, "UserNoticeDialog") as dialog:
            assert user_notice.confirm_user_notice(loaded)
            dialog.assert_not_called()

        # 全新空配置也必须带配置版本号，才能在下一次 load 时识别。
        first = real_dialog()
        QTimer.singleShot(0, first.confirm_button.click)
        fresh = {}
        with patch.object(user_notice, "UserNoticeDialog", return_value=first), \
                patch.dict(os.environ):
            os.environ.pop("DDM_NO_SAVE", None)
            assert user_notice.confirm_user_notice(fresh)
        assert config.load()["user_notice_accepted"] is True

    with ExitStack() as stack:
        for method in ("refresh_status", "refresh_stats", "refresh_account", "load_room_avatars",
                       "load_cached_covers", "load_cached_avatars", "start_all"):
            stack.enter_context(patch.object(app_module.MainWindow, method))
        window = app_module.MainWindow([], [], state={"plugins_enabled": [], "user_notice_accepted": True})
        assert window.current_state()["user_notice_accepted"] is True
        window.close()

    # 真正的启动入口：关闭须知正常构建、显示主窗口，并记住已显示。
    closing = real_dialog()
    QTimer.singleShot(0, closing.reject)
    unconfirmed = {}
    with patch.object(app_module, "QApplication", return_value=app), \
            patch.object(app_module, "setup_file_log", return_value=""), \
            patch.object(config, "load", return_value=unconfirmed), \
            patch.object(config, "save") as save, \
            patch.object(user_notice, "UserNoticeDialog", return_value=closing), \
            patch("ddm.update_install.clean_previous"), \
            patch.object(app_module.overlay, "module_paths", return_value=[]), \
            patch.object(app_module, "QTimer"), \
            patch.object(app_module.watchdog, "start"), \
            patch.object(app_module.watchdog, "stop"), \
            patch.object(app, "exec", return_value=0), \
            patch.object(app_module.os, "_exit", side_effect=SystemExit(0)), \
            patch.object(app_module, "MainWindow") as window, \
            patch.object(app_module.TilePlayer, "vlc_version", return_value="test"), \
            patch.object(app_module.TilePlayer, "warm_up_vlc") as warm:
        window.return_value._update_plan = ""
        window.return_value._restart_requested = False
        try:
            app_module.main([])
        except SystemExit as result:
            assert result.code == 0
        else:
            raise AssertionError("main must complete its normal event loop and shutdown")
        window.assert_called_once()
        window.return_value.showMaximized.assert_called_once()
        warm.assert_called_once()
        save.assert_called_once_with(unconfirmed)
        assert unconfirmed["user_notice_accepted"] is True
    print("PASS: notice content, confirmation persistence, repeated launch and normal startup after dismissal")


if __name__ == "__main__":
    main()
