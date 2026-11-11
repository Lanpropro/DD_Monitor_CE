"""User-block list editing; identity validation and matching live in danmaku_filter."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from .danmaku_filter import normalize_users
from .ui import SelectControl


PLATFORMS = {'bilibili': '哔哩哔哩', 'douyin': '抖音', 'douyu': '斗鱼',
             'huya': '虎牙', 'twitch': 'Twitch', 'youtube': 'YouTube'}


class BlockedUsersEditor(QWidget):
    changed = Signal()

    def __init__(self, users, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setAccessibleName('已屏蔽用户')
        self.list.setObjectName('BlockedUsersList')
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMinimumWidth(0)
        self.list.setFixedHeight(150)
        layout.addWidget(self.list)
        self.empty = QLabel('尚未屏蔽用户，可在弹幕左键菜单中屏蔽。')
        self.empty.setObjectName('SettingsHint')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.platform = SelectControl()
        self.platform.setAccessibleName('屏蔽用户所属平台')
        for key, label in PLATFORMS.items():
            self.platform.addItem(label, key)
        self.platform.setFixedWidth(112)
        self.uid = QLineEdit()
        self.uid.setMinimumWidth(0)
        self.uid.setPlaceholderText('用户 ID')
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
        layout.addLayout(row)
        self.remove = QPushButton('移除所选')
        self.remove.setObjectName('IconButton')
        self.remove.setAutoDefault(False)
        self.remove.clicked.connect(self._remove)
        layout.addWidget(self.remove, 0, Qt.AlignRight)
        self.list.itemSelectionChanged.connect(lambda: self.remove.setEnabled(bool(self.list.selectedItems())))
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
            text = f"{label} · {name}{identity}"
            item = QListWidgetItem(text, self.list)
            item.setToolTip(text)
            item.setData(Qt.UserRole, rule)
        self.empty.setVisible(self.list.count() == 0)
        self.remove.setEnabled(False)

    def _add(self):
        values = normalize_users([*self.users(), {'platform': self.platform.currentData(), 'uid': self.uid.text()}])
        if values != self.users():
            self.set_users(values)
            self.uid.clear()
            self.changed.emit()

    def _remove(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.empty.setVisible(self.list.count() == 0)
        self.changed.emit()
