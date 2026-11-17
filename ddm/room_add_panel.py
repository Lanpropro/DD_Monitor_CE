"""In-window room entry anchored to the sidebar; never replaces search or follow content."""
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
        self.busy = False
        self.folder_id = ''
        self.folder_names = set()
        self.folder_creator = sidebar.create_folder
        self.setObjectName('InlineRoomAdd')
        if QApplication.platformName() == 'windows':
            self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
            self.setAttribute(Qt.WA_NativeWindow)
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
        self.fit_to_search()
        self.show()
        self.raise_()
        self.entry.setFocus(Qt.OtherFocusReason)

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
        self.dismissed.emit()
        if self.sidebar.search.isVisible():
            self.sidebar.search.setFocus(Qt.OtherFocusReason)

    def _import(self):
        self.close_editor()
        self.sidebar.import_button.click()

    def fit_to_search(self):
        sidebar = self.sidebar
        parent = self.parentWidget()
        width = max(160, min(400, parent.width() - 16))
        height = 132 if self.error.isHidden() else 156
        if sidebar.side == 'left':
            point = sidebar.mapTo(parent, QPoint(sidebar.width() + 4, 12))
        else:
            button = (sidebar.navigation.collapsed_add_button if sidebar.collapsed
                      else sidebar.navigation.add_button)
            point = button.mapTo(parent, QPoint(button.width() - width, button.height() + 6))
        folder_width = max(52, min(120, width - 20 - 24 - self.submit_button.sizeHint().width() - 18))
        self.folder_button.setMaximumWidth(folder_width)
        if hasattr(self, '_folder_name'):
            self.folder_button.setText(self.folder_button.fontMetrics().elidedText(
                self._folder_name, Qt.ElideRight, max(20, folder_width - 30)))
        point.setX(max(8, min(point.x(), parent.width() - width - 8)))
        point.setY(max(0, min(point.y(), parent.height() - height)))
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
            elif (event.type() == QEvent.MouseButtonPress and isinstance(watched, QWidget)
                  and watched.window() is self.parentWidget() and watched is not self
                  and not self.isAncestorOf(watched)):
                self.close_editor()
        return super().eventFilter(watched, event)
