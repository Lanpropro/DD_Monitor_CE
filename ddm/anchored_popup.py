"""Shared non-grabbing picker behavior, following bili_live's anchored popup.

The mixin supports both QWidget panels and QMenu content without changing their
painting, actions or keyboard navigation. It must precede the Qt widget base.
"""
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


class AnchoredPopupMixin:
    GAP = 6

    def __init__(self, anchor=None, *, align_right=False, accept_focus=True):
        # A native picker belongs to the top-level owner, never a tile's native
        # child surface. Tool flags preserve the host's mouse and title bar.
        super().__init__(anchor.window() if anchor is not None else None)
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        if not accept_focus:
            flags |= Qt.WindowDoesNotAcceptFocus
            self.setFocusPolicy(Qt.NoFocus)
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._anchor = anchor
        self._owner = anchor.window() if anchor is not None else None
        self._align_right = align_right
        self._accept_focus = accept_focus
        self._owner_dragging = False
        self._native_follow = None
        self._placement_timer = QTimer(self)
        self._placement_timer.setSingleShot(True)
        self._placement_timer.timeout.connect(self._place_after_layout)
        if anchor is not None:
            anchor.destroyed.connect(self.deleteLater)
            anchor.installEventFilter(self)

    def _event_targets_alive(self):
        return (isValid(self) and '_anchor' in self.__dict__ and self._anchor is not None and
                isValid(self._anchor) and self._owner is not None and isValid(self._owner))

    def open_at(self, anchor):
        if self._anchor is not anchor:
            if self._anchor is not None and isValid(self._anchor):
                self._anchor.removeEventFilter(self)
            anchor.destroyed.connect(self.deleteLater)
            anchor.installEventFilter(self)
            self._anchor = anchor
        self._owner = anchor.window()
        self.ensurePolished()
        self.adjustSize()
        self.place_at()
        self.show()
        self.raise_()
        if self._accept_focus:
            self.activateWindow()
            self.setFocus(Qt.PopupFocusReason)

    def place_at(self):
        self._placement_timer.stop()
        if self._native_follow is not None and self._native_follow.dragging:
            return
        self._owner = self._anchor.window()
        if self.parentWidget() is not self._owner:
            visible = self.isVisible()
            self.setParent(self._owner, self.windowFlags())
            if visible:
                self.show()
        screen = self._anchor.screen().availableGeometry()
        point = self._anchor.mapToGlobal(QPoint(0, 0))
        if self._align_right:
            x = point.x() + self._anchor.width() - self.width()
        else:
            x = point.x() + self._anchor.width() // 2 - self.width() // 2
        y = point.y() - self.height() - self.GAP
        if y < screen.top():
            y = point.y() + self._anchor.height() + self.GAP
        self.move(max(screen.left(), min(x, screen.right() - self.width() + 1)),
                  max(screen.top(), min(y, screen.bottom() - self.height() + 1)))
        if self._native_follow is not None and self.isVisible():
            self._native_follow.start()

    def _schedule_placement(self):
        if not self._placement_timer.isActive():
            self._placement_timer.start(0)

    def _place_after_layout(self):
        if self._event_targets_alive() and self.isVisible():
            self.place_at()

    def _contains_pointer(self, point):
        return (self.geometry().contains(point) or
                QRect(self._anchor.mapToGlobal(QPoint()), self._anchor.size()).contains(point))

    def _on_anchor_enter(self):
        pass

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QEvent.Enter, QEvent.Move, QEvent.Resize, QEvent.MouseButtonPress,
                        QEvent.MouseButtonRelease, QEvent.NonClientAreaMouseButtonPress,
                        QEvent.NonClientAreaMouseButtonRelease, QEvent.KeyPress,
                        QEvent.ApplicationDeactivate, QEvent.Hide, QEvent.Close):
            return False
        if not self._event_targets_alive():
            return False
        if watched is self._anchor and kind == QEvent.Enter and not self.isVisible():
            self._on_anchor_enter()
        if not self.isVisible():
            return False
        if kind in (QEvent.Move, QEvent.Resize, QEvent.Hide, QEvent.Close):
            widget = self._anchor
            while widget is not None:
                if watched is widget:
                    if kind in (QEvent.Hide, QEvent.Close):
                        self.hide()
                    elif watched is self._owner and kind == QEvent.Move:
                        self.place_at()  # Same dispatch as the owner, no queued drag lag.
                    else:
                        self._schedule_placement()
                    break
                widget = widget.parentWidget()
        elif kind == QEvent.NonClientAreaMouseButtonPress:
            if watched in (self._owner, self._owner.windowHandle()) and event.button() == Qt.LeftButton:
                self._owner_dragging = True
        elif kind in (QEvent.MouseButtonRelease, QEvent.NonClientAreaMouseButtonRelease):
            self._owner_dragging = False
        elif kind == QEvent.MouseButtonPress:
            if not self._contains_pointer(event.globalPosition().toPoint()):
                self.hide()
        elif kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.hide()
            return True
        elif kind == QEvent.ApplicationDeactivate:
            self.hide()
        return False  # Outside clicks continue to the host, including its title bar.

    def showEvent(self, event):
        super().showEvent(event)
        # Closed tiles can remain alive until Qt/GC teardown. Only visible
        # pickers need global events; otherwise each tile multiplies UI work.
        QApplication.instance().installEventFilter(self)
        if QApplication.platformName() == 'windows':
            if self._native_follow is None:
                from .native_popup import NativePopupFollower
                self._native_follow = NativePopupFollower(self)
                self.destroyed.connect(self._native_follow.stop)
            self._native_follow.start()

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._placement_timer.stop()
        self._owner_dragging = False
        if self._native_follow is not None:
            self._native_follow.stop()
        super().hideEvent(event)
