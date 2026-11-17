"""User-block list editing; identity validation and matching live in danmaku_filter."""
import os
from datetime import datetime, timezone
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from .danmaku_filter import manual_user_error, normalize_users
from .ui import SelectControl
from .widget_support import BRAND_ASSETS_DIR


PLATFORMS = {'bilibili': '哔哩哔哩', 'douyin': '抖音', 'douyu': '斗鱼',
             'huya': '虎牙', 'twitch': 'Twitch', 'youtube': 'YouTube'}


class BlockedUsersList(QListWidget):
    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()


class BlockedUsersDetails(QPlainTextEdit):
    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()


class BlockedUsersEditor(QWidget):
    changed = Signal()

    def __init__(self, users, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = BlockedUsersList()
        self.list.setProperty('settingsWheelLocal', True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setAccessibleName('已屏蔽用户')
        self.list.setObjectName('BlockedUsersList')
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMinimumWidth(0)
        self.list.setMinimumHeight(120)
        self.list.setMaximumHeight(190)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self.list)
        self.empty = QLabel('尚未屏蔽用户，可在弹幕左键菜单中屏蔽。')
        self.empty.setObjectName('SettingsHint')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.platform = SelectControl()
        self.platform.setAccessibleName('屏蔽用户所属平台')
        for key, label in PLATFORMS.items():
            self.platform.addItem(label, key)
        self.platform.setMinimumWidth(112)
        self.uid = QLineEdit()
        self.uid.setMinimumWidth(0)
        self.uid.setPlaceholderText('数字用户 ID')
        self.uid.setAccessibleName('待屏蔽的用户 ID')
        self.add = QPushButton('添加')
        self.add.setObjectName('IconButton')
        self.add.setAutoDefault(False)
        self.add.clicked.connect(self._add)
        self.uid.returnPressed.connect(self._add)
        row = QHBoxLayout()
        row.addWidget(self.platform)
        row.addWidget(self.uid, 1)
        row.addWidget(self.add)
        self.remove = QPushButton('移除所选')
        self.remove.setObjectName('IconButton')
        self.remove.setAutoDefault(False)
        self.remove.clicked.connect(self._remove)
        row.addWidget(self.remove)
        layout.addLayout(row)
        self.feedback = QLabel(self)
        self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setObjectName('SettingsHint')
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.hint = QLabel('填写平台真实用户 ID，不是昵称或房间号；只检查格式，未核验账户是否存在。\n'
                           'Ctrl / Shift 可多选；列表滚轮只滚动本列表。', self)
        self.hint.setObjectName('SettingsHint')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.details = BlockedUsersDetails(self)
        self.details.setReadOnly(True)
        self.details.setProperty('settingsWheelLocal', True)
        self.details.setFixedHeight(160)
        self.details.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.details.setObjectName('SettingsHint')
        layout.addWidget(self.details)
        self.details.hide()
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.platform.currentIndexChanged.connect(self._platform_changed)
        self.set_users(users)

    def users(self):
        return [dict(self.list.item(index).data(Qt.UserRole)) for index in range(self.list.count())]

    def set_users(self, users):
        self.list.clear()
        for rule in normalize_users(users):
            platform = rule['platform']
            if self.platform.findData(platform) < 0:
                self.platform.addItem(platform, platform)
            label = PLATFORMS.get(platform, platform)
            identity = 'ID: ' + rule['uid'] if rule['uid'] else '按昵称匹配，含同名用户'
            name = (rule['uname'] + ' · ') if rule['uname'] else ''
            text = f"{name}{identity}"
            item = QListWidgetItem(text, self.list)
            icon_path = os.path.join(BRAND_ASSETS_DIR, 'platforms',
                                     'huya.png' if platform == 'huya' else platform + '.ico')
            if not os.path.isfile(icon_path):
                icon_path = os.path.join(BRAND_ASSETS_DIR, 'platforms', 'generic.svg')
            item.setIcon(QIcon(icon_path))
            item.setData(Qt.UserRole + 1, platform)
            item.setToolTip(text)
            item.setData(Qt.UserRole, rule)
        # QListWidget defers its geometry pass after clear()/insert; force it so
        # the internal scrollbar is immediately available to the settings page.
        self.list.doItemsLayout()
        self.empty.setVisible(self.list.count() == 0)
        self.remove.setEnabled(False)
        self.details.hide()

    def _platform_changed(self):
        youtube = self.platform.currentData() == 'youtube'
        self.uid.setPlaceholderText('频道 ID（UC 开头）' if youtube else '数字用户 ID')
        self.feedback.clear()

    def _selection_changed(self):
        selected = self.list.selectedItems()
        self.remove.setEnabled(bool(selected))
        self.details.setVisible(bool(selected))
        if not selected:
            return
        if len(selected) > 1:
            self.details.setPlainText(f'已选择 {len(selected)} 位用户，可一起移除；单选可查看屏蔽详情。')
            return
        rule = selected[0].data(Qt.UserRole)
        timestamp = rule.get('blocked_at', '')
        try:
            when = datetime.fromisoformat(timestamp).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
        except ValueError:
            when = '旧记录未记录屏蔽时间'
        source = rule.get('source')
        origin = {'message': '弹幕菜单屏蔽', 'manual': '手动添加'}.get(source, '旧记录未记录来源')
        parts = ['平台：' + PLATFORMS.get(rule['platform'], rule['platform']),
                 '用户 ID：' + (rule['uid'] or '未提供，按昵称匹配'),
                 '昵称：' + (rule['uname'] or '未记录'), '屏蔽时间：' + when, '来源：' + origin]
        if source == 'message':
            parts.append('触发文本：' + (rule.get('source_text') or '该条消息未提供文本'))
            if rule.get('source_room_id'):
                parts.append('来源直播间：' + rule['source_room_id'])
        else:
            parts.append('触发文本：' + ('手动添加，没有触发消息' if source == 'manual' else '旧记录未记录触发消息'))
        self.details.setPlainText('\n'.join(parts))

    def _add(self):
        platform, uid = self.platform.currentData(), self.uid.text().strip()
        error = manual_user_error(platform, uid)
        if error:
            self.feedback.setText(error)
            return
        current = self.users()
        if any(rule['platform'] == platform and rule['uid'] == uid for rule in current):
            self.feedback.setText('该平台的此用户 ID 已在屏蔽列表中')
            return
        rule = dict(platform=platform, uid=uid, blocked_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    source='manual')
        self.set_users([*current, rule])
        self.uid.clear()
        self.feedback.setText('已添加屏蔽规则；未核验该用户是否存在')
        self.changed.emit()

    def _remove(self):
        selected = self.list.selectedItems()
        if not selected:
            return
        for item in selected:
            self.list.takeItem(self.list.row(item))
        self.empty.setVisible(self.list.count() == 0)
        self.feedback.setText(f'已移除 {len(selected)} 位屏蔽用户')
        self.changed.emit()
