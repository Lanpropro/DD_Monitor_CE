"""Appearance controls for custom backgrounds and plugin ownership."""
from pathlib import Path
from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTabBar, QVBoxLayout, QWidget)

from .skins import AssetImport
from .folder_icons import IconDropArea


class SkinAssetDropArea(IconDropArea):
    def __init__(self, parent=None, *, video=False):
        super().__init__(parent)
        from .skins import IMAGES, VIDEOS
        self.extensions = IMAGES | VIDEOS if video else IMAGES
        self.setText('将图片或视频拖到这里\n或点击选择文件' if video else '将图片拖到这里\n或点击选择文件')
        self.setAutoDefault(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('#IconDropArea {background: palette(button); color: palette(button-text);'
            'border: 1px dashed #70839A; border-radius: 10px; padding: 10px;}'
            '#IconDropArea:hover, #IconDropArea[dragging="true"] {border-color: palette(highlight);}')

    def _path(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            if Path(path).suffix.lower() in self.extensions and Path(path).is_file():
                return path
        return ''


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

    def _follow_package(self):
        self._overrides = dict.fromkeys(self._overrides, False)
        self.changed.emit(self.values())

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
        self.follow.setVisible(override is not None and not self._locked())
        self.follow.setEnabled(not locked)
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


class PartSettings(QDialog):
    """Edit only explicit personal overrides; omitted fields inherit the skin pack."""
    def __init__(self, owner, parent=None, *, professional=False, embedded=False):
        super().__init__(parent)
        from .skin_parts import PARTS, NUMBERS
        from .skin_preview import BASIC_PARTS, GROUPS, SkinPreview
        self.owner = owner
        self.professional = professional
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.Widget)
            self.setProperty('skinPart', 'settings.content')
        self._drafts = {}
        self._loading = False
        self.setWindowTitle('专业美化' if professional else '分区美化')
        self.resize(1100, 700)
        outer = QVBoxLayout(self) if embedded else QHBoxLayout(self)
        if embedded:
            outer.setContentsMargins(0, 0, 0, 0)
        preview_panel = QWidget(self)
        preview_column = QVBoxLayout(preview_panel)
        preview_column.setContentsMargins(0, 0, 0, 0)
        if embedded:
            preview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.scenes = QTabBar()
        self.scenes.setStyleSheet('QTabBar::tab {background: palette(base); color: palette(text);'
            'padding: 8px 12px; margin-right: 4px; border: 1px solid palette(mid); border-radius: 8px;}'
            'QTabBar::tab:selected {background: palette(light); border-color: palette(highlight);}')
        for text in ('主界面', '设置页面', '菜单与提示' if professional else '布局预设'):
            self.scenes.addTab(text)
        preview_column.addWidget(self.scenes)
        self.preview = SkinPreview(self, editable_parts=None if professional else BASIC_PARTS)
        if embedded:
            self.preview.setMinimumSize(320, 280)
            self.preview.setFixedHeight(280)
        preview_column.addWidget(self.preview, 1)
        self.group_labels = {}
        if not professional:
            colors = QHBoxLayout()
            for key, (name, _dark, _light) in GROUPS.items():
                label = QLabel('● ' + name)
                colors.addWidget(label)
                self.group_labels[key] = label
            preview_column.addLayout(colors)
        legend = QLabel('点击彩色框选择区域；实线表示当前选择。\n空画面、顶部浮标和关注卡片不提供修改入口。')
        legend.setWordWrap(True)
        preview_column.addWidget(legend)
        legend.setVisible(not embedded)
        outer.addWidget(preview_panel, 0 if embedded else 3)
        right = QVBoxLayout()
        self.page_title = QLabel('界面美化')
        self.page_title.setObjectName('SettingsTitle')
        right.addWidget(self.page_title)
        self.page_title.setVisible(not embedded)
        self.introduction = QLabel('点击上方预览图中可修改部分 在下方自定义修改' if embedded else
                                  '点击左侧预览图中可修改部分 在下方自定义修改')
        self.introduction.setObjectName('SettingsHint')
        self.introduction.setWordWrap(True)
        right.addWidget(self.introduction)
        outer.addLayout(right, 0 if embedded else 2)
        content = QWidget()
        if embedded:
            right.addWidget(content)
        else:
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setMinimumWidth(350)
            scroll.setWidget(content)
            right.addWidget(scroll, 1)
        layout = QVBoxLayout(content)
        if embedded:
            layout.setContentsMargins(0, 0, 0, 0)
        self.selection_title = QLabel()
        self.selection_title.setObjectName('SettingsTitle')
        layout.addWidget(self.selection_title)
        self.part = QComboBox(self)
        self.part.addItem('软件整体背景', 'background')
        for key, label in PARTS.items():
            if professional or key in BASIC_PARTS:
                self.part.addItem('设置页面背景' if key == 'settings' and not professional else
                                  '布局预设背景' if key == 'layout_menu' and not professional else label, key)
        self.part.hide()
        self.part.setCurrentIndex(self.part.findData('background'))
        self.background_controls = SkinSettings(owner.settings, owner.skin_controller, content)
        self.background_controls.parts_button.hide()
        self.background_controls.findChild(QLabel, 'SettingsTitle').hide()
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
        self.variant.setVisible(professional)
        form = QFormLayout()
        self.form = form
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
                button = SkinAssetDropArea()
                button.setAutoDefault(False)
                button.clicked.connect(lambda _checked=False, field=key: self._choose(field))
                button.fileDropped.connect(lambda source, field=key: self._import_part_asset(field, source))
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
        self.close_button = close
        right.addLayout(row)
        if embedded:
            self.apply_button.hide()
            close.hide()
        else:
            layout.addStretch(1)
        self.part.currentIndexChanged.connect(self.load_part)
        self.variant.currentIndexChanged.connect(self.load_part)
        self.scenes.currentChanged.connect(self._select_scene)
        self.preview.partSelected.connect(self._select_part)
        owner.skin_controller.changed.connect(self._update_background)
        owner.skin_controller.layer.frameReady.connect(self._update_background)
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

    def keyPressEvent(self, event):
        if self.embedded:
            QWidget.keyPressEvent(self, event)
        else:
            super().keyPressEvent(event)

    def _select_part(self, part):
        index = self.part.findData(part)
        if index >= 0:
            self.part.setCurrentIndex(index)

    def _select_scene(self, index):
        self._select_part(('background', 'settings', 'menus' if self.professional else 'layout_menu')[index])

    def _editable_fields(self):
        return set(self.fields) if self.professional else {'icon' if self.part.currentData().startswith('buttons.') else 'image'}

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
        if not self.professional and not background:
            previous = self._draft_values().get(self.part.currentData(), {})
            target = {key: value for key, value in previous.items()
                      if key in self.fields and key not in self._editable_fields()} | target
        try:
            values = self._draft_values(None if background else target)
            self.preview.personal = validate_parts(values, Path(config.REPO)/'utils/skins')
        except (OSError, ValueError) as error:
            if not self.professional and self.preview.scene != 'main':
                self.preview.capture_interface(self.owner)
                self.preview.update()
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
        from .skin_preview import group_color
        for group, label in self.group_labels.items():
            label.setStyleSheet('color: ' + group_color(group, self.preview.light).name() + ';')
        self.preview.state = variant if variant not in ('light', 'dark') else ''
        if not self.professional and self.preview.scene != 'main':
            self.preview.capture_interface(self.owner)
        self.preview.update()
        self.status.setText('整体背景选择后立即生效。' if background else
                           '预览已同步；点击设置页下方“保存”后生效。' if self.embedded else
                           '预览已同步；点击应用并保存后生效。')
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
        self.selection_title.setText(self.part.currentText())
        self.background_controls.setVisible(background)
        self.parameter_box.setVisible(not background)
        for button in (self.reset_button, self.builtin_button):
            button.setVisible(not background)
        if not self.professional:
            self.builtin_button.setText('恢复默认图标' if part.startswith('buttons.') else '恢复默认背景')
            self.reset_button.setText('跟随美化包')
        self._loading = True
        values = self._draft_values().get(part, {})
        variant = self.variant.currentData()
        if variant:
            values = values.get(variant, {})
        for key, (check, edit) in self.fields.items():
            visible = key in self._editable_fields()
            self.form.setRowVisible(check, visible)
            if not self.professional and key in self.asset_buttons:
                check.hide()
                edit.hide()
            check.setChecked(key in values)
            part = self.part.currentData()
            check.setEnabled(visible and not (key == 'foreground' and part == 'sidebar') and
                not (key == 'icon' and part != 'folders' and not part.startswith('buttons')))
            if key in self.asset_buttons:
                self.asset_buttons[key].setEnabled(check.isEnabled())
            if isinstance(edit, QSpinBox):
                edit.setValue(values.get(key, 0))
            else:
                edit.setText(values.get(key, ''))
            if key in self.asset_buttons:
                self.asset_buttons[key].setToolTip(values.get(key, '') or '尚未导入；跟随美化包或默认')
        self._loading = False
        self.status.setText('整体背景选择后立即生效。' if background else
                           '预览已同步；点击设置页下方“保存”后生效。' if self.embedded else
                           '预览已同步；点击应用并保存后生效。')
        self._update_preview()

    def _choose(self, key):
        source, _ = QFileDialog.getOpenFileName(self, '导入分区图片', '', '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not source:
            return
        self._import_part_asset(key, source)

    def _import_part_asset(self, key, source):
        from .skins import import_asset, validate_asset, IMAGES
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
        if self.save_changes() and not self.professional and not self.embedded:
            self.accept()

    def save_changes(self):
        if not self.professional and not self._drafts:
            part = self.part.currentData()
            field = 'icon' if part.startswith('buttons.') else 'image'
            check, edit = self.fields[field]
            current = edit.text().strip() if check.isChecked() else None
            saved = self.owner.settings.get('skin_parts', {}).get(part, {}).get(field)
            if part == 'background' or current == saved:
                return True
        if not self._update_preview():
            return False
        values = self._draft_values()
        try:
            self.owner.set_skin_parts(values)
            self._drafts.clear()
            self.status.setText('已应用并保存；未修改的部分继续跟随美化包／默认。')
            return True
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return False

    def reset_part(self):
        self._drafts = {key: value for key, value in self._drafts.items() if key[0] != self.part.currentData()}
        values = deepcopy(self.owner.settings.get('skin_parts', {}))
        if self.professional:
            values.pop(self.part.currentData(), None)
        else:
            target = values.get(self.part.currentData(), {})
            target.pop('builtin', None)
            for field in self._editable_fields():
                target.pop(field, None)
                for variant in ('dark', 'light'):
                    target.get(variant, {}).pop(field, None)
        self.owner.set_skin_parts(values)
        self.load_part()

    def use_builtin(self):
        self._drafts = {key: value for key, value in self._drafts.items() if key[0] != self.part.currentData()}
        values = deepcopy(self.owner.settings.get('skin_parts', {}))
        part = self.part.currentData()
        target = {} if self.professional else values.get(part, {})
        for field in self._editable_fields():
            target.pop(field, None)
            for variant in ('dark', 'light'):
                target.get(variant, {}).pop(field, None)
        values[part] = target | {'builtin': True}
        self.owner.set_skin_parts(values)
        self.load_part()
        self.status.setText('本分区已使用软件默认；可继续在默认基础上修改。')
