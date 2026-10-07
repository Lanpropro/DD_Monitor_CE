"""操作提示、插件页切换与刷新旋转：中间帧、打断、结束和关闭动画。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from ddm import motion, theme
from ddm.dialogs import PluginSettingsPage
from ddm.online_ui import PluginStorePage, show_result
from ddm.widgets import RefreshButton


def main():
    errors = []
    original_hook = sys.excepthook
    def capture_error(kind, error, tb):
        errors.append(error)
        original_hook(kind, error, tb)
    sys.excepthook = capture_error
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    owner = QWidget()
    owner.resize(800, 600)
    layout = QVBoxLayout(owner)
    button = RefreshButton(size=22, object_name="ChipButton")
    layout.addWidget(button)
    with patch.object(PluginStorePage, "open_catalog"), patch.object(motion, "enabled", return_value=True):
        plugins = PluginSettingsPage()
        layout.addWidget(plugins)
        owner.show()
        app.processEvents()
        button.set_refreshing(True)
        assert button._spin.state() == QAbstractAnimation.Running
        button._spin.setCurrentTime(250)
        assert button._angle == 90
        button.set_refreshing(True)
        assert button._angle == 90, "queued refresh must not restart the rotation"
        button.hide()
        assert button._spin.state() != QAbstractAnimation.Running
        button.show()
        assert button._spin.state() == QAbstractAnimation.Running
        button.set_refreshing(False)
        assert button._spin.state() != QAbstractAnimation.Running and button._angle == 0

        tabs = plugins.tabs
        QTest.mouseClick(tabs.tabBar(), Qt.LeftButton, pos=tabs.tabBar().tabRect(1).center())
        assert tabs._slide.state() == QAbstractAnimation.Running
        target = QPoint(tabs._slide.endValue())
        assert tabs.currentWidget().windowOpacity() == 1
        tabs._slide.setCurrentTime(50)
        assert 0 < tabs.currentWidget().x() - target.x() < 16
        old_page = tabs.currentWidget()
        QTest.mouseClick(tabs.tabBar(), Qt.LeftButton, pos=tabs.tabBar().tabRect(0).center())
        assert old_page.pos() == target
        tabs._slide.setCurrentTime(160)
        assert tabs.currentWidget().pos() == tabs._slide.endValue()
        tabs.setCurrentIndex(1)
        assert tabs._slide.state() != QAbstractAnimation.Running, "programmatic/keyboard changes must be immediate"
        tabs.tabBar().setFocus()
        QTest.keyClick(tabs.tabBar(), Qt.Key_Left)
        assert tabs.currentIndex() == 0 and tabs._slide.state() != QAbstractAnimation.Running

        show_result(owner, "已添加测试主播")
        notice = owner._result_notice
        assert notice.isVisible() and notice.windowOpacity() == 1
        assert notice.timer.interval() == 3000 and notice.timer.isActive()
        notice._motion.setCurrentTime(60)
        assert 0 < notice._progress < 1
        progress = notice._progress
        show_result(owner, "导入完成：新增 2 个")
        assert owner._result_notice is notice and notice._progress == progress
        notice._motion.setCurrentTime(160)
        assert notice.pos() == owner.mapToGlobal(QPoint((owner.width() - notice.width()) // 2, 20))
        owner.resize(900, 650)
        app.processEvents()
        assert notice.pos() == owner.mapToGlobal(QPoint((owner.width() - notice.width()) // 2, 20))
        notice.timer.timeout.emit()
        notice._motion.setCurrentTime(180)
        assert not notice.isVisible() and notice.windowOpacity() == 1
        show_result(owner, "插件已安装，重启后生效")
        plugins.store_page.installed.disconnect()
        plugins.store_page._installed(("test", False))
        assert "插件已安装" in notice.title.text() and notice.timer.isActive()
        owner.hide()
        assert not notice.isVisible() and not notice.timer.isActive()
        assert notice._motion.state() != QAbstractAnimation.Running
        owner.show()
        with patch.object(motion, "enabled", return_value=False):
            button.set_refreshing(True)
            assert button._spin.state() != QAbstractAnimation.Running and button._angle == 0
            QTest.mouseClick(tabs.tabBar(), Qt.LeftButton, pos=tabs.tabBar().tabRect(0).center())
            assert tabs._slide.state() != QAbstractAnimation.Running
            show_result(owner, "完成")
            assert notice._progress == 1 and notice._motion.state() != QAbstractAnimation.Running
            notice.dismiss()
            assert not notice.isVisible()
        button.set_refreshing(False)
        owner.close()
        plugins.store_page.stop()
    sys.excepthook = original_hook
    assert not errors, errors
    print("PASS: refresh spin/reentry/stop, opaque plugin tabs, result notice reuse/timeout/hide and reduced motion")


if __name__ == "__main__":
    main()
