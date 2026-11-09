"""Right-anchored room avatars for choosing a chat pane's video source."""
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QScrollArea, QWidget

from . import motion, theme
from .avatar_widgets import Avatar
from .corner_geometry import continuous_path


class SourceAvatar(QPushButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('''QPushButton {background: transparent; border: none; padding: 0;}
            QPushButton:checked, QPushButton:focus {border: 1px solid ACCENT; border-radius: 13px;}
            QPushButton[sourceEmpty="true"]:checked, QPushButton[sourceEmpty="true"]:focus {
                border: 1px solid NEUTRAL; border-radius: 7px;}
            '''.replace('ACCENT', theme.ACCENT).replace('NEUTRAL', theme.TEXT2))
        self.avatar = None
        self.identity = None
        self.face_key = None
        self.pointer_activation = True

    def mousePressEvent(self, event):
        self.pointer_activation = True
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        self.pointer_activation = False
        super().keyPressEvent(event)

    def sync(self, name, index, room_id, pixmap):
        identity = (room_id, name)
        if self.identity != identity:
            if self.avatar is not None:
                self.avatar.hide()
                self.avatar.deleteLater()
            self.avatar = None
            self.identity, self.face_key = identity, None
        if room_id and pixmap is not None and not pixmap.isNull():
            if self.avatar is None:
                self.avatar = Avatar(name, index, size=24, parent=self)
                self.avatar.move(1, 1)
                self.avatar.show()
            if pixmap.cacheKey() != self.face_key:
                self.avatar.set_pixmap_image(pixmap)
                self.face_key = pixmap.cacheKey()
        if self.property('sourceEmpty') != (self.avatar is None):
            self.setProperty('sourceEmpty', self.avatar is None)
            self.style().unpolish(self)
            self.style().polish(self)
        self.setToolTip(name)
        self.setAccessibleName(name)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.identity is None or self.avatar is not None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.qcolor(theme.TEXT2), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(continuous_path(QRectF(6, 5, 15, 11), 3))
        rear = QPainterPath(QPointF(4, 9))
        rear.lineTo(4, 16)
        rear.cubicTo(4, 18, 5, 19, 7, 19)
        rear.lineTo(16, 19)
        painter.drawPath(rear)
        painter.drawLine(QPointF(12, 9), QPointF(16, 9))
        painter.drawLine(QPointF(14, 7), QPointF(14, 11))


class SourcePicker(QWidget):
    SIZE, STEP = 26, 30

    def __init__(self, panel, controller):
        super().__init__(panel.header)
        self.panel, self.controller = panel, controller
        self.setFixedSize(self.SIZE, self.SIZE)
        self.anchor = SourceAvatar(self)
        self.anchor.clicked.connect(lambda: self.set_expanded(
            not self.expanded, animate=self.anchor.pointer_activation))
        self.tray = QFrame(panel.header)
        self.tray.setObjectName('PaneSourceTray')
        self.tray.setStyleSheet('#PaneSourceTray {background: transparent; border: none;}')
        self.tray.setAttribute(Qt.WA_StyledBackground)
        self.tray.hide()
        self.scroll = QScrollArea(self.tray)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet('QScrollArea, QScrollArea > QWidget {background: transparent; border: none;}')
        self.content = QWidget()
        self.scroll.setWidget(self.content)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.horizontalScrollBar().valueChanged.connect(lambda _value: self._render())
        self.empty = QLabel('暂无可关联画面', self.tray)
        self.empty.setObjectName('SettingsHint')
        self.buttons = {}
        self.order = []
        self.covered = None
        self._placing = False
        self.expanded = False
        self.progress = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setEasingCurve(motion.THEME_WAVE_EASING)
        self.animation.valueChanged.connect(self._frame)
        self.animation.finished.connect(self._settled)
        panel.header.installEventFilter(self)
        panel.installEventFilter(self)
        panel.header.layout().insertWidget(panel.header.layout().count() - 1, self)

    def refresh(self):
        controller = self.controller
        tiles = [(cell, tile) for cell, tile in controller.cell_tiles().items()
                 if cell not in controller.bindings() and tile.room.get('room_id')]
        faces = {str(item.room.get('room_id')): item.thumb.face_pixmap() for item in
                 controller.wall.window().sidebar.items()} if hasattr(controller.wall.window(), 'sidebar') else {}
        selected = controller.target(self.panel)
        self.order = [tile for _cell, tile in tiles]
        for tile in list(self.buttons):
            if tile not in [item for _cell, item in tiles]:
                button = self.buttons.pop(tile)
                button.hide()
                button.deleteLater()
        for cell, tile in tiles:
            if tile not in self.buttons:
                button = SourceAvatar(self.content)
                button.clicked.connect(lambda _checked=False, t=tile: self.choose(t))
                button.installEventFilter(self)
                self.buttons[tile] = button
            name = str(tile.room.get('uname') or tile.room['room_id'])
            self.buttons[tile].sync(name, cell, str(tile.room['room_id']), faces.get(str(tile.room['room_id'])))
            self.buttons[tile].setChecked(tile is selected)
        if selected is not None:
            name = str(selected.room.get('uname') or selected.room['room_id'])
            self.anchor.sync(name, controller.cell_for_tile(selected) or 0,
                             str(selected.room['room_id']), faces.get(str(selected.room['room_id'])))
            self.anchor.setToolTip(name + ' · 点击更换弹幕来源')
        else:
            self.anchor.sync('选择弹幕来源', 0, '', None)
        self.anchor.setChecked(selected is not None)
        self.empty.setVisible(not tiles)
        self._place()

    def _place(self):
        if self._placing:
            return
        self._placing = True
        try:
            self._place_header()
        finally:
            self._placing = False

    def _place_header(self):
        header = self.panel.header
        layout = header.layout()
        left = layout.contentsMargins().left()
        if self.covered is not None:
            avatars = max(self.SIZE, len(self.buttons) * self.STEP - 4)
            controls = sum(max(widget.minimumWidth(), min(widget.maximumWidth(), widget.sizeHint().width()))
                           for widget in self.covered)
            required = (left + controls + layout.spacing() * (len(self.covered) + 1)
                        + avatars + self.panel.count.width() + layout.contentsMargins().right())
            compact = header.width() < required
            for widget in self.covered:
                widget.setVisible(not compact)
            layout.activate()
            if not compact:
                left = max((widget.geometry().right() + 1 for widget in self.covered), default=left)
                left += layout.spacing()
        width = max(self.SIZE, self.panel.count.x() - layout.spacing() - left)
        self.tray.setGeometry(left, 0, width, header.height())
        self.scroll.setGeometry(0, (header.height() - self.SIZE) // 2, width, self.SIZE)
        self.content.resize(max(width, len(self.buttons) * self.STEP - 4), self.SIZE)
        self.empty.setGeometry(self.tray.rect())
        self._render()

    def _render(self):
        anchor = self.scroll.horizontalScrollBar().value() + self.scroll.viewport().width() - self.SIZE
        right = self.content.width() - self.SIZE
        for index, tile in enumerate(self.order):
            button = self.buttons[tile]
            button.move(round(anchor + (right - index * self.STEP - anchor) * self.progress), 0)
            button.setVisible(self.expanded or self.progress > 0)
        selected = self.controller.target(self.panel)
        if selected in self.buttons:
            self.buttons[selected].raise_()

    def _frame(self, value):
        self.progress = float(value)
        self._render()

    def _settled(self):
        if not self.expanded:
            self.tray.hide()
            if self.covered is not None:
                for widget in self.covered:
                    widget.show()
                self.covered = None
                self.panel.header.layout().activate()
            self.anchor.show()
            QApplication.instance().removeEventFilter(self)

    def set_expanded(self, expanded, *, animate=True):
        progress = self.progress
        self.animation.stop()
        self.expanded = expanded
        if expanded:
            if self.covered is None:
                layout = self.panel.header.layout()
                self.covered = [layout.itemAt(index).widget() for index in range(layout.count())
                    if layout.itemAt(index).widget() is not None and
                    layout.itemAt(index).widget() not in (self, self.panel.count) and
                    not layout.itemAt(index).widget().isHidden()]
            self.refresh()
            self.anchor.hide()
            self.tray.show()
            self.tray.raise_()
            self.scroll.horizontalScrollBar().setValue(self.scroll.horizontalScrollBar().maximum())
            QApplication.instance().installEventFilter(self)
        target = 1.0 if expanded else 0.0
        if animate and motion.enabled() and self.isVisible() and abs(target - progress) > .001:
            self.animation.blockSignals(True)
            self.animation.setDuration(max(1, round(180 * abs(target - progress))))
            self.animation.setStartValue(progress)
            self.animation.setEndValue(target)
            self.animation.setCurrentTime(0)
            self.animation.blockSignals(False)
            self._frame(progress)
            self.animation.start()
        else:
            self._frame(target)
            self._settled()

    def choose(self, tile):
        cell = next((cell for cell, panel in self.controller.panels.items() if panel is self.panel), None)
        if cell is None or tile not in self.buttons:
            return
        self.controller.request(cell, tile)
        self.refresh()
        if self.controller.target(self.panel) is tile:
            self.set_expanded(False, animate=self.buttons[tile].pointer_activation)

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.panel.header and kind == QEvent.Resize:
            self._place()
        elif watched is self.panel and kind == QEvent.Hide:
            self.set_expanded(False, animate=False)
        elif self.expanded and kind == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
            event.accept()
            return True
        elif self.expanded and kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.set_expanded(False, animate=False)
            self.anchor.setFocus(Qt.OtherFocusReason)
            return True
        elif self.expanded and kind == QEvent.MouseButtonPress:
            point = event.globalPosition().toPoint()
            if not self.tray.rect().contains(self.tray.mapFromGlobal(point)):
                self.set_expanded(False)
        elif self.expanded and kind == QEvent.ApplicationDeactivate:
            self.set_expanded(False, animate=False)
        elif kind == QEvent.Wheel and (watched is self.scroll.viewport() or watched in self.buttons.values()):
            delta = event.angleDelta().x() or event.angleDelta().y()
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.value() - round(delta / 120 * self.STEP))
            event.accept()
            return True
        return False
