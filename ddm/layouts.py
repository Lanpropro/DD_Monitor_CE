"""画面墙布局方案。

每个方案用 (rows, cols, cells) 描述，cells 是 [(row, col, rowspan, colspan), ...]，
cells 的数量就是这个方案一屏能放几路；多出来的窗口按同样的列数继续往下排。
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

from . import theme


def even_cells(rows: int, cols: int) -> list[tuple[int, int, int, int]]:
    return [(row, col, 1, 1) for row in range(rows) for col in range(cols)]


def main_plus_side(count: int) -> tuple[int, int, list]:
    """左侧主画面 + 右侧一列小窗。"""
    rows = max(1, count)
    cells = [(0, 0, rows, 2)] + [(row, 2, 1, 1) for row in range(rows)]
    return rows, 3, cells


def danmaku_side(count: int) -> tuple[int, int, list]:
    """左侧主画面 + 右侧一列小窗（count 个，含弹幕那一格）。"""
    rows = max(2, count)
    cells = [(0, 0, rows, 2)] + [(row, 2, 1, 1) for row in range(rows)]
    return rows, 3, cells


LAYOUTS: list[dict] = [
    {"id": "auto", "name": "自动", "spec": None,
     "hint": "按窗口大小自动决定行列"},
    {"id": "1x1", "name": "单画面", "spec": (1, 1, even_cells(1, 1))},
    {"id": "2x1", "name": "上下两分", "spec": (2, 1, even_cells(2, 1))},
    {"id": "1x2", "name": "左右两分", "spec": (1, 2, even_cells(1, 2))},
    {"id": "2x2", "name": "四分", "spec": (2, 2, even_cells(2, 2))},
    {"id": "3x2", "name": "六分", "spec": (2, 3, even_cells(2, 3))},
    {"id": "3x3", "name": "九分", "spec": (3, 3, even_cells(3, 3))},
    {"id": "main2", "name": "主画面 + 2 小", "spec": main_plus_side(2)},
    {"id": "main3", "name": "主画面 + 3 小", "spec": main_plus_side(3)},
    {"id": "main4", "name": "主画面 + 4 小", "spec": main_plus_side(4)},
    {"id": "main6", "name": "主画面 + 6 小", "spec": main_plus_side(6)},
    {"id": "top1_2", "name": "上 1 大 + 下 2", "spec": (2, 2, [(0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1)])},
    {"id": "left2_right1", "name": "左 2 小 + 右 1 大", "spec": (2, 2, [(0, 0, 1, 1), (1, 0, 1, 1), (0, 1, 2, 1)])},
    {"id": "corner", "name": "一大 + 一圈小", "spec": (3, 3, [(0, 0, 2, 2), (0, 2, 1, 1), (1, 2, 1, 1), (2, 0, 1, 1), (2, 1, 1, 1), (2, 2, 1, 1)])},
    {"id": "two_rows", "name": "两大 + 侧 4 小", "spec": (4, 3, [(0, 0, 2, 2), (2, 0, 2, 2)] + [(row, 2, 1, 1) for row in range(4)])},
]

DANMAKU_LAYOUTS: list[dict] = [
    {"id": "dm_pair", "name": "主画面 + 弹幕",
     "hint": "左边一路直播，右边整格给弹幕",
     "spec": (1, 2, even_cells(1, 2)), "danmaku": 1},
    {"id": "dm_top", "name": "上 1 大 + 小 + 弹幕",
     "spec": (2, 2, [(0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1)]), "danmaku": 2},
    {"id": "dm_main2", "name": "主画面 + 1 小 + 弹幕",
     "spec": danmaku_side(2), "danmaku": 2},
    {"id": "dm_main3", "name": "主画面 + 2 小 + 弹幕",
     "spec": danmaku_side(3), "danmaku": 3},
    {"id": "dm_main4", "name": "主画面 + 3 小 + 弹幕",
     "spec": danmaku_side(4), "danmaku": 4},
    {"id": "dm_left", "name": "弹幕在左 + 主画面 + 2 小",
     "spec": (2, 3, [(0, 0, 2, 1), (0, 1, 2, 1), (0, 2, 1, 1), (1, 2, 1, 1)]),
     "danmaku": 0},
]

# 布局菜单里的两个子菜单，用顶部的按钮来回切
GROUPS: list[tuple[str, list[dict]]] = [("普通布局", LAYOUTS), ("弹幕布局", DANMAKU_LAYOUTS)]

BY_ID = {layout["id"]: layout for layout in LAYOUTS + DANMAKU_LAYOUTS}


def danmaku_cell(layout_id: str) -> int | None:
    """这个布局里哪一格是弹幕格；普通布局返回 None。"""
    layout = BY_ID.get(layout_id)
    return None if not layout else layout.get("danmaku")


def thumbnail(spec, size=(52, 34), danmaku: int | None = None) -> QPixmap:
    """把布局画成缩略图。spec 为 None 时画成虚线自动网格，danmaku 是弹幕格下标。"""
    width, height = size
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    cells, rows, cols = [], 2, 2
    if spec:
        rows, cols, cells = spec
    else:
        cells = even_cells(2, 2)

    padding = 2.0
    gap = 2.0
    cell_width = (width - padding * 2 - gap * (cols - 1)) / cols
    cell_height = (height - padding * 2 - gap * (rows - 1)) / rows
    for index, (row, col, rowspan, colspan) in enumerate(cells):
        x = padding + col * (cell_width + gap)
        y = padding + row * (cell_height + gap)
        w = cell_width * colspan + gap * (colspan - 1)
        h = cell_height * rowspan + gap * (rowspan - 1)
        if spec and index == danmaku:
            # 弹幕格：主题色描边 + 三道横线
            painter.setBrush(QColor(theme.ACCENT_SOFT))
            painter.setPen(QPen(QColor(theme.ACCENT), 1))
            painter.drawRoundedRect(QRectF(x, y, w, h), 2.0, 2.0)
            painter.setPen(QPen(QColor(theme.TEXT3), 1))
            for line in range(3):
                line_y = y + h * (0.3 + line * 0.2)
                painter.drawRect(QRectF(x + 2, line_y, max(1.0, w - 4), 1.0))
            continue
        if spec:
            painter.setBrush(QColor(theme.CONTENT_HOVER))
            painter.setPen(QPen(QColor(theme.BORDER), 1))
        else:
            painter.setBrush(QColor(theme.ACCENT_SOFT))
            pen = QPen(QColor(theme.ACCENT), 1, Qt.DashLine)
            painter.setPen(pen)
        painter.drawRoundedRect(QRectF(x, y, w, h), 2.0, 2.0)
    painter.end()
    return pixmap
