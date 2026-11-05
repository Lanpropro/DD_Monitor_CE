"""A selected group of existing playback panes in one independent floating window."""
import math
import sys

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPainterPath, QPen, QRegion, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from . import theme
from .ui import ActionButton, ElidedLabel, page_header


FOCUS_LAYOUT = -1


def composition_rows(aspects, columns=0):
    def rows(cols):
        return [aspects[index:index + cols] for index in range(0, len(aspects), cols)]
    if not columns:
        columns = min(range(1, len(aspects) + 1), key=lambda cols:
                      (abs(math.log(composition_aspect(rows(cols)) / (16 / 9))), math.ceil(len(aspects) / cols)))
    return rows(min(len(aspects), columns))


def composition_aspect(rows):
    return 1 / sum(1 / sum(row) for row in rows)


def _focus_parts(aspects, primary):
    order = [primary] + [index for index in range(6) if index != primary]
    values = [aspects[index] for index in order]
    right = 1 / (1 / values[1] + 1 / values[2])
    return order, values, values[0] + right, sum(values[3:])


def composition_ratio(aspects, columns=0, primary=0):
    if columns == FOCUS_LAYOUT and len(aspects) == 6:
        _order, _values, top, bottom = _focus_parts(aspects, primary)
        return 1 / (1 / top + 1 / bottom)
    return composition_aspect(composition_rows(aspects, 0 if columns == FOCUS_LAYOUT else columns))


def video_aspect(player):
    if player is not None:
        for name in ('video-out-params', 'video-params'):
            params = player._prop(name)
            if not isinstance(params, dict):
                continue
            width, height = params.get('dw', params.get('w')), params.get('dh', params.get('h'))
            aspect = params.get('aspect') or (width / height if width and height else 0)
            if isinstance(aspect, (int, float)) and math.isfinite(aspect) and aspect > 0:
                return 1 / aspect if params.get('rotate', 0) % 180 == 90 else float(aspect)
    return None


def pane_rectangles(count, area, columns=0, aspects=None, primary=0):
    if not count:
        return []
    aspects = aspects or [16 / 9] * count
    aspect = composition_ratio(aspects, columns, primary)
    width = max(1, min(area.width(), round(area.height() * aspect)))
    height = max(1, min(area.height(), round(width / aspect)))
    canvas = QRect(0, 0, width, height)
    canvas.moveCenter(area.center())
    if columns == FOCUS_LAYOUT and count == 6:
        order, values, top_aspect, bottom_aspect = _focus_parts(aspects, primary)
        split_y = round(height * aspect / top_aspect)
        split_x = round(width * values[0] / top_aspect)
        right_y = round(split_y * values[2] / (values[1] + values[2]))
        arranged = [QRect(0, 0, split_x, split_y),
                    QRect(split_x, 0, width - split_x, right_y),
                    QRect(split_x, right_y, width - split_x, split_y - right_y)]
        left, offset = 0, 0.0
        for value in values[3:]:
            offset += value
            right = round(width * offset / bottom_aspect)
            arranged.append(QRect(left, split_y, right - left, height - split_y))
            left = right
        rectangles = [None] * count
        for index, rect in zip(order, arranged):
            rectangles[index] = rect.translated(canvas.topLeft())
        return rectangles
    rows = composition_rows(aspects, 0 if columns == FOCUS_LAYOUT else columns)
    rectangles, top, weight = [], 0, 0.0
    for row in rows:
        total = sum(row)
        weight += 1 / total
        bottom = round(height * weight * aspect)
        left, offset = 0, 0.0
        for value in row:
            offset += value
            right = round(width * offset / total)
            rectangles.append(QRect(canvas.x() + left, canvas.y() + top, right - left, bottom - top))
            left = right
        top = bottom
    return rectangles


class CompositionPreview(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('PluginCard')
        self.setFixedHeight(156)
        self.labels = []
        self.columns = 0
        self.aspect = 16 / 9
        self.aspects = []
        self.primary = 0

    def set_panes(self, names, columns, aspects=None, primary=0):
        for label in self.labels:
            label.deleteLater()
        self.labels = [ElidedLabel('主画面 · ' + name if columns == FOCUS_LAYOUT and index == primary else name, self)
                       for index, name in enumerate(names)]
        self.columns = columns
        self.primary = primary
        self.aspects = aspects or [16 / 9] * len(names)
        self.aspect = composition_ratio(self.aspects, columns, primary) if names else 16 / 9
        for label in self.labels:
            label.setAlignment(Qt.AlignCenter)
            label.setObjectName('PluginCard')
            label.setTextFormat(Qt.PlainText)
            label.show()
        self._arrange()

    def _arrange(self):
        area = self.rect().adjusted(8, 8, -8, -8)
        width = min(area.width(), round(area.height() * self.aspect))
        canvas = QRect(0, 0, width, min(area.height(), round(width / self.aspect)))
        canvas.moveCenter(area.center())
        for label, rect in zip(self.labels, pane_rectangles(
                len(self.labels), canvas, self.columns, self.aspects, self.primary)):
            label.setGeometry(rect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()


class PictureInPictureDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.floating or controller.host)
        self.controller = controller
        self.setWindowTitle('组合画中画')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(480, 580)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addLayout(page_header('画中画', '选择画面组合；关闭小窗后返回原监控室布局'))
        self.preview = CompositionPreview(self)
        layout.addWidget(self.preview)
        self.columns = QComboBox(self)
        for title, value in (('自动排列', 0), ('横向排列', 16), ('纵向排列', 1), ('两列排列', 2), ('三列排列', 3),
                             ('单主＋五辅（6路）', FOCUS_LAYOUT)):
            self.columns.addItem(title, value)
        self.columns.setAccessibleName('画中画排列方式')
        self.columns.setCurrentIndex(max(0, self.columns.findData(controller.columns)))
        layout.addWidget(self.columns)
        self.primary_row = QWidget(self)
        primary_box = QHBoxLayout(self.primary_row)
        primary_box.setContentsMargins(0, 0, 0, 0)
        primary_label = QLabel('主画面', self.primary_row)
        self.primary = QComboBox(self.primary_row)
        self.primary.setAccessibleName('画中画主画面')
        primary_label.setBuddy(self.primary)
        primary_box.addWidget(primary_label)
        primary_box.addWidget(self.primary, 1)
        layout.addWidget(self.primary_row)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        choices = QVBoxLayout(content)
        self.checks = {}
        capacity = controller.host.wall._capacity() or len(controller.host.wall.tiles)
        for index, tile in enumerate(controller.host.wall.tiles[:capacity]):
            if not tile.room.get('room_id'):
                continue
            name = f'{index + 1} · ' + str(tile.room.get('uname') or tile.room['room_id'])
            check = QCheckBox(name, content)
            check.setToolTip(name)
            check.setChecked(index in controller.selection)
            check.toggled.connect(self._refresh)
            self.checks[index] = check
            choices.addWidget(check)
        choices.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.hint = QLabel(self)
        self.hint.setObjectName('SettingsHint')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        footer = QHBoxLayout()
        cancel = ActionButton('取消', self)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        footer.addStretch()
        self.start = ActionButton('应用组合' if controller.active else '打开画中画', self)
        self.start.setObjectName('PrimaryButton')
        self.start.clicked.connect(self._apply)
        footer.addWidget(self.start)
        layout.addLayout(footer)
        self.columns.currentIndexChanged.connect(self._refresh)
        self.primary.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _selected(self):
        checked = [index for index, check in self.checks.items() if check.isChecked()]
        return ([index for index in self.controller.selection if index in checked]
                + [index for index in checked if index not in self.controller.selection])

    def _refresh(self, *_args):
        selection = self._selected()
        names = [self.checks[index].text() for index in selection]
        primary = self.primary.currentData() if self.primary.count() else self.controller.primary
        self.primary.blockSignals(True)
        self.primary.clear()
        for index, name in zip(selection, names):
            self.primary.addItem(name, index)
        self.primary.setCurrentIndex(max(0, self.primary.findData(primary)))
        self.primary.blockSignals(False)
        focus = self.columns.currentData() == FOCUS_LAYOUT
        self.primary_row.setVisible(focus)
        primary = selection.index(self.primary.currentData()) if selection else 0
        self.preview.set_panes(names, self.columns.currentData(), self.controller.aspects_for(selection), primary)
        valid = bool(names) and (not focus or len(names) == 6)
        self.start.setEnabled(valid)
        self.hint.setText('单主＋五辅需要选择6路画面；主画面可在上方指定。' if focus and len(names) != 6 else
                          f'已选择 {len(names)} 路。按直播比例缩放并支持置顶，其他画面按原声音设置在后台播放。'
                          if self.checks else '画面墙中还没有直播间，请先添加画面。')

    def _apply(self):
        selected = self._selected()
        self.controller.start(selected, self.columns.currentData(), self.primary.currentData())
        self.accept()


class PictureInPictureButton(QPushButton):
    def __init__(self, kind, tooltip, parent):
        super().__init__(parent)
        self.kind = kind
        self.keyboard_focus = False
        self.setFixedSize(24, 24)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover)
        self.setStyleSheet('QPushButton { border: none; background: transparent; padding: 0; min-width: 0; min-height: 0; }')

    def event(self, event):
        if event.type() == QEvent.FocusIn:
            self.keyboard_focus = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
            self.update()
        elif event.type() == QEvent.FocusOut:
            self.keyboard_focus = False
            self.update()
        return super().event(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        hovered = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        active = hovered or (self.keyboard_focus and self.hasFocus()) or self.isChecked()
        if self.kind in ('pin', 'reorder'):
            # Blue denotes an enabled mode rather than a lingering hover.
            background = (theme.qcolor(theme.ACCENT) if self.isChecked()
                          else QColor(45, 49, 55, 210) if active else QColor(0, 0, 0, 170))
        else:
            background = theme.qcolor(theme.ACCENT) if active else QColor(0, 0, 0, 170)
        painter.setBrush(background)
        painter.drawEllipse(QRectF(self.rect()))
        painter.setPen(QPen(QColor('#e7ebf0'), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        if self.kind == 'composition':
            for x in (6, 13):
                for y in (6, 13):
                    painter.drawRoundedRect(QRectF(x, y, 5, 5), 1, 1)
        elif self.kind == 'pin':
            painter.drawLine(9, 6, 15, 6)
            painter.drawLine(10, 6, 9, 12)
            painter.drawLine(14, 6, 15, 12)
            painter.drawLine(8, 13, 16, 13)
            painter.drawLine(12, 13, 12, 19)
        elif self.kind == 'reorder':
            painter.drawLine(5, 8, 19, 8)
            painter.drawLine(16, 5, 19, 8)
            painter.drawLine(19, 8, 16, 11)
            painter.drawLine(19, 16, 5, 16)
            painter.drawLine(8, 13, 5, 16)
            painter.drawLine(5, 16, 8, 19)
        else:
            painter.drawLine(8, 8, 16, 16)
            painter.drawLine(16, 8, 8, 16)


class PictureInPictureTools(QWidget):
    """An owned alpha surface keeps the icons above native video without a bar."""
    def __init__(self, owner):
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(108, 24)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.manage = PictureInPictureButton('composition', '选择画面组合', self)
        self.reorder = PictureInPictureButton('reorder', '调整画面位置', self)
        self.reorder.setCheckable(True)
        self.pin = PictureInPictureButton('pin', '置顶画中画', self)
        self.pin.setCheckable(True)
        self.pin.setChecked(owner.controller.pinned)
        self.pin.setToolTip('已置顶，点击取消置顶' if owner.controller.pinned else '未置顶，点击置顶')
        self.back = PictureInPictureButton('back', '关闭画中画并返回监控室（Esc）', self)
        for button in (self.manage, self.reorder, self.pin, self.back):
            box.addWidget(button)
        self.manage.clicked.connect(owner.controller.manage)
        self.reorder.toggled.connect(owner._set_reordering)
        self.pin.toggled.connect(owner._pin)
        self.back.clicked.connect(owner.close)
        QShortcut(QKeySequence(Qt.Key_Escape), self).activated.connect(owner.close)


class PictureInPictureWindow(QWidget):
    def __init__(self, controller):
        flags = Qt.Window | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        if controller.pinned:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.controller = controller
        self.setWindowTitle('画中画 · DD监控室CE')
        self.setObjectName('PictureInPicture')
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet('#PictureInPicture { background: #000; }')
        self.setFocusPolicy(Qt.StrongFocus)
        self.aspect = 16 / 9
        self._native_rounding = False
        self._rounding_hwnd = None
        self._fitting = False
        self.resize(640, 360)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)
        self.tools = PictureInPictureTools(self)
        self.pin = self.tools.pin
        self._gesture = None
        self._reorder_drag = None
        self._live_resize = None
        self._pending_geometry = None
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setTimerType(Qt.PreciseTimer)
        self._geometry_timer.setInterval(16)
        self._geometry_timer.timeout.connect(self._flush_geometry)
        self._surface_state = [(widget, widget.hasMouseTracking(),
                                widget.cursor() if widget.testAttribute(Qt.WA_SetCursor) else None)
                               for tile in controller.host.wall.tiles for widget in (tile, tile.video)]
        for widget, _tracking, _cursor in self._surface_state:
            widget.setMouseTracking(True)
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(100)
        self._hover_timer.timeout.connect(self._poll_tools)
        self._hover_timer.start()
        QApplication.instance().installEventFilter(self)
        shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        shortcut.activated.connect(self.close)

    def _poll_tools(self):
        if self._live_resize is not None:
            self.tools.hide()
            if (not self._live_resize.starting and not self._live_resize.finishing
                    and not self._live_resize.sync()):
                self._live_resize.finish(immediate=True)
            return
        hovered = self._pointer_over()
        focused = any(button.keyboard_focus and button.hasFocus()
                      for button in self.tools.findChildren(PictureInPictureButton))
        visible = (self.isVisible() and not self.isMinimized()
                   and self.controller.dialog is None and (hovered or focused))
        position = self.mapToGlobal(QPoint(self.width() - self.tools.width() - 8, 8))
        moved = self.tools.pos() != position
        was_visible = self.tools.isVisible()
        if moved:
            self.tools.move(position)
        if was_visible != visible:
            self.tools.setVisible(visible)
        if visible and (not was_visible or moved):
            self.tools.raise_()

    def _pointer_over(self):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            point = wintypes.POINT()
            user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
            user32.WindowFromPoint.argtypes = (wintypes.POINT,)
            user32.WindowFromPoint.restype = wintypes.HWND
            user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
            user32.GetAncestor.restype = wintypes.HWND
            user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
            user32.GetWindow.restype = wintypes.HWND
            user32.GetCursorPos(ctypes.byref(point))
            hit = user32.GetAncestor(user32.WindowFromPoint(point), 2)  # GA_ROOT
            roots = (int(self.internalWinId()), int(self.tools.internalWinId()))
            while hit:
                if hit in roots:
                    return True
                hit = user32.GetWindow(hit, 4)  # GW_OWNER, including our tooltip.
            return False
        widget = QApplication.widgetAt(QCursor.pos())
        return widget is not None and widget.window() in (self, self.tools)

    def focusNextPrevChild(self, next):
        self.tools.show()
        self.tools.activateWindow()
        (self.tools.manage if next else self.tools.back).setFocus(Qt.TabFocusReason)
        return True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._fitting and abs(self.height() - self.width() / self.aspect) > 1:
            by_height = abs(event.size().height() - event.oldSize().height()) * self.aspect > abs(event.size().width() - event.oldSize().width())
            width = round(self.height() * self.aspect) if by_height else self.width()
            self.resize_to_width(width)
        # The native top-level has already resized. Activate the wall layout in
        # this event, before returning to queued pointer/paint events.
        self.box.activate()
        self._apply_rounding()
        self._poll_tools()

    def saveGeometry(self):
        if self._live_resize is not None:
            return self._live_resize.preview.saveGeometry()
        return super().saveGeometry()

    def set_composition(self, aspects, columns, primary=0):
        self.aspect = composition_ratio(aspects, columns, primary)
        minimum = max(self.tools.width() + 16, round(48 * self.aspect))
        self.setMinimumSize(minimum, round(minimum / self.aspect))
        screen = self.screen().availableGeometry()
        self.resize_to_width(min(self.width(), screen.width(), round(screen.height() * self.aspect)))

    def resize_to_width(self, width):
        self._fitting = True
        width = max(self.minimumWidth(), width)
        self.resize(width, round(width / self.aspect))
        self._fitting = False

    def _apply_rounding(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        region = QRegion(path.toFillPolygon().toPolygon())
        # Keep comment clipping separate: a hard native region disables DWM's
        # antialiased window corners, especially visible at fractional DPI.
        self.setProperty('presentationMask', region)
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            from .window_fullscreen import _dwm_set
            hwnd = int(self.winId())
            if hwnd != self._rounding_hwnd:
                self._rounding_hwnd = hwnd
                self._native_rounding = _dwm_set(hwnd, 33, 2) == 0
                _dwm_set(hwnd, 34, 0xFFFFFFFE)
        if self._native_rounding:
            if not self.mask().isEmpty():
                self.clearMask()
        else:
            self.setMask(region)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_native_window()

    def _refresh_native_window(self):
        self._apply_rounding()
        self._apply_pin(self.controller.pinned)

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.DevicePixelRatioChange, QEvent.WinIdChange) and hasattr(self, 'tools'):
            QTimer.singleShot(0, self, self._refresh_native_window)
        return result

    def moveEvent(self, event):
        super().moveEvent(event)
        self._poll_tools()

    def hideEvent(self, event):
        self.tools.hide()
        super().hideEvent(event)

    def _resize_edges(self, point):
        edges = Qt.Edges()
        # Larger corner targets, narrow edge targets: no visible resize frame.
        corner = ((point.x() < 18 or point.x() >= self.width() - 18)
                  and (point.y() < 18 or point.y() >= self.height() - 18))
        margin = 18 if corner else 6
        if point.x() < margin:
            edges |= Qt.LeftEdge
        elif point.x() >= self.width() - margin:
            edges |= Qt.RightEdge
        if point.y() < margin:
            edges |= Qt.TopEdge
        elif point.y() >= self.height() - margin:
            edges |= Qt.BottomEdge
        return edges

    def _tile_at(self, point):
        if self.tools.isVisible() and self.tools.geometry().contains(point):
            return None
        return next((tile for tile in self.controller.host.wall.visible_tiles()
                     if tile.rect().contains(tile.mapFromGlobal(point))), None)

    def _set_reordering(self, enabled):
        self._reorder_drag = None
        if self._gesture is None and QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.setCursor(Qt.OpenHandCursor if enabled else Qt.ArrowCursor)
        for widget, _tracking, _cursor in self._surface_state:
            widget.unsetCursor()
        self.tools.reorder.setToolTip('拖到另一格后松开互换；点击结束调整' if enabled else '调整画面位置')

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.UngrabMouse and watched is self and self._reorder_drag is not None:
            self._reorder_drag = None
            self.setCursor(Qt.OpenHandCursor if self.tools.reorder.isChecked() else Qt.ArrowCursor)
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseMove,
                        QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return False
        preview = self._live_resize.preview if self._live_resize is not None else None
        if not isinstance(watched, QWidget) or watched.window() not in (self, preview):
            return False
        wall = self.controller.host.wall
        surfaces = (self, preview, wall, *(surface for tile in wall.visible_tiles()
                                 for surface in (tile, tile.video, tile.cover, tile.video_danmaku, tile.spinner, tile.pause_overlay)))
        if watched not in surfaces:
            return False
        point = event.globalPosition().toPoint()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._live_resize is not None:
                self._live_resize.finish(immediate=True)
            self.setFocus(Qt.MouseFocusReason)
            edges = self._resize_edges(self.mapFromGlobal(point))
            if self.tools.reorder.isChecked() and not edges:
                tile = self._tile_at(point)
                if tile is not None:
                    self._reorder_drag = (tile, point)
                    self.setCursor(Qt.ClosedHandCursor)
                    self.grabMouse()
                return True
            self._gesture = (point, self.geometry(), edges)
            self.grabMouse()
            return True
        if kind == QEvent.MouseMove:
            if self._reorder_drag is not None:
                source, _start = self._reorder_drag
                target = self._tile_at(point)
                self.setCursor(Qt.DragMoveCursor if target is not None and target is not source
                               else Qt.ClosedHandCursor if target is source else Qt.ForbiddenCursor)
                return True
            edges = self._gesture[2] if self._gesture is not None else self._resize_edges(self.mapFromGlobal(point))
            cursor = (Qt.SizeFDiagCursor if edges in (Qt.TopEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge)
                      else Qt.SizeBDiagCursor if edges in (Qt.TopEdge | Qt.RightEdge, Qt.BottomEdge | Qt.LeftEdge)
                      else Qt.SizeHorCursor if edges & (Qt.LeftEdge | Qt.RightEdge)
                      else Qt.SizeVerCursor if edges else Qt.OpenHandCursor if self.tools.reorder.isChecked() else Qt.ArrowCursor)
            watched.setCursor(cursor)
            if self._gesture is not None:
                start, bounds, edges = self._gesture
                delta = point - start
                rect = QRect(bounds)
                if not edges:
                    rect.translate(delta)
                else:
                    if edges & Qt.LeftEdge:
                        rect.setLeft(min(bounds.left() + delta.x(), bounds.right() - self.minimumWidth() + 1))
                    if edges & Qt.RightEdge:
                        rect.setRight(max(bounds.right() + delta.x(), bounds.left() + self.minimumWidth() - 1))
                    if edges & Qt.TopEdge:
                        rect.setTop(min(bounds.top() + delta.y(), bounds.bottom() - self.minimumHeight() + 1))
                    if edges & Qt.BottomEdge:
                        rect.setBottom(max(bounds.bottom() + delta.y(), bounds.top() + self.minimumHeight() - 1))
                    by_height = (not edges & (Qt.LeftEdge | Qt.RightEdge)
                                 or bool(edges & (Qt.TopEdge | Qt.BottomEdge)) and abs(delta.y()) * self.aspect > abs(delta.x()))
                    width = round(rect.height() * self.aspect) if by_height else rect.width()
                    width = max(self.minimumWidth(), width)
                    size = QSize(width, round(width / self.aspect))
                    rect.setSize(size)
                    if edges & Qt.LeftEdge:
                        rect.moveRight(bounds.right())
                    if edges & Qt.TopEdge:
                        rect.moveBottom(bounds.bottom())
                if edges:
                    self._pending_geometry = rect
                    if not self._geometry_timer.isActive():
                        self._geometry_timer.start()
                else:
                    self.setGeometry(rect)
                return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._reorder_drag is not None:
            source, start = self._reorder_drag
            target = self._tile_at(point)
            self._reorder_drag = None
            self.releaseMouse()
            self.setCursor(Qt.OpenHandCursor)
            if target is not None and (point - start).manhattanLength() >= QApplication.startDragDistance():
                self.controller.swap_positions(source, target)
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._gesture is not None:
            self._flush_geometry(finishing=True)
            self._gesture = None
            self.releaseMouse()
            if self._live_resize is not None:
                self._live_resize.finish()
            return True
        return kind == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton

    def _flush_geometry(self, *, finishing=False):
        self._geometry_timer.stop()
        rect, self._pending_geometry = self._pending_geometry, None
        if rect is not None:
            if (not finishing and self._live_resize is None and self._gesture is not None
                    and sys.platform == 'win32' and QApplication.platformName() == 'windows'):
                from .picture_in_picture_resize import LiveResize
                self._live_resize = LiveResize(self)
                if not self._live_resize.begin():
                    self._live_resize = None
            if self._live_resize is not None:
                self._live_resize.set_geometry(rect)
            else:
                self.setGeometry(rect)

    def stop(self):
        if self._live_resize is not None:
            self._live_resize.finish(immediate=True)
        self._hover_timer.stop()
        self._geometry_timer.stop()
        self._pending_geometry = None
        QApplication.instance().removeEventFilter(self)
        self.tools.hide()
        self._gesture = None
        self._reorder_drag = None
        grabber = QWidget.mouseGrabber()
        if grabber is not None and grabber.window() is self:
            grabber.releaseMouse()
        for widget, tracking, cursor in self._surface_state:
            widget.setMouseTracking(tracking)
            if cursor is None:
                widget.unsetCursor()
            else:
                widget.setCursor(cursor)

    def _pin(self, pinned):
        self.controller.pinned = pinned
        self._apply_pin(pinned)
        self.pin.setToolTip('已置顶，点击取消置顶' if pinned else '未置顶，点击置顶')
        for button in self.tools.findChildren(PictureInPictureButton):
            button.update()

    def _apply_pin(self, pinned):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
            # Change only native Z order. Recomputing all Qt window flags can
            # disturb alpha tool surfaces even without a QWidget Hide event.
            user32.SetWindowPos(int(self.winId()), -1 if pinned else -2, 0, 0, 0, 0, 0x13)
        else:
            self.windowHandle().setFlag(Qt.WindowStaysOnTopHint, pinned)

    def closeEvent(self, event):
        self.controller.restore(activate=True)
        event.accept()


class PictureInPicture(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.floating = None
        self.dialog = None
        saved = host.state.get('ui', {}).get('picture_in_picture', {})
        self.selection = list(saved.get('selection', []))
        self.columns = saved.get('columns', 0)
        self.primary = saved.get('primary')
        self.pinned = bool(saved.get('pinned', True))
        self.geometry = saved.get('geometry', '')
        self._video_aspects = {}
        self._aspect_timer = QTimer(self)
        self._aspect_timer.setInterval(1000)
        self._aspect_timer.timeout.connect(self._refresh_aspects)
        theme.signals().changed.connect(self._refresh_theme)
        self.placeholder = QFrame(host._content)
        self.placeholder.setObjectName('PluginCard')
        layout = QVBoxLayout(self.placeholder)
        layout.addStretch()
        text = QLabel('正在画中画中观看\n其他画面按原设置在后台播放\n返回后恢复原监控室布局', self.placeholder)
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)
        for title, action in (('管理画中画', self.manage), ('返回监控室', self.restore)):
            button = ActionButton(title, self.placeholder)
            button.clicked.connect(action)
            layout.addWidget(button, 0, Qt.AlignHCenter)
        layout.addStretch()
        self.placeholder.hide()

    @property
    def active(self):
        return self.floating is not None

    def _refresh_theme(self, *_args):
        if self.active:
            self.floating.tools.update()
            for button in self.floating.tools.findChildren(PictureInPictureButton):
                button.update()

    def manage(self):
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if not self.selection:
            capacity = self.host.wall._capacity() or len(self.host.wall.tiles)
            self.selection = [index for index, tile in enumerate(self.host.wall.tiles[:capacity])
                              if tile.room.get('room_id')]
        self.dialog = PictureInPictureDialog(self)
        self.dialog.finished.connect(self._finish_manage)
        self.dialog.open()

    def _finish_manage(self, _result):
        self.dialog = None
        self._sync_overlays()

    def aspects_for(self, selection):
        aspects = []
        for index in selection:
            tile = self.host.wall.tiles[index]
            room = tile.room.get('room_id')
            aspect = video_aspect(self.host.players.get(tile))
            previous_room, previous_aspect = self._video_aspects.get(tile, (None, 16 / 9))
            aspect = aspect or (previous_aspect if previous_room == room else 16 / 9)
            self._video_aspects[tile] = (room, aspect)
            aspects.append(aspect)
        return aspects

    def _refresh_aspects(self):
        if not self.active or self.floating._gesture is not None or self.floating._reorder_drag is not None:
            return
        wall = self.host.wall
        aspects = self.aspects_for(self.selection)
        if aspects == wall.picture_in_picture_aspects:
            return
        wall.picture_in_picture_aspects = aspects
        self.floating.set_composition(aspects, self.columns, self.selection.index(self.primary))
        wall.relayout(force=True)

    def swap_positions(self, source, target):
        tiles = self.host.wall.picture_in_picture_tiles
        if source is target or source not in tiles or target not in tiles:
            return
        first, second = tiles.index(source), tiles.index(target)
        primary = self.selection.index(self.primary)
        self.selection[first], self.selection[second] = self.selection[second], self.selection[first]
        if self.columns == FOCUS_LAYOUT:
            self.primary = self.selection[primary]
        self.start(self.selection, self.columns, self.primary)

    def start(self, selection, columns=0, primary=None):
        wall = self.host.wall
        tiles = [wall.tiles[index] for index in selection
                 if 0 <= index < len(wall.tiles) and wall.tiles[index].room.get('room_id')]
        if not tiles:
            return
        selection = [wall.tiles.index(tile) for tile in tiles]
        primary = primary if primary in selection else selection[0]
        self.host._cancel_interactive_resize()
        if self.host._fullscreen_tile is not None:
            self.host._exit_fullscreen()
        self.selection, self.columns = list(selection), columns
        self.primary = primary
        opened = not self.active
        if opened:
            wall.set_sidebar_animating(False)
            self.floating = PictureInPictureWindow(self)
            if self.geometry:
                self.floating.restoreGeometry(QByteArray.fromBase64(self.geometry.encode('ascii')))
            else:
                width = 480 if len(tiles) == 1 else 640
                self.floating.resize_to_width(width)
            self._minimums = {tile: tile.minimumSize() for tile in wall.tiles}
            content = self.host._content.layout()
            content.removeWidget(wall)
            content.insertWidget(0, self.placeholder, 1)
            self.placeholder.show()
            self.floating.box.addWidget(wall, 1)
        aspects = self.aspects_for(selection)
        wall.set_picture_in_picture(tiles, columns, aspects, selection.index(primary))
        self.floating.set_composition(aspects, columns, selection.index(primary))
        self.floating.show()
        wall.show()
        self._sync_overlays()
        self._aspect_timer.start()
        self.host.sidebar.picture_in_picture_button.setToolTip(f'管理画中画（{len(tiles)} 路）')
        if opened:
            QTimer.singleShot(0, self, self._minimize_host)

    def _minimize_host(self):
        if self.active and not self.host._closing:
            self.host.showMinimized()

    def _sync_overlays(self):
        wall = self.host.wall
        layer = wall._quick_danmaku_layer
        if layer is not None:
            layer.set_presentation_window(self.host._fullscreen_tile)
            layer.show()
        for tile in wall.tiles:
            tile.video_danmaku.super_chat_overlay.set_presentation_changing(False)
            dialog = self.host._stream_info_dialogs.get(tile)
            if dialog is not None:
                dialog.set_presentation_owner(tile.window())

    def restore(self, *, activate=False):
        floating = self.floating
        if floating is None:
            return
        if self.dialog is not None:
            self.dialog.reject()
        self.geometry = str(floating.saveGeometry().toBase64(), 'ascii')
        floating.stop()
        self._aspect_timer.stop()
        self.floating = None
        wall = self.host.wall
        floating.box.removeWidget(wall)
        content = self.host._content.layout()
        content.removeWidget(self.placeholder)
        self.placeholder.hide()
        content.insertWidget(0, wall, 1)
        for tile, minimum in self._minimums.items():
            tile.setMinimumSize(minimum)
        wall.set_picture_in_picture(None)
        floating.hide()
        floating.deleteLater()
        wall.show()
        self._sync_overlays()
        self.host.sidebar.picture_in_picture_button.setToolTip('选择多路画面，组合为置顶小窗')
        self.host._refresh_meta()
        if activate:
            self.host._tray.restore()

    def state(self):
        geometry = (str(self.floating.saveGeometry().toBase64(), 'ascii')
                    if self.active else self.geometry)
        return dict(selection=self.selection, columns=self.columns, primary=self.primary, pinned=self.pinned, geometry=geometry)
