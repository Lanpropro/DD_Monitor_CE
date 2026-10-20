"""Non-grabbing volume slider, following the bili_live anchored picker pattern."""
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSlider, QVBoxLayout, QWidget
from . import theme
from .anchored_popup import AnchoredPopupMixin


class VolumePopup(AnchoredPopupMixin, QWidget):
    def __init__(self, anchor):
        super().__init__(anchor, accept_focus=False)
        self.setObjectName('TileVolumePopup')
        self._slider_pressed = False
        self._outside_since = None
        self._pointer_timer = QTimer(self)
        self._pointer_timer.setInterval(30)
        self._pointer_timer.timeout.connect(self._check_pointer)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)
        self.slider = QSlider(Qt.Vertical, self)
        self.slider.setRange(0, 100)
        self.slider.setFixedSize(26, 110)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.setAccessibleName('当前格子的音量')
        layout.addWidget(self.slider, 0, Qt.AlignHCenter)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(theme.qcolor(theme.ELEVATED))
        painter.setPen(QPen(theme.qcolor(theme.BORDER), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
                                theme.RADIUS_LG, theme.RADIUS_LG)

    def _on_anchor_enter(self):
        if self._anchor.compact_popup:
            self._outside_since = None
            self.open_at(self._anchor)

    def _contains_pointer(self, point):
        popup = self.geometry()
        anchor = QRect(self._anchor.mapToGlobal(QPoint()), self._anchor.size())
        if popup.contains(point) or anchor.contains(point):
            return True
        # Protect only the vertical travel corridor, not neighboring buttons.
        left, right = max(popup.left(), anchor.left()), min(popup.right(), anchor.right())
        if popup.bottom() < anchor.top():
            top, bottom = popup.bottom() + 1, anchor.top() - 1
        elif anchor.bottom() < popup.top():
            top, bottom = anchor.bottom() + 1, popup.top() - 1
        else:
            return False
        return QRect(QPoint(left, top), QPoint(right, bottom)).contains(point)

    def _check_pointer(self):
        if not self._event_targets_alive():
            self.hide()
            return
        if self._owner_dragging or self._slider_pressed or self._contains_pointer(QCursor.pos()):
            self._outside_since = None
            return
        now = time.monotonic()
        if self._outside_since is None:
            self._outside_since = now
        elif now - self._outside_since >= .15:
            self.hide()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonRelease:
            self._slider_pressed = False
        elif (watched is getattr(self, 'slider', None) and event.type() == QEvent.MouseButtonPress
              and event.button() == Qt.LeftButton):
            self._slider_pressed = True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._pointer_timer.start()

    def hideEvent(self, event):
        self._pointer_timer.stop()
        self._outside_since = None
        self._slider_pressed = False
        super().hideEvent(event)
