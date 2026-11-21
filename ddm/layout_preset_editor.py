"""Edit a preset's dividers in a translucent overlay above the existing wall."""
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget

from . import layouts, resize_layout, room_presets, theme
from .corner_geometry import continuous_path
from .ui import ActionButton, TitleLabel


class LayoutPreview(QWidget):
    def __init__(self, wall, base, ratios, parent):
        super().__init__(parent)
        self.base = base
        self.tree = room_presets.partition(base)
        self.weights = room_presets.partition_weights(base, ratios)
        self.wall = wall
        self.drag = None
        self.setMouseTracking(True)
        self.setAccessibleName('拖动格子之间的分隔线调整布局')

    def _geometry(self):
        size = self.wall._corner_area().size()
        portrait = layouts.is_portrait_layout(self.base)
        if portrait != (size.height() > size.width()):
            size.transpose()
        minimum = lambda cell: QSize(200, 140 if cell == layouts.danmaku_cell(self.base) else 150)
        gap = self.wall.grid.spacing()
        size = size.expandedTo(self.tree.minimum(gap, minimum))
        drawn = size.scaled(self.size(), Qt.KeepAspectRatio)
        bounds = QRect(QPoint(), drawn)
        bounds.moveCenter(self.rect().center())
        scale = drawn.width() / max(1, size.width())
        leaves, dividers = resize_layout.geometry(
            self.tree, QRect(QPoint(), size), gap, minimum, self.weights,
            lambda node, rect: room_presets.partition_defaults(self.base, node, rect, gap))
        return leaves, dividers, scale, bounds.topLeft(), minimum

    def _mapped(self, rect, scale, origin):
        return QRectF(origin.x() + rect.x() * scale, origin.y() + rect.y() * scale,
                      rect.width() * scale, rect.height() * scale)

    def _hit(self, point):
        _, dividers, scale, origin, minimum = self._geometry()
        if not scale:
            return None
        matches = []
        for node, index, rect, _, sizes in dividers:
            rect = self._mapped(rect, scale, origin)
            if rect.adjusted(-4, -4, 4, 4).contains(point):
                center = rect.center()
                dx, dy = abs(point.x() - center.x()), abs(point.y() - center.y())
                matches.append((dx if node.axis == Qt.Horizontal else dy, dx + dy, node, index, sizes))
        if matches:
            _, _, node, index, sizes = min(matches, key=lambda match: match[:2])
            return node, index, sizes, scale, minimum
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        leaves, dividers, scale, origin, _ = self._geometry()
        for cell, rect in leaves.items():
            frame = self._mapped(rect, scale, origin).adjusted(1, 1, -1, -1)
            if frame.isEmpty():
                continue
            chat = cell == layouts.danmaku_cell(self.base)
            painter.setBrush(QColor(13, 22, 34, 144))
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
            painter.drawPath(continuous_path(frame, 8))
            painter.setPen(QColor('#ffffff'))
            painter.drawText(frame, Qt.AlignCenter, '弹幕' if chat else str(cell + 1))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(235, 246, 255, 200))
        for _, _, rect, _, _ in dividers:
            grip = self._mapped(rect, scale, origin)
            if grip.width() < grip.height():
                inset = max(grip.height() * .35, (grip.height() - 44) / 2)
                grip.adjust(0, inset, 0, -inset)
            else:
                inset = max(grip.width() * .35, (grip.width() - 44) / 2)
                grip.adjust(inset, 0, -inset, 0)
            painter.drawRoundedRect(grip, 3, 3)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and (target := self._hit(event.position())):
            self.drag = target, event.position(), self.weights
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag is None:
            target = self._hit(event.position())
            self.setCursor((Qt.SplitHCursor if target[0].axis == Qt.Horizontal else Qt.SplitVCursor)
                           if target else Qt.ArrowCursor)
            return
        (node, index, original, scale, minimum), start, weights = self.drag
        horizontal = node.axis == Qt.Horizontal
        delta = event.position() - start
        movement = round((delta.x() if horizontal else delta.y()) / scale)
        if movement == 0:
            self.weights = weights
        else:
            sizes = list(original)
            total = sizes[index] + sizes[index + 1]
            first, second = [child.minimum(self.wall.grid.spacing(), minimum)
                             for child in node.children[index:index + 2]]
            lower = first.width() if horizontal else first.height()
            upper = total - (second.width() if horizontal else second.height())
            sizes[index] = max(lower, min(upper, sizes[index] + movement))
            sizes[index + 1] = total - sizes[index]
            self.weights = {**weights, node.key: [size / sum(sizes) for size in sizes]}
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag is not None and event.button() == Qt.LeftButton:
            self.mouseMoveEvent(event)
            self.drag = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class LayoutPresetEditor(QDialog):
    def __init__(self, host, base, ratios):
        super().__init__(host, Qt.Tool | Qt.FramelessWindowHint)
        self.wall = host.wall
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowTitle('修改布局')
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        bar = QHBoxLayout()
        title = TitleLabel('修改布局 · ' + layouts.BY_ID[base]['name'])
        title.setStyleSheet('color: white; background: #202630; padding: 4px 8px; border-radius: 6px;')
        bar.addWidget(title)
        bar.addStretch(1)
        cancel = ActionButton('取消', self)
        save = ActionButton('保存布局', self)
        save.setObjectName('PrimaryButton')
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(save)
        box.addLayout(bar)
        self.preview = LayoutPreview(self.wall, base, ratios, self)
        box.addWidget(self.preview, 1)
        self._align_wall()
        self.wall.installEventFilter(self)
        host.installEventFilter(self)

    def paintEvent(self, event):
        QPainter(self).fillRect(event.rect(), QColor(12, 18, 28, 46))

    def _align_wall(self):
        geometry = QRect(self.wall.mapToGlobal(QPoint()), self.wall.size())
        if self.geometry() != geometry:
            self.preview.drag = None
            self.setGeometry(geometry)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Move, QEvent.Resize):
            self._align_wall()
        elif event.type() in (QEvent.Hide, QEvent.Close) and self.isVisible():
            self.reject()
        return super().eventFilter(watched, event)

    def ratios(self):
        weights = self.preview.weights
        return room_presets.corner_ratios_from_weights(weights) if self.preview.base == 'corner' else weights
