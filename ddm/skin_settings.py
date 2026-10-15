"""Appearance controls for custom backgrounds and plugin ownership."""
from pathlib import Path
from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from .skins import AssetImport


class SkinSettings(QWidget):
    changed = Signal(dict)

    def __init__(self, settings, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.path = settings.get('skin_background', '')
        self._sidebar = bool(settings.get('skin_sidebar', False))
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
        self.choose = QPushButton('导入图片或视频…')
        self.choose.setObjectName('IconButton')
        self.choose.clicked.connect(self._choose)
        self.clear = QPushButton('恢复默认背景')
        self.clear.setObjectName('IconButton')
        self.clear.clicked.connect(self.reset)
        row.addWidget(self.choose)
        row.addWidget(self.clear)
        layout.addLayout(row)
        self.follow = QPushButton('跟随美化包背景')
        self.follow.setObjectName('IconButton')
        self.follow.clicked.connect(self._follow_package)
        layout.addWidget(self.follow)
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
        self.sidebar_toggle = QCheckBox('背景覆盖左侧关注栏')
        self.sidebar_toggle.setChecked(bool(settings.get('skin_sidebar', False)))
        self.sidebar_toggle.toggled.connect(self._sidebar_changed)
        layout.addWidget(self.sidebar_toggle)
        note = QLabel('图片居中铺满；视频静音循环，最小化时暂停。文件复制到软件目录，立即生效并保存。'
                      '美化包沿用插件安装入口；新版美化包可继续单独修改，旧版背景插件仍保留接管行为。')
        note.setWordWrap(True)
        note.setObjectName('SettingsHint')
        layout.addWidget(note)
        self.parts_button = QPushButton('分区美化（背景、按钮与图标）')
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
                'skin_sidebar': self._sidebar, **self._overrides}

    def _locked(self):
        override = self.controller.override if self.controller else None
        return override is not None and override.get('version', 1) == 1

    def _follow_package(self):
        self._overrides = dict.fromkeys(self._overrides, False)
        self.changed.emit(self.values())

    def _edit_parts(self):
        PartSettings(self.controller.window, self).exec()

    def sync(self):
        override = self.controller.override if self.controller is not None else None
        locked = self._locked() or self.job is not None
        for widget in (self.choose, self.clear, self.mask_slider, self.sidebar_toggle):
            widget.setEnabled(not locked)
        self.follow.setVisible(override is not None and not self._locked())
        self.follow.setEnabled(not locked)
        self.sidebar_toggle.setVisible(bool(self.path or (override or {}).get('path')) and not self._locked()
            and not (self.controller is not None and self.controller.error))
        value = self.controller.layer.mask if self.controller else self._mask
        previous = self.mask_slider.blockSignals(True)
        self.mask_slider.setValue(value)
        self.mask_slider.blockSignals(previous)
        previous = self.sidebar_toggle.blockSignals(True)
        from . import theme
        self.sidebar_toggle.setChecked(theme._skin_sidebar if self.controller and not self._locked() else self._sidebar)
        self.sidebar_toggle.blockSignals(previous)
        self.mask_label.setText(str(value) + '%')
        if self.job is not None:
            self.status.setText('正在导入背景文件…')
        elif self.controller is not None and self.controller.error:
            self.status.setText(('皮肤插件背景错误：' if override else '背景错误：') + self.controller.error)
        elif override:
            self.status.setText('皮肤插件「' + override['name'] + '」' +
                ('接管，自定义选项已锁定。' if self._locked() else '已启用，个人修改优先；可恢复跟随美化包。'))
        else:
            filename = Path(self.path).name if self.path else '默认背景'
            prefix, separator, name = filename.partition('_')
            if separator and len(prefix) == 32 and all(c in '0123456789abcdef' for c in prefix):
                filename = name
            self.status.setText('当前：' + filename)

    def _mask_changed(self, value):
        if self._locked():
            self.sync()
            return
        self._mask = value
        self._overrides['skin_mask_override'] = True
        self.changed.emit(self.values())
        self.sync()

    def _sidebar_changed(self, value):
        if self._locked():
            return
        self._overrides['skin_sidebar_override'] = True
        self._sidebar = value
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
        self._sidebar = False
        self._overrides = dict.fromkeys(self._overrides, True)
        self.sidebar_toggle.setChecked(False)
        self.mask_slider.setValue(35)
        self.changed.emit(self.values())
        self.sync()

    def hideEvent(self, event):
        if self.job is not None:
            self.job.requestInterruption()
        super().hideEvent(event)


class PartSettings(QDialog):
    """Edit only explicit personal overrides; omitted fields inherit the skin pack."""
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        from .skin_parts import PARTS, NUMBERS
        self.owner = owner
        self.setWindowTitle('分区美化')
        self.resize(580, 520)
        layout = QVBoxLayout(self)
        note = QLabel('勾选需要单独修改的字段；未勾选项跟随美化包或软件默认。应用立即保存。'
                      '不修改空画面底、顶部浮标和关注卡片。图片居中拉伸铺满，图标保持比例。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.part = QComboBox()
        for key, label in PARTS.items():
            self.part.addItem(label, key)
        layout.addWidget(self.part)
        self.variant = QComboBox()
        for key, label in (('', '通用'), ('dark', '深色'), ('light', '浅色'),
                ('hover', '悬停'), ('pressed', '按下'), ('checked', '选中'),
                ('disabled', '禁用'), ('muted', '静音'), ('paused', '暂停')):
            self.variant.addItem(label, key)
        layout.addWidget(self.variant)
        form = QFormLayout()
        self.fields = {}
        self.asset_buttons = {}
        for key, label in (('background', '底色'), ('foreground', '文字颜色'),
                ('border_color', '边框颜色'), ('border_width', '边框宽度'),
                ('radius', '圆角'), ('image', '背景图片'), ('icon', '图标图片')):
            check = QCheckBox(label)
            row = QHBoxLayout()
            if key in NUMBERS:
                edit = QSpinBox()
                edit.setRange(*NUMBERS[key])
            else:
                edit = QLineEdit()
                edit.setPlaceholderText('#RRGGBB / #AARRGGBB' if key not in ('image', 'icon') else '导入本地图片')
                edit.setReadOnly(key in ('image', 'icon'))
            row.addWidget(edit)
            if key in ('image', 'icon'):
                button = QPushButton('选择图片')
                button.setObjectName('IconButton')
                button.setAutoDefault(False)
                button.clicked.connect(lambda _checked=False, field=key: self._choose(field))
                row.addWidget(button)
                self.asset_buttons[key] = button
            form.addRow(check, row)
            self.fields[key] = (check, edit)
        layout.addLayout(form)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.apply_button = QPushButton('应用本分区')
        self.apply_button.setObjectName('PrimaryButton')
        self.apply_button.clicked.connect(self.apply_part)
        self.reset_button = QPushButton('本分区跟随美化包／默认')
        self.reset_button.setObjectName('IconButton')
        self.reset_button.clicked.connect(self.reset_part)
        self.builtin_button = QPushButton('本分区使用软件默认')
        self.builtin_button.setObjectName('IconButton')
        self.builtin_button.setAutoDefault(False)
        self.builtin_button.clicked.connect(self.use_builtin)
        close = QPushButton('关闭')
        close.setObjectName('IconButton')
        close.clicked.connect(self.accept)
        defaults = QHBoxLayout()
        defaults.addWidget(self.reset_button)
        defaults.addWidget(self.builtin_button)
        layout.addLayout(defaults)
        for button in (self.apply_button, close):
            button.setAutoDefault(False)
            row.addWidget(button)
        layout.addLayout(row)
        self.part.currentIndexChanged.connect(self.load_part)
        self.variant.currentIndexChanged.connect(self.load_part)
        self.load_part()

    def load_part(self):
        values = self.owner.settings.get('skin_parts', {}).get(self.part.currentData(), {})
        variant = self.variant.currentData()
        if variant:
            values = values.get(variant, {})
        for key, (check, edit) in self.fields.items():
            check.setChecked(key in values)
            part = self.part.currentData()
            check.setEnabled(not (key == 'foreground' and part == 'sidebar') and
                not (key == 'icon' and part != 'folders' and not part.startswith('buttons')))
            if key in self.asset_buttons:
                self.asset_buttons[key].setEnabled(check.isEnabled())
            if isinstance(edit, QSpinBox):
                edit.setValue(values.get(key, 0))
            else:
                edit.setText(values.get(key, ''))
        self.status.setText('只编辑当前分区和当前状态；切换分区前请先应用。')

    def _choose(self, key):
        from .skins import import_asset, validate_asset, IMAGES
        source, _ = QFileDialog.getOpenFileName(self, '导入分区图片', '', '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not source:
            return
        try:
            path = validate_asset(source)
            if path.suffix.lower() not in IMAGES or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError('分区素材限 8MB 以内的静态图片')
            imported = Path(import_asset(source)).relative_to('utils/skins').as_posix()
            check, edit = self.fields[key]
            edit.setText(imported)
            check.setChecked(True)
        except (OSError, ValueError) as error:
            self.status.setText(str(error))

    def apply_part(self):
        values = deepcopy(self.owner.settings.get('skin_parts', {}))
        part, variant = self.part.currentData(), self.variant.currentData()
        target = {key: edit.value() if isinstance(edit, QSpinBox) else edit.text().strip()
                  for key, (check, edit) in self.fields.items() if check.isChecked() and check.isEnabled()}
        if variant:
            values.setdefault(part, {})[variant] = target
        else:
            previous = values.get(part, {})
            values[part] = {key: value for key, value in previous.items() if isinstance(value, dict) or key == 'builtin'} | target
        try:
            self.owner.set_skin_parts(values)
            self.status.setText('已应用并保存；未勾选字段继续跟随美化包／默认。')
        except (OSError, ValueError) as error:
            self.status.setText(str(error))

    def reset_part(self):
        values = deepcopy(self.owner.settings.get('skin_parts', {}))
        values.pop(self.part.currentData(), None)
        self.owner.set_skin_parts(values)
        self.load_part()

    def use_builtin(self):
        values = deepcopy(self.owner.settings.get('skin_parts', {}))
        values[self.part.currentData()] = {'builtin': True}
        self.owner.set_skin_parts(values)
        self.load_part()
        self.status.setText('本分区已使用软件默认；可继续在默认基础上修改。')
