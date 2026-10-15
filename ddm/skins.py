"""Local image/video backgrounds, independent of live-stream players."""
import os
import sys
from pathlib import Path
import time
import uuid

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QImageReader, QPainter
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QWidget

from . import config, theme

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
    source = validate_asset(source)
    directory = Path(config.REPO) / 'utils' / 'skins'
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
    return target.relative_to(config.REPO).as_posix()


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


def plugin_skin(plugin, folder):
    """Resolve a declarative skin inside its own installed plugin folder."""
    spec = plugin.skin
    if not isinstance(spec, dict):
        raise ValueError('皮肤必须是对象')
    version = spec.get('version', 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError('不支持的皮肤接口版本')
    if not isinstance(spec.get('background', '' if version == 2 else None), str):
        raise ValueError('皮肤需要 background 相对路径')
    root = Path(folder).resolve()
    relative = Path(spec.get('background') or '')
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root):
        raise ValueError('皮肤背景必须位于插件包内')
    if (version == 1 or spec.get('background')) and path.suffix.lower() not in IMAGES | VIDEOS:
        raise ValueError('皮肤背景格式不受支持')
    mask = spec.get('mask', 35)
    if type(mask) is not int or not 0 <= mask <= 100:
        raise ValueError('皮肤 mask 必须是 0–100 的整数')
    from .skin_parts import validate_parts
    parts = validate_parts(spec.get('parts', {}), root)
    return {'path': str(path) if spec.get('background') else '', 'mask': mask,
            'owner': plugin.context.name, 'name': plugin.name, 'version': version, 'parts': parts}


class BackgroundLayer(QWidget):
    failed = Signal(str)
    frameReady = Signal()

    def __init__(self, root, window):
        super().__init__(root)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._window = window
        self.image = None
        self.mask = 35
        self.video_enabled = True
        self.path = ''
        self._last_frame = 0
        self.player = None
        self.error = ''
        root.installEventFilter(self)
        window.installEventFilter(self)
        theme.signals().changed.connect(lambda _mode: self.update())
        self.setGeometry(root.rect())
        self.lower()
        self.hide()

    def load(self, path, *, video_enabled=True):
        if path == self.path and video_enabled == self.video_enabled:
            return
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        self.image = None
        self.path = path
        self.video_enabled = video_enabled
        self._last_frame = 0
        self.error = ''
        if path:
            try:
                asset = validate_asset(path)
                if asset.suffix.lower() in IMAGES:
                    reader = QImageReader(str(asset))
                    reader.setAutoTransform(True)
                    self.image = reader.read()
                else:
                    if self.player is None:
                        self.player = QMediaPlayer(self)
                        self.player.setAudioOutput(None)
                        self.player.setLoops(QMediaPlayer.Infinite)
                        self.sink = QVideoSink(self)
                        self.player.setVideoSink(self.sink)
                        self.sink.videoFrameChanged.connect(self._frame)
                        self.player.errorOccurred.connect(self._error)
                    self.player.setSource(QUrl.fromLocalFile(str(asset)))
                    self._visibility()
            except (OSError, ValueError) as error:
                self.error = str(error)
                self.failed.emit(self.error)
        self.setVisible(bool(path))
        self.lower()
        self.update()

    def _frame(self, frame):
        now = time.monotonic()
        if (self.player is None or self.player.source().isEmpty()
                or Path(self.path).suffix.lower() not in VIDEOS
                or (self.mask == 100 and self.video_enabled)
                or (not self.video_enabled and self.image is not None)
                or not self._window.isVisible() or self._window.isMinimized()
                or self.error or not frame.isValid() or now - self._last_frame < 1 / 30):
            return
        self._last_frame = now
        image = frame.toImage()
        if not image.isNull():
            self.image = image
            if not self.video_enabled:
                self.player.pause()
            self.update()
            self.frameReady.emit()

    def _error(self, _code, message):
        if self.player.source().isEmpty() or Path(self.path).suffix.lower() not in VIDEOS:
            return
        self.player.stop()
        self.image = None
        self.update()
        self.error = '视频背景无法播放：' + message
        self.failed.emit(self.error)

    def _visibility(self):
        if self.player is None or self.player.source().isEmpty() or self.error:
            return
        needs_frame = not self.video_enabled and self.image is None
        if (self._window.isVisible() and not self._window.isMinimized()
                and (needs_frame or (self.video_enabled and self.mask < 100))):
            self.player.play()
        else:
            self.player.pause()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(watched.rect())
        if watched is self._window and event.type() in (QEvent.Show, QEvent.Hide, QEvent.WindowStateChange):
            self._visibility()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme.qcolor(theme.BG))
        if self.mask < 100 and self.image is not None and not self.image.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            scale = max(self.width() / self.image.width(), self.height() / self.image.height())
            width, height = self.image.width() * scale, self.image.height() * scale
            painter.drawImage(QRectF((self.width()-width)/2, (self.height()-height)/2, width, height), self.image)
            veil = theme.qcolor(theme.BG)
            veil.setAlpha(round(255 * self.mask / 100))
            painter.fillRect(self.rect(), veil)


class SkinController(QObject):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.layer = BackgroundLayer(window.centralWidget(), window)
        self.override = None
        self.error = ''
        self.layer.failed.connect(self._failed)
        sidebar = window.sidebar
        for attribute, key in (('sort_button', 'sort'), ('refresh_button', 'refresh'),
                ('appearance_button', 'appearance'), ('toggle_button', 'sidebar_toggle'),
                ('settings_button', 'settings'), ('layout_button', 'layout'),
                ('import_button', 'import'), ('add_button', 'add')):
            button = getattr(sidebar, attribute)
            button.setProperty('skinPart', 'buttons.' + key)
            button.setProperty('skinIconOnly', key in ('sort', 'refresh', 'appearance', 'sidebar_toggle'))

    def refresh(self):
        if getattr(self.window, '_closing', False):
            return
        manager = getattr(self.window, 'plugins', None)
        self.override = manager.active_skin() if manager is not None else None
        settings = self.window.settings
        from .skin_parts import configure, validate_parts
        try:
            personal = validate_parts(settings.get('skin_parts', {}), Path(config.REPO) / 'utils' / 'skins')
        except (OSError, ValueError) as error:
            personal = {}
            print(f'[皮肤] 个人分区配置无效：{error}', file=sys.stderr)
        configure(self.override.get('parts', {}) if self.override else {}, personal)
        use_package = self.override is not None and (self.override['version'] == 1
            or (bool(self.override['path']) and not settings.get('skin_background_override', False)))
        path = self.override['path'] if use_package else settings.get('skin_background', '')
        if path and not use_package:
            root = Path(config.REPO).resolve()
            path = (root / path).resolve()
            if not path.is_relative_to(root / 'utils' / 'skins'):
                path = ''
        self.error = ''
        try:
            mask = max(0, min(100, int(settings.get('skin_mask', 35))))
        except (TypeError, ValueError):
            mask = 35
        legacy = self.override is not None and self.override['version'] == 1
        self.layer.mask = self.override['mask'] if use_package and (legacy or not settings.get('skin_mask_override')) else mask
        theme.set_skin_active(bool(path), True)
        self.layer.load(str(path) if path else '', video_enabled=bool(settings.get('skin_video_enabled', True)))
        self.layer._visibility()
        self.error = self.layer.error
        self.layer.update()
        self.changed.emit()

    def _failed(self, message):
        self.error = message
        self.changed.emit()

    def stop(self):
        if self.layer.player is not None:
            self.layer.player.stop()
            self.layer.player.setSource(QUrl())
        for job in self.window.findChildren(AssetImport):
            job.requestInterruption()
            job.wait()
