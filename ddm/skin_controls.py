"""Shared skin asset names and local-file drop controls."""
from pathlib import Path
from PySide6.QtCore import Qt
from .folder_icons import IconDropArea


def _background_name(path):
    filename = Path(path).name if path else '默认背景'
    prefix, separator, name = filename.partition('_')
    if separator and len(prefix) == 32 and all(c in '0123456789abcdef' for c in prefix):
        return name
    return filename


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
