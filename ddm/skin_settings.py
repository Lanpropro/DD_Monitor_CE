"""Appearance controls for custom backgrounds and plugin ownership."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from .skins import AssetImport


class SkinSettings(QWidget):
    changed = Signal(dict)

    def __init__(self, settings, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.path = settings.get('skin_background', '')
        self.job = None
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
        self.choose = QPushButton('导入图片或视频…')
        self.choose.setObjectName('IconButton')
        self.choose.clicked.connect(self._choose)
        self.clear = QPushButton('恢复默认背景')
        self.clear.setObjectName('IconButton')
        self.clear.clicked.connect(self.reset)
        row.addWidget(self.choose)
        row.addWidget(self.clear)
        layout.addLayout(row)
        mask_row = QHBoxLayout()
        mask_row.addWidget(QLabel('背景遮罩'))
        self.mask_slider = QSlider(Qt.Horizontal)
        self.mask_slider.setRange(0, 80)
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
        self.sidebar_toggle = QCheckBox('背景覆盖左侧关注栏')
        self.sidebar_toggle.setChecked(bool(settings.get('skin_sidebar', False)))
        self.sidebar_toggle.toggled.connect(self._sidebar_changed)
        layout.addWidget(self.sidebar_toggle)
        note = QLabel('图片居中铺满；视频静音循环，最小化时暂停。文件复制到软件目录，立即生效并保存。'
                      '皮肤插件在插件页安装、启用并重启装载后，会覆盖并锁定自定义选项；停用后恢复原选择。')
        note.setWordWrap(True)
        note.setObjectName('SettingsHint')
        layout.addWidget(note)
        if controller is not None:
            self.changed.connect(controller.window.set_skin)
            controller.changed.connect(self.sync)
        self.sync()

    def values(self):
        return {'skin_background': self.path, 'skin_mask': self._mask,
                'skin_sidebar': self.sidebar_toggle.isChecked()}

    def sync(self):
        override = self.controller.override if self.controller is not None else None
        locked = override is not None or self.job is not None
        for widget in (self.choose, self.clear, self.mask_slider, self.sidebar_toggle):
            widget.setEnabled(not locked)
        self.sidebar_toggle.setVisible(bool(self.path) and override is None
            and not (self.controller is not None and self.controller.error))
        value = override['mask'] if override else self._mask
        previous = self.mask_slider.blockSignals(True)
        self.mask_slider.setValue(value)
        self.mask_slider.blockSignals(previous)
        self.mask_label.setText(str(value) + '%')
        if self.job is not None:
            self.status.setText('正在导入背景文件…')
        elif self.controller is not None and self.controller.error:
            self.status.setText(('皮肤插件背景错误：' if override else '背景错误：') + self.controller.error)
        elif override:
            self.status.setText('由皮肤插件「' + override['name'] + '」接管，自定义选项已锁定。')
        else:
            filename = Path(self.path).name if self.path else '默认背景'
            prefix, separator, name = filename.partition('_')
            if separator and len(prefix) == 32 and all(c in '0123456789abcdef' for c in prefix):
                filename = name
            self.status.setText('当前：' + filename)

    def _mask_changed(self, value):
        if self.controller is not None and self.controller.override is not None:
            self.sync()
            return
        self._mask = value
        self.sync()
        self.changed.emit(self.values())

    def _sidebar_changed(self, value):
        if self.controller is not None and self.controller.override is not None:
            return
        self.changed.emit(self.values())

    def _choose(self):
        source, _filter = QFileDialog.getOpenFileName(self, '导入背景皮肤', '',
            '图片或视频 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.webm *.mkv *.mov)')
        if source:
            self.import_file(source)

    def import_file(self, source):
        if self.job is not None or (self.controller is not None and self.controller.override is not None):
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
        self.sidebar_toggle.setChecked(False)
        self.mask_slider.setValue(35)
        self.changed.emit(self.values())
        self.sync()

    def hideEvent(self, event):
        if self.job is not None:
            self.job.requestInterruption()
        super().hideEvent(event)
