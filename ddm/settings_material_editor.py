"""Inline material controls; the dialog coordinates preview and persistence."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .settings_material import DEFAULTS, normalize
from .ui import SettingsSlider, SettingsSurface, SettingsValueLabel, SelectControl, ToggleSwitch


class SettingsMaterialEditor(SettingsSurface):
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(18)
        title = QLabel('视觉效果')
        title.setObjectName('SettingsSectionTitle')
        layout.addWidget(title)
        self.controls = {}
        self.glass_parameters = QWidget(self)
        parameters = QVBoxLayout(self.glass_parameters)
        parameters.setContentsMargins(18, 0, 0, 4)
        parameters.setSpacing(10)
        heading = QLabel('毛玻璃参数')
        heading.setObjectName('SettingsHint')
        parameters.addWidget(heading)
        self.background_status = QLabel()
        self.background_status.setObjectName('SettingsHint')
        self.background_status.setWordWrap(True)
        parameters.addWidget(self.background_status)
        entries = (
            ('settings_glass_enabled', '启用毛玻璃效果', '实时模糊设置窗口背后的内容；底色不透明度仅在开启时生效。'),
            ('settings_segment_motion', '滑动分段指示器', '鼠标切换时滑动选中底片，系统关闭动画时直接切换。'),
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
            if key == 'settings_glass_enabled':
                layout.addWidget(self.glass_parameters)
        self.sliders = {}
        for key, label, minimum, maximum in (
                ('settings_glass_opacity', '底色不透明度', 0, 100),):
            row = QHBoxLayout()
            row.addWidget(QLabel(label), 1)
            slider = SettingsSlider()
            slider.setRange(minimum, maximum)
            slider.setAccessibleName(label)
            value = SettingsValueLabel()
            slider.valueChanged.connect(value.setNum)
            slider.valueChanged.connect(self._changed)
            row.addWidget(slider)
            row.addWidget(value)
            parameters.addLayout(row)
            self.sliders[key] = (slider, value)
        row = QHBoxLayout()
        row.addWidget(QLabel('设置卡片布局'), 1)
        self.card_layout = SelectControl()
        self.card_layout.setFixedWidth(180)
        self.card_layout.addItem('自适应双列', 'auto')
        self.card_layout.addItem('纵向单列', 'vertical')
        self.card_layout.currentIndexChanged.connect(self._changed)
        row.addWidget(self.card_layout, 0, Qt.AlignRight)
        layout.addLayout(row)
        self.set_values(settings)

    def set_values(self, settings):
        self._values = normalize(settings)
        for key, control in self.controls.items():
            previous = control.blockSignals(True)
            control.setChecked(self._values[key])
            control.blockSignals(previous)
        for key, (slider, label) in self.sliders.items():
            previous = slider.blockSignals(True)
            slider.setValue(self._values[key])
            slider.blockSignals(previous)
            label.setNum(slider.value())
        previous = self.card_layout.blockSignals(True)
        self.card_layout.setCurrentIndex(self.card_layout.findData(self._values['settings_card_layout']))
        self.card_layout.blockSignals(previous)
        self._sync_enabled()

    def values(self):
        return {**self._values, **{key: control.isChecked() for key, control in self.controls.items()},
                **{key: slider.value() for key, (slider, _label) in self.sliders.items()},
                'settings_card_layout': self.card_layout.currentData()}

    def _changed(self, *_args):
        self._sync_enabled()
        self.changed.emit()

    def _sync_enabled(self):
        for slider, label in self.sliders.values():
            slider.setEnabled(self.controls['settings_glass_enabled'].isChecked())
            label.setEnabled(slider.isEnabled())
        from .settings_backdrop import blur_available
        self.background_status.setText('显示窗口背后的实时内容；模糊程度由 Windows 控制，仅影响设置窗口。'
            if blur_available() else '当前平台不支持系统毛玻璃，将使用纯色底板。')

    def reset(self):
        self.set_values(DEFAULTS)
        self.changed.emit()
