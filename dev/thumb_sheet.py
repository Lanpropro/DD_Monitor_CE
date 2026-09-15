"""把每个布局的缩略图放大排成一张对照图，方便看清弹幕条画在哪。"""
import os
import sys

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import layouts, theme  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    columns = 6
    cell = QSize(150, 100)
    pad = 14
    all_layouts = [item for _name, group in layouts.GROUPS for item in group]
    rows = (len(all_layouts) + columns - 1) // columns
    sheet = QPixmap(columns * (cell.width() + pad) + pad,
                    rows * (cell.height() + 40) + pad)
    sheet.fill(QColor(theme.BG))
    painter = QPainter(sheet)
    painter.setFont(QFont("Microsoft YaHei UI", 9))
    for index, layout in enumerate(all_layouts):
        row, col = divmod(index, columns)
        x = pad + col * (cell.width() + pad)
        y = pad + row * (cell.height() + 40)
        painter.drawPixmap(
            x, y,
            layouts.thumbnail(layout["spec"], size=(cell.width(), cell.height()),
                              danmaku=layout.get("danmaku")))
        painter.setPen(QColor(theme.TEXT2))
        name = layout["name"] if layout.get("danmaku") is None else "★ " + layout["name"]
        painter.drawText(x, y + cell.height() + 16, name)
    painter.end()
    out = os.path.join(REPO, "dev", "preview", "thumb_sheet.png")
    sheet.save(out, "PNG")
    print("已保存", out, sheet.width(), sheet.height())


if __name__ == "__main__":
    main()
