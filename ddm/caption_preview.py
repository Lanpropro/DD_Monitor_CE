"""Interactive settings preview using the same caption renderer and gestures."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget
from . import theme
from .video_caption import CaptionStyle, VideoCaption


class CaptionPlacementPreview(QWidget):
    styleChanged = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.setAccessibleName('字幕位置与大小预览')
        self.setToolTip('拖动字幕移动位置，拖动右下角缩放；双击恢复位置和大小')
        self.video = QWidget(self)
        self.video.setStyleSheet('background: #15191f; border-radius: 12px;')
        self.caption = VideoCaption(self, embedded=True)
        self.caption.styleChanged.connect(self._edited)
        self._style = CaptionStyle()
        self.set_style(self._style.as_dict())

    def set_style(self, value):
        self._style = CaptionStyle.from_value(value)
        style = dict(self._style.as_dict(), locked=False)
        self.caption.set_caption('今日はみんなとゲームを楽しみます。', '今天和大家一起享受游戏。', style=style)

    def _edited(self, value):
        value = dict(value, locked=self._style.locked)
        self._style = CaptionStyle.from_value(value)
        self.styleChanged.emit(self._style.as_dict())

    def resizeEvent(self, event):
        self.video.setGeometry(self.rect().adjusted(4, 4, -4, -4))
        self.caption.sync_geometry()
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.caption.sync_geometry()
