"""Settings card material; only static artwork is blurred, never its controls."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene

from .. import theme
from ..corner_geometry import continuous_path


@lru_cache(maxsize=4)
def _frosted_image(path, modified, size):
    source = QPixmap(path)
    if source.isNull():
        return source
    # Follow notification artwork: cache the blur of the image, not a widget grab.
    source = source.scaled(960, 960, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(source)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(24)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    result = QPixmap(source.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.drawPixmap(0, 0, source)
    scene.render(painter, QRectF(result.rect()), QRectF(source.rect()))
    painter.end()
    return result


class SettingsSurface(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty('customControlSurface', True)
        theme.signals().changed.connect(self.update)

    def showEvent(self, event):
        super().showEvent(event)
        owner = self.parentWidget()
        while owner is not None:
            owner.installEventFilter(self)
            owner = owner.parentWidget()

    def eventFilter(self, owner, event):
        # Scrolling moves the content ancestor; resample the stationary artwork.
        if event.type() in (QEvent.Move, QEvent.Resize):
            self.update()
        return super().eventFilter(owner, event)

    def _backdrop(self):
        from ..skin_parts import part_for, resolve_values, values_for
        preview = getattr(self.window(), '_settings_material_preview', None)
        owner = self.parentWidget()
        while owner is not None:
            part = part_for(owner)
            if part in ('settings', 'settings.content', 'dialogs'):
                values = resolve_values(part, preview[1], preview[0]) if preview is not None else values_for(part)
                path = values.get('image')
                if path:
                    try:
                        stat = Path(path).stat()
                    except OSError:
                        return None
                    return owner, _frosted_image(path, stat.st_mtime_ns, stat.st_size)
                if QColor(values.get('background', '#00000000')).alpha() == 255:
                    return None
            owner = owner.parentWidget()
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -1.5)
        path = continuous_path(rect, theme.RADIUS_LG)
        painter.setClipPath(path)
        backdrop = self._backdrop()
        if backdrop is not None:
            owner, image = backdrop
            offset = self.mapTo(owner, QPoint())
            painter.drawPixmap(QRectF(-offset.x(), -offset.y(), owner.width(), owner.height()),
                               image, QRectF(image.rect()))
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        top, bottom = theme.qcolor(theme.CONTENT), theme.qcolor(theme.CONTENT)
        top.setAlpha(218 if theme.is_light() else 210)
        bottom.setAlpha(200 if theme.is_light() else 188)
        fill.setColorAt(0, top)
        fill.setColorAt(1, bottom)
        painter.fillPath(path, fill)
        sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        sheen.setColorAt(0, QColor(255, 255, 255, 24 if theme.is_light() else 12))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        painter.fillPath(path, sheen)
        painter.setClipping(False)
        edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        edge.setColorAt(0, QColor(255, 255, 255, 150 if theme.is_light() else 30))
        edge.setColorAt(1, QColor(0, 0, 0, 24))
        painter.setPen(QPen(edge, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
