"""Room combinations live inside the existing layout picker."""
from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMenu, QMessageBox, QPushButton, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget)

from . import layouts, room_presets, theme


def thumbnail(snapshot):
    image = QPixmap(224, 138)
    image.fill(theme.qcolor(theme.BG))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    font = painter.font()
    font.setPointSize(9)
    painter.setFont(font)
    slots = {slot["cell"]: slot for slot in snapshot["slots"]}
    for cell, rect in room_presets.thumbnail_geometry(snapshot, QRect(5, 5, 214, 128)).items():
        slot = slots.get(cell)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.CONTENT))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(theme.qcolor(theme.TEXT1 if slot and slot["room_id"] else theme.TEXT3))
        name = (slot["label"] or slot["room_id"]) if slot and slot["room_id"] else ("空位" if slot else "弹幕")
        text = painter.fontMetrics().elidedText(name, Qt.ElideRight, max(0, rect.width() - 6))
        painter.drawText(rect.adjusted(3, 2, -3, -2), Qt.AlignCenter, text)
    painter.end()
    return image


class RoomPresetsPage(QWidget):
    def __init__(self, host, picker):
        super().__init__(picker)
        self.host, self.picker = host, picker
        self.setMinimumSize(460, 260)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.summary = QLabel("保存布局、主播位置和每格声音")
        self.summary.setObjectName("SectionLabel")
        bar.addWidget(self.summary, 1)
        self.save_button = QPushButton("保存当前组合…")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self.save_new)
        bar.addWidget(self.save_button)
        outer.addLayout(bar)
        self.name_form = QWidget()
        form = QVBoxLayout(self.name_form)
        form.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("组合名称"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("输入当前组合的名称")
        self.name_edit.setAccessibleName("组合名称")
        self.name_edit.textChanged.connect(self._name_changed)
        self.name_edit.returnPressed.connect(self._save_named)
        row.addWidget(self.name_edit, 1)
        self.confirm_save = QPushButton("保存")
        self.confirm_save.setObjectName("PrimaryButton")
        self.confirm_save.clicked.connect(self._save_named)
        row.addWidget(self.confirm_save)
        self.cancel_save = QPushButton("取消")
        self.cancel_save.setObjectName("IconButton")
        self.cancel_save.clicked.connect(self._cancel_name)
        row.addWidget(self.cancel_save)
        form.addLayout(row)
        self.name_hint = QLabel()
        self.name_hint.setWordWrap(True)
        form.addWidget(self.name_hint)
        self._overwrite_id = None
        self.name_form.hide()
        outer.addWidget(self.name_form)
        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.holder = QWidget()
        self.grid = QGridLayout(self.holder)
        self.grid.setContentsMargins(0, 4, 0, 0)
        self.grid.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.holder)
        outer.addWidget(scroll, 1)
        self.refresh()

    def refresh(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.cards = {}
        self.save_button.setEnabled(self.host.room_presets["version"] == 1)
        records = self.host.room_presets["items"]
        columns = max(1, (max(self.picker.width(), 460) - 32) // 236)
        if not records:
            label = QLabel("尚未保存直播间组合\n点击右上方“保存当前组合…”开始")
            label.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(label, 0, 0, 1, columns)
        try:
            current = self.host.room_preset_snapshot()
        except ValueError:
            current = None
        for index, record in enumerate(records):
            container = QWidget()
            container.setFixedWidth(224)
            box = QVBoxLayout(container)
            box.setContentsMargins(0, 0, 0, 0)
            actions = QHBoxLayout()
            name = str(record.get("name") or "无效组合")
            label = QLabel(name)
            label.setMaximumWidth(190)
            label.setWordWrap(True)
            actions.addWidget(label, 1)
            menu = QToolButton()
            menu.setText("···")
            menu.setObjectName("GhostButton")
            menu.setFixedSize(28, 24)
            menu.setToolTip("管理此组合")
            menu.clicked.connect(lambda _checked=False, item=record, button=menu: self.manage(item, button))
            actions.addWidget(menu)
            box.addLayout(actions)
            card = QToolButton()
            card.setObjectName("LayoutCard")
            card.setProperty("roomPresetId", record.get("id"))
            card.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            card.setCheckable(True)
            card.setFixedSize(224, 175)
            card.setCursor(Qt.PointingHandCursor)
            try:
                if self.host.room_presets["version"] != 1 or not isinstance(record.get("id"), str):
                    raise ValueError("组合数据版本或标识暂不支持")
                snapshot = room_presets.validate(record)
                card.setIcon(QIcon(thumbnail(snapshot)))
                card.setIconSize(QSize(208, 128))
                active = record.get("id") == self.host._active_room_preset_id
                equal = current is not None and room_presets.same(snapshot, current)
                suffix = " · 已调整" if active and not equal else (" · 当前" if active else "")
                label.setText(name + suffix)
                count = sum(bool(slot["room_id"]) for slot in snapshot["slots"])
                text = f"{layouts.BY_ID[snapshot['layout']['id']]['name']} · {count} 个直播间"
                card.setText(card.fontMetrics().elidedText(text, Qt.ElideRight, 210))
                card.setChecked(active and equal)
                lines = [name, "点击恢复保存时的布局、主播和声音"]
                for slot in snapshot["slots"]:
                    channel = {0: "默认", 3: "左", 4: "右"}.get(slot["audio_channel"], str(slot["audio_channel"]))
                    lines.append(f"格子 {slot['cell'] + 1}：{slot['label'] or '空位'} · "
                                 f"音量 {slot['volume']} · {'静音' if slot['muted'] else '有声'} · 声道 {channel}")
                card.setToolTip("\n".join(lines))
                card.clicked.connect(lambda _checked=False, key=record["id"]: self.apply(key))
            except (ValueError, TypeError, KeyError) as error:
                card.setText("无法恢复：" + str(error))
                card.setToolTip(str(error))
                card.setEnabled(False)
            box.addWidget(card)
            self.cards[record.get("id", str(index))] = card
            self.grid.addWidget(container, index // columns, index % columns, Qt.AlignTop | Qt.AlignHCenter)

    def _ask_name(self, title, text=""):
        name, accepted = QInputDialog.getText(self.picker, title, "组合名称", text=text)
        if not self.host._closing:
            self.picker.show()
        return name.strip(), accepted

    def _confirm(self, title, message):
        result = QMessageBox.question(self.picker, title, message,
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if not self.host._closing:
            self.picker.show()
        return result == QMessageBox.Yes

    def _error(self, error):
        QMessageBox.warning(self.picker, "直播间组合", str(error))
        if not self.host._closing:
            self.picker.show()

    def save_new(self):
        self.name_edit.clear()
        self._name_changed()
        self.name_form.show()
        self.save_button.hide()
        self.name_edit.setFocus()

    def _name_changed(self):
        self._overwrite_id = None
        self.confirm_save.setText("保存")
        self.name_hint.clear()

    def _cancel_name(self):
        self.name_form.hide()
        self.name_edit.clear()
        self.save_button.show()

    def _save_named(self):
        name = self.name_edit.text().strip()
        existing = next((item for item in self.host.room_presets["items"] if item.get("name") == name), None)
        if existing and self._overwrite_id != existing.get("id"):
            self._overwrite_id = existing["id"]
            self.name_hint.setText(f"已存在“{name}”，再次确认将用当前画面覆盖此组合。")
            self.confirm_save.setText("确认覆盖")
            return
        try:
            key = self.host.save_room_preset(name, existing.get("id") if existing else None)
            self._cancel_name()
            self.refresh()
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.cards[key]) if key in self.cards else None)
        except ValueError as error:
            self.name_hint.setText(str(error))
            self.name_edit.setFocus()

    def apply(self, preset_id):
        try:
            if self.host.apply_room_preset(preset_id):
                self.picker.close()
            else:
                self.picker.show()
        except ValueError as error:
            self._error(error)

    def manage(self, record, button):
        menu = QMenu(self)
        rename = menu.addAction("重命名")
        overwrite = menu.addAction("用当前画面更新此组合")
        delete = menu.addAction("删除组合")
        action = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        menu.deleteLater()
        try:
            if action is rename:
                name, accepted = self._ask_name("重命名组合", str(record.get("name") or ""))
                if accepted:
                    self.host.rename_room_preset(record.get("id"), name)
            elif action is overwrite:
                if self._confirm("更新组合", f"是否用当前画面更新“{record.get('name', '')}”？"):
                    self.host.save_room_preset(record.get("name", ""), record.get("id"))
            elif action is delete:
                if self._confirm("删除组合", f"是否删除“{record.get('name', '')}”？当前播放保持不变。"):
                    self.host.delete_room_preset(record.get("id"))
            self.refresh()
        except ValueError as error:
            self._error(error)
