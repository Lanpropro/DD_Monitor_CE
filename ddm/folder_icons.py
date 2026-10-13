"""Folder icon rendering and a save-only editor."""
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QStyle, QToolButton, QVBoxLayout)

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


class FolderIconDialog(QDialog):
    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self.setWindowTitle('修改文件夹图标')
        self.folder = folder
        self.selection = normalize_icon(folder.get('icon'))
        self.image = None
        self.result_icon = self.selection
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.preview = QLabel()
        top.addWidget(self.preview)
        top.addWidget(QLabel(folder['name']), 1)
        layout.addLayout(top)
        grid = QGridLayout()
        self.choices = []
        for index, name in enumerate(ICON_NAMES):
            button = QToolButton()
            button.setText(NAMES[index])
            button.setIconSize(QSize(32, 32))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setCheckable(True)
            button.setStyleSheet('QToolButton:checked {border: 1px solid #4D8DFF; border-radius: 6px;}')
            button.clicked.connect(lambda _checked=False, value=name: self.select_builtin(value))
            grid.addWidget(button, index//3, index%3)
            self.choices.append(button)
        layout.addLayout(grid)
        self.color = QComboBox()
        self.color.addItems(('默认颜色', '蓝色', '粉色', '绿色', '橙色', '紫色'))
        if self.selection and self.selection['type'] == 'builtin':
            self.color.setCurrentIndex(ICON_COLORS.index(self.selection['color']))
        self.color.currentIndexChanged.connect(self._color_changed)
        layout.addWidget(self.color)
        choose = QPushButton('选择本地图片…')
        choose.clicked.connect(self._choose)
        layout.addWidget(choose)
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
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        reset = buttons.addButton('恢复默认', QDialogButtonBox.ResetRole)
        reset.clicked.connect(self.reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def select_builtin(self, name):
        self.selection = {'type': 'builtin', 'name': name, 'color': ICON_COLORS[self.color.currentIndex()]}
        self.image = None
        self.refresh()

    def _color_changed(self, index):
        if self.selection and self.selection['type'] == 'builtin':
            self.selection['color'] = ICON_COLORS[index]
        self.refresh()

    def refresh(self):
        folder = dict(self.folder, icon=self.selection)
        icon = QIcon(QPixmap.fromImage(self.image)) if self.image is not None else folder_icon(folder, self, 48)
        self.preview.setPixmap(icon.pixmap(QSize(48, 48), self.devicePixelRatioF()))
        for name, button in zip(ICON_NAMES, self.choices):
            selected = bool(self.selection and self.selection.get('name') == name)
            button.setChecked(selected)
            button.setText(NAMES[ICON_NAMES.index(name)] + (' ✓' if selected else ''))
            button.setIcon(folder_icon(dict(self.folder, icon={'type': 'builtin', 'name': name,
                'color': ICON_COLORS[self.color.currentIndex()]}), self, 32))
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
        super().accept()
