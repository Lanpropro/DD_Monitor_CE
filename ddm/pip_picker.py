"""Picture-in-picture room selection and composition dialog."""
from PySide6.QtCore import QEvent, QSignalBlocker, Qt
from PySide6.QtWidgets import QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from . import theme
from .search import matches_text
from .ui import ActionButton, Avatar, ElidedLabel, page_header
from .pip_geometry import FOCUS_LAYOUT
from .pip_preview import CompositionPreview


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
                text = ' '.join((str(room.get('uname') or ''), str(room['room_id']),
                                 str(room.get('display_room_id') or ''), button.folder_names))
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
