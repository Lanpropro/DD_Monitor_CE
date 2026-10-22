"""Folder icon rendering and a save-only editor."""
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QLineEdit,
    QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QStyle, QStyleOption,
    QToolButton, QVBoxLayout, QWidget)

from . import config, theme
from .follow_folders import ICON_COLORS, ICON_NAMES, normalize_icon

NAMES = ('文件夹', '星标', '爱心', '游戏', '音乐', '视频')
COLORS = dict(zip(ICON_COLORS, ('', '#4D8DFF', '#E95C93', '#2FA678', '#DE8534', '#A579D4')))
PATHS = (
    '<path d="M3 7V5h6l2 3h10v12H3Z"/>',
    '<path d="m12 3 2.8 5.8 6.4.9-4.6 4.5 1.1 6.3-5.7-3-5.7 3 1.1-6.3-4.6-4.5 6.4-.9Z"/>',
    '<path d="M12 21 3.5 12.5C-2 6 7 0 12 7c5-7 14-1 8.5 5.5Z"/>',
    '<path d="M7 7h10c3 0 4 3 5 10 0 3-3 3-5 0l-2-2H9l-2 2c-2 3-5 3-5 0 1-7 2-10 5-10Z"/><path d="M6 10v5m-2.5-2.5h5M17 11h.01M19 14h.01"/>',
    '<path d="M9 17V5l11-2v12M9 9l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="16" rx="3" ry="2"/>',
    '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 8 6 4-6 4Z"/>',
)


def read_image(source):
    source = Path(source)
    if source.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.ico'):
        raise ValueError('请选择 PNG、JPEG 或 ICO 图片')
    if not source.is_file() or not 0 < source.stat().st_size <= 5 * 1024 * 1024:
        raise ValueError('图标文件必须非空且不超过 5MB')
    reader = QImageReader(str(source))
    size = reader.size()
    if not reader.canRead() or not size.isValid() or max(size.width(), size.height()) > 4096:
        raise ValueError('图片无法读取或尺寸超过 4096×4096')
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ValueError('图片内容损坏，无法读取')
    canvas = QImage(256, 256, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    image = image.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(canvas)
    painter.drawImage((256-image.width())//2, (256-image.height())//2, image)
    painter.end()
    return canvas


def folder_icon(folder, widget, size=18):
    spec = normalize_icon(folder.get('icon'))
    if spec and spec['type'] == 'image':
        try:
            image = read_image(Path(config.REPO) / spec['path'])
            return QIcon(QPixmap.fromImage(image))
        except (OSError, ValueError):
            pass
    elif spec:
        color = COLORS[spec['color']] or theme.qcolor(theme.TEXT2).name()
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
            'stroke-linejoin="round">' + PATHS[ICON_NAMES.index(spec['name'])] + '</svg>')
        dpr = widget.devicePixelRatioF()
        pixmap = QPixmap(round(size*dpr), round(size*dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size, size))
        painter.end()
        return QIcon(pixmap)
    kind = QStyle.SP_DirLinkIcon if folder['type'] == 'smart' else QStyle.SP_DirIcon
    return widget.style().standardIcon(kind)


class IconDropArea(QPushButton):
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__('将图片拖到这里\n或点击选择 PNG / JPEG / ICO', parent)
        self.setObjectName('IconDropArea')
        self.setAcceptDrops(True)
        self.setMinimumHeight(64)

    def _path(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            if Path(path).suffix.lower() in ('.png', '.jpg', '.jpeg', '.ico'):
                return path
        return ''

    def _highlight(self, active):
        self.setProperty('dragging', active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def dragEnterEvent(self, event):
        if self._path(event):
            self._highlight(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._path(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._highlight(False)
        event.accept()

    def dropEvent(self, event):
        self._highlight(False)
        path = self._path(event)
        if path:
            self.fileDropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()


def create_folder_dialog(parent, creator, existing_names):
    dialog = FolderIconDialog({'name': '', 'type': 'normal'}, parent,
                              existing_names=existing_names, create=True)
    try:
        if dialog.exec() != QDialog.Accepted:
            return '', ''
        folder_id = creator(dialog.result_name, icon=dialog.result_icon)
        if not folder_id:
            QMessageBox.warning(parent, '新建文件夹', '已存在同名文件夹，请使用其他名称')
        return folder_id, dialog.result_name
    finally:
        dialog.deleteLater()


class FolderIconDialog(QDialog):
    def __init__(self, folder, parent=None, *, existing_names=(), create=False):
        super().__init__(parent)
        self.setWindowTitle('新建文件夹' if create else '修改文件夹图标')
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName('FolderIconDialog')
        self._drag_offset = None
        self.setFixedWidth(430)
        self.folder = folder
        self.existing_names = set(existing_names)
        self.result_name = folder['name']
        self.selection = normalize_icon(folder.get('icon'))
        self.image = None
        self.result_icon = self.selection
        self._color = self.selection['color'] if self.selection and self.selection['type'] == 'builtin' else 'default'
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        self.header = QWidget()
        heading = QHBoxLayout(self.header)
        heading.setContentsMargins(0, 0, 0, 0)
        title = QLabel(self.windowTitle())
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        heading.addWidget(title, 1)
        close = QPushButton('×')
        close.setObjectName('IconClose')
        close.setFixedSize(26, 26)
        close.clicked.connect(self.reject)
        heading.addWidget(close)
        layout.addWidget(self.header)
        current = QFrame()
        current.setObjectName('IconCurrent')
        top = QHBoxLayout(current)
        top.setContentsMargins(14, 12, 14, 12)
        self.preview = QLabel()
        self.preview.setFixedSize(40, 40)
        self.preview.setAlignment(Qt.AlignCenter)
        top.addWidget(self.preview)
        labels = QVBoxLayout()
        labels.setSpacing(3)
        self.name_edit = QLineEdit(folder['name'])
        self.name_edit.setReadOnly(folder['type'] == 'unclassified')
        self.name_edit.setObjectName('IconFolderName')
        self.name_edit.setAccessibleName('文件夹名称')
        self.name_edit.setPlaceholderText('输入文件夹名称')
        self.name_edit.setToolTip('填写文件夹名称，创建后应用' if create else '直接修改文件夹名称，保存后应用')
        labels.addWidget(self.name_edit)
        hint = QLabel(('智能文件夹' if folder['type'] == 'smart' else '普通文件夹') + ' · 图标预览')
        hint.setProperty('hint', True)
        labels.addWidget(hint)
        top.addLayout(labels, 1)
        layout.addWidget(current)
        layout.addWidget(QLabel('内置图标'))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.choices = []
        for index, name in enumerate(ICON_NAMES):
            button = QToolButton()
            button.setObjectName('IconChoice')
            button.setFixedSize(122, 66)
            button.setText(NAMES[index])
            button.setIconSize(QSize(24, 24))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=name: self.select_builtin(value))
            grid.addWidget(button, index//3, index%3)
            self.choices.append(button)
        layout.addLayout(grid)
        self.color = QWidget()
        colors = QHBoxLayout(self.color)
        colors.setContentsMargins(0, 0, 0, 0)
        colors.addWidget(QLabel('图标颜色'))
        colors.addStretch()
        self.swatches = {}
        for name, label in zip(ICON_COLORS, ('默认', '蓝色', '粉色', '绿色', '橙色', '紫色')):
            button = QPushButton()
            button.setFixedSize(24, 24)
            button.setToolTip(label)
            button.clicked.connect(lambda _checked=False, value=name: self.set_color(value))
            colors.addWidget(button)
            self.swatches[name] = button
        layout.addWidget(self.color)
        self.drop_area = IconDropArea(self)
        self.drop_area.clicked.connect(self._choose)
        self.drop_area.fileDropped.connect(self.import_image)
        layout.addWidget(self.drop_area)
        hint = QLabel('最大 5MB，图片保留原色。' + ('创建后应用。' if create else '保存后应用。'))
        hint.setProperty('hint', True)
        layout.addWidget(hint)
        previews = QHBoxLayout()
        self.image_previews = []
        for background in ('#191A1F', '#F4F6F9'):
            label = QLabel()
            label.setFixedSize(64, 64)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet('background: ' + background + '; border-radius: 8px;')
            previews.addWidget(label)
            self.image_previews.append(label)
        layout.addLayout(previews)
        self.error = QLabel()
        self.error.setObjectName('IconError')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        reset = QPushButton('恢复默认')
        reset.setObjectName('IconReset')
        reset.clicked.connect(self.reset)
        buttons.addWidget(reset)
        buttons.addStretch()
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton('创建' if create else '保存')
        save.setObjectName('IconSave')
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        self.refresh_theme()

    def paintEvent(self, event):
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() <= self.header.geometry().bottom():
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
        super().mouseReleaseEvent(event)

    def refresh_theme(self):
        dark = not theme.is_light()
        bg, text, secondary, border, card = (
            ('#24262B', '#F1F2F5', '#B8BDC5', '#424650', '#2D3036') if dark else
            ('#F7F9FC', '#202630', '#5E6A7D', '#D7DDE7', '#FFFFFF'))
        self.setStyleSheet(f'''
            #FolderIconDialog {{background: {bg}; border: 1px solid {border}; border-radius: 14px;}}
            #FolderIconDialog QLabel {{color: {text}; background: transparent;}}
            #FolderIconDialog QLabel[hint="true"] {{color: {secondary}; font-size: 12px;}}
            #IconCurrent {{background: {card}; border: 1px solid {border}; border-radius: 10px;}}
            #IconFolderName {{background: transparent; color: {text}; border: 1px solid transparent; border-radius: 4px; padding: 2px 0;}}
            #IconFolderName:hover {{border-color: {border};}}
            #IconFolderName:focus {{border-color: #00A1D6;}}
            #IconChoice {{background: {card}; color: {text}; border: 1px solid {border}; border-radius: 9px; padding: 8px;}}
            #IconChoice:checked {{background: {'#243A44' if dark else '#ECF7FC'}; border-color: #00A1D6;}}
            #FolderIconDialog QPushButton {{background: {card}; color: {text}; border: 1px solid {border}; border-radius: 8px; padding: 7px 12px;}}
            #FolderIconDialog #IconSave {{background: #00A1D6; border-color: #00A1D6; color: white;}}
            #FolderIconDialog #IconReset, #FolderIconDialog #IconClose {{background: transparent; border: none; color: {secondary};}}
            #FolderIconDialog #IconClose {{padding: 0; font-size: 20px;}}
            #FolderIconDialog #IconDropArea {{border-style: dashed;}}
            #FolderIconDialog #IconDropArea[dragging="true"] {{border-color: #00A1D6; background: {'#243A44' if dark else '#ECF7FC'};}}
            #FolderIconDialog #IconError {{color: #E5484D;}}
        ''')
        self.refresh()

    def select_builtin(self, name):
        self.selection = {'type': 'builtin', 'name': name, 'color': self._color}
        self.image = None
        self.refresh()

    def set_color(self, color):
        if not self.color.isEnabled():
            return
        self._color = color
        if self.selection and self.selection['type'] == 'builtin':
            self.selection['color'] = color
        self.refresh()

    def refresh(self):
        folder = dict(self.folder, icon=self.selection)
        icon = QIcon(QPixmap.fromImage(self.image)) if self.image is not None else folder_icon(folder, self, 32)
        self.preview.setPixmap(icon.pixmap(QSize(32, 32), self.devicePixelRatioF()))
        for name, button in zip(ICON_NAMES, self.choices):
            selected = bool(self.selection and self.selection.get('name') == name)
            button.setChecked(selected)
            button.setText(NAMES[ICON_NAMES.index(name)] + (' ✓' if selected else ''))
            button.setIcon(folder_icon(dict(self.folder, icon={'type': 'builtin', 'name': name,
                'color': self._color}), self, 24))
        for name, button in self.swatches.items():
            button.setText('✓' if name == self._color else '')
            button.setStyleSheet(f'background: {COLORS[name] or theme.qcolor(theme.TEXT2).name()}; color: white; border: '
                + ('2px solid #00A1D6' if name == self._color else 'none') + '; border-radius: 12px; padding: 0;')
        is_image = self.image is not None or bool(self.selection and self.selection['type'] == 'image')
        self.color.setEnabled(not is_image)
        for label in self.image_previews:
            label.setVisible(is_image)
            label.setPixmap(icon.pixmap(QSize(48, 48), self.devicePixelRatioF()))
        self.error.clear()

    def _choose(self):
        path, _filter = QFileDialog.getOpenFileName(self, '选择文件夹图标', '', '图片 (*.png *.jpg *.jpeg *.ico)')
        if path:
            self.import_image(path)

    def import_image(self, path):
        try:
            image = read_image(path)
        except (OSError, ValueError) as error:
            self.error.setText(str(error))
            return
        self.image, self.selection = image, None
        self.refresh()

    def reset(self):
        self.selection = None
        self.image = None
        self.refresh()

    def accept(self):
        name = self.name_edit.text().strip()
        if not name or name in self.existing_names:
            self.error.setText('文件夹名称不能为空' if not name else '已存在同名文件夹')
            self.name_edit.setFocus()
            return
        selection = self.selection
        if self.image is not None:
            path = Path(config.REPO) / 'utils' / 'folder-icons' / (uuid4().hex + '.png')
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not self.image.save(str(path), 'PNG'):
                    raise OSError('图标保存失败，请重试')
            except OSError as error:
                path.unlink(missing_ok=True)
                self.error.setText(str(error))
                return
            selection = {'type': 'image', 'path': path.relative_to(config.REPO).as_posix()}
        self.result_icon = selection
        self.result_name = name
        super().accept()
