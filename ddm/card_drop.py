"""Paint a released room card into its video surface without moving the player."""
import math
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from . import motion, theme
from .corner_geometry import continuous_path

DURATION_MS = 280
PIXMAP_PROPERTY = '_ddm_card_pixmap'
HOTSPOT_PROPERTY = '_ddm_card_hotspot'


def remember_card(mime, pixmap, hotspot):
    """Keep the existing drag image shared until the accepted drop is handled."""
    mime.setProperty(PIXMAP_PROPERTY, pixmap)
    mime.setProperty(HOTSPOT_PROPERTY, QPoint(hotspot))


def play_card_drop(tile, mime, position, room_id):
    if not isValid(tile) or not tile.isVisible() or str(tile.room.get('room_id')) != room_id:
        return None
    previous = getattr(tile, '_card_drop_overlay', None)
    if previous is not None:
        previous.finish()
    pixmap = mime.property(PIXMAP_PROPERTY)
    hotspot = mime.property(HOTSPOT_PROPERTY)
    if not motion.enabled() or not isinstance(pixmap, QPixmap) or pixmap.isNull():
        return None
    overlay = CardDropOverlay(tile, pixmap, position, hotspot)
    tile._card_drop_overlay = overlay
    overlay.show()
    overlay.raise_()
    overlay.timer.start()
    return overlay


class CardDropOverlay(QWidget):
    def __init__(self, tile, pixmap, position, hotspot):
        super().__init__(tile.window(), Qt.Tool | Qt.FramelessWindowHint |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setObjectName('CardDropOverlay')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.tile = tile
        self.snapshot = QPixmap(pixmap)
        self.progress = 0.0
        self.started = time.monotonic()
        self.finished = False
        source = QRect(position - hotspot, pixmap.deviceIndependentSize().toSize())
        target = QRect(tile.video.mapToGlobal(QPoint()), tile.video.size())
        bounds = source.united(target)
        self.setGeometry(bounds)
        self.source = QRectF(source.translated(-bounds.topLeft()))
        self.target = QRectF(target.translated(-bounds.topLeft()))
        self.origin = QPointF(position - bounds.topLeft())
        self.watched = (tile, tile.video, tile.window())
        for widget in self.watched:
            widget.installEventFilter(self)
        tile.destroyed.connect(self.finish)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.advance)

    def advance(self):
        self.progress = min(1.0, (time.monotonic() - self.started) * 1000 / DURATION_MS)
        if self.progress >= 1.0:
            self.finish()
        else:
            self.update()

    def card_rect(self):
        p = motion.THEME_WAVE_EASING.valueForProgress(self.progress)
        source, target = self.source, self.target
        rect = QRectF(source.x() + (target.x() - source.x()) * p,
                      source.y() + (target.y() - source.y()) * p,
                      source.width() + (target.width() - source.width()) * p,
                      source.height() + (target.height() - source.height()) * p)
        depth = math.sin(math.pi * self.progress)
        inset = min(rect.width(), rect.height()) * .035 * depth
        rect.adjust(inset, inset, -inset, -inset)
        rect.translate(0, min(14, target.height() * .04) * depth)
        return rect

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p = self.progress
        rect = self.card_rect()
        painter.save()
        painter.setClipPath(continuous_path(rect, 12 - 4 * p))
        painter.setOpacity(1 - motion.THEME_WAVE_EASING.valueForProgress(p))
        # Crop the shared snapshot instead of stretching card text and avatars.
        size = self.snapshot.deviceIndependentSize()
        scale = max(rect.width() / size.width(), rect.height() / size.height())
        image = QRectF(0, 0, size.width() * scale, size.height() * scale)
        image.moveCenter(rect.center())
        painter.drawPixmap(image, self.snapshot, QRectF(self.snapshot.rect()))
        painter.restore()
        painter.setClipPath(continuous_path(self.target, 8))
        color = theme.qcolor(theme.ACCENT)
        color.setAlphaF(.22 * (1 - p))
        painter.setPen(QPen(color, 1.5))
        painter.setBrush(Qt.NoBrush)
        radius = 16 + max(self.target.width(), self.target.height()) * .65 * p
        for factor in (1.0, .72):
            painter.drawEllipse(self.origin, radius * factor, radius * factor * .65)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Hide, QEvent.Close, QEvent.Move, QEvent.Resize,
                            QEvent.WindowDeactivate, QEvent.DeferredDelete):
            self.finish()
        return False

    def finish(self, *_args):
        if self.finished:
            return
        self.finished = True
        self.timer.stop()
        for widget in self.watched:
            if isValid(widget):
                widget.removeEventFilter(self)
        if isValid(self.tile):
            self.tile.destroyed.disconnect(self.finish)
            if getattr(self.tile, '_card_drop_overlay', None) is self:
                self.tile._card_drop_overlay = None
        self.snapshot = QPixmap()
        self.hide()
        self.deleteLater()
