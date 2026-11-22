"""Shared floating actions for one comment and its room-bound input control."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QToolTip

from . import theme
from .danmaku_filter import event_blocked, user_identity
from .ui import ActionButton


def comment_hover_color():
    color = theme.qcolor(theme.ACCENT)
    color.setAlpha(24)
    return color


class CommentToolbar(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName('CommentToolbar')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.copy_action = QAction('复制', self)
        self.repeat_action = QAction('+1', self)
        self.block_action = QAction('屏蔽弹幕', self)
        self.block_user_action = QAction('屏蔽用户', self)
        self.command_actions = [self.copy_action, self.repeat_action, self.block_action, self.block_user_action]
        self.chosen = None
        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        surface = QFrame(self, objectName='CommentToolbarSurface')
        shell.addWidget(surface)
        layout = QHBoxLayout(surface)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        self.copy_button = self._button(self.copy_action, surface)
        self.repeat_button = self._button(self.repeat_action, surface)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.repeat_button)
        separator = QFrame(surface, objectName='CommentToolbarSeparator')
        separator.setFixedSize(1, 18)
        layout.addWidget(separator, 0, Qt.AlignVCenter)
        self.block_button = self._button(self.block_action, surface)
        self.block_user_button = self._button(self.block_user_action, surface)
        layout.addWidget(self.block_button)
        layout.addWidget(self.block_user_button)
        self.refresh_theme()

    def _button(self, action, parent):
        button = QPushButton(action.text(), parent)
        button.setFixedHeight(32)
        button.setMinimumWidth(52)
        button.setAutoDefault(False)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(action.trigger)
        action.changed.connect(lambda: button.setEnabled(action.isEnabled()))
        action.triggered.connect(lambda: self._choose(action))
        return button

    def _choose(self, action):
        self.chosen = action
        self.accept()

    def mousePressEvent(self, event):
        # Dismissing the popup must not replay the click onto another comment.
        self.setAttribute(Qt.WA_NoMouseReplay)
        super().mousePressEvent(event)

    def refresh_theme(self):
        color = theme.qcolor(theme.ELEVATED)
        background = f'rgba({color.red()}, {color.green()}, {color.blue()}, 250)'
        self.setStyleSheet(f'''
            #CommentToolbar {{background: transparent; border: none;}}
            #CommentToolbarSurface {{background: {background}; border: 1px solid {theme.BORDER_STRONG};
                border-radius: 12px;}}
            #CommentToolbarSeparator {{background: {theme.BORDER_STRONG}; border: none;}}
            #CommentToolbar QPushButton {{background: transparent; color: {theme.TEXT1};
                border: none; border-radius: 8px; padding: 0 10px;}}
            #CommentToolbar QPushButton:hover:!disabled {{background: {theme.CONTENT_HOVER};}}
            #CommentToolbar QPushButton:pressed {{background: {theme.BORDER};}}
            #CommentToolbar QPushButton:disabled {{color: {theme.TEXT4};}}
        ''')

    def _place(self, position):
        _place_at(self, position)

    def popup(self, position):
        self._place(position)
        self.show()

    def exec(self, position):
        self._place(position)
        super().exec()
        return self.chosen


def _place_at(widget, position):
    widget.adjustSize()
    screen = QApplication.screenAt(position) or widget.screen()
    area = screen.availableGeometry()
    widget.move(max(area.left(), min(position.x(), area.right() - widget.width() + 1)),
                max(area.top(), min(position.y(), area.bottom() - widget.height() + 1)))


class CommentUndoNotice(QFrame):
    def __init__(self, parent, position, label, undo):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setObjectName('CommentUndoNotice')
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        surface = QFrame(self, objectName='CommentToolbarSurface')
        surface.setStyleSheet(f'#CommentToolbarSurface {{background: {theme.ELEVATED}; '
                              f'border: 1px solid {theme.BORDER_STRONG}; border-radius: 12px;}}')
        layout.addWidget(surface)
        row = QHBoxLayout(surface)
        row.setContentsMargins(12, 5, 5, 5)
        self.message = QLabel('已' + label, surface)
        row.addWidget(self.message)
        self.undo = ActionButton('撤回', surface)
        self.undo.setAccessibleName('撤回' + label)
        self.undo.clicked.connect(self._undo)
        row.addWidget(self.undo)
        self._reverse = undo
        self._label = label
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self.close)
        _place_at(self, position)
        self.show()
        self.timer.start(10000)

    def _undo(self):
        self.message.setText(('已撤回' if self._reverse() else '无法撤回') + self._label)
        self.undo.hide()
        self.adjustSize()
        self.timer.start(2500)


def show_comment_menu(parent, message, controls, position, finished=None, restore=None):
    event = dict(message) if isinstance(message, dict) else {'text': str(message)}
    text = str(event.get('text') or '')
    room_id = str(event.get('room_id') or (controls.room_id() if controls is not None else
                                         getattr(parent, '_linked_room_id', '')))
    blocker = getattr(parent, '_danmaku_blocking', None)
    menu = CommentToolbar(parent)
    copy, repeat, block, block_user = menu.command_actions
    copy.setEnabled(bool(text))
    repeat.setToolTip('复制并发送到当前直播间')
    menu.repeat_button.setToolTip(repeat.toolTip())
    repeat.setEnabled(bool(controls is not None and (text or event.get('dm_type') == 1)
                           and controls.can_repeat(event)))
    identity = user_identity(event, room_id)
    block.setEnabled(blocker is not None and bool(text.strip()))
    block_user.setEnabled(blocker is not None and identity is not None)
    menu.block_button.setToolTip('将这条弹幕的正文加入全局屏蔽词，可在设置 → 弹幕中管理')
    menu.block_user_button.setToolTip('屏蔽该用户在此平台所有房间的消息，可在设置 → 弹幕中管理' if identity and identity['uid'] else
                                    '此消息未提供用户 ID，将按昵称屏蔽（同名用户也会被屏蔽）')
    def complete(_result):
        try:
            if text and (menu.chosen is copy or menu.chosen is repeat):
                QApplication.clipboard().setText(text)
            if menu.chosen is repeat and not controls.repeat_message(event, room_id):
                QToolTip.showText(position, '当前房间的发送入口不可用，请检查登录状态或发送控件。', parent)
            if menu.chosen is block or menu.chosen is block_user:
                reverse = blocker.block(event, room_id, user=menu.chosen is block_user)
                if reverse:
                    hidden = event_blocked(event, room_id, blocker.host.settings)
                    def undo():
                        removed = reverse()
                        if (removed and hidden and restore is not None
                                and not event_blocked(event, room_id, blocker.host.settings)):
                            restore()
                        return removed
                    owner = parent.window()
                    for previous in owner.findChildren(CommentUndoNotice):
                        if previous.isVisible():
                            previous.close()
                    CommentUndoNotice(parent, position, menu.chosen.text(), undo)
        finally:
            if finished is not None:
                finished()
            menu.deleteLater()
    menu.finished.connect(complete)
    menu.popup(position)
    return menu
