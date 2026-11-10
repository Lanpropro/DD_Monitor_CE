"""Thumbnail choices for already imported local backgrounds."""
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QListView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from . import theme
from .settings_material import base_color


class _GalleryDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        if not option.state & QStyle.State_Enabled:
            painter.setOpacity(.45)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect).adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.State_Selected)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if selected else theme.BORDER), 2 if selected else 1))
        painter.setBrush(theme.qcolor(base_color(option.widget, 'control', theme.CONTENT)))
        painter.drawRoundedRect(rect, 8, 8)
        icon = index.data(Qt.DecorationRole)
        if icon:
            icon.paint(painter, rect.adjusted(5, 4, -5, -23).toRect(), Qt.AlignCenter)
        painter.setPen(theme.qcolor(theme.ACCENT if selected else theme.TEXT2))
        painter.drawText(rect.adjusted(4, rect.height() - 21, -4, -1), Qt.AlignCenter,
                         option.fontMetrics.elidedText(str(index.data()), Qt.ElideRight, int(rect.width() - 8)))
        painter.restore()


class SkinGallery(QListWidget):
    selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName('本地背景图库')
        self.setViewMode(QListView.IconMode)
        self.setItemDelegate(_GalleryDelegate(self))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setIconSize(QSize(88, 56))
        self.setGridSize(QSize(106, 84))
        self.setSpacing(3)
        self.setFixedHeight(180)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.itemClicked.connect(lambda item: self.selected.emit(item.data(Qt.UserRole)))
        self.itemActivated.connect(lambda item: self.selected.emit(item.data(Qt.UserRole)))
        self._current = ''
        self._loaded = False

    def refresh(self):
        from . import config
        from .skins import IMAGES, VIDEOS
        root = Path(config.data_root())
        folder = root / 'utils/skins'
        self.clear()
        item = QListWidgetItem(self.style().standardIcon(QStyle.SP_FileIcon), '默认背景', self)
        item.setData(Qt.UserRole, '')
        paths = sorted(folder.iterdir(), key=lambda path: path.name) if folder.is_dir() else []
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in IMAGES | VIDEOS:
                continue
            name = path.name
            prefix, separator, suffix = name.partition('_')
            if separator and len(prefix) == 32 and all(c in '0123456789abcdef' for c in prefix):
                name = suffix
            icon = self.style().standardIcon(QStyle.SP_MediaPlay if path.suffix.lower() in VIDEOS else QStyle.SP_FileIcon)
            if path.suffix.lower() in IMAGES:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    reader.setScaledSize(size.scaled(176, 112, Qt.KeepAspectRatio))
                image = reader.read()
                if not image.isNull():
                    icon = QIcon(QPixmap.fromImage(image))
            item = QListWidgetItem(icon, name, self)
            item.setToolTip(name)
            item.setData(Qt.UserRole, path.relative_to(root).as_posix())
        self._loaded = True
        self.set_current(self._current)

    def set_current(self, path):
        self._current = path
        if self._loaded:
            self.clearSelection()
            for index in range(self.count()):
                item = self.item(index)
                if item.data(Qt.UserRole) == path:
                    self.setCurrentItem(item)
                    break

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self.refresh()
