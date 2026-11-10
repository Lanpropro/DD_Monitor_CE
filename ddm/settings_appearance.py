"""Settings appearance; owned page implementations with legacy exports in dialogs."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
)
from . import theme
from .ui import page_header as _page_head
from .ui import SegmentedControl
from .settings_layout import SettingsColumns, SettingsSection


class AppearanceSettingsPage(QWidget):
    modeChanged = Signal(str)
    materialChanged = Signal(dict)

    def __init__(self, settings, parent=None, skin_controller=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addLayout(_page_head("外观", "设置主题、背景与界面分区样式。"))
        self.sections = SettingsColumns(content)
        colors = SettingsSection('主题')
        colors.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        colors.grid.addWidget(QLabel('界面主题'), 0, 0)
        self.mode_control = SegmentedControl(
            (("dark", "深色"), ("light", "浅色"), ("system", "跟随系统")))
        self.mode_control.setFixedWidth(260)
        self.buttons = self.mode_control.buttons
        self.group = self.mode_control.group
        self.mode_control.valueChanged.connect(self._choose)
        colors.grid.addWidget(self.mode_control, 0, 1, Qt.AlignRight)
        from .settings_theme_editor import SettingsThemeEditor
        self.theme_editor = SettingsThemeEditor(settings)
        self.theme_editor.changed.connect(self._preferences_changed)
        colors.grid.addWidget(self.theme_editor, 1, 0, 1, 2)
        self.sections.add_section('theme', colors)
        from .settings_material_editor import SettingsMaterialEditor
        self.material_editor = SettingsMaterialEditor(settings, content)
        self.material_editor.changed.connect(self._emit_material)
        self.material_editor.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        self.sections.add_section('material', self.material_editor)
        layout.addWidget(self.sections)
        from .skin_settings import PartSettings, SkinSettings
        self.parts_editor = None
        if skin_controller is not None:
            self.parts_editor = PartSettings(skin_controller.window, content, embedded=True)
            self.skin_settings = self.parts_editor.background_controls
            layout.addWidget(self.parts_editor)
        else:
            self.skin_settings = SkinSettings(settings, skin_controller, self)
            self.skin_settings.hide()
        self.skin_settings.changed.connect(self._emit_material)
        layout.addStretch(1)
        self._mode = theme.normalize_mode(settings.get("appearance_mode"))
        self.sync(self._mode)
        theme.signals().changed.connect(self.sync)

    def sync(self, mode):
        self._mode = mode
        previous = self.mode_control.blockSignals(True)
        self.mode_control.setValue(mode)
        self.mode_control.blockSignals(previous)

    def _choose(self, mode):
        self.sync(mode)
        self.modeChanged.emit(mode)

    def values(self):
        return {"appearance_mode": self._mode, **self.material_editor.values(),
                **self.theme_editor.values(), **self.skin_settings.values()}

    def _preferences_changed(self):
        if theme.configure_appearance(self.theme_editor.values()):
            theme.apply(theme.mode())
        self._emit_material()

    def _emit_material(self, *_args):
        values = {**self.material_editor.values(), **self.theme_editor.values(), **self.skin_settings.values()}
        if self.skin_settings.controller is not None:
            values['settings_backdrop_path'] = self.skin_settings.controller.layer.path
        else:
            from pathlib import Path
            from . import config
            values['settings_backdrop_path'] = str(Path(config.data_root()) / self.skin_settings.path) if self.skin_settings.path else ''
        self.material_editor.set_background(values['settings_backdrop_path'])
        self.materialChanged.emit(values)

    def showEvent(self, event):
        super().showEvent(event)
        self._emit_material()

    def reset(self):
        self.theme_editor.set_values({})
        self.material_editor.reset()
        self._preferences_changed()
        self._choose("dark")
