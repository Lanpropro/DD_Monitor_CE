"""In-window room entry over the search/follow area; never changes wall layout."""
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QMenu,
    QPlainTextEdit, QVBoxLayout, QWidget)
from . import theme
from .continuous_corners import stylesheet
from .follow_folders import default_folder
from .room_folder_controls import _add_folder_option, _create_folder_for_dialog
from .sidebar_navigation import NavigationButton
from .ui import ActionButton
from .ui.labels import ElidedLabel


class RoomAddPanel(QFrame):
    submitted = Signal(str, str)
    dismissed = Signal()

    def __init__(self, sidebar):
        super().__init__(sidebar.window())
        self.sidebar = sidebar
        sidebar.room_add_panel = self
        self._placement = None
        self._saved_widgets = []
        self.busy = False
        self.folder_id = ''
        self.folder_names = set()
        self.folder_creator = sidebar.create_folder
        self.setObjectName('InlineRoomAdd')
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
        self.close_button = NavigationButton('返回搜索', 'close')
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
        self.import_button = NavigationButton('导入关注', 'import')
        self.import_button.setFixedSize(24, 24)
        self.import_button.clicked.connect(self._import)
        footer.addWidget(self.import_button)
        footer.addStretch(1)
        self.submit_button = ActionButton('添加')
        self.submit_button.setObjectName('PrimaryButton')
        self.submit_button.clicked.connect(lambda: self.submitted.emit(self.entry.toPlainText(), self.folder_id))
        footer.addWidget(self.submit_button)
        box.addLayout(footer)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_to_search)
        QApplication.instance().installEventFilter(self)
        theme.signals().changed.connect(self._theme)
        self._theme()
        self.hide()
        self._update_count()

    def _theme(self):
        self.setStyleSheet(stylesheet(f'''
            #InlineRoomAdd {{background:{theme.CONTENT}; border:1px solid {theme.ACCENT}; border-radius:12px;}}
            #InlineRoomInput {{background:transparent; border:none; padding:0; color:{theme.TEXT1};}}
            #InlineRoomImport {{background:transparent; border:none; padding:0 2px; color:{theme.ACCENT};}}
        '''))
        self.error.setStyleSheet(f'color:{theme.ERROR};')

    def open(self):
        if not self.busy:
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
        self._place_editor()
        self.fit_to_search()
        self.show()
        self.raise_()
        self.entry.setFocus(Qt.OtherFocusReason)

    def _place_editor(self):
        if self._placement is not None:
            return
        sidebar = self.sidebar
        mode = 'floating' if sidebar.collapsed else ('portrait' if sidebar.side == 'top' else 'column')
        self._placement = mode
        parent = sidebar.window() if mode == 'floating' else (sidebar if mode == 'portrait' else sidebar._column)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        if QApplication.platformName() == 'windows':
            self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
            self.setAttribute(Qt.WA_NativeWindow, mode == 'floating')
        self.setParent(parent)
        widgets = (sidebar.search,) if mode == 'column' else (() if mode == 'floating' else (
            sidebar.search, sidebar.scroll, sidebar._head_scroll, sidebar.navigation.filters,
            sidebar.navigation.folder_toggle_button, sidebar.navigation.add_button,
            sidebar.navigation.manage_button, sidebar.toggle_button))
        for widget in widgets:
            policy = widget.sizePolicy()
            self._saved_widgets.append((widget, widget.isHidden(), policy))
            if mode == 'portrait' and not widget.isHidden():
                retained = widget.sizePolicy()
                retained.setRetainSizeWhenHidden(True)
                widget.setSizePolicy(retained)
            widget.hide()
        if mode == 'column':
            sidebar._layout.insertWidget(sidebar._layout.indexOf(sidebar.search), self)

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
        self._update_count()

    def show_error(self, message):
        self.error.setText(message)
        self.error.setToolTip(message)
        self.error.show()
        self.fit_to_search()

    def close_editor(self):
        self._fit_timer.stop()
        self.hide()
        if self._placement == 'column':
            self.sidebar._layout.removeWidget(self)
        for widget, hidden, policy in self._saved_widgets:
            widget.setSizePolicy(policy)
            widget.setVisible(not hidden)
        self._saved_widgets.clear()
        self._placement = None
        self.dismissed.emit()
        if self.sidebar.search.isVisible():
            self.sidebar.search.setFocus(Qt.OtherFocusReason)

    def _import(self):
        self.close_editor()
        self.sidebar.import_button.click()

    def fit_to_search(self):
        sidebar = self.sidebar
        parent = self.parentWidget()
        anchor = sidebar._head_scroll if sidebar.side == 'top' and sidebar.collapsed else sidebar.search
        if sidebar.side == 'left' and sidebar.collapsed:
            # No search field exists in the narrow rail; keep it collapsed and
            # place the same editor beside its add button inside the main window.
            point = sidebar.mapTo(parent, QPoint(sidebar.width() + 4, 12))
            width, height = min(400, parent.width() - point.x() - 12), 132
        else:
            point = anchor.mapTo(parent, QPoint(0, 0))
            right = sidebar.mapTo(parent, QPoint(sidebar.width() - 10, 0)).x()
            width = right - point.x()
            if sidebar.side == 'top':
                bottom = sidebar.mapTo(parent, QPoint(0, sidebar.height() - 8)).y()
                height = max(102, bottom - point.y())
            else:
                lines = min(4, max(1, self.entry.document().blockCount()))
                height = 82 + self.entry.fontMetrics().lineSpacing() * lines
        if not self.error.isHidden():
            height = max(height, 126)
        width = max(160, min(width, parent.width() - 16))
        folder_width = max(52, min(120, width - 20 - 24 - self.submit_button.sizeHint().width() - 18))
        self.folder_button.setMaximumWidth(folder_width)
        if hasattr(self, '_folder_name'):
            self.folder_button.setText(self.folder_button.fontMetrics().elidedText(
                self._folder_name, Qt.ElideRight, max(20, folder_width - 30)))
        point.setX(max(8, min(point.x(), parent.width() - width - 8)))
        point.setY(max(0, min(point.y(), parent.height() - height)))
        if self._placement == 'column':
            self.setFixedHeight(height)
            self.sidebar._layout.activate()
        else:
            self.setGeometry(QRect(point, QSize(width, height)))
        if self.isVisible():
            self.raise_()

    def eventFilter(self, watched, event):
        if watched is self.entry and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.close_editor()
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
                if self.submit_button.isEnabled():
                    self.submit_button.click()
                return True
        if self.isVisible():
            if watched in (self.sidebar, self.sidebar.search, self.sidebar.scroll, self.parentWidget()) and event.type() in (
                    QEvent.Resize, QEvent.Move, QEvent.LayoutRequest, QEvent.Show):
                self._fit_timer.start(0)
            elif (self._placement == 'floating' and event.type() == QEvent.MouseButtonPress and isinstance(watched, QWidget)
                  and watched.window() is self.parentWidget() and watched is not self
                  and not self.isAncestorOf(watched)):
                self.close_editor()
        return super().eventFilter(watched, event)
