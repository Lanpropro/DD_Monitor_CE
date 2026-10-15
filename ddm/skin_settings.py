"""Appearance controls for custom backgrounds and plugin ownership."""
from pathlib import Path
from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QTabBar, QVBoxLayout, QWidget)

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
        self.parts_button = QPushButton('分区美化（界面预览）')
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
        dialog = PartSettings(self.controller.window, self)
        dialog.exec()
        dialog.deleteLater()

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
        from .skin_preview import SkinPreview
        self.owner = owner
        self._drafts = {}
        self._loading = False
        self.setWindowTitle('分区美化（界面预览）')
        self.resize(1100, 700)
        outer = QHBoxLayout(self)
        preview_column = QVBoxLayout()
        self.scenes = QTabBar()
        self.scenes.setStyleSheet('QTabBar::tab {background: palette(base); color: palette(text);'
            'padding: 8px 12px; margin-right: 4px; border: 1px solid palette(mid); border-radius: 8px;}'
            'QTabBar::tab:selected {background: palette(light); border-color: palette(highlight);}')
        for text in ('主界面', '设置页面', '菜单与提示'):
            self.scenes.addTab(text)
        preview_column.addWidget(self.scenes)
        self.preview = SkinPreview(self)
        preview_column.addWidget(self.preview, 1)
        legend = QLabel('点击亮框选择区域；实线表示当前选择。\n空画面、顶部浮标和关注卡片不提供修改入口。')
        legend.setWordWrap(True)
        preview_column.addWidget(legend)
        outer.addLayout(preview_column, 3)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumWidth(350)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 2)
        layout = QVBoxLayout(content)
        self.selection_title = QLabel()
        self.selection_title.setObjectName('SettingsTitle')
        layout.addWidget(self.selection_title)
        note = QLabel('勾选要修改的字段，缩略图会同步预览。切换区域会保留修改，点击“应用并保存”后生效。'
                      '未勾选项跟随美化包或软件默认。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.part = QComboBox(self)
        self.part.addItem('软件整体背景', 'background')
        for key, label in PARTS.items():
            self.part.addItem(label, key)
        self.part.hide()
        self.part.setCurrentIndex(self.part.findData('sidebar'))
        self.background_controls = SkinSettings(owner.settings, owner.skin_controller, content)
        self.background_controls.parts_button.hide()
        layout.addWidget(self.background_controls)
        self.parameter_box = QWidget(content)
        parameters = QVBoxLayout(self.parameter_box)
        parameters.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.parameter_box)
        self.variant = QComboBox()
        for key, label in (('', '通用'), ('dark', '深色'), ('light', '浅色'),
                ('hover', '悬停'), ('pressed', '按下'), ('checked', '选中'),
                ('disabled', '禁用'), ('muted', '静音'), ('paused', '暂停')):
            self.variant.addItem(label, key)
        parameters.addWidget(self.variant)
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
        parameters.addLayout(form)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.apply_button = QPushButton('应用并保存')
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
        layout.addStretch(1)
        self.part.currentIndexChanged.connect(self.load_part)
        self.variant.currentIndexChanged.connect(self.load_part)
        self.scenes.currentChanged.connect(self._select_scene)
        self.preview.partSelected.connect(self._select_part)
        owner.skin_controller.changed.connect(self._update_background)
        from . import theme
        theme.signals().changed.connect(self._update_preview)
        for check, edit in self.fields.values():
            check.toggled.connect(self._update_preview)
            if isinstance(edit, QSpinBox):
                edit.valueChanged.connect(self._update_preview)
            else:
                edit.textChanged.connect(self._update_preview)
        self.load_part()
        self._update_background()

    def _select_part(self, part):
        self.part.setCurrentIndex(self.part.findData(part))

    def _select_scene(self, index):
        self._select_part(('sidebar', 'settings', 'menus')[index])

    def _update_background(self):
        layer = self.owner.skin_controller.layer
        self.preview.background = layer.image
        self.preview.background_mask = layer.mask
        self.preview.update()

    def _draft_values(self, extra=None):
        values = deepcopy(self.owner.settings.get('skin_parts', {}))
        drafts = dict(self._drafts)
        if extra is not None:
            drafts[(self.part.currentData(), self.variant.currentData())] = extra
        for (part, variant), target in drafts.items():
            if variant:
                values.setdefault(part, {})[variant] = target
            else:
                previous = values.get(part, {})
                values[part] = {key: value for key, value in previous.items()
                               if isinstance(value, dict) or key == 'builtin'} | target
        return values

    def _update_preview(self, *_args):
        if self._loading:
            return False
        from . import config, theme
        from .skin_parts import validate_parts
        target = {key: edit.value() if isinstance(edit, QSpinBox) else edit.text().strip()
                  for key, (check, edit) in self.fields.items() if check.isChecked() and check.isEnabled()}
        background = self.part.currentData() == 'background'
        try:
            values = self._draft_values(None if background else target)
            self.preview.personal = validate_parts(values, Path(config.REPO)/'utils/skins')
        except (OSError, ValueError) as error:
            self.status.setText('预览保留上次有效参数：' + str(error))
            return False
        if not background:
            key = (self.part.currentData(), self.variant.currentData())
            saved = self.owner.settings.get('skin_parts', {}).get(key[0], {})
            saved = saved.get(key[1], {}) if key[1] else {
                name: value for name, value in saved.items() if not isinstance(value, dict) and name != 'builtin'}
            if saved == target:
                self._drafts.pop(key, None)
            else:
                self._drafts[key] = target
        variant = self.variant.currentData()
        self.preview.light = variant == 'light' or (variant != 'dark' and theme.is_light())
        self.preview.state = variant if variant not in ('light', 'dark') else ''
        self.preview.update()
        self.status.setText('整体背景选择后立即生效。' if background else '预览已同步；点击应用并保存后生效。')
        return True

    def load_part(self):
        from .skin_parts import PARTS
        part = self.part.currentData()
        if getattr(self, '_loaded_part', None) != part:
            previous = self.variant.blockSignals(True)
            self.variant.setCurrentIndex(0)
            self.variant.blockSignals(previous)
            self._loaded_part = part
        background = part == 'background'
        self.preview.select_part(part)
        blocked = self.scenes.blockSignals(True)
        self.scenes.setCurrentIndex(('main', 'settings', 'popups').index(self.preview.scene))
        self.scenes.blockSignals(blocked)
        self.selection_title.setText(PARTS.get(part, '软件整体背景'))
        self.background_controls.setVisible(background)
        self.parameter_box.setVisible(not background)
        for button in (self.reset_button, self.builtin_button):
            button.setVisible(not background)
        self._loading = True
        values = self._draft_values().get(part, {})
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
        self._loading = False
        self.status.setText('整体背景选择后立即生效。' if background else '预览已同步；点击应用并保存后生效。')
        self._update_preview()

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
        if not self._update_preview():
            return
        values = self._draft_values()
        try:
            self.owner.set_skin_parts(values)
            self._drafts.clear()
            self.status.setText('已应用并保存；未勾选字段继续跟随美化包／默认。')
        except (OSError, ValueError) as error:
            self.status.setText(str(error))

    def reset_part(self):
        self._drafts = {key: value for key, value in self._drafts.items() if key[0] != self.part.currentData()}
        values = deepcopy(self.owner.settings.get('skin_parts', {}))
        values.pop(self.part.currentData(), None)
        self.owner.set_skin_parts(values)
        self.load_part()

    def use_builtin(self):
        self._drafts = {key: value for key, value in self._drafts.items() if key[0] != self.part.currentData()}
        values = deepcopy(self.owner.settings.get('skin_parts', {}))
        values[self.part.currentData()] = {'builtin': True}
        self.owner.set_skin_parts(values)
        self.load_part()
        self.status.setText('本分区已使用软件默认；可继续在默认基础上修改。')
