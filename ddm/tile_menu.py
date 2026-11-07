"""Built-in playback context menu choices, ordering and settings editor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from .ui import ActionButton


MENU_ITEMS = (
    ('volume', '音量'), ('quality', '画质'), ('codec', '当前窗口编解码设置'),
    ('stream_info', '直播流信息'), ('audio_channel', '声道'), ('mute', '静音／取消静音'),
    ('danmaku_settings', '弹幕观看设置'), ('reload', '刷新重连'), ('fullscreen', '全屏查看'),
    ('plugins', '插件扩展功能'), ('switch_danmaku', '切换为弹幕'), ('close', '关闭这一路'),
)


def menu_choices(value):
    choices = []
    known = dict(MENU_ITEMS)
    seen = set()
    for entry in value if isinstance(value, list) else ():
        if isinstance(entry, dict) and entry.get('id') in known and entry['id'] not in seen:
            seen.add(entry['id'])
            choices.append({'id': entry['id'], 'enabled': bool(entry.get('enabled', True))})
    choices.extend({'id': key, 'enabled': True} for key, _label in MENU_ITEMS if key not in seen)
    return choices


def arrange_menu(menu, choices):
    actions = [action for action in menu.actions() if not action.isSeparator()]
    for action in menu.actions():
        menu.removeAction(action)
    groups = {'volume': 0, 'quality': 1, 'codec': 1, 'stream_info': 1, 'audio_channel': 1,
              'mute': 2, 'danmaku_settings': 2, 'reload': 2, 'fullscreen': 2,
              'plugins': 3, 'switch_danmaku': 4, 'close': 4}
    previous = None
    for entry in menu_choices(choices):
        if not entry['enabled']:
            continue
        selected = [action for action in actions if action.data() == entry['id']]
        if selected:
            group = groups[entry['id']]
            if previous is not None and group != previous:
                menu.addSeparator()
            for action in selected:
                menu.addAction(action)
            previous = group


class TileMenuEditor(QWidget):
    def __init__(self, choices=None, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setAccessibleName('画面右键菜单功能与顺序')
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setMinimumHeight(270)
        box.addWidget(self.list)
        row = QHBoxLayout()
        for label, direction in (('上移', -1), ('下移', 1)):
            button = ActionButton(label)
            button.clicked.connect(lambda _checked=False, delta=direction: self.move_item(delta))
            row.addWidget(button)
        reset = ActionButton('恢复默认菜单')
        reset.clicked.connect(lambda: self.set_choices(None))
        row.addWidget(reset)
        row.addStretch(1)
        box.addLayout(row)
        self.set_choices(choices)

    def set_choices(self, choices):
        self.list.clear()
        labels = dict(MENU_ITEMS)
        for entry in menu_choices(choices):
            item = QListWidgetItem(labels[entry['id']], self.list)
            item.setData(Qt.UserRole, entry['id'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if entry['enabled'] else Qt.Unchecked)
        self.list.setCurrentRow(0)

    def move_item(self, delta):
        index = self.list.currentRow()
        target = index + delta
        if 0 <= index < self.list.count() and 0 <= target < self.list.count():
            self.list.insertItem(target, self.list.takeItem(index))
            self.list.setCurrentRow(target)

    def values(self):
        return [{'id': self.list.item(index).data(Qt.UserRole),
                 'enabled': self.list.item(index).checkState() == Qt.Checked}
                for index in range(self.list.count())]
