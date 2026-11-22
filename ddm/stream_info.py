"""Read-only, per-tile stream information and its live display."""
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QFormLayout, QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from .settings_window import SettingsWindow
from .ui import SettingsSurface, TitleLabel


FIELDS = (
    ('state', '播放状态'), ('format', '封装格式'), ('core', '播放内核'),
    ('video', '视频信息'), ('audio', '音频信息'), ('encoder', '流编码器'),
    ('host', '流服务器'), ('buffer', '缓冲长度'), ('decode', '解码统计'),
    ('video_bitrate', '视频码率'), ('download', '下载速率'),
)
STATES = {'idle': '未播放', 'connecting': '连接中', 'playing': '播放中',
          'buffering': '缓冲中', 'frozen': '画面停滞', 'error': '播放失败', 'paused': '已暂停'}


def _number(value, divisor=1, suffix='', digits=2):
    if value is None or not math.isfinite(float(value)) or float(value) < 0:
        return ''
    text = f'{float(value) / divisor:.{digits}f}'.rstrip('0').rstrip('.') if digits else str(int(value))
    return text + suffix


def _bitrate(value):
    if value is None:
        return ''
    return (_number(value, 1_000_000, ' Mbps') if value >= 1_000_000
            else _number(value, 1000, ' kbps'))


def _joined(*parts):
    return ' · '.join(str(part) for part in parts if part) or '未知'


def format_stream_info(info):
    video, audio = info.get('video') or {}, info.get('audio') or {}
    width, height = video.get('w'), video.get('h')
    resolution = f'{width}×{height}' if width and height else ''
    channels = audio.get('hr-channels') or audio.get('channels') or ''
    channels = {'stereo': '立体声', 'mono': '单声道'}.get(channels, channels)
    decoder = info.get('decoder') or ''
    decoder = '软件解码' if decoder == 'no' else decoder
    drops = [_number(info.get(key), digits=0) or '未知' for key in ('decoder_drops', 'display_drops')]
    download = _bitrate(info.get('download_bps'))
    if download and info.get('download_estimated'):
        download += '（分片估算）'
    return {
        'state': STATES.get(info.get('state'), '未播放'),
        'format': info.get('format') or '未知', 'core': info.get('core') or 'libmpv',
        'video': _joined(resolution, _number(info.get('fps'), suffix=' FPS'), info.get('video_codec'), decoder),
        'audio': _joined(info.get('audio_codec'), _number(audio.get('samplerate'), 1000, ' kHz'),
                         channels, _bitrate(info.get('audio_bitrate'))),
        'encoder': info.get('encoder') or '未知', 'host': info.get('host') or '未知',
        'buffer': _joined(_number(info.get('buffer_seconds'), suffix=' 秒'),
                          _number(info.get('buffer_bytes'), 1024 * 1024, ' MiB')),
        'decode': _joined(_number(info.get('decode_fps'), suffix=' FPS'),
                         f'丢帧 {drops[0]} / {drops[1]}（解码 / 显示）'),
        'video_bitrate': _bitrate(info.get('video_bitrate')) or '未知',
        'download': download or '未知',
    }


class StreamInfoDialog(SettingsWindow):
    def __init__(self, snapshot, parent=None, *, settings=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.setWindowTitle('直播流信息')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.window_header.breadcrumb.setText('直播流信息')
        self.window_header.close_button.setAccessibleName('关闭直播流信息')
        self.window_header.close_button.setToolTip('关闭直播流信息')
        scroll = QScrollArea(self)
        scroll.setObjectName('SettingsPage')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName('SettingsPage')
        scroll.setWidget(content)
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        self.body_layout.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 4, 12, 8)
        layout.setSpacing(8)
        overview = QHBoxLayout()
        self.room = QLabel()
        self.room.setTextFormat(Qt.PlainText)
        self.room.setWordWrap(True)
        self.room.setObjectName('SettingsTitle')
        overview.addWidget(self.room, 1)
        self.values = {}
        status = self._value('state')
        status.setObjectName('SettingsValue')
        status.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        status.setAccessibleName('播放状态')
        overview.addWidget(status, 0, Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(overview)
        layout.addWidget(self._card('媒体与解码', ('format', 'core', 'video', 'audio', 'encoder', 'decode')))
        layout.addWidget(self._card('连接与传输', ('host', 'buffer', 'video_bitrate', 'download')))
        layout.addStretch(1)
        self.set_material(settings or {})
        area = (parent.screen() if parent is not None else self.screen()).availableGeometry()
        self.resize(min(560, area.width() - 24), min(452, area.height() - 24))
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)

    def _value(self, key):
        label = QLabel()
        label.setTextFormat(Qt.PlainText)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.values[key] = label
        return label

    def _card(self, title, keys):
        card = SettingsSurface(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
        heading = TitleLabel(title)
        heading.setObjectName('SettingsSectionTitle')
        layout.addWidget(heading)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(5)
        titles = dict(FIELDS)
        for key in keys:
            label = QLabel(titles[key])
            label.setObjectName('SettingsHint')
            value = self._value(key)
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            form.addRow(label, value)
        layout.addLayout(form)
        return card

    def set_presentation_owner(self, owner):
        # The full-screen tile is a separate native window, not the main window.
        owner.winId()
        self.winId()
        self.windowHandle().setTransientParent(owner.windowHandle())

    def position_for_tile(self, tile):
        anchor = tile.mapToGlobal(tile.rect().topRight())
        screen = QApplication.screenAt(anchor) or tile.screen()
        area = screen.availableGeometry()
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
        x = anchor.x() - 10 - self.width() + 1
        y = anchor.y() + 10
        self.move(max(area.left(), min(x, area.right() - self.width() + 1)),
                  max(area.top(), min(y, area.bottom() - self.height() + 1)))

    def set_material(self, settings):
        super().set_material({key: settings[key] for key in
                              ('settings_glass_enabled', 'settings_glass_opacity', 'settings_no_shadows')
                              if key in settings})

    def refresh(self):
        info = self.snapshot()
        if info is None:
            self.close()
            return
        self.room.setText(info.get('room', ''))
        for key, value in format_stream_info(info).items():
            self.values[key].setText(value)

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
        if self.isVisible():
            self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
