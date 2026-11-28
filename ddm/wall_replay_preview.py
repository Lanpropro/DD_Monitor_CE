"""Show a separate video preview while scrubbing the replay timeline."""
import math

from PySide6.QtCore import QObject, QPoint, QProcess, QRect, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel

from .wall_replay_timeline import format_time


class ReplayPreview(QObject):
    def __init__(self, slider, tile, source, executable):
        super().__init__(slider)
        self.slider = slider
        self.tile = tile
        self.source = source
        self.executable = executable
        self.card = QFrame(slider, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
                          | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.card.setObjectName('ReplayPreviewPane')
        self.card.setAttribute(Qt.WA_TranslucentBackground)
        self.card.setAttribute(Qt.WA_ShowWithoutActivating)
        self.card.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.card.setAccessibleName('回看目标画面预览')
        self.card.setStyleSheet(
            '#ReplayPreviewPane {background: #101216; border: 1px solid #585d67; border-radius: 9px;} '
            '#ReplayPreviewPane QLabel {color: #f1f3f5; background: transparent; border: none;} '
            '#ReplayPreviewPane #ReplayPreviewTime {background: rgba(12, 14, 19, 200); '
            'border-radius: 7px; padding: 2px 6px;}')
        layout = QGridLayout(self.card)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        self.label = QLabel(self.card, alignment=Qt.AlignCenter)
        policy = self.label.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.label.setSizePolicy(policy)
        self.label.hide()
        self.caption = QLabel(self.card, alignment=Qt.AlignCenter, objectName='ReplayPreviewTime')
        layout.addWidget(self.label, 0, 0)
        layout.addWidget(self.caption, 0, 0, Qt.AlignRight | Qt.AlignBottom)
        self.timer = QTimer(self, interval=120, singleShot=True)
        self.timer.timeout.connect(self._decode)
        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self._request = None
        self._running = None
        self._displayed = None
        self._time_text = ''
        self._running_time = self._displayed_time = ''
        slider.sliderPressed.connect(lambda: self.request(slider.sliderPosition()))
        slider.sliderMoved.connect(self.request)
        slider.sliderReleased.connect(self.hide)

    def request(self, position):
        media = self.source(position)
        if media is None:
            self.hide()
            return
        path, seconds = media
        media = (path, math.floor(seconds * 2) / 2)
        previous = self._request
        self._request = media
        self._time_text = format_time(position - self.slider.minimum())
        if media == self._displayed:
            self.caption.setText(self._time_text)
        else:
            self.caption.setText((self._displayed_time or self._time_text) + ' · 预览中')
        video = self.tile.video
        width = max(1, min(224, video.width() - 24, round(video.height() * .70)))
        self.label.setFixedSize(width, round(width * 9 / 16))
        self.card.adjustSize()
        self._place()
        self.card.show()
        if (media != self._displayed and media != previous and not self.timer.isActive()
                and self.process.state() == QProcess.NotRunning):
            self.timer.start()

    def _decode(self):
        if self._request is None or self.process.state() != QProcess.NotRunning:
            return
        path, seconds = self._running = self._request
        self._running_time = self._time_text
        self.process.start(self.executable, ['-nostdin', '-hide_banner', '-loglevel', 'error',
            '-ss', f'{seconds:.3f}', '-i', str(path), '-frames:v', '1',
            '-vf', 'scale=224:126:force_original_aspect_ratio=decrease', '-threads', '1',
            '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'])

    def _finished(self, code, _status):
        data = self.process.readAllStandardOutput()
        self.process.readAllStandardError()
        if self._request is None:
            return
        media = self._request
        if self._running != media and self._displayed == media:
            return
        current = self._running == media
        picture = QPixmap()
        if code == 0 and picture.loadFromData(data):
            self._displayed = self._running
            self._displayed_time = self._time_text if current else self._running_time
            self.label.setPixmap(picture.scaled(self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.label.show()
            self.caption.raise_()
            self.caption.setText(self._displayed_time + ('' if current else ' · 预览中'))
        elif current:
            self.label.hide()
            self.caption.setText(self._time_text + ' · 暂无画面')
        if not current:
            self.timer.start()
        self.card.adjustSize()
        self._place()

    def _place(self):
        video = self.tile.video
        bounds = QRect(video.mapToGlobal(QPoint()), video.size())
        area = bounds.intersected(self.slider.screen().availableGeometry())
        if not area.isValid():
            area = bounds
        bottom = min(area.bottom() + 1, self.slider.mapToGlobal(QPoint()).y())
        self.card.move(area.left() + 8, max(area.top(), bottom - self.card.height() - 8))

    def hide(self):
        self._request = self._displayed = None
        self._displayed_time = ''
        self.timer.stop()
        self.label.hide()
        self.card.hide()

    def stop(self):
        self.hide()
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(500)
