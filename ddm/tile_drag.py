"""Room-card drag visuals shared by wall gestures and native fallback windows."""
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPixmap

from . import motion, theme
from .corner_geometry import continuous_path


def tile_drag_visual(tile, position):
    sidebar = getattr(tile.window(), 'sidebar', None)
    room_id = str(tile.room.get('room_id') or '')
    item = next((item for item in sidebar.items()
                 if str(item.room.get('room_id')) == room_id), None) if sidebar is not None else None
    if item is not None:
        snapshot = item._drag_pixmap()
    else:
        ratio = tile.devicePixelRatioF()
        snapshot = QPixmap(round(240 * ratio), round(104 * ratio))
        snapshot.setDevicePixelRatio(ratio)
        snapshot.fill(Qt.transparent)
        painter = QPainter(snapshot)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(0, 0, 240, 104)
        painter.setClipPath(continuous_path(bounds, theme.RADIUS_MD))
        painter.fillRect(bounds, theme.qcolor(theme.ELEVATED))
        cover = getattr(tile, '_cover_source', None)
        if isinstance(cover, QPixmap) and not cover.isNull():
            painter.drawPixmap(bounds, cover, QRectF(cover.rect()))
            painter.fillRect(bounds, theme.qcolor('#a0101114'))
        painter.setPen(theme.qcolor(theme.TEXT1))
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(14, 15, 212, 28), Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(str(tile.room.get('uname') or room_id), Qt.ElideRight, 212))
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(theme.qcolor(theme.TEXT2))
        painter.drawText(QRectF(14, 48, 212, 40), Qt.TextWordWrap,
                         painter.fontMetrics().elidedText(str(tile.room.get('title') or ''), Qt.ElideRight, 424))
        painter.end()
    size = snapshot.deviceIndependentSize()
    hotspot = QPoint(round(size.width() * min(1, max(0, position.x() / max(1, tile.width())))),
                     round(size.height() * min(1, max(0, position.y() / max(1, tile.height())))))
    snapshot, hotspot = motion.lifted_drag(snapshot, hotspot)
    return getattr(sidebar, 'drag_session', None), snapshot, hotspot
