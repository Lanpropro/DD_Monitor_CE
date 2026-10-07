"""轻量动效：真实鼠标点击、中间帧、连续打断、最终位置和系统动画关闭。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import config, motion, theme
from ddm.dialogs import SettingsDialog
from ddm.online_ui import UpdateNotice
from ddm.widgets import Sidebar


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    with patch.object(motion, "enabled", return_value=True):
        settings = SettingsDialog(config.DEFAULT_SETTINGS, {})
        settings.show()
        app.processEvents()
        original = settings.settings()
        nav = settings.nav
        QTest.mouseClick(nav.viewport(), Qt.LeftButton, pos=nav.visualItemRect(nav.item(1)).center())
        assert settings.stack.currentIndex() == 1
        assert settings.stack._fade.state() == QAbstractAnimation.Running
        settings.stack._fade.setCurrentTime(80)
        opacity = settings.stack._effect.opacity()
        assert 0.65 < opacity < 1
        QTest.mouseClick(nav.viewport(), Qt.LeftButton, pos=nav.visualItemRect(nav.item(2)).center())
        assert settings.stack.currentIndex() == 2
        assert settings.stack._effect.opacity() >= opacity, "rapid switching must not flash from the initial opacity"
        QTest.qWait(210)
        assert settings.stack.graphicsEffect() is None
        assert settings.settings() == original
        # 程序跳转 / 键盘导航不播放动画。
        nav.setCurrentRow(3)
        assert settings.stack.graphicsEffect() is None
        with patch.object(motion, "enabled", return_value=False):
            QTest.mouseClick(nav.viewport(), Qt.LeftButton, pos=nav.visualItemRect(nav.item(0)).center())
            assert settings.stack.graphicsEffect() is None
        settings.reject()

        for side in ("left", "top"):
            sidebar = Sidebar([{"room_id": str(i), "uname": str(i), "live": False} for i in range(4)],
                              auto_compact=False)
            sidebar.resize(248, 900)
            folder = sidebar.create_folder("Apex")
            other = sidebar.create_folder("其他")
            sidebar.move_to_folder(["0", "1"], folder)
            sidebar.move_to_folder(["2", "3"], other)
            sidebar.set_side(side)
            if side == "top":
                sidebar.resize(1400, sidebar.height())
            sidebar.show()
            app.processEvents()
            button = sidebar._folder_buttons[folder]
            following = sidebar._folder_buttons[other]
            original_pos = following.pos()
            QTest.mouseClick(button, Qt.LeftButton)
            assert sidebar.get_folder(folder)["collapsed"]
            animation = sidebar.list_box._animations[following]
            assert animation.state() == QAbstractAnimation.Running
            animation.setCurrentTime(75)
            intermediate = following.pos()
            assert intermediate != original_pos and intermediate != animation.endValue()
            QTest.mouseClick(button, Qt.LeftButton)
            assert not sidebar.get_folder(folder)["collapsed"]
            QTest.qWait(210)
            assert following.pos() == original_pos
            with patch.object(motion, "enabled", return_value=False):
                QTest.mouseClick(button, Qt.LeftButton)
                assert sidebar.get_folder(folder)["collapsed"]
                assert all(anim.state() != QAbstractAnimation.Running for anim in sidebar.list_box._animations.values())
            sidebar.close()

        parent = QWidget()
        parent.resize(900, 600)
        parent.show()
        app.processEvents()
        notice = UpdateNotice(parent)
        offer = {"version": "0.3.1"}
        notice.show_offer(offer)
        assert notice._motion.state() == QAbstractAnimation.Running and notice._progress == 0
        notice._motion.setCurrentTime(80)
        assert 0 < notice._progress < 1
        QTest.qWait(200)
        assert notice._progress == 1
        anchored = notice.pos()
        notice.timer.timeout.emit()
        assert not notice.timer.isActive() and notice._leaving
        notice._motion.setCurrentTime(70)
        assert notice.y() < anchored.y()
        progress = notice._progress
        notice.show_offer(offer)
        assert not notice._leaving and notice._progress == progress
        QTest.qWait(210)
        assert notice.isVisible() and notice.pos() == anchored
        activated = []
        notice.activated.connect(lambda: activated.append(True))
        QTest.mouseClick(notice.action, Qt.LeftButton)
        assert activated == [True] and not notice.isVisible()
        assert notice._motion.state() != QAbstractAnimation.Running
        with patch.object(motion, "enabled", return_value=False):
            notice.show_offer(offer)
            assert notice._progress == 1 and notice._motion.state() != QAbstractAnimation.Running
            notice.dismiss()
            assert not notice.isVisible()
        notice.show_offer(offer)
        parent.hide()
        app.processEvents()
        assert not notice.isVisible() and notice._motion.state() != QAbstractAnimation.Running
        parent.close()
    print("PASS: settings fade, folder reflow in both orientations, notice entry/exit, interruption and reduced motion")


if __name__ == "__main__":
    main()
