"""Chat document text escaping and medal image formatting."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap
from . import theme
from .corner_geometry import continuous_path


def _brightness(color: str) -> int:
    """这个颜色够不够亮（用来决定徽章上写黑字还是白字）。"""
    text = str(color).lstrip("#")
    if len(text) != 6:
        return 0
    try:
        red, green, blue = (int(text[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return 0
    return (red * 299 + green * 587 + blue * 114) // 1000


def _medal_chip(name: str, level: str, color: str, font_size: int) -> QPixmap:
    """粉丝牌底：圆角小色块 + 名字和等级。

    QTextDocument 的富文本不支持圆角，所以直接把牌子画成图片贴进弹幕行里。
    """
    font = QFont(theme.FONT_DEFAULT)
    font.setPixelSize(max(8, round(font_size * 0.82)))
    font.setBold(True)
    text = f"{name}{level}"
    metrics = QFontMetrics(font)
    padding = max(4, round(font_size * 0.42))
    height = max(12, round(font_size * 1.45))
    width = metrics.horizontalAdvance(text) + padding * 2
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    radius = max(3.0, height * 0.28)
    path = QPainterPath()
    path.addPath(continuous_path(QRectF(0, 0, width, height), radius))
    painter.fillPath(path, QColor(color))
    painter.setPen(QColor("#14161a" if _brightness(color) > 150 else "#ffffff"))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, width, height), int(Qt.AlignCenter), text)
    painter.end()
    return pixmap


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
