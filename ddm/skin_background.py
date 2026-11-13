"""Image/video background surface independent of live stream players."""
from pathlib import Path
import time
from PySide6.QtCore import QEvent, QRunnable, QRectF, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QPainter
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QWidget
from . import theme
from .skin_assets import IMAGES, VIDEOS, validate_asset


class _FrameImage(QRunnable):
    def __init__(self, frame, generation, completed):
        super().__init__()
        self.frame, self.generation, self.completed = frame, generation, completed

    def run(self):
        image = self.frame.toImage()
        try:
            self.completed.emit(self.generation, image)
        except RuntimeError:
            pass  # 关闭窗口后，已销毁的接收者不再接收转换结果。


class BackgroundLayer(QWidget):
    failed = Signal(str)
    frameReady = Signal()
    _converted = Signal(int, QImage)

    def __init__(self, root, window):
        super().__init__(root)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._window = window
        self.image = None
        self.mask = 35
        self.video_enabled = True
        self.path = ''
        self._last_frame = 0
        self._generation = 0
        self._frame_pending = False
        self._frame_pool = QThreadPool(self)
        self._frame_pool.setMaxThreadCount(1)
        self._converted.connect(self._frame_converted)
        self.player = None
        self.error = ''
        root.installEventFilter(self)
        window.installEventFilter(self)
        theme.signals().changed.connect(self._theme_changed)
        self.setGeometry(root.rect())
        self.lower()
        self.hide()

    @Slot(str)
    def _theme_changed(self, _mode):
        self.update()

    def load(self, path, *, video_enabled=True):
        if path == self.path and video_enabled == self.video_enabled:
            return
        self._generation += 1
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
            self.player.setVideoSink(None)
            if self.sink is not None:
                self.sink.deleteLater()
            self.sink = None
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
                        self.player.errorOccurred.connect(self._error)
                    self.sink = QVideoSink(self)
                    self.player.setVideoSink(self.sink)
                    # A queued frame from the previous source must not become
                    # the new source's frozen first frame.
                    self.sink.videoFrameChanged.connect(lambda frame, source=self.sink:
                        self._frame(frame) if source is self.sink else None)
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
                or self._frame_pending
                or self.error or not frame.isValid() or now - self._last_frame < 1 / 30):
            return
        self._last_frame = now
        self._frame_pending = True
        self._frame_pool.start(_FrameImage(frame, self._generation, self._converted))

    def _frame_converted(self, generation, image):
        self._frame_pending = False
        if (generation != self._generation or self.error or self.player is None
                or self.player.source().isEmpty()
                or not self._window.isVisible() or self._window.isMinimized()
                or (self.video_enabled and self.mask == 100)):
            return
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
