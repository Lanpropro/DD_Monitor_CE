"""按钮按下反馈：绘制颜色、固定几何、拖出取消、键盘和禁用状态。"""
import os
from pathlib import Path
import sys

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget
from ddm import theme


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    window = QWidget()
    layout = QHBoxLayout(window)
    for name in ("IconButton", "PrimaryButton"):
        button = QPushButton("保存", window)
        button.setObjectName(name)
        button.setFixedSize(180, 44)
        layout.addWidget(button)
    window.show()
    app.processEvents()
    for button in window.findChildren(QPushButton):
        name = button.objectName()
        clicks = []
        button.clicked.connect(lambda checked=False: clicks.append(checked))
        geometry = button.geometry()
        sample = QPoint(button.width() - 20, button.height() // 2)
        def color():
            return button.grab().toImage().pixelColor(sample)
        QTest.mouseMove(button, button.rect().center())
        app.processEvents()
        normal = color()
        QTest.mousePress(button, Qt.LeftButton)
        assert button.isDown() and button.geometry() == geometry
        expected = theme.mix(theme.CONTENT if name == "IconButton" else theme.ACCENT,
                             "#000000", 0.12 if name == "IconButton" else 0.16)
        assert color() == QColor(expected), (name, color().name(), expected)
        QTest.mouseRelease(button, Qt.LeftButton)
        app.processEvents()
        assert clicks == [False] and not button.isDown() and button.geometry() == geometry
        assert color() == normal, (name, color().name(), normal.name())
        QTest.mousePress(button, Qt.LeftButton)
        QTest.mouseRelease(button, Qt.LeftButton, pos=QPoint(-8, -8))
        assert len(clicks) == 1 and not button.isDown()
        button.setFocus()
        QTest.keyPress(button, Qt.Key_Space)
        assert button.isDown() and color() == QColor(expected)
        QTest.keyRelease(button, Qt.Key_Space)
        assert len(clicks) == 2 and not button.isDown()
        button.setCheckable(True)
        QTest.mouseClick(button, Qt.LeftButton)
        assert button.isChecked() and clicks[-1] is True
        checked_color = color()
        QTest.mousePress(button, Qt.LeftButton)
        assert color() == QColor(expected)
        QTest.mouseRelease(button, Qt.LeftButton, pos=QPoint(-8, -8))
        assert button.isChecked() and color() == checked_color
        button.setEnabled(False)
        count = len(clicks)
        QTest.mouseClick(button, Qt.LeftButton)
        assert not button.isDown() and len(clicks) == count and button.geometry() == geometry
    window.close()
    print("PASS: pressed colors, stable geometry, release/cancel, keyboard, checked and disabled buttons")


if __name__ == "__main__":
    main()
