"""插件页拖放、EXE 内嵌 ZIP 校验，以及显式重启的生命周期。"""
import argparse
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from unittest.mock import patch

os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from PySide6.QtCore import QMimeData, QPoint, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, config, plugins as plugin_api
from ddm.app import MainWindow
from ddm.dialogs import PluginSettingsPage, SettingsDialog
from ddm.online_ui import PluginStorePage
from ddm.plugins import PluginManager


def package(path, plugin_id, prefix=b""):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(f"{plugin_id}/plugin.json", json.dumps({
            "id": plugin_id, "name": plugin_id, "description": "test", "version": "1"}))
        archive.writestr(f"{plugin_id}/plugin.py", "raise RuntimeError('must not execute at install')")
    with open(path, "wb") as handle:
        handle.write(prefix + data.getvalue())


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, *args):
        super().__init__(args[-1])

    def run(self):
        pass


def check_domestic_import(app, archive):
    """Import the actual release into an empty install, then load its saved state."""
    with tempfile.TemporaryDirectory(prefix="ddm_domestic_restart_") as root:
        class InstallDialog(SettingsDialog):
            def exec(self):
                assert not self.plugin_page.checks
                self.plugin_page._install_archive(archive)
                assert self.plugin_page.checks["domestic_live"].isChecked()
                assert self.confirm_button.text() == "重启以应用"
                self.confirm_button.click()
                return self.result()

        with patch.object(plugin_api, "DEFAULT_PLUGINS_DIR", os.path.join(root, "plugins")), \
                patch.object(app_module, "SettingsDialog", InstallDialog), \
                patch("ddm.dialogs.QMessageBox.information"), patch.object(config, "save") as save:
            window = MainWindow([], [], state={"plugins_enabled": []})
            assert not window.plugins.plugins and not window.plugins.catalog()
            assert window.open_settings()
            assert window._closing and window._restart_requested
            assert not window.plugins.platforms, "Installing must not execute the plugin"
            saved = save.call_args.args[0]
            app.processEvents()
            restarted = MainWindow([], [], state=saved)
            try:
                assert set(restarted.plugins.platforms) == {"huya", "douyu", "douyin"}
                assert len(restarted.plugins.plugins) == 1
                assert restarted.plugins.plugins[0].version == "1.0"
                app.processEvents()
            finally:
                restarted.close()
                app.processEvents()
    print("PASS: empty install, actual domestic 1.0 ZIP, save/restart and three platforms")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domestic-package")
    args = parser.parse_args()
    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="ddm_plugin_drop_") as root, patch.object(PluginStorePage, 'open_catalog'):
        manager = PluginManager(plugins_dir=os.path.join(root, "plugins"))
        page = PluginSettingsPage(manager)
        page.show()
        app.processEvents()
        first = os.path.join(root, "第一个插件.ZIP")
        second = os.path.join(root, "second.exe")
        package(first, "first")
        package(second, "second", b"MZ self extracting stub\0")
        mime = QMimeData()
        point = QPoint(5, 5)
        actions = Qt.CopyAction | Qt.MoveAction
        search = page.installed_browser.search
        mime.setUrls([QUrl.fromLocalFile(first), QUrl.fromLocalFile(os.path.join(root, '说明.txt'))])
        enter = QDragEnterEvent(point, actions, mime, Qt.LeftButton, Qt.ShiftModifier)
        QApplication.sendEvent(search, enter)
        assert enter.isAccepted() and enter.dropAction() == Qt.CopyAction
        drop = QDropEvent(point, actions, mime, Qt.LeftButton, Qt.ShiftModifier)
        QApplication.sendEvent(search, drop)
        assert drop.isAccepted() and drop.dropAction() == Qt.CopyAction
        assert not search.text() and set(page.checks) == {"first"}
        assert os.path.isfile(first), "拖入安装必须保留源文件"

        mime.setUrls([QUrl.fromLocalFile(second)])
        for index, targets in enumerate(((page.installed_scroll.viewport(), page),
                                         (page.store_page.search, page.store_page.scroll.viewport()))):
            page.tabs.setCurrentIndex(index)
            app.processEvents()
            for target in targets:
                enter = QDragEnterEvent(point, actions, mime, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(target, enter)
                assert enter.isAccepted(), target
                assert page.drop_feedback.isVisible()
                QApplication.sendEvent(target, QDragLeaveEvent())
                assert page.drop_feedback.isHidden()
        viewport = page.store_page.scroll.viewport()
        QApplication.sendEvent(viewport, QDragEnterEvent(point, actions, mime, Qt.LeftButton, Qt.NoModifier))
        drop = QDropEvent(point, actions, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(viewport, drop)
        assert drop.isAccepted() and page.drop_feedback.isHidden()
        assert set(page.checks) == {"first", "second"}
        assert manager.plugins == [], "安装不能执行插件或 EXE"
        assert all(entry["status"] == "待重启" for entry in manager.catalog())

        invalid = os.path.join(root, "ordinary.exe")
        with open(invalid, "wb") as handle:
            handle.write(b"MZ not a plugin archive")
        mime.setUrls([QUrl.fromLocalFile(invalid)])
        with patch("ddm.dialogs.QMessageBox.warning") as warning:
            page.dropEvent(QDropEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
            assert warning.called
        assert set(page.checks) == {"first", "second"}
        mime.setUrls([QUrl("https://example.com/plugin.zip")])
        enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        page.dragEnterEvent(enter)
        assert not enter.isAccepted()
        page.close()

    class RestartDialog(SettingsDialog):
        def exec(self):
            self.general_page._checks["fullscreen_solo_audio"].setChecked(False)
            self.plugin_page._files_changed = True
            self.plugin_page.changed.emit()
            assert self.confirm_button.text() == "重启以应用"
            self.confirm_button.click()
            assert self.restart_requested
            return self.result()

    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    window = MainWindow([], [], state={"plugins_enabled": []})
    with patch.object(app_module, "SettingsDialog", RestartDialog), \
            patch.object(config, "save") as save:
        assert window.open_settings()
        assert window._restart_requested and window._closing
        assert save.call_args.args[0]["settings"]["fullscreen_solo_audio"] is False
    with patch.object(app_module.QProcess, "startDetached", return_value=(True, 123)) as launch, \
            patch.object(sys, "argv", ["main.py", "--example"]), \
            patch.object(sys, "frozen", False, create=True):
        assert app_module._launch_restart()
        launch.assert_called_once_with(sys.executable,
                                       [os.path.join(config.REPO, "main.py"), "--example"], config.REPO)
    with patch.object(app_module.QProcess, "startDetached", return_value=(False, 0)) as launch, \
            patch.object(sys, "argv", ["DD监控室CE-v0.2.exe"]), \
            patch.object(sys, "frozen", True, create=True):
        assert not app_module._launch_restart()
        launch.assert_called_once_with(sys.executable, [], config.REPO)
    with tempfile.TemporaryDirectory(prefix="ddm_restart with spaces ") as root:
        marker = os.path.join(root, "started.txt")
        with open(os.path.join(root, "main.py"), "w", encoding="utf-8") as handle:
            handle.write(f"import os\nfrom pathlib import Path\nos.chdir({REPO!r})\n"
                         f"Path({marker!r}).write_text('started')\n")
        children = []
        start_detached = app_module.QProcess.startDetached
        def record_launch(*arguments):
            result = start_detached(*arguments)
            children.append(result[1])
            return result
        with patch.object(config, "REPO", root), patch.object(sys, "argv", ["main.py"]), \
                patch.object(sys, "frozen", False, create=True), \
                patch.object(app_module.QProcess, "startDetached", side_effect=record_launch):
            assert app_module._launch_restart(), "真实子进程应能启动"
        deadline = time.monotonic() + 5
        while not os.path.isfile(marker) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert os.path.isfile(marker), "含空格的目录和入口路径必须可启动"
        if os.name == "nt":  # 标记写入时子进程可能仍占用临时目录，先等它退出。
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            handle = kernel32.OpenProcess(0x100000, False, children[0])
            if handle:
                try:
                    assert kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 5000) == 0
                finally:
                    kernel32.CloseHandle(ctypes.c_void_p(handle))
            else:
                assert ctypes.get_last_error() == 87, "子进程必须已退出或可等待"
    app.processEvents()
    if args.domestic_package:
        check_domestic_import(app, os.path.abspath(args.domestic_package))
    print("PASS: drag packages, embedded ZIP EXE, reject ordinary EXE, explicit restart")


if __name__ == "__main__":
    main()
