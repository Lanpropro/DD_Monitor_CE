"""关注栏内部拖拽：单张拖影、鼠标捕获与现有 Qt 落点事件。"""
import logging

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from shiboken6 import isValid

from .sidebar_hit_test import widget_at
from .card_drop import remember_card

ROOM_MIME = 'application/x-ddm-room'
TILE_MIME = 'application/x-ddm-tile'
NAV_MIME = 'application/x-ddm-nav'
FOLDER_MIME = 'application/x-ddm-folder'


class SidebarDrag(QObject):
    """拖影按屏幕刷新节奏合并移动；落点每 16 ms 检查一次。"""

    def __init__(self, sidebar):
        super().__init__(sidebar)
        self.sidebar = sidebar
        self.source = None
        self.target = None
        self.ghost = None
        self.owner = None
        self.mime = None
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.visual_timer = QTimer(self)
        self.visual_timer.setTimerType(Qt.PreciseTimer)
        self.visual_timer.timeout.connect(self._move_ghost)

    @property
    def active(self):
        return self.source is not None

    def start(self, source, mime, pixmap, hotspot, global_pos):
        if self.active:
            return
        self.source, self.mime = source, mime
        if mime.hasFormat(ROOM_MIME) or mime.hasFormat(TILE_MIME):
            remember_card(mime, pixmap, hotspot)
        self.position = QPoint(global_pos)
        self.hotspot = QPoint(hotspot)
        self._last_update = None
        self.owner = self.sidebar.window()
        self.actions = Qt.MoveAction if (mime.hasFormat(FOLDER_MIME) or mime.hasFormat(TILE_MIME)) else Qt.CopyAction | Qt.MoveAction
        self.ghost = QLabel(self.owner, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
        self.ghost.setAttribute(Qt.WA_ShowWithoutActivating)
        self.ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.ghost.setAttribute(Qt.WA_TranslucentBackground)
        self.ghost.setPixmap(pixmap)
        self.ghost.resize(pixmap.deviceIndependentSize().toSize())
        QApplication.instance().installEventFilter(self)
        source.destroyed.connect(self.cancel)
        try:
            if mime.hasFormat(FOLDER_MIME):
                self.sidebar.start_folder_drag()
            elif mime.hasFormat(NAV_MIME):
                rid = bytes(mime.data(NAV_MIME)).decode()
                self.sidebar.show_drop_indicator(rid, source._index_in_host())
            self.ghost.move(self.position - self.hotspot)
            self.ghost.show()
            handle = self.ghost.windowHandle()
            self._set_frame_interval(handle.screen())
            handle.screenChanged.connect(self._set_frame_interval)
            self.owner.grabMouse()
            self.owner.grabKeyboard()
            self.timer.start()
            self.visual_timer.start()
        except BaseException:
            self.cancel()
            raise

    def eventFilter(self, watched, event):
        if not self.active:
            return False
        kind = event.type()
        if kind == QEvent.MouseMove:
            self.position = event.globalPosition().toPoint()
            if not event.buttons() & Qt.LeftButton:
                self.cancel()
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.position = event.globalPosition().toPoint()
            self.finish()
            return True
        if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.cancel()
            return True
        if kind == QEvent.Wheel:
            self._wheel(event)
            return True
        if (kind == QEvent.ApplicationDeactivate or
                watched is self.owner and kind in (QEvent.WindowDeactivate, QEvent.Hide, QEvent.Close, QEvent.UngrabMouse) or
                watched is self.sidebar and kind == QEvent.Hide):
            self.cancel()
        return False

    def _wheel(self, event):
        area = self.sidebar.scroll
        if not area.viewport().rect().contains(area.viewport().mapFromGlobal(event.globalPosition().toPoint())):
            return
        horizontal = self.sidebar.list_box.horizontal
        bar = area.horizontalScrollBar() if horizontal else area.verticalScrollBar()
        pixels = event.pixelDelta()
        delta = (pixels.x() or pixels.y()) if horizontal else pixels.y()
        if delta == 0:
            angle = event.angleDelta()
            delta = (angle.y() or angle.x()) / 120 * self.sidebar.list_box.WHEEL_PIXELS
        bar.setValue(bar.value() - round(delta))

    def _tick(self):
        if not self.active:
            return
        if not isValid(self.source) or not self.owner.isVisible():
            self.cancel()
            return
        try:
            area = self.sidebar.scroll
            key = (self.position.x(), self.position.y(), area.horizontalScrollBar().value(),
                   area.verticalScrollBar().value())
            if key != self._last_update:
                self._last_update = key
                self._update_target()
        except BaseException:
            self.cancel()
            raise

    def _set_frame_interval(self, screen):
        rate = max(60, screen.refreshRate() if screen is not None else 60)
        self.visual_timer.setInterval(max(1, int(1000 / rate)))

    def _move_ghost(self):
        if self.active:
            target = self.position - self.hotspot
            if self.ghost.pos() != target:
                self.ghost.move(target)

    def _event(self, kind, target):
        point = target.mapFromGlobal(self.position)
        modifiers = QApplication.keyboardModifiers()
        if kind is QDropEvent:
            return kind(QPointF(point), self.actions, self.mime, Qt.LeftButton, modifiers)
        return kind(point, self.actions, self.mime, Qt.LeftButton, modifiers)

    def _leave(self):
        target, self.target = self.target, None
        if target is not None and isValid(target):
            QApplication.sendEvent(target, QDragLeaveEvent())

    def _update_target(self):
        widget = widget_at(self.position)
        candidate = None
        while widget is not None:
            if widget.acceptDrops() and widget.isEnabled():
                candidate = widget
                if candidate is self.target:
                    break
                self._leave()
                enter = self._event(QDragEnterEvent, candidate)
                QApplication.sendEvent(candidate, enter)
                if enter.isAccepted():
                    break
                candidate = None
            widget = widget.parentWidget()
        if candidate is not self.target:
            self._leave()
            self.target = candidate
        if self.target is not None:
            QApplication.sendEvent(self.target, self._event(QDragMoveEvent, self.target))
        viewport = self.sidebar.scroll.viewport()
        if not viewport.rect().contains(viewport.mapFromGlobal(self.position)):
            self.sidebar.list_box.set_scroll_dir(0)

    def finish(self):
        if not self.active:
            return False
        try:
            hovered = type(self.target).__name__ if self.target is not None else 'none'
            # Exclude our transparent top-level from Qt's mask-based widgetAt lookup.
            self.ghost.hide()
            self._update_target()  # Release position wins over the last throttled move.
            target = self.target
            drop = self._event(QDropEvent, target) if target is not None else None
            self._release_input()  # Playback callbacks must not run with mouse capture held.
            if target is not None and isValid(target):
                QApplication.sendEvent(target, drop)
            accepted = drop is not None and drop.isAccepted()
            logging.getLogger(__name__).info('sidebar_drop hovered=%s target=%s accepted=%s',
                hovered, type(target).__name__ if target is not None else 'none', accepted)
            return accepted
        finally:
            self._release_input()
            self._cleanup()

    def cancel(self, *_args):
        if self.active:
            self._release_input()
            self._cleanup()

    def _release_input(self):
        self.timer.stop()
        self.visual_timer.stop()
        QApplication.instance().removeEventFilter(self)
        if QWidget.mouseGrabber() is self.owner:
            self.owner.releaseMouse()
        if QWidget.keyboardGrabber() is self.owner:
            self.owner.releaseKeyboard()
        self.ghost.hide()

    def _cleanup(self):
        source, self.source = self.source, None
        try:
            self._leave()
        finally:
            if source is not None and isValid(source):
                source.destroyed.disconnect(self.cancel)
                source._press_pos = None
                if hasattr(source, 'setDown'):
                    source.setDown(False)
            self.ghost.deleteLater()
            self.ghost = None
            folder = self.mime.hasFormat(FOLDER_MIME)
            tile = self.mime.hasFormat(TILE_MIME)
            self.mime = self.owner = None
            if folder:
                self.sidebar.end_folder_drag()
            elif not tile:
                self.sidebar.end_drag()
