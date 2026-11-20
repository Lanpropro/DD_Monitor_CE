"""In-window room entry anchored to the sidebar; never replaces search or follow content."""
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QMenu,
    QPlainTextEdit, QVBoxLayout, QWidget)
from shiboken6 import isValid
from . import theme
from .corner_geometry import continuous_path
from .follow_folders import default_folder
from .room_add_followed import FollowedRoomPicker, PresetRoomPicker
from .room_folder_controls import _add_folder_option, _create_folder_for_dialog
from .sidebar_navigation import NavigationButton
from .ui import ActionButton
from .ui.labels import ElidedLabel


class RoomAddPanel(QFrame):
    submitted = Signal(str, str)
    dismissed = Signal()
    followed_requested = Signal()
    followed_selected = Signal(str)
    preset_selected = Signal(dict, str)

    def __init__(self, sidebar):
        windows = QApplication.platformName() == 'windows'
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint if windows else Qt.Widget
        super().__init__(sidebar.window(), flags)
        self.sidebar = sidebar
        sidebar.room_add_panel = self
        self.busy = False
        self._focus_on_close = None
        self.folder_id = ''
        self.folder_names = set()
        self.folder_creator = sidebar.create_folder
        self.setObjectName('InlineRoomAdd')
        self.setProperty('customControlSurface', True)
        if windows:
            # A child HWND shares the owner's backing store and can expose overlapping video first.
            self.setAttribute(Qt.WA_TranslucentBackground)
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.entry = QPlainTextEdit()
        self.entry.setObjectName('InlineRoomInput')
        self.entry.setPlaceholderText('房间号或链接，每行一个')
        self.entry.setMinimumHeight(32)
        self.entry.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.entry.textChanged.connect(self._update_count)
        self.entry.installEventFilter(self)
        top.addWidget(self.entry, 1)
        self.close_button = NavigationButton('关闭添加', 'close')
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.close_editor)
        top.addWidget(self.close_button, 0, Qt.AlignTop)
        box.addLayout(top, 1)
        self.error = ElidedLabel('')
        self.error.setToolTip('')
        self.error.hide()
        box.addWidget(self.error)
        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.folder_button = ActionButton()
        self.folder_button.setMaximumWidth(120)
        self.folder_button.setToolTip('添加到文件夹')
        footer.addWidget(self.folder_button)
        self.import_button = NavigationButton('从平台账号导入关注', 'import_follows')
        self.import_button.setFixedSize(24, 24)
        self.import_button.clicked.connect(self._import)
        footer.addWidget(self.import_button)
        self.followed_toggle = NavigationButton('从关注列表选择', 'follow')
        self.followed_toggle.setFixedSize(24, 24)
        self.followed_toggle.setCheckable(True)
        self.followed_toggle.hide()
        footer.addWidget(self.followed_toggle)
        self.preset_button = NavigationButton('频道预设', 'tv')
        self.preset_button.setFixedSize(24, 24)
        self.preset_button.setCheckable(True)
        self.preset_button.hide()
        footer.addWidget(self.preset_button)
        self._file_filters = []
        footer.addStretch(1)
        self.submit_button = ActionButton('添加')
        self.submit_button.setObjectName('PrimaryButton')
        self.submit_button.clicked.connect(lambda: self.submitted.emit(self.entry.toPlainText(), self.folder_id))
        footer.addWidget(self.submit_button)
        box.addLayout(footer)
        self.followed = FollowedRoomPicker(sidebar, self)
        self.followed.selected.connect(self.followed_selected.emit)
        self.followed.hide()
        box.addWidget(self.followed)
        self.followed_toggle.toggled.connect(self._toggle_followed)
        self.presets = PresetRoomPicker(self)
        self.presets.selected.connect(lambda room_id: self.preset_selected.emit(
            self.presets.rooms[room_id], self.folder_id))
        self.presets.file_button.clicked.connect(self._choose_files)
        self.presets.hide()
        box.addWidget(self.presets)
        self.preset_button.toggled.connect(self._toggle_presets)
        escape = QShortcut(QKeySequence(Qt.Key_Escape), self)
        escape.setContext(Qt.WidgetWithChildrenShortcut)
        escape.activated.connect(self.close_editor)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_to_search)
        QApplication.instance().installEventFilter(self)
        theme.signals().changed.connect(self._theme)
        self._theme()
        self.hide()
        self._update_count()

    def _theme(self):
        self.entry.setStyleSheet(f'background:transparent; border:none; padding:0; color:{theme.TEXT1};')
        self.error.setStyleSheet(f'color:{theme.ERROR};')
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(theme.qcolor(theme.CONTENT))
        painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1))
        painter.drawPath(continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 11.5))

    def _sidebar_add_button(self):
        navigation = self.sidebar.navigation
        return navigation.collapsed_add_button if self.sidebar.collapsed else navigation.add_button

    def open(self, *, can_choose_followed=False, focus_on_close=None):
        self._focus_on_close = self._sidebar_add_button() if focus_on_close is None else focus_on_close
        if not self.busy:
            self.followed_toggle.setChecked(False)
            self.followed_toggle.setVisible(can_choose_followed)
            self.followed.search.clear()
            self.preset_button.setChecked(False)
            self.presets.search.clear()
            folders = self.sidebar.folder_state()
            selected = self.folder_id
            self.folder_names = {folder['name'] for folder in folders}
            old = self.folder_button.menu()
            if old is not None:
                old.deleteLater()
            menu = QMenu(self.folder_button)
            self.folder_button.setMenu(menu)
            _add_folder_option(self, menu, '', default_folder(folders)['name'])
            for folder in folders:
                if folder.get('type', 'normal') == 'normal':
                    _add_folder_option(self, menu, folder['id'], folder['name'])
            action = next((action for action in menu.actions() if action.data() == selected), menu.actions()[0])
            self._select_folder(action)
            menu.addSeparator()
            menu.addAction('新建文件夹…').triggered.connect(lambda: _create_folder_for_dialog(self, self.folder_creator))
        self.fit_to_search()
        self.ensurePolished()
        self.layout().activate()
        self.show()
        self.raise_()
        if self.isWindow():
            self.activateWindow()
        self.entry.setFocus(Qt.OtherFocusReason)

    def _toggle_followed(self, expanded):
        if expanded:
            self.preset_button.setChecked(False)
            self.followed_requested.emit()
        self.followed.setVisible(expanded)
        if self.isVisible():
            self.fit_to_search()
        if expanded:
            self.followed.search.setFocus(Qt.OtherFocusReason)
        elif self.isVisible():
            self.followed_toggle.setFocus(Qt.OtherFocusReason)

    def _toggle_presets(self, expanded):
        if expanded:
            self.followed_toggle.setChecked(False)
        self.presets.setVisible(expanded)
        if self.isVisible():
            self.fit_to_search()
            if expanded:
                first_control = self.presets.search if self.presets.rooms else self.presets.file_button
                first_control.setFocus(Qt.OtherFocusReason)
            else:
                self.preset_button.setFocus(Qt.OtherFocusReason)

    def _select_folder(self, action):
        self.folder_id = action.data()
        self._folder_name = action.text()
        self.folder_button.setText(action.text())
        self.folder_button.setToolTip('添加到：' + action.text())
        for option in self.folder_button.menu().actions():
            if option.isCheckable():
                option.setChecked(option is action)

    def _update_count(self):
        count = len({line.strip() for line in self.entry.toPlainText().splitlines() if line.strip()})
        self.submit_button.setText('添加中…' if self.busy else (f'添加 {count} 个' if count else '添加'))
        self.submit_button.setEnabled(bool(count) and not self.busy)
        if not self.busy:
            self.error.hide()
        if self.isVisible() and self.sidebar.side == 'left':
            self._fit_timer.start(0)

    def set_busy(self, busy):
        self.busy = busy
        self.entry.setReadOnly(busy)
        self.folder_button.setEnabled(not busy)
        self.import_button.setEnabled(not busy)
        self.followed_toggle.setEnabled(not busy)
        self.followed.setEnabled(not busy)
        self.preset_button.setEnabled(not busy)
        self.presets.setEnabled(not busy)
        self._update_count()

    def show_error(self, message):
        self.error.setText(message)
        self.error.setToolTip(message)
        self.error.show()
        self.fit_to_search()

    def close_editor(self, *, click_target=None):
        if self.isHidden():
            return
        owner = self.parentWidget()
        restore_owner = self.isWindow() and (self.isActiveWindow() or click_target is not None)
        focus_target, self._focus_on_close = self._focus_on_close, None
        focused = QApplication.focusWidget()
        if (restore_owner and click_target is not None and click_target.isEnabled()
                and click_target.focusPolicy() & Qt.ClickFocus):
            click_target.setFocus(Qt.MouseFocusReason)
        elif focus_target is not None and focused is not None and self.isAncestorOf(focused):
            if not isValid(focus_target) or not focus_target.isVisible() or not focus_target.isEnabled():
                focus_target = owner
            focus_target.setFocus(Qt.OtherFocusReason)
        self._fit_timer.stop()
        self.hide()
        if restore_owner and owner.isVisible():
            owner.activateWindow()
        self.followed_toggle.setChecked(False)
        self.preset_button.setChecked(False)
        self.dismissed.emit()

    def _import(self):
        self.close_editor()
        self.sidebar.import_button.click()

    def set_presets(self, rooms, filters):
        self._file_filters = list(dict.fromkeys(filters))
        self.presets.load(rooms, bool(self._file_filters))
        available = bool(rooms or self._file_filters)
        if not available:
            self.preset_button.setChecked(False)
        self.preset_button.setVisible(available)

    def _choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择播放列表', '', ';;'.join(self._file_filters))
        if paths:
            text = self.entry.toPlainText().strip()
            self.entry.setPlainText('\n'.join([text, *paths] if text else paths))
            self.preset_button.setChecked(False)
            self.entry.setFocus(Qt.OtherFocusReason)

    def fit_to_search(self):
        sidebar = self.sidebar
        parent = self.parentWidget()
        width = max(160, min(400, parent.width() - 16))
        height = 132 if self.error.isHidden() else 156
        expanded = self.presets if self.preset_button.isChecked() else self.followed
        if not expanded.isHidden():
            desired_height = 280 if expanded is self.followed or self.presets.rooms else expanded.sizeHint().height()
            expanded_height = max(0, min(desired_height, parent.height() - height - 6))
            expanded.setFixedHeight(expanded_height)
            height += expanded_height + 6
        if sidebar.side == 'left':
            point = sidebar.mapTo(parent, QPoint(sidebar.width() + 4, 12))
        else:
            button = self._sidebar_add_button()
            point = button.mapTo(parent, QPoint(button.width() - width, button.height() + 6))
        icon_space = self.import_button.width() + (self.followed_toggle.width() + 6
                                                 if not self.followed_toggle.isHidden() else 0)
        preset_width = self.preset_button.width() + 6 if not self.preset_button.isHidden() else 0
        used = 38 + icon_space + preset_width + self.submit_button.sizeHint().width()
        folder_width = max(52, min(120, width - used))
        self.folder_button.setMaximumWidth(folder_width)
        if hasattr(self, '_folder_name'):
            self.folder_button.setText(self.folder_button.fontMetrics().elidedText(
                self._folder_name, Qt.ElideRight, max(20, folder_width - 30)))
        point.setX(max(8, min(point.x(), parent.width() - width - 8)))
        point.setY(max(0, min(point.y(), parent.height() - height)))
        if self.isWindow():
            point = parent.mapToGlobal(point)
        self.setGeometry(QRect(point, QSize(width, height)))
        if self.isVisible() and not self.isWindow():
            self.raise_()

    def eventFilter(self, watched, event):
        if watched is self.entry and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
                if self.submit_button.isEnabled():
                    self.submit_button.click()
                return True
        if self.isVisible():
            owner = self.parentWidget()
            if watched is owner and event.type() == QEvent.Hide:
                self.close_editor()
            elif watched is owner and event.type() in (QEvent.Resize, QEvent.Move) and self.isWindow():
                self.fit_to_search()
            elif watched in (self.sidebar, self.sidebar.search, self.sidebar.scroll, owner) and event.type() in (
                    QEvent.Resize, QEvent.Move, QEvent.LayoutRequest, QEvent.Show):
                self._fit_timer.start(0)
            elif (event.type() == QEvent.MouseButtonPress and isinstance(watched, QWidget)
                  and watched.window() is owner and watched is not self
                  and not self.isAncestorOf(watched)):
                self.close_editor(click_target=watched)
        return super().eventFilter(watched, event)
