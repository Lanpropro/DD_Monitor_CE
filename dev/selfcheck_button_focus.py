"""回归：关注栏和布局按钮鼠标点击不留焦点框，键盘仍可聚焦和激活。"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import theme  # noqa: E402
from ddm.widgets import LayoutPicker, Sidebar, Tile  # noqa: E402


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
    owner = QWidget()
    layout = QVBoxLayout(owner)
    buttons = []
    for name in ('TileCtrl', 'TileToggle', 'BiliVolumeButton', 'DanmakuSendButton'):
        button = QPushButton('测试按钮')
        button.setObjectName(name)
        layout.addWidget(button)
        buttons.append(button)
    owner.show()
    owner.activateWindow()
    for mode in ('dark', 'light'):
        theme.apply(mode)
        app.processEvents()
        for button in buttons:
            button.clearFocus()
            app.processEvents()
            before = button.grab().toImage()
            button.setFocus(Qt.TabFocusReason)
            app.processEvents()
            assert button.hasFocus(), 'Removing the outline must preserve keyboard focus'
            assert before == button.grab().toImage(), (mode, button.objectName(), 'Focus must not add a frame')
            activated = []
            button.clicked.connect(lambda: activated.append(True))
            QTest.keyClick(button, Qt.Key_Space)
            assert activated, 'Keyboard activation must remain usable'
            button.clicked.disconnect()
    owner.close()
    tile = Tile({'room_id': '1001', 'uname': '测试', 'live': False})
    tile.resize(800, 450)
    tile.show()
    tile.activateWindow()
    tile.set_controls_visible(True)
    app.processEvents()
    for button in (tile.quality_button, tile.reload_button, tile.close_button,
                   tile.pause_button, tile.volume_button, tile.fullscreen_button,
                   tile.danmaku_button, tile.danmaku_settings_button, tile.recording_button):
        assert button.focusPolicy() == Qt.TabFocus
        button.clicked.disconnect()  # Keep this fixture free of popup menus and playback actions.
        tile.set_controls_visible(True)
        check_button(app, button)
        if button in (tile.pause_button, tile.recording_button):
            assert button.property('tileButton')
            def rendered_button():
                frame = tile.grab()
                factor = frame.devicePixelRatio()
                point = button.mapTo(tile, button.rect().topLeft())
                result = frame.toImage().copy(round(point.x() * factor), round(point.y() * factor),
                                             round(button.width() * factor), round(button.height() * factor))
                result.setDevicePixelRatio(factor)
                return result
            button.setProperty('hovered', True)
            button.style().unpolish(button)
            button.style().polish(button)
            for mode in ('dark', 'light'):
                theme.apply(mode)
                app.processEvents()
                for down in (False, True):
                    button.setDown(down)
                    button.clearFocus()
                    before = rendered_button()
                    QTest.keyClick(tile, Qt.Key_Tab)
                    button.setFocus(Qt.TabFocusReason)
                    after = rendered_button()
                    assert before != after, 'Tab focus must retain the white outline'
                    scale = after.devicePixelRatio()
                    top = [after.pixelColor(round(button.width() / 2 * scale), y) for y in range(max(4, round(4 * scale)))]
                    assert any(abs(pixel.red() - pixel.blue()) < 25 and pixel.red() > 180 for pixel in top), 'Tab outline must be white'
                    for x in range(after.width()):
                        for y in (0, 1, after.height() - 2, after.height() - 1):
                            edge = after.pixelColor(x, y)
                            assert edge.blue() - edge.red() < 25, 'Hover blue must not leak outside the white frame'
            button.setDown(False)
            button.setProperty('hovered', False)
    tile.close()
    print("关注栏和布局页签的鼠标/键盘焦点：通过", flush=True)


if __name__ == "__main__":
    main()
