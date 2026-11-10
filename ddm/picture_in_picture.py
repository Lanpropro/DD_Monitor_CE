"""A selected group of existing playback panes in one independent floating window."""
import math
import sys

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, QRectF, QSignalBlocker, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPainterPath, QPen, QRegion, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from . import follow_folders, theme
from .search import matches_text
from .ui import ActionButton, Avatar, ElidedLabel, page_header


from .pip_composition import FOCUS_LAYOUT, focus_chat_cells, focus_slots


def composition_rows(aspects, columns=0):
    def rows(cols):
        return [aspects[index:index + cols] for index in range(0, len(aspects), cols)]
    if not columns:
        columns = min(range(1, len(aspects) + 1), key=lambda cols:
                      (abs(math.log(composition_aspect(rows(cols)) / (16 / 9))), math.ceil(len(aspects) / cols)))
    return rows(min(len(aspects), columns))


def composition_aspect(rows):
    return 1 / sum(1 / sum(row) for row in rows)


def _focus_parts(aspects, primary):
    order = [primary] + [index for index in range(6) if index != primary]
    values = [aspects[index] for index in order]
    right = 1 / (1 / values[1] + 1 / values[2])
    return order, values, values[0] + right, sum(values[3:])


def composition_ratio(aspects, columns=0, primary=0):
    if columns == FOCUS_LAYOUT and len(aspects) == 6:
        _order, _values, top, bottom = _focus_parts(aspects, primary)
        return 1 / (1 / top + 1 / bottom)
    return composition_aspect(composition_rows(aspects, 0 if columns == FOCUS_LAYOUT else columns))


def video_aspect(player):
    if player is not None:
        for name in ('video-out-params', 'video-params'):
            params = player._prop(name)
            if not isinstance(params, dict):
                continue
            width, height = params.get('dw', params.get('w')), params.get('dh', params.get('h'))
            aspect = params.get('aspect') or (width / height if width and height else 0)
            if isinstance(aspect, (int, float)) and math.isfinite(aspect) and aspect > 0:
                return 1 / aspect if params.get('rotate', 0) % 180 == 90 else float(aspect)
    return None


def pane_rectangles(count, area, columns=0, aspects=None, primary=0):
    if not count:
        return []
    aspects = aspects or [16 / 9] * count
    aspect = composition_ratio(aspects, columns, primary)
    width = max(1, min(area.width(), round(area.height() * aspect)))
    height = max(1, min(area.height(), round(width / aspect)))
    canvas = QRect(0, 0, width, height)
    canvas.moveCenter(area.center())
    if columns == FOCUS_LAYOUT and count == 6:
        order, values, top_aspect, bottom_aspect = _focus_parts(aspects, primary)
        split_y = round(height * aspect / top_aspect)
        split_x = round(width * values[0] / top_aspect)
        right_y = round(split_y * values[2] / (values[1] + values[2]))
        arranged = [QRect(0, 0, split_x, split_y),
                    QRect(split_x, 0, width - split_x, right_y),
                    QRect(split_x, right_y, width - split_x, split_y - right_y)]
        left, offset = 0, 0.0
        for value in values[3:]:
            offset += value
            right = round(width * offset / bottom_aspect)
            arranged.append(QRect(left, split_y, right - left, height - split_y))
            left = right
        rectangles = [None] * count
        for index, rect in zip(order, arranged):
            rectangles[index] = rect.translated(canvas.topLeft())
        return rectangles
    rows = composition_rows(aspects, 0 if columns == FOCUS_LAYOUT else columns)
    rectangles, top, weight = [], 0, 0.0
    for row in rows:
        total = sum(row)
        weight += 1 / total
        bottom = round(height * weight * aspect)
        left, offset = 0, 0.0
        for value in row:
            offset += value
            right = round(width * offset / total)
            rectangles.append(QRect(canvas.x() + left, canvas.y() + top, right - left, bottom - top))
            left = right
        top = bottom
    return rectangles


class CompositionPreview(QFrame):
    positionsSwapped = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('PluginCard')
        self.setFixedHeight(156)
        self.labels = []
        self.columns = 0
        self.aspect = 16 / 9
        self.aspects = []
        self.primary = 0
        self.locked = set()
        self._drag = None
        self._ghost = None
        self._drop_target = None
        self.setAccessibleName('拖动预览画面交换位置')

    def set_panes(self, names, columns, aspects=None, primary=0, locked=()):
        self.cancel_drag()
        for label in self.labels:
            label.hide()
            label.deleteLater()
        self.labels = [ElidedLabel(name, self) for name in names]
        self.columns = columns
        self.primary = primary
        self.locked = set(locked)
        self.aspects = aspects or [16 / 9] * len(names)
        self.aspect = composition_ratio(self.aspects, columns, primary) if names else 16 / 9
        for index, label in enumerate(self.labels):
            label.setAlignment(Qt.AlignCenter)
            label.setObjectName('PluginCard')
            label.setTextFormat(Qt.PlainText)
            label.setCursor(Qt.ArrowCursor if index in self.locked else Qt.OpenHandCursor)
            label.setToolTip(label.text() if index in self.locked else label.text() + '\n拖到另一画面上交换位置')
            label.installEventFilter(self)
            label.show()
        self._arrange()

    def _arrange(self):
        area = self.rect().adjusted(8, 8, -8, -8)
        width = min(area.width(), round(area.height() * self.aspect))
        canvas = QRect(0, 0, width, min(area.height(), round(width / self.aspect)))
        canvas.moveCenter(area.center())
        for label, rect in zip(self.labels, pane_rectangles(
                len(self.labels), canvas, self.columns, self.aspects, self.primary)):
            label.setGeometry(rect)

    def resizeEvent(self, event):
        self.cancel_drag()
        super().resizeEvent(event)
        self._arrange()

    def _highlight(self, target):
        if target is self._drop_target:
            return
        previous, self._drop_target = self._drop_target, target
        for label in (previous, target):
            if label is not None:
                label.setProperty('pipDropTarget', label is target)
                label.style().unpolish(label)
                label.style().polish(label)
                label.update()

    def cancel_drag(self):
        self._drag = None
        QApplication.instance().removeEventFilter(self)
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        if self._ghost is not None:
            self._ghost.hide()
            self._ghost.deleteLater()
            self._ghost = None
        self._highlight(None)

    def eventFilter(self, watched, event):
        kind = event.type()
        if self._drag is None:
            if (watched in self.labels and self.labels.index(watched) not in self.locked
                    and kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton):
                position = event.globalPosition().toPoint()
                self._drag = (self.labels.index(watched), position, watched.mapFromGlobal(position))
                self.grabMouse(Qt.ClosedHandCursor)
                QApplication.instance().installEventFilter(self)
                return True
            return False
        if kind == QEvent.MouseMove:
            if not event.buttons() & Qt.LeftButton:
                self.cancel_drag()
                return True
            source, pressed, offset = self._drag
            position = event.globalPosition().toPoint()
            if self._ghost is None and (position - pressed).manhattanLength() >= QApplication.startDragDistance():
                self._ghost = QLabel(self)
                self._ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
                self._ghost.setPixmap(self.labels[source].grab())
                self._ghost.setFixedSize(self.labels[source].size())
                self._ghost.show()
            if self._ghost is not None:
                point = self.mapFromGlobal(position)
                self._ghost.move(point - offset)
                self._ghost.raise_()
                self._highlight(next((label for index, label in enumerate(self.labels)
                    if index != source and index not in self.locked and label.geometry().contains(point)), None))
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            source = self._drag[0]
            point = self.mapFromGlobal(event.globalPosition().toPoint())
            target = next((index for index, label in enumerate(self.labels)
                           if index not in self.locked and label.geometry().contains(point)), None)
            moved = self._ghost is not None
            self.cancel_drag()
            if moved and target is not None and target != source:
                self.positionsSwapped.emit(source, target)
            return True
        if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.cancel_drag()
            return True
        if (kind == QEvent.ApplicationDeactivate or
                watched is self and kind in (QEvent.Hide, QEvent.UngrabMouse) or
                watched is self.window() and kind in (QEvent.Hide, QEvent.WindowDeactivate)):
            self.cancel_drag()
        return False


class RoomChoice(QPushButton):
    def __init__(self, room, name, index, pixmap, parent):
        super().__init__(parent)
        self.preview_name = name
        self.setObjectName('PipRoomChoice')
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(name + ' · ' + str(room['room_id']))
        self.setAccessibleName(self.toolTip())
        box = QVBoxLayout(self)
        box.setContentsMargins(5, 5, 5, 4)
        box.setSpacing(3)
        display = str(room.get('uname') or room['room_id'])
        self.avatar = Avatar(display, index, size=28, parent=self)
        self.avatar.set_pixmap_image(pixmap)
        box.addWidget(self.avatar, 0, Qt.AlignHCenter)
        label = ElidedLabel(display, self)
        label.setStyleSheet(f'color: {theme.TEXT1};')
        label.setAlignment(Qt.AlignCenter)
        label.setTextFormat(Qt.PlainText)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        box.addWidget(label)
        self.badge = QLabel('✓', self)
        self.badge.setObjectName('PipChoiceBadge')
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.badge.setFixedSize(16, 16)
        self.badge.hide()
        self.toggled.connect(self.badge.setVisible)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.badge.move(self.width() - 20, 4)


class PictureInPictureDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.floating or controller.host)
        self.controller = controller
        self._order = list(controller.selected_choices())
        self._primary = controller.primary_choice()
        self.setWindowTitle('组合画中画')
        self.setAttribute(Qt.WA_DeleteOnClose)
        available = self.screen().availableGeometry()
        self.resize(min(520, available.width() - 48), min(720, available.height() - 80))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addLayout(page_header('画中画', '选择画面组合；退出后恢复原监控室布局'))
        self.preview = CompositionPreview(self)
        self.preview.positionsSwapped.connect(self._swap_preview)
        layout.addWidget(self.preview)
        self.columns = QComboBox(self)
        for title, value in (('自动排列', 0), ('横向排列', 16), ('纵向排列', 1), ('两列排列', 2), ('三列排列', 3),
                             ('单主＋五辅（6格）', FOCUS_LAYOUT)):
            self.columns.addItem(title, value)
        self.columns.setAccessibleName('画中画排列方式')
        self.columns.setCurrentIndex(max(0, self.columns.findData(controller.columns)))
        chat = controller.chat_cells(self.columns.currentData())
        if chat and len(self._order) > 6 - len(chat):
            wall = {key for key, _room in controller._wall_candidates()}
            self._order = ([key for key in self._order if key in wall]
                           + [key for key in self._order if key not in wall])[:6 - len(chat)]
        layout.addWidget(self.columns)
        self.search = QLineEdit(self)
        self.search.setObjectName('Search')
        self.search.setPlaceholderText(controller.host.sidebar.search.placeholderText())
        self.search.setToolTip(controller.host.sidebar.search.toolTip())
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('搜索画中画直播间')
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.choice_viewport = scroll.viewport()
        self.choice_viewport.installEventFilter(self)
        content = QWidget()
        choices = QVBoxLayout(content)
        choices.setContentsMargins(0, 0, 0, 0)
        choices.setSpacing(10)
        self.checks = {}
        self.choice_buttons = {}
        self.rooms = {}
        self.sections = []
        self.choice_grids = []
        selected = self._order
        faces = {str(item.room.get('room_id')): item.thumb.face_pixmap() for item in controller.host.sidebar.items()}
        for title, entries in controller.candidate_groups():
            if not entries:
                continue
            holder = QFrame(content)
            holder.setObjectName('PluginCard')
            block = QVBoxLayout(holder)
            block.setContentsMargins(10, 10, 10, 10)
            heading = QLabel(title, holder)
            heading.setObjectName('SectionLabel')
            heading.setTextFormat(Qt.PlainText)
            block.addWidget(heading)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(6)
            block.addLayout(grid)
            choices.addWidget(holder)
            self.choice_grids.append(grid)
            group = []
            for key, room in entries:
                name = (f'{key + 1} · ' if isinstance(key, int) else '') + str(room.get('uname') or room['room_id'])
                index = self.checks[key].avatar._index if key in self.checks else len(self.checks)
                check = RoomChoice(room, name, index, faces.get(str(room['room_id'])), holder)
                check.choice = key
                sidebar = controller.host.sidebar
                folder = sidebar.get_folder(sidebar.folder_for(str(room['room_id'])))
                check.folder_names = ' '.join((folder['name'] if folder else '',
                                               title if title != '已入墙' else ''))
                check.setChecked(key in selected)
                self.checks.setdefault(key, check)
                self.choice_buttons.setdefault(key, []).append(check)
                check.toggled.connect(lambda checked, choice=key: self._toggle_choice(choice, checked))
                self.rooms[key] = room
                check.show()
                group.append(check)
            self.sections.append((heading, group))
        choices.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.hint = QLabel(self)
        self.hint.setObjectName('SettingsHint')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        footer = QHBoxLayout()
        cancel = ActionButton('取消', self)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        footer.addStretch()
        self.start = ActionButton('应用组合' if controller.active else '打开画中画', self)
        self.start.setObjectName('PrimaryButton')
        self.start.clicked.connect(self._apply)
        footer.addWidget(self.start)
        layout.addLayout(footer)
        self.columns.currentIndexChanged.connect(self._refresh)
        self._refresh()
        self._arrange_choices()

    def _selected(self):
        checked = [index for index, check in self.checks.items() if check.isChecked()]
        previous = self._order
        return ([index for index in previous if index in checked]
                + [index for index in checked if index not in previous])

    def _toggle_choice(self, key, checked):
        for button in self.choice_buttons[key]:
            with QSignalBlocker(button):
                button.setChecked(checked)
            button.badge.setVisible(checked)
        self._refresh()

    def _filter(self, value):
        words = value.strip().lower().split()
        for heading, buttons in self.sections:
            visible = []
            for button in buttons:
                room = self.rooms[button.choice]
                text = ' '.join((str(room.get('uname') or ''), str(room['room_id']), button.folder_names))
                matches = all(matches_text(text, word) for word in words)
                button.setVisible(matches)
                visible.append(matches)
            heading.setVisible(any(visible))
        self._arrange_choices()

    def _arrange_choices(self):
        columns = max(1, min(6, (self.choice_viewport.width() - 20 + 6) // 110))
        for (_heading, buttons), grid in zip(self.sections, self.choice_grids):
            while grid.count():
                grid.takeAt(0)
            visible = [button for button in buttons if not button.isHidden()]
            for column in range(max(columns, grid.columnCount())):
                grid.setColumnStretch(column, 1 if column < columns else 0)
            for index, button in enumerate(visible):
                grid.addWidget(button, index // columns, index % columns)
            grid.parentWidget().setVisible(bool(visible))

    def eventFilter(self, watched, event):
        if watched is self.choice_viewport and event.type() == QEvent.Resize:
            self._arrange_choices()
        return super().eventFilter(watched, event)

    def _swap_preview(self, first, second):
        selection = self._selected()
        if self.controller.chat_cells(self.columns.currentData()):
            source, target = self._preview_choices[first], self._preview_choices[second]
            if source is None or target is None:
                return
            left, right = selection.index(source), selection.index(target)
            selection[left], selection[right] = selection[right], selection[left]
            self._order = selection
            if first == 0 or second == 0:
                self._primary = target if first == 0 else source
            self._refresh()
            return
        primary = selection.index(self._primary)
        selection[first], selection[second] = selection[second], selection[first]
        self._order = selection
        if self.columns.currentData() == FOCUS_LAYOUT and len(selection) == 6:
            self._primary = selection[primary]
        self._refresh()

    def _refresh(self, *_args):
        selection = self._selected()
        self._order = selection
        names = [self.checks[index].preview_name for index in selection]
        if self._primary not in selection:
            self._primary = selection[0] if selection else None
        focus = self.columns.currentData() == FOCUS_LAYOUT
        slots, aspects, primary = self.controller.composition(selection, self.columns.currentData(), self._primary)
        self._preview_choices = slots
        chat = self.controller.chat_cells(self.columns.currentData())
        if chat:
            names = ['弹幕' if index in chat else self.checks[key].preview_name if key is not None else '未选择视频'
                     for index, key in enumerate(slots)]
            self.preview.set_panes(names, self.columns.currentData(), aspects, primary,
                                   locked=[index for index, key in enumerate(slots) if key is None])
            required = 6 - len(chat)
            self.start.setEnabled(len(selection) == required)
            self.hint.setText(f'此布局需要 {required} 路视频＋{len(chat)} 格弹幕，当前选择 {len(selection)} 路视频。'
                              '弹幕来源沿用监控室；取消一路视频后可从下方替换。')
            return
        self.preview.set_panes(names, self.columns.currentData(), aspects, primary)
        valid = bool(names) and (not focus or len(names) == 6)
        self.start.setEnabled(valid)
        self.hint.setText('单主＋五辅需要选择6路画面；在预览中拖动交换位置。' if focus and len(names) != 6 else
                          f'已选择 {len(names)} 路，可拖动预览交换位置；墙外直播仅在本次画中画中观看。'
                          if self.checks else '暂无可选直播间，请先添加关注或画面。')

    def _apply(self):
        selected = self._selected()
        if self.controller.start(selected, self.columns.currentData(), self._primary):
            self.accept()
        else:
            self.hint.setText('所选直播间已变化或下播，请重新选择。')


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
        self.back = PictureInPictureButton('return', '关闭画中画并返回监控室（Esc）', self)
        self.close_only = PictureInPictureButton('close', '仅关闭画中画，保持主窗口状态', self)
        for button in (self.manage, self.reorder, self.pin, self.back, self.close_only):
            box.addWidget(button)
        self.manage.clicked.connect(owner.controller.manage)
        self.reorder.toggled.connect(owner._set_reordering)
        self.pin.toggled.connect(owner._pin)
        self.back.clicked.connect(owner.return_to_monitor)
        self.close_only.clicked.connect(owner.close)
        QShortcut(QKeySequence(Qt.Key_Escape), self).activated.connect(owner._escape)


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
        self.setStyleSheet('#PictureInPicture { background: #000; }')
        self.setFocusPolicy(Qt.StrongFocus)
        self.aspect = 16 / 9
        self._native_rounding = False
        self._rounding_hwnd = None
        self._fitting = False
        self.resize(640, 360)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)
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
        QShortcut(QKeySequence(Qt.Key_Escape), self.audio_tools).activated.connect(self._escape)
        self._pending_geometry = None
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setTimerType(Qt.PreciseTimer)
        self._geometry_timer.setInterval(16)
        self._geometry_timer.timeout.connect(self._flush_geometry)
        self._surface_state = []
        self.track_tiles(controller.host.wall.tiles)
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(100)
        self._hover_timer.timeout.connect(self._poll_tools)
        self._hover_timer.start()
        QApplication.instance().installEventFilter(self)
        shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        shortcut.activated.connect(self._escape)

    def track_tiles(self, tiles):
        tracked = {widget for widget, _tracking, _cursor in self._surface_state}
        for tile in tiles:
            for widget in (tile, tile.video):
                if widget not in tracked:
                    self._surface_state.append((widget, widget.hasMouseTracking(),
                        widget.cursor() if widget.testAttribute(Qt.WA_SetCursor) else None))
                    widget.setMouseTracking(True)

    def forget_tile(self, tile):
        self._surface_state = [entry for entry in self._surface_state if entry[0] not in (tile, tile.video)]

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
        position = self.mapToGlobal(QPoint(self.width() - self.tools.width() - 8, 8))
        moved = self.tools.pos() != position
        was_visible = self.tools.isVisible()
        if moved:
            self.tools.move(position)
        if was_visible != visible:
            self.tools.setVisible(visible)
        if visible and (not was_visible or moved):
            self.tools.raise_()
        audio_position = self.mapToGlobal(QPoint(8 if self.height() < 64 else self.width() - 32, self.height() - 32))
        audio_moved = self.audio_tools.pos() != audio_position
        audio_visible = self.audio_tools.isVisible()
        if audio_moved:
            self.audio_tools.move(audio_position)
        self.audio_tools.setVisible(visible)
        if visible and (not audio_visible or audio_moved):
            self.audio_tools.raise_()
        if self.controller.dialog is not None:
            self.audio_panel.hide()

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

    def set_composition(self, aspects, columns, primary=0):
        self.aspect = composition_ratio(aspects, columns, primary)
        minimum_height = max(48, math.ceil((self.tools.width() + 48) / self.aspect))
        self.setMinimumSize(round(minimum_height * self.aspect), minimum_height)
        screen = self.screen().availableGeometry()
        self.resize_to_width(min(self.width(), screen.width(), round(screen.height() * self.aspect)))

    def resize_to_width(self, width):
        self._fitting = True
        width = max(self.minimumWidth(), width)
        self.resize(width, round(width / self.aspect))
        self._fitting = False

    def _apply_rounding(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        region = QRegion(path.toFillPolygon().toPolygon())
        # Keep comment clipping separate: a hard native region disables DWM's
        # antialiased window corners, especially visible at fractional DPI.
        self.setProperty('presentationMask', region)
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            from .window_fullscreen import _dwm_set
            hwnd = int(self.winId())
            if hwnd != self._rounding_hwnd:
                self._rounding_hwnd = hwnd
                self._native_rounding = _dwm_set(hwnd, 33, 2) == 0
                _dwm_set(hwnd, 34, 0xFFFFFFFE)
        if self._native_rounding:
            if not self.mask().isEmpty():
                self.clearMask()
        else:
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
        edges = Qt.Edges()
        # Larger corner targets, narrow edge targets: no visible resize frame.
        corner = ((point.x() < 18 or point.x() >= self.width() - 18)
                  and (point.y() < 18 or point.y() >= self.height() - 18))
        margin = 18 if corner else 6
        if point.x() < margin:
            edges |= Qt.LeftEdge
        elif point.x() >= self.width() - margin:
            edges |= Qt.RightEdge
        if point.y() < margin:
            edges |= Qt.TopEdge
        elif point.y() >= self.height() - margin:
            edges |= Qt.BottomEdge
        return edges

    def _tile_at(self, point):
        if self.tools.isVisible() and self.tools.geometry().contains(point):
            return None
        if self.audio_tools.isVisible() and self.audio_tools.geometry().contains(point):
            return None
        return next((tile for tile in self.controller.host.wall.visible_tiles()
                     if tile.rect().contains(tile.mapFromGlobal(point))), None)

    def _set_reordering(self, enabled):
        self._reorder_drag = None
        if self._gesture is None and QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.setCursor(Qt.OpenHandCursor if enabled else Qt.ArrowCursor)
        for widget, _tracking, _cursor in self._surface_state:
            widget.unsetCursor()
        self.tools.reorder.setToolTip('拖到另一格后松开互换；点击结束调整' if enabled else '调整画面位置')

    def eventFilter(self, watched, event):
        kind = event.type()
        if (self._live_move is not None and self._live_move.system_moving
                and kind in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease)):
            return False
        if (kind in (QEvent.ShortcutOverride, QEvent.KeyPress) and isinstance(watched, QWidget)
                and watched.window() in (self, self.tools, self.audio_tools)):
            pressed = QKeySequence(event.keyCombination()).toString()
            shortcuts = self.controller.host.shortcuts
            if pressed in ('Up', 'Down', shortcuts.get('mute'), shortcuts.get('solo')):
                if kind == QEvent.ShortcutOverride:
                    event.accept()
                    return True
                tile = self._tile_at(QCursor.pos()) if self._pointer_over() else None
                if tile is not None:
                    if pressed in ('Up', 'Down'):
                        tile.set_volume(tile.volume + (5 if pressed == 'Up' else -5))
                    elif pressed == shortcuts.get('mute'):
                        tile.set_muted(not tile.muted)
                    else:
                        for member in self.controller.host.wall.picture_in_picture_tiles:
                            member.set_muted(member is not tile)
                    self.audio_feedback.display(tile)
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
        wall = self.controller.host.wall
        surfaces = (self, preview, wall, *(surface for tile in wall.visible_tiles()
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
                rect = QRect(bounds)
                if not edges:
                    rect.translate(delta)
                else:
                    if edges & Qt.LeftEdge:
                        rect.setLeft(min(bounds.left() + delta.x(), bounds.right() - self.minimumWidth() + 1))
                    if edges & Qt.RightEdge:
                        rect.setRight(max(bounds.right() + delta.x(), bounds.left() + self.minimumWidth() - 1))
                    if edges & Qt.TopEdge:
                        rect.setTop(min(bounds.top() + delta.y(), bounds.bottom() - self.minimumHeight() + 1))
                    if edges & Qt.BottomEdge:
                        rect.setBottom(max(bounds.bottom() + delta.y(), bounds.top() + self.minimumHeight() - 1))
                    by_height = (not edges & (Qt.LeftEdge | Qt.RightEdge)
                                 or bool(edges & (Qt.TopEdge | Qt.BottomEdge)) and abs(delta.y()) * self.aspect > abs(delta.x()))
                    width = round(rect.height() * self.aspect) if by_height else rect.width()
                    width = max(self.minimumWidth(), width)
                    size = QSize(width, round(width / self.aspect))
                    rect.setSize(size)
                    if edges & Qt.LeftEdge:
                        rect.moveRight(bounds.right())
                    if edges & Qt.TopEdge:
                        rect.moveBottom(bounds.bottom())
                if edges:
                    self._pending_geometry = rect
                    if not self._geometry_timer.isActive():
                        self._geometry_timer.start()
                else:
                    self._move_composition(rect, native_input=event.spontaneous())
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
            if not edges:
                rect = QRect(bounds)
                rect.moveTopLeft(bounds.topLeft() + point - start)
                if self._live_move is not None:
                    self._live_move.set_geometry(rect)
                    self._live_move.finish()
                else:
                    self.move(rect.topLeft())
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
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
            # Change only native Z order. Recomputing all Qt window flags can
            # disturb alpha tool surfaces even without a QWidget Hide event.
            user32.SetWindowPos(int(self.winId()), -1 if pinned else -2, 0, 0, 0, 0, 0x13)
        else:
            self.windowHandle().setFlag(Qt.WindowStaysOnTopHint, pinned)

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


class PictureInPicture(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.floating = None
        self.dialog = None
        saved = host.state.get('ui', {}).get('picture_in_picture', {})
        self.selection = list(saved.get('selection', []))
        self.columns = saved.get('columns', 0)
        self.primary = saved.get('primary')
        self.external_rooms = list(saved.get('external_rooms', []))
        self.external_primary = saved.get('external_primary', '')
        self._choice_order = list(saved.get('choice_order', []))
        self._extra_tiles = {}
        self.pinned = bool(saved.get('pinned', True))
        self.geometry = saved.get('geometry', '')
        self._video_aspects = {}
        self._aspect_timer = QTimer(self)
        self._aspect_timer.setInterval(1000)
        self._aspect_timer.timeout.connect(self._refresh_aspects)
        theme.signals().changed.connect(self._refresh_theme)
        self.placeholder = QFrame(host._content)
        self.placeholder.setObjectName('PluginCard')
        layout = QVBoxLayout(self.placeholder)
        layout.addStretch()
        text = QLabel('正在画中画中观看\n其他画面按原设置在后台播放\n返回后恢复原监控室布局', self.placeholder)
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)
        for title, action in (('管理画中画', self.manage), ('返回监控室', self.restore)):
            button = ActionButton(title, self.placeholder)
            button.clicked.connect(action)
            layout.addWidget(button, 0, Qt.AlignHCenter)
        layout.addStretch()
        self.placeholder.hide()

    @property
    def active(self):
        return self.floating is not None

    def _refresh_theme(self, *_args):
        if self.active:
            self.floating.tools.update()
            for button in self.floating.tools.findChildren(PictureInPictureButton):
                button.update()

    def manage(self):
        if self.active:
            self.floating.audio_panel.hide()
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if not self.selection and not self.external_rooms:
            capacity = self.host.wall._capacity() or len(self.host.wall.tiles)
            self.selection = [index for index, _room in self._wall_candidates() if index < capacity]
            if self.chat_cells(FOCUS_LAYOUT):
                self.columns = FOCUS_LAYOUT
        self.dialog = PictureInPictureDialog(self)
        self.dialog.finished.connect(self._finish_manage)
        self.dialog.open()

    def _finish_manage(self, _result):
        self.dialog = None
        self._sync_overlays()

    def _wall_candidates(self):
        wall = self.host.wall
        panes = wall.pane_danmaku
        chat_cells = panes.bindings()
        chat_tiles = {tile for cell, tile in panes.cell_tiles().items() if cell in chat_cells}
        return [(index, tile.room) for index, tile in enumerate(wall.tiles)
                if tile not in chat_tiles and tile.room.get('room_id')
                and not tile.property('pictureInPictureTemporary')]

    def candidate_groups(self):
        wall = self._wall_candidates()
        wall_ids = {str(room['room_id']) for _index, room in wall}
        others = {}
        for room in self.host.sidebar.rooms():
            rid = str(room.get('room_id') or '')
            if rid and rid not in wall_ids and room.get('live') and room.get('live_known', True):
                others.setdefault(rid, room)
        for rid, tile in self._extra_tiles.items():
            if tile.room.get('room_id') and rid in self.external_rooms:
                others.setdefault(rid, tile.room)
        by_room = {}
        for key, room in wall + list(others.items()):
            by_room.setdefault(str(room['room_id']), []).append((key, room))
        sidebar = self.host.sidebar
        default = sidebar.default_folder()['id']
        groups = [('已入墙', wall)]
        for folder in sidebar.folders:
            copies = folder['type'] == 'smart' and folder['rule'].get('display') == 'copy'
            members = follow_folders.smart_members(sidebar.rooms(), sidebar.folders, folder,
                                                  sidebar._folder_pending) if copies else None
            entries = [entry for rid, choices in by_room.items()
                       if (rid in members if copies else (sidebar.folder_for(rid) or default) == folder['id'])
                       for entry in choices]
            if entries:
                groups.append((folder['name'], entries))
        return groups

    def choice_for_index(self, index):
        tiles = self.host.wall.tiles
        if isinstance(index, int) and 0 <= index < len(tiles) and tiles[index].property('pictureInPictureTemporary'):
            return str(tiles[index].room.get('room_id') or '')
        return index

    def selected_choices(self):
        choices = [self.choice_for_index(index) for index in self.selection]
        choices += [rid for rid in self.external_rooms if rid not in choices]
        if self.active:
            return choices
        return ([key for key in self._choice_order if key in choices]
                + [key for key in choices if key not in self._choice_order])

    def primary_choice(self):
        return self.external_primary or self.choice_for_index(self.primary)

    def _remove_extra(self, rid):
        tile = self._extra_tiles.pop(rid)
        if self.floating is not None:
            self.floating.forget_tile(tile)
        self._video_aspects.pop(tile, None)
        self._minimums.pop(tile, None)
        dialog = self.host._stream_info_dialogs.get(tile)
        if dialog is not None:
            dialog.close()
        self.host._clear_tile_room(tile)
        if tile in self.host.recorder.sessions:
            tile.hide()
            self.host.wall.tiles.remove(tile)
            self.host._preset_retired_tiles.add(tile)
        else:
            self.host.wall._drop_tile(tile)

    def aspects_for(self, selection):
        aspects = []
        for index in selection:
            tile = self._extra_tiles.get(index) if isinstance(index, str) else self.host.wall.tiles[index]
            if tile is None:
                aspects.append(16 / 9)
                continue
            room = tile.room.get('room_id')
            aspect = video_aspect(self.host.players.get(tile))
            previous_room, previous_aspect = self._video_aspects.get(tile, (None, 16 / 9))
            aspect = aspect or (previous_aspect if previous_room == room else 16 / 9)
            self._video_aspects[tile] = (room, aspect)
            aspects.append(aspect)
        return aspects

    def _refresh_aspects(self):
        if not self.active or self.floating._gesture is not None or self.floating._reorder_drag is not None:
            return
        wall = self.host.wall
        _slots, aspects, primary = self.composition(self.selection, self.columns, self.primary)
        if aspects == wall.picture_in_picture_aspects:
            return
        wall.picture_in_picture_aspects = aspects
        self.floating.set_composition(aspects, self.columns, primary)
        wall.relayout(force=True)

    def swap_positions(self, source, target):
        tiles = self.host.wall.picture_in_picture_tiles
        if source is target or source not in tiles or target not in tiles:
            return
        first, second = tiles.index(source), tiles.index(target)
        primary = self.selection.index(self.primary)
        self.selection[first], self.selection[second] = self.selection[second], self.selection[first]
        if self.columns == FOCUS_LAYOUT:
            self.primary = self.selection[primary]
        self.start(self.selection, self.columns, self.primary)

    def start(self, selection, columns=0, primary=None):
        wall = self.host.wall
        candidates = {key: room for _title, entries in self.candidate_groups() for key, room in entries}
        for key in selection:
            if self.choice_for_index(key) not in candidates:
                return False
        chat = self.chat_cells(columns)
        if chat and len({self.choice_for_index(key) for key in selection}) != 6 - len(chat):
            return False
        self.host._cancel_interactive_resize()
        if self.host._fullscreen_tile is not None:
            self.host._exit_fullscreen()
        tiles, primary_tile, starting = [], None, []
        for key in selection:
            if isinstance(key, str):
                tile = self._extra_tiles.get(key)
                if tile is None:
                    tile = wall._make_tile(dict(candidates[key]))
                    tile.setProperty('pictureInPictureTemporary', True)
                    self._extra_tiles[key] = tile
                    starting.append(tile)
            else:
                tile = wall.tiles[key] if 0 <= key < len(wall.tiles) else None
            if tile is not None and tile.room.get('room_id'):
                if tile not in tiles:
                    tiles.append(tile)
                if key == primary:
                    primary_tile = tile
        if not tiles:
            return False
        selection = [wall.tiles.index(tile) for tile in tiles]
        primary = wall.tiles.index(primary_tile) if primary_tile in tiles else selection[0]
        self.selection, self.columns = list(selection), columns
        self.primary = primary
        self.external_rooms = [str(tile.room['room_id']) for tile in tiles if tile.property('pictureInPictureTemporary')]
        self.external_primary = (str(wall.tiles[primary].room['room_id'])
                                 if wall.tiles[primary].property('pictureInPictureTemporary') else '')
        self._choice_order = [self.choice_for_index(index) for index in self.selection]
        opened = not self.active
        if opened:
            wall.set_sidebar_animating(False)
            self.floating = PictureInPictureWindow(self)
            if self.geometry:
                self.floating.restoreGeometry(QByteArray.fromBase64(self.geometry.encode('ascii')))
            else:
                width = 480 if len(tiles) == 1 else 640
                self.floating.resize_to_width(width)
            self._minimums = {tile: tile.minimumSize() for tile in wall.tiles}
            content = self.host._content.layout()
            content.removeWidget(wall)
            content.insertWidget(0, self.placeholder, 1)
            self.placeholder.show()
            self.floating.box.addWidget(wall, 1)
        else:
            self.floating.track_tiles(starting)
            self._minimums.update((tile, tile.minimumSize()) for tile in starting)
        _slots, aspects, composition_primary = self.composition(selection, columns, primary)
        wall.set_picture_in_picture(tiles, columns, aspects, selection.index(primary))
        self.floating.set_composition(aspects, columns, composition_primary)
        self.floating.show()
        wall.show()
        for rid, tile in list(self._extra_tiles.items()):
            if tile not in tiles:
                self._remove_extra(rid)
        self.selection = [wall.tiles.index(tile) for tile in tiles]
        self.primary = wall.tiles.index(primary_tile) if primary_tile in tiles else self.selection[0]
        for tile in starting:
            self.host.start_tile(tile)
        if chat:
            self.host.sync_danmaku()
        self.floating.audio_panel.hide()
        self._sync_overlays()
        self._aspect_timer.start()
        self.host.sidebar.picture_in_picture_button.setToolTip(f'管理画中画（{len(tiles)} 路）')
        if opened:
            QTimer.singleShot(0, self, self._minimize_host)
        self.host._save_timer.start()
        return True

    def _minimize_host(self):
        if self.active and not self.host._closing:
            self.host.showMinimized()

    def _sync_overlays(self):
        wall = self.host.wall
        layer = wall._quick_danmaku_layer
        if layer is not None:
            layer.set_presentation_window(self.host._fullscreen_tile)
            layer.show()
        for tile in wall.tiles:
            tile.video_danmaku.super_chat_overlay.set_presentation_changing(False)
            dialog = self.host._stream_info_dialogs.get(tile)
            if dialog is not None:
                dialog.set_presentation_owner(tile.window())

    def restore(self, *, activate=False):
        floating = self.floating
        if floating is None:
            return
        if self.dialog is not None:
            self.dialog.reject()
        self.geometry = str(floating.saveGeometry().toBase64(), 'ascii')
        floating.stop()
        self._aspect_timer.stop()
        self.floating = None
        wall = self.host.wall
        selected = [wall.tiles[index] for index in self.selection]
        primary_tile = wall.tiles[self.primary]
        for rid in list(self._extra_tiles):
            self._remove_extra(rid)
        self.selection = [wall.tiles.index(tile) for tile in selected if tile in wall.tiles]
        self.primary = wall.tiles.index(primary_tile) if primary_tile in wall.tiles else None
        floating.box.removeWidget(wall)
        content = self.host._content.layout()
        content.removeWidget(self.placeholder)
        self.placeholder.hide()
        content.insertWidget(0, wall, 1)
        for tile, minimum in self._minimums.items():
            tile.setMinimumSize(minimum)
        wall.set_picture_in_picture(None)
        floating.hide()
        floating.deleteLater()
        wall.show()
        self._sync_overlays()
        self.host.sidebar.picture_in_picture_button.setToolTip('选择多路画面，组合为置顶小窗')
        self.host._refresh_meta()
        if activate:
            self.host._tray.restore()

    def state(self):
        geometry = (str(self.floating.saveGeometry().toBase64(), 'ascii')
                    if self.active else self.geometry)
        selection = [index for index in self.selection if 0 <= index < len(self.host.wall.tiles)
                     and not self.host.wall.tiles[index].property('pictureInPictureTemporary')]
        primary = self.primary if self.primary in selection else None
        return dict(selection=selection, columns=self.columns, primary=primary, pinned=self.pinned,
                    geometry=geometry, external_rooms=list(self.external_rooms), external_primary=self.external_primary,
                    choice_order=self.selected_choices())


    def chat_cells(self, columns):
        return focus_chat_cells(self.host.wall, columns)

    def composition(self, selection, columns, primary=None):
        aspects = self.aspects_for(selection)
        chat = self.chat_cells(columns)
        if chat:
            values = dict(zip(selection, aspects))
            slots = focus_slots(selection, chat, primary)
            return slots, [values.get(key, 16 / 9) for key in slots], 0
        return list(selection), aspects, selection.index(primary) if primary in selection else 0
