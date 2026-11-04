"""A selected group of existing playback panes in one independent floating window."""
import math

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPainterPath, QPen, QRegion, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from . import theme
from .ui import ActionButton, ElidedLabel, page_header


def pane_rectangles(count, area, columns=0):
    if not count:
        return []
    if not columns:
        # Prefer cells close to a video's aspect ratio, including tall windows.
        columns = min(range(1, count + 1), key=lambda cols:
            abs(math.log(max(1, area.width()) * math.ceil(count / cols)
                         / (max(1, area.height()) * cols * 16 / 9)))
            + (math.ceil(count / cols) * cols - count) * .08)
    columns = min(count, columns)
    rows = math.ceil(count / columns)
    width, height = max(1, area.width()), max(1, area.height())
    return [QRect(area.x() + width * (index % columns) // columns,
                  area.y() + height * (index // columns) // rows,
                  width * (index % columns + 1) // columns - width * (index % columns) // columns,
                  height * (index // columns + 1) // rows - height * (index // columns) // rows)
            for index in range(count)]


class CompositionPreview(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('PluginCard')
        self.setFixedHeight(156)
        self.labels = []
        self.columns = 0
        self.aspect = 16 / 9

    def set_panes(self, names, columns, aspect=0):
        for label in self.labels:
            label.deleteLater()
        self.labels = [ElidedLabel(name, self) for name in names]
        self.columns = columns
        cols = min(len(names), columns or math.ceil(math.sqrt(len(names)))) if names else 1
        self.aspect = aspect or cols / max(1, math.ceil(len(names) / cols)) * 16 / 9
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
                len(self.labels), canvas, self.columns)):
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
        for title, value in (('自动排列', 0), ('横向排列', 16), ('纵向排列', 1), ('两列排列', 2), ('三列排列', 3)):
            self.columns.addItem(title, value)
        self.columns.setAccessibleName('画中画排列方式')
        self.columns.setCurrentIndex(max(0, self.columns.findData(controller.columns)))
        layout.addWidget(self.columns)
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
        self._refresh()

    def _refresh(self, *_args):
        names = [check.text() for check in self.checks.values() if check.isChecked()]
        wall = self.controller.host.wall
        aspect = wall.width() / max(1, wall.height()) if self.controller.active else 0
        self.preview.set_panes(names, self.columns.currentData(), aspect)
        self.start.setEnabled(bool(names))
        self.hint.setText(f'已选择 {len(names)} 路。小窗支持自由缩放和置顶，其他画面按原声音设置在后台播放。'
                          if self.checks else '画面墙中还没有直播间，请先添加画面。')

    def _apply(self):
        selected = [index for index, check in self.checks.items() if check.isChecked()]
        self.controller.start(selected, self.columns.currentData())
        self.accept()


class PictureInPictureButton(QPushButton):
    def __init__(self, kind, tooltip, parent):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(24, 24)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover)
        self.setStyleSheet('QPushButton { border: none; background: transparent; padding: 0; min-width: 0; min-height: 0; }')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        active = self.underMouse() or self.hasFocus() or self.isChecked()
        painter.setBrush(theme.qcolor(theme.ACCENT) if active else QColor(0, 0, 0, 170))
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
        else:
            painter.drawLine(8, 8, 16, 16)
            painter.drawLine(16, 8, 8, 16)


class PictureInPictureTools(QWidget):
    """An owned alpha surface keeps the icons above native video without a bar."""
    def __init__(self, owner):
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(80, 24)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.manage = PictureInPictureButton('composition', '选择画面组合', self)
        self.pin = PictureInPictureButton('pin', '置顶画中画', self)
        self.pin.setCheckable(True)
        self.pin.setChecked(owner.controller.pinned)
        self.back = PictureInPictureButton('back', '关闭画中画并返回监控室（Esc）', self)
        for button in (self.manage, self.pin, self.back):
            box.addWidget(button)
        self.manage.clicked.connect(owner.controller.manage)
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
        self.setMinimumSize(280, 180)
        self.resize(640, 400)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)
        self.tools = PictureInPictureTools(self)
        self.pin = self.tools.pin
        self._gesture = None
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
        widget = QApplication.widgetAt(QCursor.pos())
        focus = QApplication.focusWidget()
        hovered = widget is not None and widget.window() in (self, self.tools)
        focused = focus is not None and focus.window() is self.tools
        visible = (self.isVisible() and not self.isMinimized()
                   and self.controller.dialog is None and (hovered or focused))
        self.tools.move(self.mapToGlobal(QPoint(self.width() - 88, 8)))
        self.tools.setVisible(visible)
        if visible:
            self.tools.raise_()

    def focusNextPrevChild(self, next):
        self.tools.show()
        self.tools.activateWindow()
        (self.tools.manage if next else self.tools.back).setFocus(Qt.TabFocusReason)
        return True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self._poll_tools()

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

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseMove,
                        QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return False
        if not isinstance(watched, QWidget) or watched.window() is not self:
            return False
        wall = self.controller.host.wall
        surfaces = (self, wall, *(surface for tile in wall.visible_tiles()
                                 for surface in (tile, tile.video, tile.cover, tile.video_danmaku)))
        if watched not in surfaces:
            return False
        point = event.globalPosition().toPoint()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self._gesture = (point, self.geometry(), self._resize_edges(self.mapFromGlobal(point)))
            watched.grabMouse()
            return True
        if kind == QEvent.MouseMove:
            edges = self._resize_edges(self.mapFromGlobal(point))
            cursor = (Qt.SizeFDiagCursor if edges in (Qt.TopEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge)
                      else Qt.SizeBDiagCursor if edges in (Qt.TopEdge | Qt.RightEdge, Qt.BottomEdge | Qt.LeftEdge)
                      else Qt.SizeHorCursor if edges & (Qt.LeftEdge | Qt.RightEdge)
                      else Qt.SizeVerCursor if edges else Qt.ArrowCursor)
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
                self.setGeometry(rect)
                return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._gesture is not None:
            self._gesture = None
            watched.releaseMouse()
            return True
        return kind == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton

    def stop(self):
        self._hover_timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.tools.hide()
        self._gesture = None
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
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, pinned)
        self.setGeometry(geometry)
        self.show()

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
        self.pinned = bool(saved.get('pinned', True))
        self.geometry = saved.get('geometry', '')
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

    def start(self, selection, columns=0):
        wall = self.host.wall
        tiles = [wall.tiles[index] for index in selection
                 if 0 <= index < len(wall.tiles) and wall.tiles[index].room.get('room_id')]
        if not tiles:
            return
        self.host._cancel_interactive_resize()
        if self.host._fullscreen_tile is not None:
            self.host._exit_fullscreen()
        self.selection, self.columns = list(selection), columns
        if not self.active:
            wall.set_sidebar_animating(False)
            self.floating = PictureInPictureWindow(self)
            if self.geometry:
                self.floating.restoreGeometry(QByteArray.fromBase64(self.geometry.encode('ascii')))
            else:
                cols = min(len(tiles), columns or math.ceil(math.sqrt(len(tiles))))
                width = 480 if len(tiles) == 1 else 640
                self.floating.resize(width, round(width * math.ceil(len(tiles) / cols) / cols * 9 / 16))
            self._minimums = {tile: tile.minimumSize() for tile in wall.tiles}
            content = self.host._content.layout()
            content.removeWidget(wall)
            content.insertWidget(0, self.placeholder, 1)
            self.placeholder.show()
            self.floating.box.addWidget(wall, 1)
        wall.set_picture_in_picture(tiles, columns)
        self.floating.show()
        wall.show()
        self._sync_overlays()
        self.host.sidebar.picture_in_picture_button.setToolTip(f'管理画中画（{len(tiles)} 路）')

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
        return dict(selection=self.selection, columns=self.columns, pinned=self.pinned, geometry=geometry)
