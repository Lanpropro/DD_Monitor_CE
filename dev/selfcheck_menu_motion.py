"""右键菜单动效：原生弹出、边缘、中间帧、选项点击、键盘与系统动画开关。"""
import os
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import motion, theme
from ddm.widgets import Sidebar


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    owner = QWidget()
    owner.resize(400, 300)
    owner.show()
    app.processEvents()
    menu = motion.AnimatedMenu(owner)
    action = menu.addAction("测试操作")
    menu.addAction("其他操作")
    failures = []

    def run(reason, point, check):
        effects = (Qt.UI_FadeMenu, Qt.UI_AnimateMenu)
        previous = [QApplication.isEffectEnabled(effect) for effect in effects]
        timer = QTimer(menu)
        timer.setSingleShot(True)
        def inspect():
            try:
                check()
            except Exception:
                failures.append(traceback.format_exc())
            finally:
                menu.close()
        timer.timeout.connect(inspect)
        timer.start(20)
        event = QContextMenuEvent(reason, QPoint(), point)
        result = menu.exec_context(event)
        timer.stop()
        timer.deleteLater()
        assert not failures, failures
        assert menu._entrance.state() != QAbstractAnimation.Running
        assert menu.windowOpacity() == 1 and not menu.isVisible()
        assert [QApplication.isEffectEnabled(effect) for effect in effects] == previous
        return result

    with patch.object(motion, "enabled", return_value=True):
        bounds = owner.screen().availableGeometry()
        for point in (bounds.center(), bounds.bottomRight() - QPoint(2, 2)):
            def inspect_motion():
                assert menu._entrance.state() == QAbstractAnimation.Running
                assert menu._entrance.duration() == 160 and menu.windowOpacity() == 1, \
                    (menu._entrance.duration(), menu.windowOpacity())
                target = QPoint(menu._target)
                menu._entrance.setCurrentTime(0)
                start = menu.pos()
                assert abs(start.y() - target.y()) == 8
                assert bounds.contains(menu.geometry())
                menu._entrance.setCurrentTime(60)
                assert menu.pos() != target and menu.pos() != start
                assert bounds.contains(menu.geometry())
                menu._entrance.setCurrentTime(160)
                assert menu.pos() == target and menu.windowOpacity() == 1
            run(QContextMenuEvent.Mouse, point, inspect_motion)

        triggered = []
        action.triggered.connect(lambda: triggered.append(True))
        def click_during_entry():
            menu._entrance.setCurrentTime(40)
            position = QPoint(menu.pos())
            click = menu.actionGeometry(action).center()
            QTest.mousePress(menu, Qt.LeftButton, pos=click)
            assert menu.pos() == position and menu._entrance.state() != QAbstractAnimation.Running
            QTest.mouseRelease(menu, Qt.LeftButton, pos=click)
        assert run(QContextMenuEvent.Mouse, bounds.center(), click_during_entry) is action
        assert triggered == [True]

        def keyboard():
            assert menu._entrance.state() != QAbstractAnimation.Running
            menu.setActiveAction(action)
            QTest.keyClick(menu, Qt.Key_Return)
        assert run(QContextMenuEvent.Keyboard, bounds.center(), keyboard) is action
        assert triggered == [True, True]
        def escape():
            assert menu._entrance.state() == QAbstractAnimation.Running
            QTest.keyClick(menu, Qt.Key_Escape)
        run(QContextMenuEvent.Mouse, bounds.center(), escape)
        with patch.object(motion, "enabled", return_value=False):
            def disabled():
                assert menu._entrance.state() != QAbstractAnimation.Running
            run(QContextMenuEvent.Mouse, bounds.center(), disabled)

        sidebar = Sidebar([{"room_id": "1", "uname": "test", "live": False}], auto_compact=False)
        folder = sidebar.create_folder("Apex")
        assert isinstance(sidebar.items()[0]._context_menu(), motion.AnimatedMenu)
        assert isinstance(sidebar._folder_buttons[folder]._context_menu(), motion.AnimatedMenu)
        assert isinstance(sidebar._folder_create_menu(), motion.AnimatedMenu)
        sidebar.close()
    owner.close()
    print("PASS: native context-menu entry, screen bounds, opacity, click interruption, keyboard, Escape and reduced motion")


if __name__ == "__main__":
    main()
