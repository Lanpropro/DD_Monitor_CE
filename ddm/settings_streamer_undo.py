"""Bottom-anchored removal feedback for the streamer settings page."""
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QImage, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea,
                              QToolButton, QVBoxLayout, QWidget)

from .settings_material_paint import glass_tint, window_background_tint
from .ui import ActionButton, Avatar, ElidedLabel, SettingsSurface


class StreamerRemovalNotice(SettingsSurface):
    undo_requested = Signal()
    entry_undo_requested = Signal(str)
    expired = Signal()

    def __init__(self, parent, scroll):
        super().__init__(parent)
        self._backdrop_view = scroll.viewport()
        scroll.verticalScrollBar().valueChanged.connect(self.update)
        self.rooms = {}
        self.detail_rows = {}
        self.expanded = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 16)
        layout.setSpacing(8)
        self.details = QScrollArea(self, objectName='StreamerUndoDetails')
        self.details.setAccessibleName('本批已移除设置的主播')
        self.details.setFrameShape(QFrame.NoFrame)
        self.details.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.details.setWidgetResizable(True)
        content = QWidget(objectName='StreamerUndoDetailContent')
        self.details.viewport().setObjectName('StreamerUndoDetailViewport')
        self.details.setWidget(content)
        self.details.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        self.details.setStyleSheet(
            '#StreamerUndoDetails, #StreamerUndoDetailViewport, #StreamerUndoDetailContent '
            '{ background: transparent; }')
        self.detail_layout = QVBoxLayout(content)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(0)
        self.detail_layout.setAlignment(Qt.AlignTop)
        self.details.hide()
        layout.addWidget(self.details)
        self.header = QWidget(self)
        layout.addWidget(self.header)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        self.pile = QWidget(self.header)
        self.pile.setFixedHeight(34)
        row.addWidget(self.pile)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        self.title = ElidedLabel('', self.header)
        self.title.setTextFormat(Qt.PlainText)
        texts.addWidget(self.title)
        self.message = QLabel(self.header)
        self.message.setTextFormat(Qt.PlainText)
        texts.addWidget(self.message)
        row.addLayout(texts, 1)
        self.undo_button = ActionButton('撤回', self.header)
        self.undo_button.setAutoDefault(False)
        self.undo_button.clicked.connect(self.undo_requested)
        row.addWidget(self.undo_button)
        self.expand_button = QToolButton(self.header)
        self.expand_button.setAutoRaise(True)
        self.expand_button.setFixedSize(32, 34)
        self.expand_button.clicked.connect(self.toggle_details)
        self.expand_button.hide()
        row.addWidget(self.expand_button)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._expire)
        self.hide()

    def present(self, rooms):
        self.rooms = dict(rooms)
        if len(rooms) < 2:
            self.expanded = False
        self._sync_details()
        for avatar in self.pile.findChildren(Avatar):
            avatar.hide()
            avatar.deleteLater()
        faces = list(rooms.values())[-3:]
        self.pile.setFixedWidth(34 + 20 * (len(faces) - 1))
        self.pile.show()
        for index, room in enumerate(faces):
            avatar = Avatar(room['name'], index, size=34, parent=self.pile)
            if room.get('avatar'):
                avatar.set_pixmap_image(QPixmap(room['avatar']))
            avatar.move(index * 20, 0)
            avatar.show()
        single = len(rooms) == 1
        self.title.setText(faces[0]['name'] if single else '')
        self.title.setVisible(single)
        self.message.setText('已移除主播设置' if single else f'已移除 {len(rooms)} 位主播的设置')
        self.setAccessibleName(self.message.text())
        self.undo_button.setText('撤回' if single else '全部撤回')
        self.undo_button.show()
        self._reposition()
        self.show()
        self.raise_()
        self.timer.start(10000)

    def confirm(self, count):
        self._clear_details()
        if count == 0:
            self.hide()
            self.timer.stop()
            return
        self.title.hide()
        self.pile.hide()
        self.undo_button.hide()
        self.message.setText(f'已恢复 {count} 位主播的设置')
        self.setAccessibleName(self.message.text())
        self._reposition()
        self.timer.start(3000)

    def toggle_details(self):
        self.expanded = not self.expanded
        self._sync_details()
        self._reposition()

    def _sync_details(self):
        self.expand_button.setVisible(len(self.rooms) > 1)
        self.expand_button.setArrowType(Qt.DownArrow if self.expanded else Qt.UpArrow)
        text = '收起已移除的主播设置' if self.expanded else '展开已移除的主播设置'
        self.expand_button.setAccessibleName(text)
        self.expand_button.setToolTip(text)
        for room_id in tuple(self.detail_rows):
            if room_id not in self.rooms:
                row = self.detail_rows.pop(room_id)
                self.detail_layout.removeWidget(row)
                row.hide()
                row.deleteLater()
        if self.expanded:
            for room_id, room in self.rooms.items():
                if room_id not in self.detail_rows:
                    self._add_detail_row(room_id, room)

    def _add_detail_row(self, room_id, room):
        row = QWidget(self.details.widget())
        row.setMinimumHeight(56)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(14)
        avatar = Avatar(room['name'], len(self.detail_rows), size=34, parent=row)
        if room.get('avatar'):
            avatar.set_pixmap_image(QPixmap(room['avatar']))
        layout.addWidget(avatar)
        name = ' · '.join(part for part in (room['name'], room.get('platform')) if part)
        title = ElidedLabel(name, row)
        title.setTextFormat(Qt.PlainText)
        title.setToolTip(name)
        layout.addWidget(title, 1)
        undo = ActionButton('撤回', row)
        undo.setAccessibleName(f'撤回移除：{name}')
        undo.setAutoDefault(False)
        undo.clicked.connect(lambda _checked=False: self.entry_undo_requested.emit(room_id))
        layout.addWidget(undo)
        self.detail_rows[room_id] = row
        self.detail_layout.addWidget(row)

    def _clear_details(self):
        self.expanded = False
        self.rooms.clear()
        self._sync_details()
        self.details.hide()

    def _expire(self):
        focus = QApplication.focusWidget()
        if (self.isVisible() and not self.undo_button.isHidden()
                and (self.underMouse() or focus is not None and self.isAncestorOf(focus))):
            self.timer.start(1000)
            return
        self.hide()
        self._clear_details()
        self.expired.emit()

    def _reposition(self):
        parent = self.parentWidget()
        width = max(1, min(640, parent.width() - 48))
        margins = self.layout().contentsMargins()
        header_height = max(56, self.header.sizeHint().height() + margins.top() + margins.bottom())
        detail_height = 0
        if self.expanded:
            rows = list(self.detail_rows.values())[:4]
            preferred = sum(max(row.minimumHeight(), row.sizeHint().height()) for row in rows)
            detail_height = min(preferred, max(0, parent.height() - header_height - 56))
        self.details.setFixedHeight(detail_height)
        self.details.setVisible(detail_height > 0)
        height = header_height + (detail_height + 8 if detail_height else 0)
        self.setGeometry((parent.width() - width) // 2, parent.height() - height - 24, width, height)

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self._reposition()
        return super().eventFilter(watched, event)

    def _paint_blurred_content(self, painter):
        view = self._backdrop_view
        offset = view.mapFrom(self.parentWidget(), self.pos())
        scale = 32
        padding = 2 * scale
        area = QRect(offset, self.size()).adjusted(-padding, -padding, padding, padding)
        sample = area.intersected(view.rect())
        if sample.isEmpty():
            return
        image = QImage(sample.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        # Capture the scroll viewport alone. The floating notice is its sibling.
        with QPainter(image) as capture:
            view.render(capture, QPoint(), QRegion(sample), QWidget.DrawChildren)
        blurred = image.scaled(max(1, image.width() // scale), max(1, image.height() // scale),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(.75)
        painter.drawImage(QRectF(sample.translated(-offset)), blurred)

    def _paint_glass_fill(self, painter, path):
        layer = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        tint = Qt.transparent
        if self.window().property('settingsGlassWindow'):
            tint = glass_tint(self, window_background_tint(self))
        layer.fill(tint)
        with QPainter(layer) as backdrop:
            self._paint_blurred_content(backdrop)

        # Replace the original pixels so sharp text cannot show through the blur.
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillPath(path, QBrush(layer))
        painter.restore()
        super()._paint_glass_fill(painter, path)
