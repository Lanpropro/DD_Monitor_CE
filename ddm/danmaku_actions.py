"""Shared floating actions for one comment and its room-bound input control."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QPushButton, QToolTip

from . import theme


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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        self.copy_button = self._button(self.copy_action, self)
        self.repeat_button = self._button(self.repeat_action, self)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.repeat_button)
        layout.addSpacing(6)
        self.block_button = self._button(self.block_action, self)
        self.block_user_button = self._button(self.block_user_action, self)
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
        background = f'rgba({color.red()}, {color.green()}, {color.blue()}, 230)'
        self.setStyleSheet(f'''
            #CommentToolbar {{background: transparent; border: none;}}
            #CommentToolbar QWidget {{background: transparent;}}
            #CommentToolbar QPushButton {{background: {background}; color: {theme.TEXT1};
                border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px; padding: 0 10px;}}
            #CommentToolbar QPushButton:hover {{background: {theme.ACCENT_SOFT}; color: {theme.ACCENT};
                border-color: {theme.ACCENT};}}
            #CommentToolbar QPushButton:disabled {{color: {theme.TEXT4};}}
        ''')

    def _place(self, position):
        self.adjustSize()
        screen = QApplication.screenAt(position) or self.screen()
        area = screen.availableGeometry()
        self.move(max(area.left(), min(position.x(), area.right() - self.width() + 1)),
                  max(area.top(), min(position.y(), area.bottom() - self.height() + 1)))

    def popup(self, position):
        self._place(position)
        self.show()

    def exec(self, position):
        self._place(position)
        super().exec()
        return self.chosen


def show_comment_menu(parent, message, controls, position, finished=None):
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
    from .danmaku_filter import user_identity
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
                if blocker.block(event, room_id, user=menu.chosen is block_user):
                    QToolTip.showText(position, '已屏蔽，可在设置 → 弹幕中管理', parent)
        finally:
            if finished is not None:
                finished()
            menu.deleteLater()
    menu.finished.connect(complete)
    menu.popup(position)
    return menu
