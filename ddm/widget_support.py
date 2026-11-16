"""Shared widget geometry constants and drawing helpers; no component owners."""
import os
import sys
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from .corner_geometry import continuous_path


QUALITY_CHOICES = [("原画", 10000), ("蓝光", 400), ("超清 720P", 250), ("流畅", 80)]
QUALITY_NAMES = {value: name for name, value in QUALITY_CHOICES}
QUALITY_NAMES[20000] = "4K"

TILE_BAR_HEIGHT = 36          # 底部信息条高度（不覆盖画面）
TILE_MIME = "application/x-ddm-tile"
DANMAKU_MIME = "application/x-ddm-danmaku"

WATCHING_TEXT = "正在获取人数"   # 还没拉到实时在线人数时的占位（不能用"人气"顶上）
NAV_ITEM_HEIGHT = 128         # 展开时：206x116 左右，接近 16:9，悬停预览才看得清
NAV_LIST_ITEM_HEIGHT = 60     # 简洁模式：头像 + 两行文字
NAV_COMPACT_ITEM_HEIGHT = 60  # 收起时保持此前的头像间距和滚动手感
NAV_ITEM_GAP = 2              # 项与项之间的间距
CAROUSEL_WIDTH = 206          # 竖屏顶部横栏里横向卡片的宽度（和侧栏展开时一样宽）
PORTRAIT_LIST_WIDTH = 100     # 竖屏简洁模式：窄竖条，仍横向滚动
PORTRAIT_LIST_HEIGHT = NAV_ITEM_HEIGHT  # 竖屏展开栏恢复原 196px 高度
BRAND_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(sys.executable))
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
)



def _ignore_mouse(widget: QWidget) -> QWidget:
    widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    return widget


def _allow_shrink(label: QLabel) -> QLabel:
    """允许标签被压缩到比文本更窄，从而触发省略号。"""
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    label.setMinimumWidth(24)
    return label


def rounded_pixmap(source: QPixmap, size, radius: int) -> QPixmap:
    """圆角铺满的封面图（用于未开播时的占位）。"""
    scaled = source.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    result = QPixmap(size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addPath(continuous_path(QRectF(0, 0, size.width(), size.height()), radius))
    painter.setClipPath(path)
    painter.drawPixmap((size.width() - scaled.width()) // 2,
                       (size.height() - scaled.height()) // 2, scaled)
    painter.end()
    return result


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
