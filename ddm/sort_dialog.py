"""关注列表的批量排序窗口。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)


def move_selected(order: list[str], selected: set[str], operation: str,
                  pinned_count: int) -> list[str]:
    """在置顶区和普通区内移动选中项，保持多选项原有顺序。"""
    def move_group(group: list[str]) -> list[str]:
        if operation == "first":
            return [item for item in group if item in selected] + [
                item for item in group if item not in selected]
        if operation == "last":
            return [item for item in group if item not in selected] + [
                item for item in group if item in selected]
        group = list(group)
        if operation == "up":
            indices = range(1, len(group))
            offset = -1
        elif operation == "down":
            indices = range(len(group) - 2, -1, -1)
            offset = 1
        else:
            raise ValueError(f"Unknown move operation: {operation}")
        for index in indices:
            if group[index] in selected and group[index + offset] not in selected:
                group[index], group[index + offset] = group[index + offset], group[index]
        return group

    return move_group(order[:pinned_count]) + move_group(order[pinned_count:])


class SortManagerDialog(QDialog):
    """搜索并批量移动关注卡片；由调用方在确认后保存。"""

    def __init__(self, rooms: list[tuple[str, str]], pinned: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理关注排序")
        self.resize(430, 540)
        self._names = {room_id: name for room_id, name in rooms}
        self._pinned = set(pinned)
        self._pinned_count = sum(room_id in self._pinned for room_id, _ in rooms)

        layout = QVBoxLayout(self)
        hint = QLabel("按 Ctrl / Shift 多选卡片；置顶与普通卡片分别排序。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索主播 / 房间号")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setObjectName("FollowList")
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        layout.addWidget(self.list, 1)

        button_row = QHBoxLayout()
        self.move_buttons = {}
        for operation, label in (("first", "移到最前"), ("up", "上移一位"),
                                 ("down", "下移一位"), ("last", "移到最后")):
            button = QPushButton(label)
            button.setObjectName("GhostButton")
            button.clicked.connect(lambda _checked=False, op=operation: self._move(op))
            button_row.addWidget(button)
            self.move_buttons[operation] = button
        layout.addLayout(button_row)

        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Save).setText("保存排序")
        actions.button(QDialogButtonBox.Save).setObjectName("PrimaryButton")
        actions.button(QDialogButtonBox.Cancel).setText("取消")
        actions.button(QDialogButtonBox.Cancel).setObjectName("GhostButton")
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
        self._fill([room_id for room_id, _ in rooms])

    def order_ids(self) -> list[str]:
        return [self.list.item(index).data(Qt.UserRole)
                for index in range(self.list.count())]

    def _fill(self, order: list[str], selected: set[str] | None = None) -> None:
        self.list.clear()
        for room_id in order:
            prefix = "置顶 · " if room_id in self._pinned else ""
            item = QListWidgetItem(f"{prefix}{self._names[room_id]}  ·  {room_id}")
            item.setData(Qt.UserRole, room_id)
            self.list.addItem(item)
            item.setSelected(room_id in (selected or set()))
        self._apply_search(self.search.text())

    def _apply_search(self, text: str) -> None:
        needle = text.strip().casefold()
        for index in range(self.list.count()):
            item = self.list.item(index)
            room_id = item.data(Qt.UserRole)
            shown = not needle or needle in self._names[room_id].casefold() or needle in room_id.casefold()
            item.setHidden(not shown)
            if not shown:
                item.setSelected(False)

    def _move(self, operation: str) -> None:
        selected = {item.data(Qt.UserRole) for item in self.list.selectedItems()}
        if not selected:
            return
        order = move_selected(self.order_ids(), selected, operation, self._pinned_count)
        self._fill(order, selected)
