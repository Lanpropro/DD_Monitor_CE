"""Inline material controls; the dialog coordinates preview and persistence."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout

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
        self.value_labels = {}
        entries = (
            ('settings_glass_enabled', '启用毛玻璃效果', '关闭后使用不透明的主题底板。', None),
            ('settings_glass_blur', '背景图片模糊强度', '用于设置背景图片；Windows 系统玻璃的模糊强度跟随系统。', 40),
            ('settings_glass_opacity', '背景蒙版不透明度', '数值越低越通透，文字和控件保持清晰；自定义分区底色优先。', 100),
            ('settings_no_shadows', '禁用卡片与控件阴影', '减弱卡片边缘和选择控件的投影。', None),
        )
        for key, label, hint, maximum in entries:
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
            if maximum is None:
                control = ToggleSwitch(label)
                control.toggled.connect(self._changed)
                row.addWidget(control)
            else:
                control = QSlider(Qt.Horizontal)
                control.setRange(0, maximum)
                control.setAccessibleName(label)
                control.setFixedWidth(160)
                value = QLabel()
                value.setObjectName('SettingsText')
                value.setFixedWidth(36)
                value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.value_labels[key] = value
                control.valueChanged.connect(lambda number, value=value, key=key:
                                             value.setText(str(number) + ('%' if key.endswith('opacity') else '')))
                control.valueChanged.connect(self._changed)
                row.addWidget(control)
                row.addWidget(value)
                value.setText(str(normalize(settings)[key]) + ('%' if key.endswith('opacity') else ''))
            self.controls[key] = control
            layout.addLayout(row)
        self.set_values(settings)

    def set_values(self, settings):
        for key, value in normalize(settings).items():
            control = self.controls[key]
            previous = control.blockSignals(True)
            control.setChecked(value) if isinstance(control, ToggleSwitch) else control.setValue(value)
            control.blockSignals(previous)
            if key in self.value_labels:
                self.value_labels[key].setText(str(value) + ('%' if key.endswith('opacity') else ''))
        self._sync_enabled()

    def values(self):
        return {key: control.isChecked() if isinstance(control, ToggleSwitch) else control.value()
                for key, control in self.controls.items()}

    def _sync_enabled(self):
        enabled = self.controls['settings_glass_enabled'].isChecked()
        for key in ('settings_glass_blur', 'settings_glass_opacity'):
            self.controls[key].setEnabled(enabled)

    def _changed(self, *_args):
        self._sync_enabled()
        self.changed.emit()

    def reset(self):
        self.set_values(DEFAULTS)
        self.changed.emit()
