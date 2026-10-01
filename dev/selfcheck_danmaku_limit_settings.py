"""Default retention and the settings controls must allow more than 2000 messages."""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ddm import config
from ddm.dialogs import DanmakuSettingsPage
from ddm.widgets import DanmakuPanel


def main():
    app = QApplication(sys.argv)
    assert config.DEFAULT_SETTINGS["danmaku_max_blocks"] == 3000
    panel = DanmakuPanel()
    assert panel.max_blocks == panel.body.document().maximumBlockCount() == 3000
    for index in range(3001):
        panel.add_message(f"user{index}", "retained message")
    app.processEvents()
    assert len(panel._blocks) == panel.body.document().blockCount() == 3000
    assert "user0：" not in panel.body.toPlainText()
    assert "user3000：" in panel.body.toPlainText()
    page = DanmakuSettingsPage({})
    page.show()
    app.processEvents()
    assert page.keep_spin.value() == 3000
    buttons = {button.toolTip(): button for button in page.findChildren(QPushButton)}
    QTest.mouseClick(buttons["多留一些"], Qt.LeftButton)
    assert page.keep_spin.value() == 3050
    QTest.mouseClick(buttons["少留一些"], Qt.LeftButton)
    assert page.keep_spin.value() == 3000
    page.keep_spin.lineEdit().selectAll()
    QTest.keyClicks(page.keep_spin.lineEdit(), "4000")
    page.keep_spin.interpretText()
    values = page.values()
    assert values["danmaku_max_blocks"] == 4000
    panel.set_max_blocks(values["danmaku_max_blocks"])
    assert panel.body.document().maximumBlockCount() == 4000
    reopened = DanmakuSettingsPage(values)
    assert reopened.keep_spin.value() == 4000
    existing = DanmakuSettingsPage({"danmaku_max_blocks": 300})
    assert existing.keep_spin.value() == 300
    page.reset()
    assert page.keep_spin.value() == 3000
    page.close()
    print("3000 default, step buttons, typed values, restore and saved preference passed")


if __name__ == "__main__":
    main()
