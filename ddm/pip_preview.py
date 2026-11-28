"""Picture-in-picture layout selection preview."""
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget
from .pip_composition import FREE_LAYOUT
from .pip_placement import fit_placement, snap_position
from .room_choice import PreviewAvatar
from .ui import ElidedLabel, NavigationButton
from .pip_geometry import composition_ratio, pane_rectangles


class CompositionPreview(QFrame):
    positionsSwapped = Signal(int, int)
    positionChanged = Signal(int, tuple)
    slotPicked = Signal(int, object)
    removeRequested = Signal(int)
    SNAP_DISTANCE = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('PluginCard')
        self.setFixedHeight(220)
        self.add_chat = NavigationButton('加入弹幕栏', 'danmaku', self)
        self.add_chat.setCursor(Qt.OpenHandCursor)
        self.add_chat.setToolTip('按住左键拖入预览，松手添加或替换弹幕栏')
        self.add_chat.clicked.connect(lambda: self.slotPicked.emit(-1, None))
        self.add_chat.installEventFilter(self)
        self.labels = []
        self.columns = 0
        self.aspect = 16 / 9
        self.aspects = []
        self.primary = 0
        self.placement = ()
        self._scale = 1
        self._drag = None
        self._ghost = None
        self._drop_target = None
        self.setAccessibleName('拖动画面并吸附到目标位置')

    def set_panes(self, names, columns, aspects=None, primary=0, *, placement=(), portraits=(), removable=()):
        self.cancel_drag()
        for label in self.labels:
            label.hide()
            label.deleteLater()
        self.labels = [ElidedLabel('' if portraits and portraits[index] is not None else name, self)
                       for index, name in enumerate(names)]
        self.columns = columns
        self.primary = primary
        self.placement = placement
        self.aspects = aspects or [16 / 9] * len(names)
        self.aspect = composition_ratio(self.aspects, columns, primary, placement=placement) if names else 16 / 9
        for index, (label, name) in enumerate(zip(self.labels, names)):
            label.setAlignment(Qt.AlignCenter)
            label.setObjectName('PluginCard')
            label.setTextFormat(Qt.PlainText)
            label.setCursor(Qt.OpenHandCursor if len(names) > 1 else Qt.ArrowCursor)
            guide = '拖动以自由摆放和对齐' if placement else '靠近其他画面可吸附换位'
            label.setAccessibleName(name)
            label.setToolTip(name + '\n' + guide if len(names) > 1 else name)
            if portraits and portraits[index] is not None:
                uname, pixmap = portraits[index]
                PreviewAvatar(uname, index, pixmap, label)
            if index in removable:
                label.setContentsMargins(4, 6, 4, 2)
                close = NavigationButton('移除' + name, 'close', label)
                close.setFixedSize(20, 20)
                close.clicked.connect(lambda _checked=False, slot=index: self.removeRequested.emit(slot))
                close.show()
            label.installEventFilter(self)
            label.show()
        self._arrange()

    def _pane_area(self):
        return self.rect().adjusted(8, 40, -8, -8)

    def _arrange(self):
        area = self._pane_area()
        self.add_chat.move(self.width() - self.add_chat.width() - 8, 4)
        self.add_chat.raise_()
        if self.columns == FREE_LAYOUT and self.placement:
            rects, self._scale = fit_placement(self.placement, area)
        else:
            rects = pane_rectangles(len(self.labels), area, self.columns, self.aspects, self.primary)
        for label, rect in zip(self.labels, rects):
            label.setGeometry(rect)
            if (avatar := label.findChild(PreviewAvatar)) is not None:
                avatar.center_in(label.rect())
            if (close := label.findChild(NavigationButton)) is not None:
                close.move(max(0, label.width() - close.width() - 2), 1)

    def free_slot_at(self, point, aspect):
        if point is None or not self.placement:
            return None
        x, y, _, _ = self.placement[0]
        offset = point - self.labels[0].geometry().topLeft()
        height = round(sum(rect[3] for rect in self.placement) / len(self.placement))
        rect = QRect(0, 0, max(1, round(height * aspect)), height)
        rect.moveCenter(QPoint(x + round(offset.x() / self._scale), y + round(offset.y() / self._scale)))
        return snap_position(rect, [QRect(*value) for value in self.placement],
                             round(self.SNAP_DISTANCE / self._scale))

    def resizeEvent(self, event):
        self.cancel_drag()
        super().resizeEvent(event)
        self._arrange()

    def _highlight(self, target):
        if target is self._drop_target:
            return
        previous, self._drop_target = self._drop_target, target
        for label in (previous, target):
            if label is not None:
                label.setProperty('pipDropTarget', label is target)
                label.style().unpolish(label)
                label.style().polish(label)
                label.update()

    def _snap_target(self, point, source):
        hits = [index for index, label in enumerate(self.labels) if label.geometry().contains(point)]
        if hits:
            target = hits[0]
            return target if target != source else None
        candidates = []
        for index, label in enumerate(self.labels):
            if index == source:
                continue
            bounds = label.geometry()
            x = max(bounds.left() - point.x(), point.x() - bounds.right(), 0)
            y = max(bounds.top() - point.y(), point.y() - bounds.bottom(), 0)
            distance = x * x + y * y
            if distance <= self.SNAP_DISTANCE ** 2:
                candidates.append((distance, index))
        return min(candidates)[1] if candidates else None

    def _free_position(self, source, pressed, position):
        if not self.rect().contains(self.mapFromGlobal(position)):
            return None
        delta = position - pressed
        original = QRect(*self.placement[source])
        moved = original.translated(round(delta.x() / self._scale), round(delta.y() / self._scale))
        neighbors = [QRect(*rect) for index, rect in enumerate(self.placement) if index != source]
        return snap_position(moved, neighbors, round(self.SNAP_DISTANCE / self._scale))

    def _chat_drop_index(self, point):
        if not self._pane_area().contains(point):
            return None
        return next((index for index, label in enumerate(self.labels)
                     if label.geometry().contains(point)), -1)

    def _move_chat_preview(self, point):
        index = self._chat_drop_index(point)
        label = self.labels[index] if index is not None and index >= 0 else None
        ghost = QRect(0, 0, 68, 60)
        ghost.moveCenter(point)
        self._ghost.setGeometry(label.geometry().adjusted(2, 2, -2, -2) if label is not None else ghost)
        self._ghost.raise_()
        self._highlight(self._ghost if index == -1 else label)

    def cancel_drag(self):
        self._drag = None
        QApplication.instance().removeEventFilter(self)
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        if self._ghost is not None:
            self._ghost.hide()
            self._ghost.deleteLater()
            self._ghost = None
        self._highlight(None)

    def eventFilter(self, watched, event):
        kind = event.type()
        if self._drag is None:
            if (kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton
                    and (watched is self.add_chat or (len(self.labels) > 1 and watched in self.labels))):
                position = event.globalPosition().toPoint()
                source = None if watched is self.add_chat else self.labels.index(watched)
                self._drag = (source, position, watched.mapFromGlobal(position))
                self.grabMouse(Qt.ClosedHandCursor)
                QApplication.instance().installEventFilter(self)
                return True
            return False
        if kind == QEvent.MouseMove:
            if not event.buttons() & Qt.LeftButton:
                self.cancel_drag()
                return True
            source, pressed, offset = self._drag
            position = event.globalPosition().toPoint()
            if self._ghost is None and (position - pressed).manhattanLength() >= QApplication.startDragDistance():
                self._ghost = QLabel(self)
                self._ghost.setObjectName('PluginCard')
                self._ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
                if source is None:
                    self._ghost.setText('弹幕栏')
                    self._ghost.setAlignment(Qt.AlignCenter)
                else:
                    self._ghost.setPixmap(self.labels[source].grab())
                    self._ghost.setScaledContents(True)
                if self.placement and source is not None:
                    self._ghost.setContentsMargins(2, 2, 2, 2)
                self._ghost.show()
            if self._ghost is not None:
                point = self.mapFromGlobal(position)
                if source is None:
                    self._move_chat_preview(point)
                    return True
                if self.placement:
                    placed = self._free_position(source, pressed, position)
                    if placed is None:
                        ghost = QRect(point - offset, self.labels[source].size())
                    else:
                        x, y, _width, _height = self.placement[source]
                        ghost = self.labels[source].geometry().translated(
                            round((placed.x() - x) * self._scale), round((placed.y() - y) * self._scale))
                    self._ghost.setGeometry(ghost)
                    self._ghost.raise_()
                    self._highlight(self._ghost if placed is not None else None)
                    return True
                target = self._snap_target(point, source)
                label = self.labels[target] if target is not None else None
                if label is not None:
                    self._ghost.setGeometry(label.geometry().adjusted(2, 2, -2, -2))
                else:
                    self._ghost.setGeometry(QRect(point - offset, self.labels[source].size()))
                self._ghost.raise_()
                self._highlight(label)
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            source, pressed, _offset = self._drag
            position = event.globalPosition().toPoint()
            if source is None:
                point = self.mapFromGlobal(position)
                index = self._chat_drop_index(point) if self._ghost is not None else None
                self.cancel_drag()
                if index is not None:
                    self.slotPicked.emit(index, point)
                return True
            if self.placement:
                placed = self._free_position(source, pressed, position) if self._ghost is not None else None
                self.cancel_drag()
                if placed is not None and placed.getRect() != self.placement[source]:
                    self.positionChanged.emit(source, placed.getRect())
                return True
            point = self.mapFromGlobal(position)
            target = self._snap_target(point, source)
            moved = self._ghost is not None
            self.cancel_drag()
            if moved and target is not None and target != source:
                self.positionsSwapped.emit(source, target)
            return True
        if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.cancel_drag()
            return True
        if (kind == QEvent.ApplicationDeactivate or
                watched is self and kind in (QEvent.Hide, QEvent.UngrabMouse) or
                watched is self.window() and kind in (QEvent.Hide, QEvent.WindowDeactivate)):
            self.cancel_drag()
        return False
