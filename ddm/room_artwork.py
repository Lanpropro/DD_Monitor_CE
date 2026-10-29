"""主播卡片与通知共用的静态背景和平台标识。"""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene, QLabel, QWidget

from . import images
from .cover_focus import source_rect


def room_platform(room):
    room_id = str(room.get('room_id', ''))
    return 'bilibili' if room_id.isdigit() else (room.get('platform') or room_id.partition(':')[0])


def supports_banner(room):
    return room_platform(room) in ('bilibili', 'douyin')


class RoomArtwork:
    def __init__(self, rooms):
        self.room = dict(rooms[0]) if len(rooms) == 1 else {}
        room_id = str(self.room.get('room_id', ''))
        self.banner = images.load_room_banner(room_id) if supports_banner(self.room) else None
        self.cover = (images.load_cached_image(self.room.get('cover_url', ''), 'covers')
                      or images.load_room_cover(room_id)) if room_id else None
        self._frosted_key = None
        self._frosted = None

    @property
    def source(self):
        return self.banner if self.banner is not None else self.cover

    def frosted(self, radius=16):
        source = self.source
        if source is None or radius == 0:
            return None
        key = (source.cacheKey(), radius)
        if self._frosted_key != key:
            from PySide6.QtGui import QPixmap
            # Blur only the static artwork once; text and avatars stay sharp.
            small = source.scaled(960, 540, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scene = QGraphicsScene()
            item = QGraphicsPixmapItem(small)
            effect = QGraphicsBlurEffect()
            effect.setBlurRadius(radius)
            item.setGraphicsEffect(effect)
            scene.addItem(item)
            blurred = QPixmap(small.size())
            blurred.fill(Qt.transparent)
            painter = QPainter(blurred)
            painter.drawPixmap(0, 0, small)
            scene.render(painter, QRectF(blurred.rect()), QRectF(small.rect()))
            painter.end()
            self._frosted = blurred.scaled(source.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._frosted_key = key
        return self._frosted

    def set_image(self, room_id, pixmap, kind):
        if str(self.room.get('room_id', '')) != str(room_id):
            return False
        if kind == 'banners':
            if not supports_banner(self.room):
                return False
            self.banner = None if pixmap.isNull() else pixmap
        else:
            if pixmap.isNull():
                return False
            self.cover = pixmap
        return True


def notice_frost(widget, artwork):
    from .config import DEFAULT_SETTINGS
    while widget is not None:
        settings = getattr(widget, 'settings', None)
        if isinstance(settings, dict):
            return artwork.frosted(max(0, min(40, int(settings.get(
                'notice_banner_blur', DEFAULT_SETTINGS['notice_banner_blur'])))))
        widget = widget.parentWidget()
    return artwork.frosted(DEFAULT_SETTINGS['notice_banner_blur'])


def paint_room_background(painter, rect, pixmap, radius, *, focus=True, frost=None):
    """等比裁切，封面优先保留人脸，文字区压暗。"""
    rect = QRectF(rect)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.setClipPath(clip)
    source = source_rect(pixmap, rect.width(), rect.height(), focus=focus)
    painter.drawPixmap(rect, frost if frost is not None else pixmap, source)
    if frost is not None:
        painter.fillRect(rect, QColor(225, 235, 245, 28))
    shade = QLinearGradient(rect.topLeft(), rect.topRight())
    shade.setColorAt(0, QColor(12, 19, 30, 200))
    shade.setColorAt(1, QColor(12, 19, 30, 72))
    painter.fillRect(rect, shade)
    footer = QLinearGradient(rect.bottomLeft(), rect.topLeft())
    footer.setColorAt(0, QColor(12, 19, 30, 110))
    footer.setColorAt(1, QColor(12, 19, 30, 0))
    painter.fillRect(rect, footer)
    painter.restore()


def style_room_notice(widget, artwork):
    widget.setProperty('roomBackdrop', artwork.source is not None)
    for child in [widget, *widget.findChildren(QWidget)]:
        child.style().unpolish(child)
        child.style().polish(child)
    widget.update()


def add_platform_logos(layout, rooms, parent):
    from .widgets import BRAND_ASSETS_DIR
    seen = set()
    for room in rooms[:3]:
        platform = room_platform(room)
        if not platform or platform in seen:
            continue
        seen.add(platform)
        path = Path(BRAND_ASSETS_DIR) / 'platforms' / ('huya.png' if platform == 'huya' else platform + '.ico')
        if not path.is_file():
            path = path.with_name('generic.svg')
        label = QLabel(parent)
        label.setObjectName('NoticePlatform')
        label.setFixedSize(18, 18)
        label.setPixmap(QIcon(str(path)).pixmap(16, 16))
        label.setAlignment(Qt.AlignCenter)
        label.setToolTip(platform)
        label.setAccessibleName(platform)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(label)
