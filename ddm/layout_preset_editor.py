"""Edit a preset's dividers in a translucent overlay above the existing wall."""
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QWidget

from . import layouts, resize_layout, room_presets, theme
from .corner_geometry import continuous_path
from .ui import ActionButton


class LayoutDraftPreview(QWidget):
    undoAvailable = Signal(bool)

    def __init__(self, wall, base, draft, defaults, parent):
        super().__init__(parent)
        self.base = base
        self.draft = draft
        self.defaults = defaults
        self.wall = wall
        self.drag = None
        self._history = []
        self.setMouseTracking(True)

    def _remember(self, previous):
        if self.draft != previous:
            self._history.append(previous)
            self.undoAvailable.emit(True)

    def cancel_drag(self):
        if self.drag is not None:
            self.draft = self.drag[2]
            self.drag = None
            self.update()

    def reset_to_default(self):
        self.cancel_drag()
        previous = self.draft
        self.draft = self.defaults
        self._remember(previous)
        self.update()

    def undo(self):
        if self._history:
            self.cancel_drag()
            self.draft = self._history.pop()
            self.undoAvailable.emit(bool(self._history))
            self.update()

    def ratios(self):
        return self.draft


class LayoutPreview(LayoutDraftPreview):
    def __init__(self, wall, base, ratios, parent):
        super().__init__(wall, base, room_presets.partition_weights(base, ratios),
                         room_presets.partition_weights(base, room_presets.default_layout_ratios(base)), parent)
        self.tree = room_presets.partition(base)
        self.setAccessibleName('拖动格子之间的分隔线调整布局')

    def ratios(self):
        return room_presets.corner_ratios_from_weights(self.draft) if self.base == 'corner' else self.draft

    def _geometry(self):
        wall = self.wall
        area = wall._corner_area()
        gap = wall.grid.spacing()
        if self.base == wall.layout_id:
            _, _, _, minimum, defaults = wall._border_model()
            if self.base == 'corner':
                leaves, handles = wall._corner_rectangles(self.draft, area)
                sizes = {
                    'root': [leaves[cell].height() for cell in (0, 3)],
                    'root/0': [leaves[cell].width() for cell in (0, 1)],
                    'root/0/1': [leaves[cell].height() for cell in (1, 2)],
                    'root/1': [leaves[cell].width() for cell in (3, 4, 5)],
                }
                dividers = [(node, index, handles[node.key, index], sizes[node.key])
                            for node in self.tree.nodes() for index in range(len(node.children) - 1)]
            else:
                area.setSize(area.size().expandedTo(self.tree.minimum(gap, minimum)))
                leaves, entries = resize_layout.geometry(self.tree, area, gap, minimum, self.draft, defaults)
                dividers = [(node, index, rect, sizes) for node, index, rect, _, sizes in entries]
            return leaves, dividers, 1, QPoint(), minimum

        size = area.size()
        portrait = layouts.is_portrait_layout(self.base)
        if portrait != (size.height() > size.width()):
            size.transpose()
        minimum = lambda cell: QSize(200, 140 if cell == layouts.danmaku_cell(self.base) else 150)
        size = size.expandedTo(self.tree.minimum(gap, minimum))
        drawn = size.scaled(area.size(), Qt.KeepAspectRatio)
        bounds = QRect(QPoint(), drawn)
        bounds.moveCenter(area.center())
        scale = drawn.width() / max(1, size.width())
        leaves, entries = resize_layout.geometry(
            self.tree, QRect(QPoint(), size), gap, minimum, self.draft,
            lambda node, rect: room_presets.partition_defaults(self.base, node, rect, gap))
        dividers = [(node, index, rect, sizes) for node, index, rect, _, sizes in entries]
        return leaves, dividers, scale, bounds.topLeft(), minimum

    def _mapped(self, rect, scale, origin):
        return QRectF(origin.x() + rect.x() * scale, origin.y() + rect.y() * scale,
                      rect.width() * scale, rect.height() * scale)

    @staticmethod
    def _grip(rect, axis):
        rect = QRectF(rect)
        if axis == Qt.Horizontal:
            inset = max(rect.height() * .35, (rect.height() - 44) / 2)
            rect.adjust(0, inset, 0, -inset)
        else:
            inset = max(rect.width() * .35, (rect.width() - 44) / 2)
            rect.adjust(inset, 0, -inset, 0)
        return rect

    def _hit(self, point):
        _, dividers, scale, origin, minimum = self._geometry()
        if not scale:
            return None
        matches = []
        for node, index, rect, sizes in dividers:
            rect = self._mapped(rect, scale, origin)
            if rect.adjusted(-4, -4, 4, 4).contains(point):
                center = rect.center()
                dx, dy = abs(point.x() - center.x()), abs(point.y() - center.y())
                over_grip = self._grip(rect, node.axis).adjusted(-4, -4, 4, 4).contains(point)
                matches.append((not over_grip, dx if node.axis == Qt.Horizontal else dy,
                                dx + dy, node, index, sizes))
        if matches:
            _, _, _, node, index, sizes = min(matches, key=lambda match: match[:3])
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
        for node, _, rect, _ in dividers:
            painter.drawRoundedRect(self._grip(self._mapped(rect, scale, origin), node.axis), 3, 3)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and (target := self._hit(event.position())):
            self.drag = target, event.position(), self.draft
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
            self.draft = weights
        else:
            sizes = list(original)
            total = sizes[index] + sizes[index + 1]
            first, second = [child.minimum(self.wall.grid.spacing(), minimum)
                             for child in node.children[index:index + 2]]
            lower = first.width() if horizontal else first.height()
            upper = total - (second.width() if horizontal else second.height())
            position = max(lower, min(upper, sizes[index] + movement))
            if position == sizes[index]:
                self.draft = weights
            else:
                sizes[index] = position
                sizes[index + 1] = total - position
                self.draft = {**weights, node.key: [size / sum(sizes) for size in sizes]}
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag is not None and event.button() == Qt.LeftButton:
            previous = self.drag[2]
            self.mouseMoveEvent(event)
            self.drag = None
            self._remember(previous)
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
        self.setWindowTitle('修改布局 · ' + layouts.BY_ID[base]['name'])
        if layouts.snap_grid_size(base):
            from .snap_grid_editor import SnapGridPreview
            self.preview = SnapGridPreview(self.wall, base, ratios, self)
        else:
            self.preview = LayoutPreview(self.wall, base, ratios, self)
        self.actions = QWidget(self)
        bar = QHBoxLayout(self.actions)
        bar.setContentsMargins(0, 0, 0, 0)
        reset = ActionButton('恢复默认', self.actions)
        reset.setToolTip('在预览中恢复默认比例，保存后生效')
        reset.clicked.connect(self.preview.reset_to_default)
        undo = ActionButton('撤回', self.actions)
        undo.setToolTip('撤回上一步布局调整')
        undo.setEnabled(False)
        undo.clicked.connect(self.preview.undo)
        self.preview.undoAvailable.connect(undo.setEnabled)
        cancel = ActionButton('取消', self.actions)
        save = ActionButton('保存布局', self.actions)
        save.setObjectName('PrimaryButton')
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        bar.addWidget(reset)
        bar.addWidget(undo)
        bar.addWidget(cancel)
        bar.addWidget(save)
        self._align_wall()
        self.wall.installEventFilter(self)
        host.installEventFilter(self)

    def paintEvent(self, event):
        QPainter(self).fillRect(event.rect(), QColor(12, 18, 28, 46))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.preview.setGeometry(self.rect())
        self.actions.adjustSize()
        bounds = self.wall._corner_area().intersected(self.rect())
        self.actions.move(max(0, bounds.right() - self.actions.width() - 10),
                          max(0, bounds.bottom() - self.actions.height() - 10))

    def _align_wall(self):
        geometry = QRect(self.wall.mapToGlobal(QPoint()), self.wall.size())
        if self.geometry() != geometry:
            self.preview.cancel_drag()
            self.setGeometry(geometry)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Move, QEvent.Resize):
            self._align_wall()
        elif event.type() in (QEvent.Hide, QEvent.Close) and self.isVisible():
            self.reject()
        return super().eventFilter(watched, event)

    def ratios(self):
        return self.preview.ratios()
