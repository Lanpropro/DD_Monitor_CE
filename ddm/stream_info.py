"""Read-only, per-tile stream information and its live display."""
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from .motion import AnimatedDialog


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


class StreamInfoDialog(AnimatedDialog):
    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.setWindowTitle('直播流信息')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(540, 390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        self.room = QLabel()
        self.room.setTextFormat(Qt.PlainText)
        self.room.setWordWrap(True)
        self.room.setObjectName('AppSubtitle')
        layout.addWidget(self.room)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        self.values = {}
        for key, title in FIELDS:
            label = QLabel()
            label.setTextFormat(Qt.PlainText)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
            form.addRow(title, label)
            self.values[key] = label
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText('关闭')
        buttons.button(QDialogButtonBox.Close).setObjectName('IconButton')
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)

    def refresh(self):
        info = self.snapshot()
        if info is None:
            self.close()
            return
        self.room.setText(info.get('room', ''))
        for key, value in format_stream_info(info).items():
            self.values[key].setText(value)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        if self.isVisible():
            self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
