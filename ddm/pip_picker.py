"""Picture-in-picture room selection and composition dialog."""
from PySide6.QtCore import QEvent, QRect, QRectF, QSize, QSignalBlocker, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from . import theme
from .corner_geometry import continuous_path
from .search import matches_text
from .settings_window import SettingsTitleBar
from .ui import ActionButton, Avatar, ElidedLabel, HintLabel, ToggleSwitch, page_header
from .pip_arrangements import PipArrangements
from .pip_composition import FOCUS_LAYOUT, FREE_LAYOUT, MAIN_LAYOUT
from .pip_placement import initial_placement, placement_bounds
from .pip_preview import CompositionPreview


class RoomChoice(QPushButton):
    def __init__(self, room, name, index, pixmap, parent):
        super().__init__(parent)
        self.preview_name = name
        self.setObjectName('PipRoomChoice')
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(64)
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
        super().__init__(controller.floating or controller.host, Qt.Dialog | Qt.FramelessWindowHint)
        self.controller = controller
        self._order = list(controller.selected_choices())
        self._primary = controller.primary_choice()
        self._placements = dict(zip(self._order, controller.placement)) if len(self._order) == len(controller.placement) else {}
        self._vacancies = []
        self.setWindowTitle('组合画中画')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setProperty('customControlSurface', True)
        theme.signals().changed.connect(self.update)
        available = self.screen().availableGeometry()
        self.resize(min(560, available.width() - 48), min(740, available.height() - 80))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        self.titlebar = SettingsTitleBar(self)
        self.titlebar.row.setContentsMargins(0, 0, 0, 0)
        self.titlebar.breadcrumb.hide()
        self.titlebar.row.takeAt(1)
        self.titlebar.row.insertLayout(0, page_header('画中画', '选择画面组合；退出后恢复原监控室布局'), 1)
        self.titlebar.close_button.setAccessibleName('关闭组合画中画')
        self.titlebar.close_button.setToolTip('关闭组合画中画')
        self.titlebar.row.setAlignment(self.titlebar.close_button, Qt.AlignTop)
        layout.addWidget(self.titlebar)
        self.preview = CompositionPreview(self)
        self.preview.positionsSwapped.connect(self._swap_preview)
        self.preview.positionChanged.connect(self._place_preview)
        layout.addWidget(self.preview)
        options = QFrame(self)
        options.setObjectName('PluginCard')
        option_rows = QVBoxLayout(options)
        option_rows.setContentsMargins(12, 10, 12, 10)
        option_rows.setSpacing(8)
        self.arrangements = PipArrangements(controller.columns, options)
        self.arrangements.setAccessibleName('画中画排列方式')
        option_rows.addWidget(self.arrangements)
        parallel_row = QHBoxLayout()
        parallel_label = QLabel('与主窗口同时播放', options)
        self.parallel = ToggleSwitch(parallel_label.text(), options)
        self.parallel.setChecked(controller.parallel_preference)
        self.parallel.setToolTip('主画面墙继续播放，小窗默认静音。')
        parallel_label.setBuddy(self.parallel)
        parallel_row.addWidget(parallel_label, 1)
        parallel_row.addWidget(self.parallel)
        option_rows.addLayout(parallel_row)
        layout.addWidget(options)
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
        sidebar = controller.host.sidebar
        faces = {str(item.room.get('room_id')): item.thumb.face_pixmap() for item in sidebar.items()}
        for title, entries in controller.candidate_groups():
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
                folder = sidebar.get_folder(sidebar.folder_for(str(room['room_id'])))
                folder_names = ' '.join((folder['name'] if folder else '', title if title != '已入墙' else ''))
                group.append(self._create_choice(key, room, holder, faces.get(str(room['room_id'])),
                                                 key in selected, folder_names))
            self.sections.append((heading, group))
        self._wall_count = len(self.sections[0][1])
        choices.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.hint = HintLabel(parent=self)
        layout.addWidget(self.hint)
        footer = QHBoxLayout()
        cancel = ActionButton('取消', self)
        cancel.clicked.connect(self.reject)
        footer.addStretch()
        footer.addWidget(cancel)
        self.start = ActionButton('应用组合' if controller.active else '打开画中画', self)
        self.start.setObjectName('PrimaryButton')
        self.start.clicked.connect(self._apply)
        footer.addWidget(self.start)
        layout.addLayout(footer)
        self.arrangements.changed.connect(self._refresh)
        self._refresh()
        self._arrange_choices()
        self.search.setFocus(Qt.OtherFocusReason)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 22)
        painter.fillPath(path, theme.qcolor(theme.BG))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
        painter.drawPath(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.windowHandle() is not None:
            x, y = event.position().toPoint().toTuple()
            edges = Qt.Edge(0)
            if x < 8:
                edges |= Qt.LeftEdge
            elif x >= self.width() - 8:
                edges |= Qt.RightEdge
            if y < 8:
                edges |= Qt.TopEdge
            elif y >= self.height() - 8:
                edges |= Qt.BottomEdge
            if edges and self.windowHandle().startSystemResize(edges):
                event.accept()
                return
        super().mousePressEvent(event)

    def _selected(self):
        checked = [index for index, check in self.checks.items() if check.isChecked()]
        previous = self._order
        return ([index for index in previous if index in checked]
                + [index for index in checked if index not in previous])

    def _create_choice(self, key, room, holder, face, checked, folder_names=''):
        name = (f'{key + 1} · ' if isinstance(key, int) else '') + str(room.get('uname') or room['room_id'])
        index = self.checks[key].avatar._index if key in self.checks else len(self.checks)
        button = RoomChoice(room, name, index, face, holder)
        button.choice = key
        button.folder_names = folder_names
        button.setChecked(checked)
        self.checks.setdefault(key, button)
        self.choice_buttons.setdefault(key, []).append(button)
        self.rooms[key] = room
        button.toggled.connect(lambda checked, choice=key: self._toggle_choice(choice, checked))
        button.show()
        return button

    def _sync_top_group(self, selection):
        extras = [key for key in selection if isinstance(key, str)]
        heading, buttons = self.sections[0]
        mirrors = {button.choice: button for button in buttons[self._wall_count:]}
        if extras == list(mirrors):
            return
        for key in tuple(mirrors):
            if key not in extras:
                mirror = mirrors.pop(key)
                self.choice_buttons[key].remove(mirror)
                mirror.hide()
                mirror.deleteLater()
        words = self.search.text().strip().lower().split()
        for key in extras:
            if key not in mirrors:
                source = self.checks[key]
                mirror = self._create_choice(key, self.rooms[key], heading.parentWidget(), source.avatar._source, True)
                mirror.setVisible(self._matches(mirror, words))
                mirrors[key] = mirror
        buttons[self._wall_count:] = [mirrors[key] for key in extras]
        title = '已入墙与已选' if self._wall_count else '已选直播间'
        heading.setText(title if extras else '已入墙')
        self._arrange_choices(top_only=True)

    def _toggle_choice(self, key, checked):
        for button in self.choice_buttons[key]:
            with QSignalBlocker(button):
                button.setChecked(checked)
            button.badge.setVisible(checked)
        self._refresh()

    def _filter(self, value):
        words = value.strip().lower().split()
        for _heading, buttons in self.sections:
            for button in buttons:
                button.setVisible(self._matches(button, words))
        self._arrange_choices()

    def _matches(self, button, words):
        room = self.rooms[button.choice]
        text = ' '.join((str(room.get('uname') or ''), str(room['room_id']),
                         str(room.get('display_room_id') or ''), button.folder_names))
        return all(matches_text(text, word) for word in words)

    def _arrange_choices(self, *, top_only=False):
        columns = max(1, min(6, (self.choice_viewport.width() - 20 + 6) // 110))
        section_count = 1 if top_only else len(self.sections)
        for section in range(section_count):
            heading, buttons = self.sections[section]
            grid = self.choice_grids[section]
            while grid.count():
                grid.takeAt(0)
            visible = [button for button in buttons if not button.isHidden()]
            for column in range(max(columns, grid.columnCount())):
                grid.setColumnStretch(column, 1 if column < columns else 0)
            for position, button in enumerate(visible):
                grid.addWidget(button, position // columns, position % columns)
            heading.setVisible(bool(visible))
            grid.parentWidget().setVisible(bool(visible))

    def eventFilter(self, watched, event):
        if watched is self.choice_viewport and event.type() == QEvent.Resize:
            self._arrange_choices()
        return super().eventFilter(watched, event)

    def _swap_preview(self, first, second):
        selection = self._selected()
        primary = selection.index(self._primary)
        selection[first], selection[second] = selection[second], selection[first]
        self._order = selection
        if self.arrangements.mode in (FOCUS_LAYOUT, MAIN_LAYOUT):
            self._primary = selection[primary]
        self._refresh()

    def _place_preview(self, index, rect):
        self._placements[self._order[index]] = rect
        self._refresh()

    def _custom_placement(self, selection, aspects):
        for key in list(self._placements):
            if key not in selection:
                self._vacancies.append(self._placements.pop(key))
        if not self._placements and not self._vacancies:
            self._placements = dict(zip(selection, initial_placement(aspects)))
        for key, aspect in zip(selection, aspects):
            if key in self._placements:
                continue
            occupied = [QRect(*value) for value in self._placements.values()]
            slot = None
            while self._vacancies and slot is None:
                vacancy = QRect(*self._vacancies.pop(0))
                if not any(vacancy.intersects(rect) for rect in occupied):
                    size = QSize(max(1, round(vacancy.height() * aspect)), vacancy.height())
                    size.scale(vacancy.size(), Qt.KeepAspectRatio)
                    slot = QRect(vacancy.topLeft(), size)
            if slot is None:
                if occupied:
                    bounds = placement_bounds(list(self._placements.values()))
                    next_row = bounds.width() > bounds.height() * 2
                    x, y = ((bounds.left(), bounds.bottom() + 1) if next_row
                            else (bounds.right() + 1, bounds.top()))
                    height = round(sum(rect.height() for rect in occupied) / len(occupied))
                else:
                    x, y, height = 0, 0, 240
                slot = QRect(x, y, max(1, round(height * aspect)), height)
            self._placements[key] = slot.getRect()
        return tuple(self._placements[key] for key in selection)

    def _refresh(self, *_args):
        selection = self._selected()
        self._order = selection
        self._sync_top_group(selection)
        names = [self.checks[index].preview_name for index in selection]
        if self._primary not in selection:
            self._primary = selection[0] if selection else None
        mode = self.arrangements.update_context(len(selection))
        aspects = self.controller.aspects_for(selection)
        primary = selection.index(self._primary) if selection else 0
        placement = self._custom_placement(selection, aspects) if mode == FREE_LAYOUT else ()
        self.preview.set_panes(names, mode, aspects, primary, placement=placement)
        self.start.setEnabled(bool(selection))
        if mode == FREE_LAYOUT:
            hint = '拖动画面自由摆放，靠近其他画面的边缘时自动吸附对齐。'
        elif len(names) > 1:
            hint = f'已选择 {len(names)} 路，拖到其他画面附近可吸附换位。'
        elif names:
            hint = '已选择 1 路。'
        else:
            hint = '请选择直播间。' if self.checks else '暂无可选直播间，请先添加关注或画面。'
        if any(isinstance(key, str) for key in selection):
            hint += '墙外直播仅在本次画中画中观看。'
        self.hint.setText(hint)

    def _apply(self):
        selected = self._selected()
        if self.controller.start(selected, self.arrangements.mode, self._primary,
                                 parallel=self.parallel.isChecked(), placement=self.preview.placement):
            self.accept()
        else:
            self.hint.setText('所选直播间已变化或下播，请重新选择。')
