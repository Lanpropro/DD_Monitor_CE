"""Picture-in-picture floating window, controls and native interaction."""
import math
import sys
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget
from . import theme
from .danmaku_widgets import DanmakuPanel
from .pip_geometry import composition_ratio
from .shortcut_actions import DEFAULT_SHORTCUTS
from .window_fullscreen import set_window_topmost


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
        if self.kind == 'pin':
            # Blue denotes the pinned state rather than a lingering hover.
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
        elif self.kind == 'return':
            painter.drawRoundedRect(QRectF(5, 5, 14, 14), 1, 1)
            painter.drawLine(8, 12, 16, 12)
            painter.drawLine(8, 12, 11, 9)
            painter.drawLine(8, 12, 11, 15)
        elif self.kind == 'audio':
            painter.drawLine(5, 10, 8, 10)
            painter.drawLine(8, 10, 12, 7)
            painter.drawLine(12, 7, 12, 17)
            painter.drawLine(12, 17, 8, 14)
            painter.drawLine(8, 14, 5, 14)
            painter.drawLine(5, 14, 5, 10)
            painter.drawArc(QRectF(10, 7, 8, 10), -60 * 16, 120 * 16)
        else:
            painter.drawLine(8, 8, 16, 16)
            painter.drawLine(16, 8, 8, 16)


class PictureInPictureTools(QWidget):
    """An owned alpha surface keeps the icons above native video without a bar."""
    def __init__(self, owner):
        super().__init__(owner, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(136, 24)
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
        self.back = PictureInPictureButton('return', '关闭画中画并返回监控室', self)
        self.close_only = PictureInPictureButton('close', '仅关闭画中画，保持主窗口状态', self)
        for button in (self.manage, self.reorder, self.pin, self.back, self.close_only):
            box.addWidget(button)
        self.manage.clicked.connect(owner.controller.manage)
        self.reorder.toggled.connect(owner._set_reordering)
        self.pin.toggled.connect(owner._pin)
        self.back.clicked.connect(owner.return_to_monitor)
        self.close_only.clicked.connect(owner.close)


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
        self.setFocusPolicy(Qt.StrongFocus)
        self.aspect = 16 / 9
        self._native_rounding = False
        self._rounding_hwnd = None
        self._fitting = False
        self._pane_rectangles = ()
        self._pane_region = QRegion()
        self._has_pane_gaps = False
        self.resize(640, 360)
        self.box = QHBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)
        self.danmaku_panels = {}
        self.tools = PictureInPictureTools(self)
        self.pin = self.tools.pin
        self._gesture = None
        self._reorder_drag = None
        self._live_resize = None
        self._live_move = None
        from .picture_in_picture_audio import AudioFeedback, PictureInPictureAudio
        self.audio_tools = QWidget(self, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.audio_tools.setAttribute(Qt.WA_TranslucentBackground)
        self.audio_tools.setAttribute(Qt.WA_ShowWithoutActivating)
        self.audio_tools.setFixedSize(24, 24)
        self.audio_button = PictureInPictureButton('audio', '画中画音量', self.audio_tools)
        self.audio_button.setCheckable(True)
        self.audio_panel = PictureInPictureAudio(self)
        self.audio_feedback = AudioFeedback(self)
        self.audio_button.clicked.connect(self.audio_panel.toggle)
        self._pending_geometry = None
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setTimerType(Qt.PreciseTimer)
        self._geometry_timer.setInterval(16)
        self._geometry_timer.timeout.connect(self._flush_geometry)
        self._surface_state = []
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(100)
        self._hover_timer.timeout.connect(self._poll_tools)
        self._hover_timer.start()
        QApplication.instance().installEventFilter(self)

    def track_tiles(self, tiles):
        tracked = {widget for widget, _tracking, _cursor in self._surface_state}
        for tile in tiles:
            for widget in (tile, tile.video):
                if widget not in tracked:
                    self._surface_state.append((widget, widget.hasMouseTracking(),
                        widget.cursor() if widget.testAttribute(Qt.WA_SetCursor) else None))
                    widget.setMouseTracking(True)

    def forget_tile(self, tile):
        remaining = []
        for widget, tracking, cursor in self._surface_state:
            if widget not in (tile, tile.video):
                remaining.append((widget, tracking, cursor))
                continue
            widget.setMouseTracking(tracking)
            if cursor is None:
                widget.unsetCursor()
            else:
                widget.setCursor(cursor)
        self._surface_state = remaining

    def _poll_tools(self):
        if self._live_move is not None:
            if (not self._live_move.starting and not self._live_move.finishing
                    and not self._live_move.sync()):
                self._live_move.finish(immediate=True)
            return
        if self._gesture is not None and not self._gesture[2]:
            return
        if self._live_resize is not None:
            self.tools.hide()
            self.hide_audio()
            if (not self._live_resize.starting and not self._live_resize.finishing
                    and not self._live_resize.sync()):
                self._live_resize.finish(immediate=True)
            return
        hovered = self._pointer_over()
        focused = any(button.keyboard_focus and button.hasFocus()
                      for button in (*self.tools.findChildren(PictureInPictureButton), self.audio_button))
        visible = (self.isVisible() and not self.isMinimized()
                   and self.controller.dialog is None and (hovered or focused or self.audio_panel.isVisible()))
        position = self.mapToGlobal(self._tool_position(self.tools.size()))
        moved = self.tools.pos() != position
        was_visible = self.tools.isVisible()
        if moved:
            self.tools.move(position)
        if was_visible != visible:
            self.tools.setVisible(visible)
        if visible and (not was_visible or moved):
            self.tools.raise_()
        audio_position = self.mapToGlobal(self._tool_position(self.audio_tools.size(), bottom=True))
        audio_moved = self.audio_tools.pos() != audio_position
        audio_visible = self.audio_tools.isVisible()
        if audio_moved:
            self.audio_tools.move(audio_position)
        self.audio_tools.setVisible(visible)
        if visible and (not audio_visible or audio_moved):
            self.audio_tools.raise_()
        if self.controller.dialog is not None:
            self.audio_panel.hide()

    def _tool_position(self, size, *, bottom=False):
        preferred = QPoint(8 if bottom and self.height() < 64 else self.width() - size.width() - 8,
                           self.height() - size.height() - 8 if bottom else 8)
        if not self._has_pane_gaps or QRegion(QRect(preferred, size)).subtracted(self._pane_region).isEmpty():
            return preferred
        panes = sorted(self._pane_rectangles,
                       key=lambda rect: (-rect.bottom() if bottom else rect.top(), -rect.right()))
        # The toolbar can also span adjoining panes if they occupy the whole row.
        for pane in panes:
            position = QPoint(max(0, pane.right() + 1 - size.width() - 8),
                              pane.bottom() + 1 - size.height() - 8 if bottom else pane.top() + 8)
            if QRegion(QRect(position, size)).subtracted(self._pane_region).isEmpty():
                return position
        return QPoint(min(max(0, self.width() - size.width()), panes[0].x()),
                      max(0, min(panes[0].y(), self.height() - size.height())))

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
        return widget is not None and widget.window() in (self, self.tools, self.audio_tools, self.audio_panel)

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
        if self._live_move is not None:
            return self._live_move.preview.saveGeometry()
        if self._live_resize is not None:
            return self._live_resize.preview.saveGeometry()
        return super().saveGeometry()

    def set_danmaku_panes(self, slots, wall):
        keys = {chat.key for _, chat in slots}
        for key in self.danmaku_panels.keys() - keys:
            panel = self.danmaku_panels.pop(key)
            panel.hide()
            panel.deleteLater()
        for _, chat in slots:
            if chat.key not in self.danmaku_panels:
                panel = DanmakuPanel(wall)
                panel.setAcceptDrops(False)
                panel.setCursor(Qt.ArrowCursor)
                self.controller.host._connect_danmaku_panel(panel)
                self.danmaku_panels[chat.key] = panel
        return tuple((index, self.danmaku_panels[chat.key]) for index, chat in slots)

    def set_composition(self, aspects, columns, primary=0, *, placement=()):
        self.aspect = composition_ratio(aspects, columns, primary, placement=placement)
        minimum_height = max(48, math.ceil((self.tools.width() + 48) / self.aspect))
        self.setMinimumSize(round(minimum_height * self.aspect), minimum_height)
        screen = self.screen().availableGeometry()
        self.resize_to_width(min(self.width(), screen.width(), round(screen.height() * self.aspect)))

    def resize_to_width(self, width):
        self._fitting = True
        width = max(self.minimumWidth(), width)
        self.resize(width, round(width / self.aspect))
        self._fitting = False

    def set_pane_rectangles(self, rectangles):
        rectangles = tuple(rectangles)
        if rectangles == self._pane_rectangles:
            return
        self._pane_rectangles = rectangles
        self._pane_region = QRegion()
        for rect in rectangles:
            self._pane_region |= QRegion(rect)
        self._apply_rounding()

    def _apply_rounding(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        region = QRegion(path.toFillPolygon().toPolygon())
        # Allow for the one-pixel remainder when fitting a rectangular layout.
        self._has_pane_gaps = bool(self._pane_rectangles) and not QRegion(
            self.rect().adjusted(1, 1, -1, -1)).subtracted(self._pane_region).isEmpty()
        if self._has_pane_gaps:
            region &= self._pane_region
        if self.property('presentationMask') != region:
            self.setProperty('presentationMask', region)
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            from .window_fullscreen import _dwm_set
            hwnd = int(self.winId())
            if hwnd != self._rounding_hwnd:
                self._rounding_hwnd = hwnd
                self._native_rounding = _dwm_set(hwnd, 33, 2) == 0
                _dwm_set(hwnd, 34, 0xFFFFFFFE)
        # DWM smooths the outer corners even with rectangular holes. Including a
        # polygonal corner in the window region cuts its antialiased pixels off.
        if self._native_rounding:
            region = self._pane_region if self._has_pane_gaps else QRegion()
        if self.mask() != region:
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
        if self._gesture is None:
            self._poll_tools()

    def hideEvent(self, event):
        self.tools.hide()
        self.hide_audio()
        super().hideEvent(event)

    def hide_audio(self):
        self.audio_tools.hide()
        self.audio_panel.hide()
        self.audio_feedback.hide()

    def _resize_edges(self, point):
        surface = self._pane_region if self._has_pane_gaps else self.rect()

        def edges_at(margin):
            horizontal = Qt.Edges()
            vertical = Qt.Edges()
            if not surface.contains(point - QPoint(margin, 0)):
                horizontal = Qt.LeftEdge
            elif not surface.contains(point + QPoint(margin, 0)):
                horizontal = Qt.RightEdge
            if not surface.contains(point - QPoint(0, margin)):
                vertical = Qt.TopEdge
            elif not surface.contains(point + QPoint(0, margin)):
                vertical = Qt.BottomEdge
            return horizontal, vertical

        # Larger corner targets, narrow edge targets, including exposed pane edges.
        horizontal, vertical = edges_at(18)
        if not (horizontal and vertical):
            horizontal, vertical = edges_at(6)
        return horizontal | vertical

    def _resize_geometry(self, bounds, edges, delta):
        rect = QRect(bounds)
        if delta.isNull():
            return rect
        horizontal = edges & (Qt.LeftEdge | Qt.RightEdge)
        vertical = edges & (Qt.TopEdge | Qt.BottomEdge)
        width_delta = -delta.x() if edges & Qt.LeftEdge else delta.x()
        height_delta = -delta.y() if edges & Qt.TopEdge else delta.y()
        aspect = self.aspect
        if horizontal and vertical:
            # Project the signed pointer motion onto the aspect-ratio diagonal.
            width_delta = (width_delta * aspect + height_delta) * aspect / (aspect * aspect + 1)
        elif vertical:
            width_delta = height_delta * aspect
        width = max(self.minimumWidth(), round(bounds.width() + width_delta))
        rect.setSize(QSize(width, round(width / aspect)))
        if edges & Qt.LeftEdge:
            rect.moveRight(bounds.right())
        if edges & Qt.TopEdge:
            rect.moveBottom(bounds.bottom())
        return rect

    def _tile_at(self, point):
        if self.tools.isVisible() and self.tools.geometry().contains(point):
            return None
        if self.audio_tools.isVisible() and self.audio_tools.geometry().contains(point):
            return None
        return next((tile for tile in self.controller.display_wall.visible_tiles()
                     if tile.rect().contains(tile.mapFromGlobal(point))), None)

    def _set_reordering(self, enabled):
        self._reorder_drag = None
        if self._gesture is None and QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.setCursor(Qt.OpenHandCursor if enabled else Qt.ArrowCursor)
        for widget, _tracking, _cursor in self._surface_state:
            widget.unsetCursor()
        self.tools.reorder.setToolTip('拖到另一格后松开互换；点击结束调整' if enabled else '调整画面位置')

    def _handle_shortcut(self, watched, event):
        if not isinstance(watched, QWidget):
            return False
        window = watched.window()
        if window not in (self, self.tools, self.audio_tools, self.audio_panel):
            return False
        pressed = QKeySequence(event.keyCombination()).toString()
        if not pressed:
            return False
        shortcuts = self.controller.host.shortcuts
        actions = ('pip_exit',) if window is self.audio_panel else (
            'pip_exit', 'pip_volume_up', 'pip_volume_down', 'pip_mute', 'pip_solo')
        action = next((key for key in actions if pressed == shortcuts.get(key, DEFAULT_SHORTCUTS[key])), None)
        if action is None:
            # Keep Qt from dispatching a main-window binding for a key delivered to PiP.
            if (event.type() == QEvent.ShortcutOverride and
                    any(pressed == sequence for key, sequence in shortcuts.items() if not key.startswith('pip_'))):
                event.accept()
                return True
            return False
        event.accept()
        if event.type() == QEvent.ShortcutOverride:
            return True
        if action == 'pip_exit':
            self._escape()
            return True
        tile = self._tile_at(QCursor.pos()) if self._pointer_over() else None
        if tile is not None:
            if action in ('pip_volume_up', 'pip_volume_down'):
                tile.set_volume(tile.volume + (5 if action == 'pip_volume_up' else -5))
            elif action == 'pip_mute':
                tile.set_muted(not tile.muted)
            else:
                for member in self.controller.audio_tiles():
                    member.set_muted(member is not tile)
            self.audio_feedback.display(tile)
        return True

    def eventFilter(self, watched, event):
        kind = event.type()
        if (self._live_move is not None and self._live_move.system_moving
                and kind in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease)):
            return False
        if kind in (QEvent.ShortcutOverride, QEvent.KeyPress) and self._handle_shortcut(watched, event):
            return True
        if kind == QEvent.UngrabMouse and watched is self and self._reorder_drag is not None:
            self._reorder_drag = None
            self.setCursor(Qt.OpenHandCursor if self.tools.reorder.isChecked() else Qt.ArrowCursor)
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseMove,
                        QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return False
        live = self._live_move or self._live_resize
        preview = live.preview if live is not None else None
        if not isinstance(watched, QWidget) or watched.window() not in (self, preview):
            return False
        wall = self.controller.display_wall
        surfaces = (self, preview, wall, *self.danmaku_panels.values(), *(surface for tile in wall.visible_tiles()
                                 for surface in (tile, tile.video, tile.cover, tile.video_danmaku, tile.spinner, tile.pause_overlay)))
        if watched not in surfaces:
            return False
        point = event.globalPosition().toPoint()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._live_move is not None:
                self._live_move.finish(immediate=True)
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
            if not edges:
                # Keep auxiliary native windows out of the pointer-move path.
                self.tools.hide()
                self.hide_audio()
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
                if edges:
                    self._pending_geometry = self._resize_geometry(bounds, edges, delta)
                    if not self._geometry_timer.isActive():
                        self._geometry_timer.start()
                else:
                    self._move_composition(bounds.translated(delta), native_input=event.spontaneous())
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
            start, bounds, edges = self._gesture
            delta = point - start
            if not edges:
                rect = bounds.translated(delta)
                if self._live_move is not None:
                    self._live_move.set_geometry(rect)
                    self._live_move.finish()
                else:
                    self.move(rect.topLeft())
            else:
                rect = self._resize_geometry(bounds, edges, delta)
                self._pending_geometry = rect if self._live_resize is not None or rect != self.geometry() else None
            self._flush_geometry(finishing=True)
            self._gesture = None
            self.releaseMouse()
            if self._live_resize is not None:
                self._live_resize.finish()
            self._poll_tools()
            return True
        return kind == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton

    def _move_composition(self, rect, *, native_input=False):
        if (self._live_move is None and sys.platform == 'win32'
                and QApplication.platformName() == 'windows'):
            from .picture_in_picture_resize import LiveMove
            self._live_move = LiveMove(self)
            if not self._live_move.begin():
                self._live_move = None
        if self._live_move is not None:
            live = self._live_move
            live.set_geometry(rect)
            if native_input and live.run_system_move() and self._live_move is live:
                self._gesture = None
                live.finish()
                self._poll_tools()
        else:
            self.move(rect.topLeft())

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
        if self._live_move is not None:
            self._live_move.finish(immediate=True)
        if self._live_resize is not None:
            self._live_resize.finish(immediate=True)
        self._hover_timer.stop()
        self._geometry_timer.stop()
        self._pending_geometry = None
        QApplication.instance().removeEventFilter(self)
        self.tools.hide()
        self.hide_audio()
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
        set_window_topmost(self, pinned)

    def return_to_monitor(self):
        self.controller.restore(activate=True)

    def _escape(self):
        if self._live_move is not None and self._live_move.system_moving:
            return
        if self.audio_panel.isVisible():
            self.audio_panel.hide()
        else:
            self.return_to_monitor()

    def closeEvent(self, event):
        self.controller.restore(activate=False)
        event.accept()
