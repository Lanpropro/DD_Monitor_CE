"""Super Chat avatar resource selection, lifetime and painting."""
from __future__ import annotations
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QTransform
from PySide6.QtWidgets import QApplication
from .images import AvatarLoader, load_cached_image


class SuperChatAvatar(QObject):
    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.url = ''
        self.pixmap = None
        self._loaders = {}

    def set_url(self, url):
        # Keep the established replaceable image providers on the public entry point.
        from .super_chat import AvatarLoader, load_cached_image
        url = str(url or '')
        if url == self.url:
            return
        self.url = url
        self.pixmap = load_cached_image(url, 'sc-avatars') if url else None
        self.changed.emit()
        if not url or self.pixmap is not None or url in self._loaders:
            return
        app = QApplication.instance()
        loader = AvatarLoader({url: url}, app, subdir='sc-avatars')
        self._loaders[url] = loader
        loader.loaded.connect(self._loaded)
        loader.finished.connect(lambda: self._loaders.pop(url, None))
        loader.finished.connect(loader.deleteLater)
        app.aboutToQuit.connect(loader.wait)
        loader.start()

    def _loaded(self, url, pixmap):
        if url == self.url and not pixmap.isNull():
            self.pixmap = pixmap
            self.changed.emit()


def paint_sc_avatar(painter, rect, pixmap, name):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setPen(Qt.NoPen)
    if pixmap is not None:
        brush = QBrush(pixmap)
        factor = max(rect.width() / pixmap.width(), rect.height() / pixmap.height())
        transform = QTransform()
        transform.translate(rect.center().x() - pixmap.width() * factor / 2,
                            rect.center().y() - pixmap.height() * factor / 2)
        transform.scale(factor, factor)
        brush.setTransform(transform)
        painter.setBrush(brush)
    else:
        painter.setBrush(QColor('#64748b'))
    painter.drawEllipse(rect)
    if pixmap is None:
        painter.setPen(QColor('white'))
        painter.drawText(rect, Qt.AlignCenter, (name or '?')[0])
    painter.restore()
