"""Shared compact selector using Qt's model, popup placement and input handling."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QFrame, QListView, QSizePolicy, QStyle, QStyledItemDelegate

from .. import theme


class _SelectDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(theme.CONTROL_HEIGHT, option.fontMetrics.height() + 12))
        return size

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.State_Selected)
        if not option.state & QStyle.State_Enabled:
            painter.setOpacity(.45)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor(theme.ACCENT_SOFT))
            painter.drawRoundedRect(rect, theme.RADIUS_MD, theme.RADIUS_MD)
        painter.setPen(theme.qcolor(theme.ACCENT if selected else theme.TEXT1))
        painter.setFont(option.font)
        painter.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft,
                         option.fontMetrics.elidedText(str(index.data()), Qt.ElideRight, max(0, int(rect.width()) - 20)))
        painter.restore()


class SelectControl(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty('customControlSurface', True)
        self.setFixedHeight(theme.CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self.setMaxVisibleItems(8)
        self.setCursor(Qt.PointingHandCursor)
        view = QListView(self)
        view.setFrameShape(QFrame.NoFrame)
        view.setProperty('customItemSurface', True)
        view.setStyleSheet('QListView {background: transparent; border: none; padding: 4px;}')
        view.viewport().setAutoFillBackground(False)
        view.setItemDelegate(_SelectDelegate(view))
        self.setView(view)
        popup = view.window()
        popup.setObjectName('SelectPopup')
        popup.setWindowFlag(Qt.FramelessWindowHint, True)
        popup.setAttribute(Qt.WA_TranslucentBackground)
        popup.setStyleSheet(f'#SelectPopup {{background: palette(tooltip-base); border: 1px solid palette(mid); '
                           f'border-radius: {theme.RADIUS_LG}px; padding: 4px;}}')
        self.currentTextChanged.connect(self.setToolTip)
        theme.signals().changed.connect(self.update)

    def sizeHint(self):
        width = max((self.fontMetrics().horizontalAdvance(self.itemText(index))
                     for index in range(self.count())), default=80)
        return QSize(width + 46, theme.CONTROL_HEIGHT)

    def minimumSizeHint(self):
        return QSize(min(180, self.sizeHint().width()), theme.CONTROL_HEIGHT)

    def showPopup(self):
        from ..settings_material import base_color, shadows_enabled
        popup = self.view().window()
        background = base_color(self, 'card', 'palette(tooltip-base)')
        popup.setStyleSheet(f'#SelectPopup {{background: {background}; border: 1px solid palette(mid); '
                           f'border-radius: {theme.RADIUS_LG}px; padding: 4px;}}')
        self.view().window().setWindowFlag(Qt.NoDropShadowWindowHint, not shadows_enabled(self))
        super().showPopup()
        self.update()

    def hidePopup(self):
        super().hidePopup()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(.45)
        opened = self.view().isVisible()
        focused = self.hasFocus() or opened
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if focused else theme.BORDER), 1.5 if focused else 1))
        from ..settings_material import base_color
        painter.setBrush(theme.qcolor(theme.CONTENT_HOVER if self.underMouse() or opened else
                                     base_color(self, 'control', theme.CONTENT)))
        painter.drawRoundedRect(rect, theme.RADIUS_MD, theme.RADIUS_MD)
        painter.setPen(theme.qcolor(theme.TEXT1))
        painter.drawText(rect.adjusted(12, 0, -32, 0), Qt.AlignVCenter | Qt.AlignLeft,
                         self.fontMetrics().elidedText(self.currentText(), Qt.ElideRight, max(0, self.width() - 46)))
        center, middle = self.width() - 18, self.height() / 2
        direction = -1 if opened else 1
        arrow = QPainterPath()
        arrow.moveTo(center - 4, middle - direction * 2)
        arrow.lineTo(center, middle + direction * 2)
        arrow.lineTo(center + 4, middle - direction * 2)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if opened else theme.TEXT3), 1.8,
                            Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(arrow)
