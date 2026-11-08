"""Appearance controls for custom backgrounds and plugin ownership."""
from pathlib import Path
from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTabBar, QVBoxLayout, QWidget)

from .settings_layout import SettingsColumns, SettingsSection
from .skins import AssetImport
from .folder_icons import IconDropArea


from .skin_controls import (_background_name, SkinAssetDropArea)


class SkinSettings(QWidget):
    changed = Signal(dict)

    def __init__(self, settings, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.path = settings.get('skin_background', '')
        self._video_enabled = bool(settings.get('skin_video_enabled', True))
        self.job = None
        self._overrides = {key: bool(settings.get(key, False)) for key in
                           ('skin_background_override', 'skin_mask_override', 'skin_sidebar_override')}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel('背景皮肤')
        title.setObjectName('SettingsTitle')
        layout.addWidget(title)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName('SettingsHint')
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.choose = SkinAssetDropArea(video=True)
        self.choose.clicked.connect(self._choose)
        self.choose.fileDropped.connect(self.import_file)
        self.clear = QPushButton('恢复默认背景')
        self.clear.setObjectName('IconButton')
        self.clear.clicked.connect(self.reset)
        layout.addWidget(self.choose)
        row.addWidget(self.clear)
        layout.addLayout(row)
        mask_row = QHBoxLayout()
        mask_row.addWidget(QLabel('背景遮罩'))
        self.mask_slider = QSlider(Qt.Horizontal)
        self.mask_slider.setRange(0, 100)
        try:
            value = int(settings.get('skin_mask', 35))
        except (TypeError, ValueError):
            value = 35
        self.mask_slider.setValue(value)
        self._mask = self.mask_slider.value()
        self.mask_label = QLabel()
        mask_row.addWidget(self.mask_slider, 1)
        mask_row.addWidget(self.mask_label)
        self.mask_slider.valueChanged.connect(self._mask_changed)
        layout.addLayout(mask_row)
        self.video_toggle = QCheckBox('启用视频')
        self.video_toggle.setChecked(self._video_enabled)
        self.video_toggle.toggled.connect(self._video_changed)
        layout.addWidget(self.video_toggle)
        note = QLabel('图片居中铺满；视频静音循环，最小化时暂停。关闭“启用视频”后使用视频首帧作为静态背景。')
        note.setWordWrap(True)
        note.setObjectName('SettingsHint')
        layout.addWidget(note)
        self.parts_button = QPushButton('分区美化')
        self.parts_button.setObjectName('IconButton')
        self.parts_button.setEnabled(controller is not None)
        self.parts_button.clicked.connect(self._edit_parts)
        layout.addWidget(self.parts_button)
        if controller is not None:
            self.changed.connect(controller.window.set_skin)
            controller.changed.connect(self.sync)
        self.sync()

    def values(self):
        return {'skin_background': self.path, 'skin_mask': self._mask,
                'skin_sidebar': True, 'skin_video_enabled': self._video_enabled, **self._overrides}

    def _locked(self):
        override = self.controller.override if self.controller else None
        return override is not None and override.get('version', 1) == 1

    def _edit_parts(self):
        dialog = PartSettings(self.controller.window, self)
        dialog.exec()
        dialog.deleteLater()

    def sync(self):
        if self.controller is not None:
            settings = self.controller.window.settings
            self.path = settings.get('skin_background', '')
            self._mask = settings.get('skin_mask', 35)
            self._video_enabled = bool(settings.get('skin_video_enabled', True))
            self._overrides = {key: bool(settings.get(key, False)) for key in self._overrides}
        override = self.controller.override if self.controller is not None else None
        locked = self._locked() or self.job is not None
        for widget in (self.choose, self.clear, self.mask_slider, self.video_toggle):
            widget.setEnabled(not locked)
        from .skins import VIDEOS
        path = self.controller.layer.path if self.controller else self.path
        self.video_toggle.setVisible(Path(path).suffix.lower() in VIDEOS)
        value = self.controller.layer.mask if self.controller else self._mask
        previous = self.mask_slider.blockSignals(True)
        self.mask_slider.setValue(value)
        self.mask_slider.blockSignals(previous)
        previous = self.video_toggle.blockSignals(True)
        self.video_toggle.setChecked(self._video_enabled)
        self.video_toggle.blockSignals(previous)
        self.mask_label.setText(str(value) + '%')
        if self.job is not None:
            self.status.setText('正在导入背景文件…')
        elif self.controller is not None and self.controller.error:
            self.status.setText(('皮肤插件背景错误：' if override else '背景错误：') + self.controller.error)
        elif override and self._locked():
            self.status.setText('皮肤插件「' + override['name'] + '」接管，自定义选项已锁定。')
        else:
            self.status.setText('当前：' + _background_name(path))

    def _mask_changed(self, value):
        if self._locked():
            self.sync()
            return
        self._mask = value
        self._overrides['skin_mask_override'] = True
        self.changed.emit(self.values())
        self.sync()

    def _video_changed(self, value):
        if self._locked():
            return
        self._video_enabled = value
        self.changed.emit(self.values())

    def _choose(self):
        source, _filter = QFileDialog.getOpenFileName(self, '导入背景皮肤', '',
            '图片或视频 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.webm *.mkv *.mov)')
        if source:
            self.import_file(source)

    def import_file(self, source):
        if self.job is not None or self._locked():
            return
        # The application owns the worker so closing settings cannot destroy a
        # running copy thread. A completed copy does not change a closed page.
        parent = self.controller.window if self.controller is not None else self.window()
        job = AssetImport(source, parent)
        self.job = job
        job.imported.connect(self._imported)
        job.failed.connect(self._failed)
        job.finished.connect(self._finished)
        self.sync()
        job.start()

    def _imported(self, path):
        if self.job is None or self.job.isInterruptionRequested():
            return
        self.path = path
        self._video_enabled = True
        self._overrides['skin_background_override'] = True
        self.changed.emit(self.values())

    def _failed(self, message):
        self._import_error = message

    def _finished(self):
        job, self.job = self.job, None
        self.sync()
        error = getattr(self, '_import_error', '')
        if error:
            self.status.setText(error)
            self._import_error = ''
        job.deleteLater()

    def reset(self):
        if not self.clear.isEnabled():
            return
        self.path = ''
        self._video_enabled = True
        self._overrides = dict.fromkeys(self._overrides, True)
        self.mask_slider.setValue(35)
        self.changed.emit(self.values())
        self.sync()

    def hideEvent(self, event):
        if self.job is not None:
            self.job.requestInterruption()
        super().hideEvent(event)


from .skin_part_settings import (PartSettings)
