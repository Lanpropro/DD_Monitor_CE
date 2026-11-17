"""Shared compact selector using Qt's model, popup placement and input handling."""
from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLabel, QLineEdit, QListView, QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget

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


class FontSelectControl(SelectControl):
    """Installed font families with the same compact surface and popup as settings."""
    currentFontChanged = Signal(QFont)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItems(QFontDatabase.families())
        self.currentTextChanged.connect(lambda family: self.currentFontChanged.emit(QFont(family)))
        popup = self.view().window()
        header = QWidget(popup)
        header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(header)
        layout.setContentsMargins(8, 8, 8, 4)
        self.search = QLineEdit(header)
        self.search.setPlaceholderText('搜索字体名称')
        self.search.setAccessibleName('搜索字体名称')
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(theme.CONTROL_HEIGHT)
        layout.addWidget(self.search)
        self.empty = QLabel('没有匹配的字体', header)
        self.empty.setObjectName('SettingsHint')
        self.empty.hide()
        layout.addWidget(self.empty)
        popup.layout().insertWidget(0, header)
        self.search.textChanged.connect(self._filter_fonts)
        self.search.installEventFilter(self)
        self.view().installEventFilter(self)

    def showPopup(self):
        self.search.clear()
        super().showPopup()
        self._resize_popup()
        self.search.setFocus(Qt.PopupFocusReason)

    def _resize_popup(self):
        view = self.view()
        popup = view.window()
        if not popup.isVisible():
            return
        self.search.parentWidget().updateGeometry()
        popup.layout().invalidate()
        popup.layout().activate()
        visible = [row for row in range(self.count()) if not view.isRowHidden(row)]
        row_height = max(1, view.sizeHintForRow(visible[0]) if visible else theme.CONTROL_HEIGHT)
        margins = view.contentsMargins()
        padding = margins.top() + margins.bottom()
        bounds = self.screen().availableGeometry()
        overhead = popup.height() - view.height() + padding
        rows = min(max(1, len(visible)), self.maxVisibleItems(),
                   max(1, (bounds.height() - overhead) // row_height))
        width = max(popup.width(), self.width(), self.search.parentWidget().sizeHint().width() + 10)
        view.setFixedHeight(rows * row_height + padding)
        view.doItemsLayout()
        view.scrollTo(view.currentIndex())
        popup.layout().invalidate()
        popup.adjustSize()
        popup.resize(min(width, bounds.width()), min(popup.height(), bounds.height()))
        below = self.mapToGlobal(QPoint(0, self.height())).y()
        above = self.mapToGlobal(QPoint(0, 0)).y() - popup.height()
        top = below if below + popup.height() <= bounds.bottom() + 1 else above
        popup.move(max(bounds.left(), min(popup.x(), bounds.right() - popup.width() + 1)),
                   max(bounds.top(), min(top, bounds.bottom() - popup.height() + 1)))

    def _filter_fonts(self, text):
        terms = text.casefold().split()
        view = self.view()
        visible = []
        for row in range(self.count()):
            matches = all(term in self.itemText(row).casefold() for term in terms)
            view.setRowHidden(row, not matches)
            if matches:
                visible.append(row)
        self.empty.setVisible(not visible)
        current = view.currentIndex()
        if not current.isValid() or current.row() not in visible:
            view.setCurrentIndex(self.model().index(visible[0], 0) if visible else self.model().index(-1, 0))
        self._resize_popup()

    def eventFilter(self, watched, event):
        if watched in (self.search, self.view()) and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.hidePopup()
                return True
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                view = self.view()
                visible = [row for row in range(self.count()) if not view.isRowHidden(row)]
                if visible:
                    current = view.currentIndex().row()
                    position = visible.index(current) if current in visible else 0
                    if watched is view:
                        position = max(0, min(len(visible) - 1,
                                             position + (1 if event.key() == Qt.Key_Down else -1)))
                    view.setCurrentIndex(self.model().index(visible[position], 0))
                    view.scrollTo(view.currentIndex())
                    view.setFocus(Qt.ShortcutFocusReason)
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                index = self.view().currentIndex()
                if not index.isValid() or self.view().isRowHidden(index.row()):
                    return True
                if watched is self.search:
                    self.view().setFocus(Qt.ShortcutFocusReason)
                    QApplication.sendEvent(self.view(), event)
                    return True
            if (watched is self.view() and event.text().isprintable()
                    and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
                self.search.setFocus(Qt.ShortcutFocusReason)
                QApplication.sendEvent(self.search, event)
                return True
        return super().eventFilter(watched, event)

    def currentFont(self):
        return QFont(self.currentText())

    def setCurrentFont(self, font):
        index = self.findText(font.family(), Qt.MatchFixedString)
        if index < 0:
            self.addItem(font.family())
            index = self.count() - 1
        self.setCurrentIndex(index)
