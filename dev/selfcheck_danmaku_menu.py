"""弹幕文本右键菜单：中文、复制、全选、链接复制。不联网。"""
import os
import sys
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QContextMenuEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm.widgets import DanmakuTextBrowser  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    body = DanmakuTextBrowser()
    body.resize(400, 200)
    body.show()
    app.processEvents()
    position = QPoint(8, 8)

    def open_menu(check):
        class TestMenu(QMenu):
            def exec(self, _pos):
                check(self.actions())

        event = QContextMenuEvent(QContextMenuEvent.Mouse, position,
                                 body.viewport().mapToGlobal(position))
        with patch("ddm.widgets.QMenu", TestMenu):
            body.contextMenuEvent(event)

    def check_empty(actions):
        assert [a.text() for a in actions] == ["复制", "", "全选"]
        assert not actions[0].isEnabled()
        assert not actions[-1].isEnabled()
        assert actions[0].shortcut() == QKeySequence(QKeySequence.Copy)
        assert actions[-1].shortcut() == QKeySequence(QKeySequence.SelectAll)

    open_menu(check_empty)
    body.setPlainText("主播：测试弹幕")

    def check_select(actions):
        assert not actions[0].isEnabled()
        assert actions[-1].isEnabled()
        actions[-1].trigger()
        assert body.textCursor().selectedText() == "主播：测试弹幕"

    open_menu(check_select)

    def check_copy(actions):
        assert actions[0].isEnabled()
        actions[0].trigger()
        assert app.clipboard().text() == "主播：测试弹幕"

    open_menu(check_copy)
    body.setHtml('<a href="https://live.bilibili.com/123">测试链接</a>')
    app.processEvents()
    assert body.anchorAt(position) == "https://live.bilibili.com/123"

    def check_link(actions):
        assert [a.text() for a in actions] == ["复制", "复制链接地址", "", "全选"]
        actions[1].trigger()
        assert app.clipboard().text() == "https://live.bilibili.com/123"

    open_menu(check_link)
    body.close()
    print("Danmaku context menu checks passed")


if __name__ == "__main__":
    main()
