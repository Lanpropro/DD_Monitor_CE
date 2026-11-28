"""Icon shortcuts above editable captions, separate from their text geometry."""
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton


class CaptionToolButton(QToolButton):
    def __init__(self, kind, title, callback, parent):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(28, 28)
        self.setAccessibleName(title)
        self.setToolTip(title)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(callback)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.underMouse() or self.isDown():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 42))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)
        painter.setPen(QPen(Qt.white, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        if self.kind in ('larger', 'smaller'):
            painter.drawLine(5, 20, 10, 7)
            painter.drawLine(10, 7, 15, 20)
            painter.drawLine(7, 16, 13, 16)
            painter.drawLine(18, 12, 24, 12)
            if self.kind == 'larger':
                painter.drawLine(21, 9, 21, 15)
        elif self.kind == 'lock':
            painter.drawRoundedRect(QRectF(7, 12, 14, 11), 2, 2)
            painter.drawArc(QRectF(10, 4, 8, 15), 0, 180 * 16)
        elif self.kind == 'reset':
            painter.drawArc(QRectF(6, 6, 16, 16), 40 * 16, 285 * 16)
            painter.drawLine(22, 5, 22, 11)
            painter.drawLine(22, 11, 16, 11)
        else:
            painter.drawRoundedRect(QRectF(4, 6, 20, 16), 3, 3)
            painter.drawLine(8, 11, 20, 11)
            painter.drawLine(8, 16, 17, 16)


class CaptionToolbar(QFrame):
    def __init__(self, interaction):
        self.interaction = interaction
        caption = interaction.caption
        flags = (Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
                 if caption.qt_composited else Qt.Widget)
        super().__init__(caption._owner, flags)
        self.setObjectName('CaptionToolbar')
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.buttons = {}
        box = QHBoxLayout(self)
        box.setContentsMargins(3, 3, 3, 3)
        box.setSpacing(1)
        for kind, title, action in (
                ('mode', '字幕显示内容', self._content_menu),
                ('smaller', '减小字号', lambda: interaction.apply(font_size=max(10, caption._style.font_size - 2))),
                ('larger', '增大字号', lambda: interaction.apply(font_size=min(64, caption._style.font_size + 2))),
                ('reset', '恢复位置与大小', lambda: interaction.apply(x=50, y=100, width=80, height=18)),
                ('lock', '锁定字幕位置', lambda: interaction.apply(locked=True))):
            button = CaptionToolButton(kind, title, action, self)
            self.buttons[kind] = button
            box.addWidget(button)
        self.setFixedSize(box.sizeHint())
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(350)
        self._hide_timer.timeout.connect(self._hide_if_left)
        caption.destroyed.connect(self.deleteLater)
        self.hide()

    def _content_menu(self):
        menu = self.interaction.menu()
        self._menu_open = True
        try:
            menu.exec(self.mapToGlobal(QPoint(0, self.height())))
        finally:
            self._menu_open = False
            menu.deleteLater()
            self.defer_hide()

    def reveal(self):
        caption = self.interaction.caption
        if caption._style.locked or not caption.isVisible():
            self.hide()
            return
        self._hide_timer.stop()
        self.sync_geometry()
        self.show()
        self.raise_()

    def sync_geometry(self):
        caption = self.interaction.caption
        area = caption._safe_rect()
        if area is None:
            return
        position = caption._owner.mapFromGlobal(caption.pos()) if caption.qt_composited else caption.pos()
        center = position.x() + (caption.width() - self.width()) // 2
        x = max(area.left(), min(center, area.right() - self.width() + 1))
        y = position.y() - self.height() - 2
        if y < area.top():
            y = min(area.bottom() - self.height() + 1, position.y() + caption.height() + 2)
        point = QPoint(x, y)
        self.move(caption._owner.mapToGlobal(point) if caption.qt_composited else point)

    def defer_hide(self):
        self._hide_timer.start()

    def _hide_if_left(self):
        if not self.underMouse() and not self.interaction.hovered and not getattr(self, '_menu_open', False):
            self.hide()

    def enterEvent(self, event):
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.defer_hide()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.interaction.caption._style.background_color())
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 9, 9)
