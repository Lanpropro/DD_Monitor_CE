"""Chat document text escaping and medal image formatting."""
from math import ceil

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap
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


def _medal_chip(name: str, level: str, color: str, font_size: int, *,
                font_family: str = '', dpr: float = 1.0) -> QPixmap:
    """粉丝牌底：圆角小色块 + 名字和等级。

    QTextDocument 的富文本不支持圆角，所以直接把牌子画成图片贴进弹幕行里。
    """
    font = theme.danmaku_font(font_family, max(8, round(font_size * 0.88)))
    font.setWeight(QFont.Weight.DemiBold)
    metrics = QFontMetricsF(font)
    padding = max(4, round(font_size * 0.42))
    height = max(12, round(font_size * 1.2))
    level_gap = "\u2002"  # 半个字宽，便于区分牌名末尾的数字和等级。
    content_width = ceil(metrics.horizontalAdvance(f"粉丝徽章{level_gap}99"))
    separator = level_gap if level else ""
    level = metrics.elidedText(level, Qt.ElideLeft, content_width - metrics.horizontalAdvance(separator))
    suffix = separator + level
    name_width = max(0, content_width - metrics.horizontalAdvance(suffix))
    text = metrics.elidedText(name, Qt.ElideRight, name_width) + suffix
    width = content_width + padding * 2
    pixmap = QPixmap(round(width * dpr), round(height * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    radius = max(3.0, height * 0.28)
    rect = QRectF(0, 0, width, height)
    painter.fillPath(continuous_path(rect, radius), QColor(color))
    painter.setPen(QColor("#14161a" if _brightness(color) > 150 else "#ffffff"))
    painter.setFont(font)
    painter.drawText(rect, int(Qt.AlignCenter), text)
    painter.end()
    return pixmap


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
