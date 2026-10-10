from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QSplitter,
)

app = QApplication([])


def make_tile(text):
    tile = QLabel(text)
    tile.setAlignment(Qt.AlignCenter)
    tile.setMinimumSize(120, 80)
    return tile


window = QWidget()
window.setWindowTitle("一大五小：拖动分隔线")
window.resize(900, 600)
window.setStyleSheet("""
    QLabel {
        background: #263449;
        color: white;
        font-size: 22px;
        border: 1px solid #53657e;
    }
    QSplitter::handle {
        background: #718096;
    }
    QSplitter::handle:hover {
        background: #38bdf8;
    }
""")

# 右侧两路：暂时保持上下等分。
right = QWidget()
right_layout = QVBoxLayout(right)
right_layout.setContentsMargins(0, 0, 0, 0)
right_layout.addWidget(make_tile("小画面 1"))
right_layout.addWidget(make_tile("小画面 2"))

# 第一条分隔线：调整主画面和右侧区域的宽度。
top = QSplitter(Qt.Horizontal)
top.addWidget(make_tile("主画面测试"))
top.addWidget(right)
top.setChildrenCollapsible(False)
top.setHandleWidth(8)
top.setStretchFactor(0, 2)
top.setStretchFactor(1, 1)

# 底部三路：暂时保持左右等分。
bottom = QWidget()
bottom_layout = QHBoxLayout(bottom)
bottom_layout.setContentsMargins(0, 0, 0, 0)
for number in (3, 4, 5):
    bottom_layout.addWidget(make_tile(f"小画面 {number}"))

# 第二条分隔线：调整上部区域和底部区域的高度。
outer = QSplitter(Qt.Vertical)
outer.addWidget(top)
outer.addWidget(bottom)
outer.setChildrenCollapsible(False)
outer.setHandleWidth(8)
outer.setStretchFactor(0, 2)
outer.setStretchFactor(1, 1)

layout = QVBoxLayout(window)
layout.addWidget(outer)

window.show()
top.setSizes([600, 300])
outer.setSizes([400, 200])

app.exec()