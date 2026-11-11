"""Thumbnail choices for already imported local backgrounds."""
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QImageReader, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QListView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from . import theme
from .settings_material import base_color
from .skin_settings import SkinAssetDropArea


def _paint_placeholder(painter, rect, kind):
    painter.setPen(QPen(theme.qcolor(theme.TEXT3), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    box = QRectF(rect.center().x() - 14, rect.center().y() - 11, 28, 22)
    painter.drawRoundedRect(box, 3, 3)
    painter.drawEllipse(box.topLeft() + QPointF(8, 7), 2, 2)
    if kind == '默认':
        painter.drawLine(box.topLeft(), box.bottomRight())
    else:
        painter.drawLine(int(box.center().x()), int(box.bottom() + 6), int(box.center().x()), int(box.bottom() - 7))
        painter.drawLine(int(box.center().x()), int(box.bottom() - 7), int(box.center().x() - 4), int(box.bottom() - 3))
        painter.drawLine(int(box.center().x()), int(box.bottom() - 7), int(box.center().x() + 4), int(box.bottom() - 3))


class _GalleryImportButton(SkinAssetDropArea):
    """Keep the existing file picker and drop contract inside a thumbnail slot."""
    def __init__(self, parent):
        super().__init__(parent, video=True)
        self.setAccessibleName('导入背景图片或视频')
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip('导入背景图片或视频\n点击选择文件，或将本地文件拖到这里')
        self.setMinimumHeight(0)
        self.setStyleSheet('background: transparent; border: none; padding: 0;')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(.45)
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        active = self.underMouse() or self.hasFocus() or self.property('dragging')
        painter.setPen(QPen(theme.qcolor(theme.ACCENT), 2) if active else Qt.NoPen)
        painter.setBrush(theme.qcolor(base_color(self, 'control', theme.CONTENT)))
        painter.drawRoundedRect(rect, 8, 8)
        _paint_placeholder(painter, rect, '导入')


class _GalleryDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = self.parent().gridSize()
        return size

    def paint(self, painter, option, index):
        painter.save()
        if not option.state & QStyle.State_Enabled:
            painter.setOpacity(.45)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(option.rect).adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.State_Selected)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(base_color(option.widget, 'control', theme.CONTENT)))
        painter.drawRoundedRect(rect, 8, 8)
        kind = index.data(Qt.UserRole + 1)
        if kind == '默认':
            _paint_placeholder(painter, rect, kind)
        elif kind == '视频':
            triangle = QPainterPath()
            triangle.moveTo(rect.center().x() - 8, rect.center().y() - 12)
            triangle.lineTo(rect.center().x() + 12, rect.center().y())
            triangle.lineTo(rect.center().x() - 8, rect.center().y() + 12)
            triangle.closeSubpath()
            painter.setBrush(theme.qcolor(theme.ACCENT))
            painter.setPen(Qt.NoPen)
            painter.drawPath(triangle)
        else:
            pixmap = index.data(Qt.UserRole + 2)
            if pixmap is not None and not pixmap.isNull():
                clip = QPainterPath()
                clip.addRoundedRect(rect, 8, 8)
                painter.save()
                painter.setClipPath(clip)
                scale = max(rect.width() / pixmap.width(), rect.height() / pixmap.height())
                source = QRectF(0, 0, rect.width() / scale, rect.height() / scale)
                source.moveCenter(QRectF(pixmap.rect()).center())
                painter.drawPixmap(rect, pixmap, source)
                painter.restore()
        painter.setBrush(Qt.NoBrush)
        if selected or option.state & QStyle.State_MouseOver:
            painter.setPen(QPen(theme.qcolor(theme.ACCENT if selected else theme.BORDER), 2))
            painter.drawRoundedRect(rect, 8, 8)
        painter.restore()


class SkinGallery(QListWidget):
    selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName('本地背景图库')
        self.setStyleSheet('QListWidget {background: transparent; border: none;}')
        self.setViewMode(QListView.IconMode)
        self.setItemDelegate(_GalleryDelegate(self))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSpacing(0)
        self.setMouseTracking(True)
        self._update_metrics()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.itemClicked.connect(self._activate)
        self.itemActivated.connect(self._activate)
        self._current = ''
        self._loaded = False
        self.import_item = QListWidgetItem('导入背景', self)
        self.import_item.setData(Qt.UserRole + 1, '导入')
        self.import_item.setFlags(Qt.ItemIsEnabled)
        self.import_button = _GalleryImportButton(self)
        self.setItemWidget(self.import_item, self.import_button)

    def _activate(self, item):
        if item is self.import_item:
            self.import_button.click()
        else:
            self.selected.emit(item.data(Qt.UserRole))

    def _append_asset(self, name, path, kind):
        item = QListWidgetItem(name)
        item.setData(Qt.UserRole, path)
        item.setData(Qt.UserRole + 1, kind)
        self.insertItem(self.count() - 1, item)
        return item

    def refresh(self):
        from . import config
        from .skins import IMAGES, VIDEOS
        root = Path(config.data_root())
        folder = root / 'utils/skins'
        # Keep the import widget alive, including its picker/drop connections.
        while self.count() > 1:
            self.takeItem(0)
        item = self._append_asset('默认背景', '', '默认')
        item.setToolTip('默认背景\n清除自定义背景，恢复默认背景')
        paths = sorted(folder.iterdir(), key=lambda path: path.name) if folder.is_dir() else []
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in IMAGES | VIDEOS:
                continue
            name = path.name
            prefix, separator, suffix = name.partition('_')
            if separator and len(prefix) == 32 and all(c in '0123456789abcdef' for c in prefix):
                name = suffix
            pixmap = None
            if path.suffix.lower() in IMAGES:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    reader.setScaledSize(size.scaled(288, 180, Qt.KeepAspectRatio))
                image = reader.read()
                if not image.isNull():
                    pixmap = QPixmap.fromImage(image)
            kind = '视频' if path.suffix.lower() in VIDEOS else '图片'
            item = self._append_asset(name, path.relative_to(root).as_posix(), kind)
            imported = datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            item.setToolTip(f'{name}\n类型：{kind}\n导入时间：{imported}\n位置：{path.resolve()}')
            item.setData(Qt.UserRole + 2, pixmap)
        self._loaded = True
        self.set_current(self._current)

    def set_current(self, path):
        self._current = path
        if self._loaded:
            self.clearSelection()
            for index in range(self.count()):
                item = self.item(index)
                if item is not self.import_item and item.data(Qt.UserRole) == path:
                    self.setCurrentItem(item)
                    break

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self.refresh()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange:
            self._update_metrics()

    def _update_metrics(self):
        self.setGridSize(QSize(144, 85))
        self.setFixedHeight(self.gridSize().height() * 2 + 14)
