"""Local background asset validation, copy and import worker."""
import os
from pathlib import Path
import uuid
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImageReader
from . import config


IMAGES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}


VIDEOS = {'.mp4', '.webm', '.mkv', '.mov'}


def validate_asset(path):
    path = Path(path)
    if not path.is_file() or path.suffix.lower() not in IMAGES | VIDEOS:
        raise ValueError('请选择支持的图片或视频文件')
    if not 0 < path.stat().st_size <= 512 * 1024 * 1024:
        raise ValueError('背景文件必须非空且不超过 512MB')
    if path.suffix.lower() in IMAGES:
        reader = QImageReader(str(path))
        size = reader.size()
        if not reader.canRead() or not size.isValid() or max(size.width(), size.height()) > 8192:
            raise ValueError('图片无法读取或尺寸超过 8192 像素')
        reader.setAutoTransform(True)
        if reader.read().isNull():
            raise ValueError('图片内容损坏，无法读取')
    return path


def import_asset(source, cancelled=lambda: False):
    from .skins import validate_asset
    source = validate_asset(source)
    directory = Path(config.data_root()) / 'utils' / 'skins'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (uuid.uuid4().hex + '_' + source.name)
    partial = target.with_suffix(target.suffix + '.part')
    try:
        with source.open('rb') as incoming, partial.open('wb') as output:
            while chunk := incoming.read(1024 * 1024):
                if cancelled():
                    raise ValueError('已取消背景导入')
                output.write(chunk)
        if cancelled():
            raise ValueError('已取消背景导入')
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target.relative_to(config.data_root()).as_posix()


class AssetImport(QThread):
    imported = Signal(str)
    failed = Signal(str)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source

    def run(self):
        try:
            self.imported.emit(import_asset(self.source, self.isInterruptionRequested))
        except (OSError, ValueError) as error:
            self.failed.emit(str(error))
