"""Layout-only entries and their controls inside the layout picker."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QInputDialog, QKeySequenceEdit, QLabel,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QVBoxLayout, QWidget)

from . import layouts


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
            item.setToolTip(f'{name}\n右键可更新比例、设置快捷键或删除布局')
            self.list.addItem(item)
        self.hint.setText('点击应用布局，右键可更新比例或设置快捷键。' if self.list.count()
                          else '在画面墙拖动分隔线后，点「保存当前布局」。')

    def save(self):
        base = self.presets.host.wall.layout_id
        name, accepted = QInputDialog.getText(self.picker, '保存当前布局', '布局名称',
                                              text=layouts.BY_ID[base]['name'])
        if accepted:
            try:
                self.presets.save(name)
            except ValueError as error:
                self._error(error)
            else:
                self.picker.set_group(self.picker.custom_layouts_key)
        self.picker.show()

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
        update = menu.addAction('用当前比例更新')
        update.setEnabled(self.presets.items[key]['base'] == self.presets.host.wall.layout_id)
        update.triggered.connect(lambda: self._update(key))
        menu.addAction('设置快捷键', lambda: self._edit_shortcut(key))
        menu.addAction('删除布局', lambda: self._delete(key))
        menu.popup(self.list.viewport().mapToGlobal(point))

    def _update(self, key):
        try:
            self.presets.update(key)
        except ValueError as error:
            self._error(error)

    def _edit_shortcut(self, key):
        dialog = QDialog(self.picker)
        dialog.setWindowTitle('布局快捷键')
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel(self.presets.items[key]['name']))
        edit = QKeySequenceEdit(QKeySequence(self.presets.items[key]['shortcut']), dialog)
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
                    self.presets.bind(key, edit.keySequence().toString())
                except ValueError as error:
                    self._error(error)
                self.refresh()
        finally:
            dialog.deleteLater()
            self.picker.show()

    def _delete(self, key):
        if QMessageBox.question(self.picker, '删除布局', f'删除「{self.presets.items[key]["name"]}」？',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.presets.delete(key)
            self.refresh()
        self.picker.show()

    def _error(self, error):
        QMessageBox.warning(self.picker, '自定义布局', str(error))
