"""Paint a released room card into its video surface without moving the player."""
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from . import motion, theme
from .corner_geometry import continuous_path

DURATION_MS = 280
LOAD_SINK_MS = 1200
REVEAL_MS = 160
PIXMAP_PROPERTY = '_ddm_card_pixmap'
HOTSPOT_PROPERTY = '_ddm_card_hotspot'


def remember_card(mime, pixmap, hotspot):
    """Keep the existing drag image shared until the accepted drop is handled."""
    mime.setProperty(PIXMAP_PROPERTY, pixmap)
    mime.setProperty(HOTSPOT_PROPERTY, QPoint(hotspot))


def play_card_drop(tile, mime, position, room_id):
    if not isValid(tile):
        return None
    if str(tile.room.get('room_id')) != room_id:
        # A hot swap moves the incoming widget into the original drop position.
        tile = next((candidate for candidate in tile.window().findChildren(type(tile))
                     if str(candidate.room.get('room_id')) == room_id and
                     QRect(candidate.mapToGlobal(QPoint()), candidate.size()).contains(position)), None)
    if tile is None or not tile.isVisible():
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
    if overlay.waiting:
        tile.spinner.stop()
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
        cover = getattr(tile, '_cover_source', None)
        self.cover = QPixmap(cover) if isinstance(cover, QPixmap) else QPixmap()
        self.room_id = str(tile.room.get('room_id'))
        self.progress = 0.0
        self.started = time.monotonic()
        self.waiting = bool(getattr(tile, '_connecting', False) and not getattr(tile, '_player_active', False))
        self.loading_bridge = self.waiting
        self.reveal_started = None
        self.reveal_from = 0.0
        self.fade = 0.0
        self.finished = False
        source = QRect(position - hotspot, pixmap.deviceIndependentSize().toSize())
        target = QRect(tile.video.mapToGlobal(QPoint()), tile.video.size())
        bounds = source.united(target)
        self.setGeometry(bounds)
        self.source = QRectF(source.translated(-bounds.topLeft()))
        self.target = QRectF(target.translated(-bounds.topLeft()))
        self.spinner = tile.spinner
        self.watched = (tile, tile.video, tile.window(), self.spinner)
        for widget in self.watched:
            widget.installEventFilter(self)
        tile.destroyed.connect(self.finish)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.advance)

    def advance(self):
        if self.finished:
            return
        now = time.monotonic()
        if str(self.tile.room.get('room_id')) != self.room_id:
            self.finish()
            return
        if self.waiting:
            if getattr(self.tile, '_player_active', False):
                self.waiting = False
                self.reveal_started, self.reveal_from = now, self.progress
            elif not getattr(self.tile, '_connecting', False):
                self.finish()
                return
            else:
                phase = min(1.0, (now - self.started) * 1000 / LOAD_SINK_MS)
                progress = .82 * phase
                if progress != self.progress:
                    self.progress = progress
                    self.update()
                return
        if self.reveal_started is not None:
            self.fade = min(1.0, (now - self.reveal_started) * 1000 / REVEAL_MS)
            self.progress = self.reveal_from + (1 - self.reveal_from) * self.fade
        else:
            self.progress = self.fade = min(1.0, (now - self.started) * 1000 / DURATION_MS)
        if self.fade >= 1.0:
            self.finish()
            return
        self.update()

    def card_rect(self):
        p = motion.THEME_WAVE_EASING.valueForProgress(self.progress)
        source, target = self.source, self.target
        scale = min(.94, target.width() * .82 / source.width(), target.height() * .75 / source.height())
        destination = QRectF(0, 0, source.width() * scale, source.height() * scale)
        destination.moveCenter(target.center() + QPointF(0, min(18, target.height() * .07)))
        return QRectF(source.x() + (destination.x() - source.x()) * p,
                      source.y() + (destination.y() - source.y()) * p,
                      source.width() + (destination.width() - source.width()) * p,
                      source.height() + (destination.height() - source.height()) * p)

    def _draw_image(self, painter, image, rect):
        size = image.deviceIndependentSize()
        scale = max(rect.width() / size.width(), rect.height() / size.height())
        destination = QRectF(0, 0, size.width() * scale, size.height() * scale)
        destination.moveCenter(rect.center())
        painter.drawPixmap(destination, image, QRectF(image.rect()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if self.loading_bridge:
            painter.save()
            painter.setClipPath(continuous_path(self.target, 8))
            painter.setOpacity(1 - self.fade)
            painter.fillRect(self.target, theme.qcolor(theme.TILE_BG))
            if not self.cover.isNull():
                self._draw_image(painter, self.cover, self.target)
            painter.restore()
        rect = self.card_rect()
        painter.save()
        painter.setClipPath(continuous_path(rect, 12))
        painter.setOpacity((1 - self.fade) * (1 - .45 * self.progress))
        # Crop the shared snapshot instead of stretching card text and avatars.
        self._draw_image(painter, self.snapshot, rect)
        painter.restore()

    def eventFilter(self, watched, event):
        if watched is self.spinner:
            if self.waiting and event.type() == QEvent.Show:
                self.spinner.stop()
            return False
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
        self.cover = QPixmap()
        self.hide()
        if isValid(self.tile) and self.tile.isVisible() and getattr(self.tile, '_connecting', False):
            self.spinner.start()
        self.deleteLater()
