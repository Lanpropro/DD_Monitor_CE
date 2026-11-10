"""Inline material controls; the dialog coordinates preview and persistence."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from .settings_material import DEFAULTS, normalize
from .ui import SettingsSurface, ToggleSwitch


class SettingsMaterialEditor(SettingsSurface):
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(18)
        title = QLabel('视觉效果')
        title.setObjectName('SettingsTitle')
        layout.addWidget(title)
        self.controls = {}
        entries = (
            ('settings_no_shadows', '禁用卡片与控件阴影', '关闭卡片外投影与选择控件的阴影。'),
        )
        for key, label, hint in entries:
            row = QHBoxLayout()
            text = QVBoxLayout()
            text.setSpacing(4)
            name = QLabel(label)
            name.setObjectName('SettingsText')
            description = QLabel(hint)
            description.setObjectName('SettingsHint')
            description.setWordWrap(True)
            text.addWidget(name)
            text.addWidget(description)
            row.addLayout(text, 1)
            control = ToggleSwitch(label)
            control.toggled.connect(self._changed)
            row.addWidget(control)
            self.controls[key] = control
            layout.addLayout(row)
        self.set_values(settings)

    def set_values(self, settings):
        self._values = normalize(settings)
        for key, control in self.controls.items():
            previous = control.blockSignals(True)
            control.setChecked(self._values[key])
            control.blockSignals(previous)

    def values(self):
        return {**self._values, **{key: control.isChecked() for key, control in self.controls.items()}}

    def _changed(self, *_args):
        self.changed.emit()

    def reset(self):
        self.set_values(DEFAULTS)
        self.changed.emit()
