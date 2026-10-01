"""回归：关注栏和布局按钮鼠标点击不留焦点框，键盘仍可聚焦和激活。"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import theme  # noqa: E402
from ddm.widgets import LayoutPicker, Sidebar  # noqa: E402


def check_button(app, button):
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    button.clearFocus()
    QTest.mouseClick(button, Qt.LeftButton)
    app.processEvents()
    assert clicked, "鼠标点击必须仍能激活按钮"
    assert not button.hasFocus(), f"{button.text()} 鼠标点击不应留下焦点框"
    for _ in range(40):
        QTest.keyClick(button.window(), Qt.Key_Tab)
        app.processEvents()
        if button.hasFocus():
            break
    assert button.hasFocus(), "键盘操作必须能聚焦按钮"
    before = len(clicked)
    QTest.keyClick(button, Qt.Key_Space)
    app.processEvents()
    assert len(clicked) == before + 1, "空格键必须仍能激活按钮"
    button.clearFocus()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    sidebar = Sidebar([])
    sidebar.resize(280, 600)
    sidebar.show()
    sidebar.activateWindow()
    app.processEvents()
    for button in (sidebar.layout_button, sidebar.settings_button,
                   sidebar.import_button, sidebar.add_button):
        button.clicked.disconnect()  # 不打开设置、登录或添加窗口。
        check_button(app, button)
    sidebar.close()
    picker = LayoutPicker("corner")
    picker.show()
    picker.activateWindow()
    app.processEvents()
    for button in picker._tabs.values():
        check_button(app, button)
        assert button.isChecked(), "布局分类切换仍必须生效"
    picker.close()
    print("关注栏和布局页签的鼠标/键盘焦点：通过", flush=True)


if __name__ == "__main__":
    main()
