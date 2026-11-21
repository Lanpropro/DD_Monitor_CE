"""Layout-only entries and their controls inside the layout picker."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QKeySequenceEdit, QLabel,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QVBoxLayout, QWidget)

from . import layouts


def edit_shortcut(picker, presets, key):
    record = presets.overrides.get(key, {}) if key in layouts.BY_ID else presets.items[key]
    name = layouts.BY_ID[key]['name'] if key in layouts.BY_ID else record['name']
    dialog = QDialog(picker)
    dialog.setWindowTitle('布局快捷键')
    box = QVBoxLayout(dialog)
    box.addWidget(QLabel(name))
    edit = QKeySequenceEdit(QKeySequence(record.get('shortcut', '')), dialog)
    edit.setAccessibleName('布局快捷键')
    edit.setMaximumSequenceLength(1)
    edit.setClearButtonEnabled(True)
    box.addWidget(edit)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=dialog)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    box.addWidget(buttons)
    try:
        if dialog.exec() == QDialog.Accepted:
            try:
                presets.bind(key, edit.keySequence().toString())
            except ValueError as error:
                QMessageBox.warning(picker, '布局快捷键', str(error))
    finally:
        dialog.deleteLater()
        picker.show()


class LayoutPresetsPage(QWidget):
    def __init__(self, picker, host):
        super().__init__(picker)
        self.picker = picker
        self.presets = host.layout_presets
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.hint = QLabel()
        self.hint.setObjectName('SettingsHint')
        self.hint.setWordWrap(True)
        box.addWidget(self.hint)
        self.list = QListWidget(self)
        self.list.setAccessibleName('自定义布局')
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemActivated.connect(self._apply)
        self.list.itemClicked.connect(self._apply)
        box.addWidget(self.list, 1)

    def refresh(self):
        self.list.clear()
        bindings = self.presets.shortcuts()
        for key, record in self.presets.items.items():
            name, base, shortcut = (record[field] for field in ('name', 'base', 'shortcut'))
            suffix = f' · {shortcut}' if shortcut and bindings.get(shortcut) == key else ''
            item = QListWidgetItem(f'{name} · {layouts.BY_ID[base]["name"]}{suffix}')
            item.setData(Qt.UserRole, key)
            item.setToolTip(f'{name}\n右键可设置快捷键或删除布局')
            self.list.addItem(item)
        self.hint.setText('之前保存的自定义布局，可点击应用。')

    def _apply(self, item):
        if self.picker.isVisible() and self.presets.apply(item.data(Qt.UserRole)):
            self.picker.close()

    def _menu(self, point):
        item = self.list.itemAt(point)
        if item is None:
            return
        key = item.data(Qt.UserRole)
        menu = QMenu(self.list)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.addAction('设置快捷键', lambda: self._edit_shortcut(key))
        menu.addAction('删除布局', lambda: self._delete(key))
        menu.popup(self.list.viewport().mapToGlobal(point))

    def _edit_shortcut(self, key):
        edit_shortcut(self.picker, self.presets, key)
        self.refresh()

    def _delete(self, key):
        if QMessageBox.question(self.picker, '删除布局', f'删除「{self.presets.items[key]["name"]}」？',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.presets.delete(key)
            self.refresh()
        self.picker.show()
