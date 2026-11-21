"""Shared rounded, non-grabbing pickers anchored to a host widget."""
from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid
from ddm import theme, ui


class RefreshSpinner(QWidget):
    """Small shared refresh indicator; hidden pickers do not animate."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setFixedSize(16,16)
        self.setAccessibleName('正在刷新')
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        policy=self.sizePolicy();policy.setRetainSizeWhenHidden(True);self.setSizePolicy(policy)
        self._busy=False;self._angle=0
        self._timer=QTimer(self);self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def set_busy(self,busy):
        self._busy=bool(busy)
        self.setVisible(self._busy)
        if self._busy and self.isVisible():self._timer.start()
        else:self._timer.stop()

    def _advance(self):
        self._angle=(self._angle-30)%360
        self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        rect=QRectF(self.rect()).adjusted(2,2,-2,-2)
        painter.setPen(QPen(theme.qcolor(theme.BORDER),1.6));painter.drawEllipse(rect)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT),1.6,Qt.SolidLine,Qt.RoundCap))
        painter.drawArc(rect,self._angle*16,100*16)

    def showEvent(self,event):
        super().showEvent(event)
        if self._busy:self._timer.start()

    def hideEvent(self,event):
        self._timer.stop()
        super().hideEvent(event)


class AnchoredPopup(QWidget):
    def __init__(self, parent=None):
        # Native tool windows belong to a top-level owner, never a tile's
        # native child surface. This also avoids promoting transient ancestors.
        super().__init__(parent.window() if parent else None,
                         Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setProperty('playbackGlassPopup', True)
        self._anchor = None
        self._owner = None
        self._owner_dragging = False
        self._native_follow = None
        self._placement_timer = QTimer(self)
        self._placement_timer.setSingleShot(True)
        self._placement_timer.timeout.connect(self._place_after_layout)
        QApplication.instance().installEventFilter(self)

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        ui.paint_playback_popup(self, painter, rect, theme.RADIUS_MD)

    def place_at(self, anchor):
        self._placement_timer.stop()
        if self._native_follow is not None and self._native_follow.dragging:
            return
        self._anchor = anchor
        self._owner = anchor.window()
        if self.parentWidget() is not self._owner:
            visible = self.isVisible()
            self.setParent(self._owner, self.windowFlags())
            if visible:self.show()
        screen = anchor.screen().availableGeometry()
        point = anchor.mapToGlobal(QPoint(anchor.width() // 2, 0))
        x = point.x() - self.width() // 2
        y = point.y() - self.height() - 6
        if y < screen.top():
            y = anchor.mapToGlobal(QPoint(0, anchor.height())).y() + 6
        self.move(max(screen.left(), min(x, screen.right()-self.width()+1)),
                  max(screen.top(), min(y, screen.bottom()-self.height()+1)))
        if self._native_follow is not None and self.isVisible():self._native_follow.start()

    def _schedule_placement(self):
        # A layout can move/resize several ancestors before the button reaches
        # its final position. Expose only the settled native window position.
        if not self._placement_timer.isActive():self._placement_timer.start(0)

    def _place_after_layout(self):
        if self._event_targets_alive() and self.isVisible() and self._anchor:
            self.place_at(self._anchor)

    def open_at(self, button):
        self._owner_dragging = False
        self.place_at(button)
        self.show()
        self.raise_()

    def _inside(self, point):
        return self.geometry().contains(point)

    def shutdown(self):
        self._placement_timer.stop()
        self.hide()
        QApplication.instance().removeEventFilter(self)
        self.deleteLater()

    def _event_targets_alive(self):
        # QWidget destruction emits application events before Qt has removed
        # every filter. Cyclic GC can also clear the Python state first.
        return (isValid(self) and '_owner' in self.__dict__ and
                (self._owner is None or isValid(self._owner)) and
                (self._anchor is None or isValid(self._anchor)))

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QEvent.NonClientAreaMouseButtonPress,QEvent.NonClientAreaMouseButtonRelease,
                        QEvent.MouseButtonPress,QEvent.MouseButtonRelease,QEvent.Move,QEvent.Resize,
                        QEvent.KeyPress,QEvent.ApplicationDeactivate,QEvent.Hide,QEvent.Close):return False
        if not self._event_targets_alive() or not self.isVisible(): return False
        if kind == QEvent.NonClientAreaMouseButtonPress:
            owner_event=watched is self._owner or self._owner and watched is self._owner.windowHandle()
            if owner_event and event.button() == Qt.LeftButton:self._owner_dragging = True
        elif kind in (QEvent.NonClientAreaMouseButtonRelease,QEvent.MouseButtonRelease):
            self._owner_dragging = False
        elif kind in (QEvent.Move, QEvent.Resize) and self._anchor:
            if not isinstance(watched,QWidget):return False
            widget = self._anchor
            while widget is not None:
                if watched is widget:
                    # Keep the owner and picker in the same move dispatch.
                    # Queuing this path makes a live drag visibly trail behind.
                    if watched is self._owner and kind==QEvent.Move:
                        self.place_at(self._anchor)
                    else:self._schedule_placement()
                    break
                widget = widget.parentWidget()
        elif kind == QEvent.MouseButtonPress:
            point = event.globalPosition().toPoint()
            on_anchor = self._anchor and self._anchor.rect().contains(self._anchor.mapFromGlobal(point))
            if not self._inside(point) and not on_anchor:
                self.hide()
        elif kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.hide()
            return True
        elif kind == QEvent.ApplicationDeactivate or (watched is self._owner and kind in (QEvent.Hide,QEvent.Close)):
            self.hide()
        # Outside clicks continue to the host, including its native title bar.
        return False

    def hideEvent(self,event):
        self._placement_timer.stop()
        if self._native_follow is not None:self._native_follow.stop()
        super().hideEvent(event)

    def showEvent(self,event):
        super().showEvent(event)
        if QApplication.platformName()=='windows':
            if self._native_follow is None:
                from .native_follow import NativePopupFollower
                self._native_follow=NativePopupFollower(self)
            self._native_follow.start()


def picker_style():
    return f'''
        QToolButton#EmoticonButton, QPushButton#GiftCard {{
            background:transparent; color:{theme.TEXT1}; border:1px solid transparent;
            border-radius:{theme.RADIUS_SM}px; padding:1px; font-size:11px;
        }}
        QToolButton#EmoticonButton:hover, QToolButton#EmoticonButton:focus,
        QPushButton#GiftCard:hover, QPushButton#GiftCard:focus {{
            background:{theme.CONTENT_HOVER}; border-color:{theme.ACCENT};
        }}
        QToolButton#EmoticonButton:disabled, QPushButton#GiftCard:disabled {{color:{theme.TEXT3};}}
        QPushButton#GiftCard QLabel {{color:{theme.TEXT1};font-size:11px;}}
        QPushButton#GiftCard:disabled QLabel {{color:{theme.TEXT3};}}
        QTabBar#GiftTabs::tab {{color:{theme.TEXT2}; background:transparent; padding:4px 8px;
            margin:2px; border:1px solid {theme.BORDER}; border-radius:{theme.RADIUS_SM}px;}}
        QTabBar#GiftTabs::tab:selected {{color:{theme.TEXT1};background:{theme.CONTENT_HOVER};border-color:{theme.ACCENT};}}
    '''
