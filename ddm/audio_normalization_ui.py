"""Time-response editor for playback loudness normalization."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QBoxLayout, QDoubleSpinBox, QGridLayout, QHBoxLayout,
                               QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget)

from .audio_normalization import FIELDS, LIMITS, PRESETS, normalize_curve, preset_curve, response_preview


REFERENCES = {
    'gentle': ('缓慢接近整体音量，短暂停顿时保持增益。建议从这里开始试听。', ''),
    'spotify': ('参考不同歌曲之间响度接近的思路，目标为 −14 LUFS。时间响应由本软件设定。',
                'https://support.spotify.com/au/artists/article/loudness-normalization/'),
    'netflix': ('参考节目之间响度一致、保留动态的思路。本软件设为 −24 LUFS，不进行对白识别。',
                'https://netflixtechblog.com/optimizing-the-aural-experience-on-android-devices-with-xhe-aac-c27714292a33'),
    'apple_music': ('参考 Sound Check 的歌曲音量一致性目标。本软件设为 −18 LUFS，非 Apple 公布参数。',
                    'https://support.apple.com/en-us/109331'),
    'custom': ('拖动曲线上的时间节点，或修改下方数值。保存后应用于所有播放格子。', ''),
}


class ResponseGraph(QWidget):
    changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 220)
        self.setAccessibleName('音量均衡时间响应曲线')
        self.setToolTip('横向拖动三个节点，调整压低、保持和恢复时间；也可使用下方数值框。')
        self.settings = normalize_curve()
        self._drag = None
        self._xmax = 20.

    def set_settings(self, settings):
        self.settings = normalize_curve(settings)
        if self._drag is None:
            total = sum(self.settings[key] for key in ('attack', 'hold', 'release'))
            self._xmax = max(5., math.ceil(total / 5) * 5 + 1)
        self.update()

    def plot_rect(self):
        return QRectF(48, 26, max(1, self.width() - 68), max(1, self.height() - 66))

    def position(self, instant, gain):
        rect = self.plot_rect()
        return QPointF(rect.left() + instant / self._xmax * rect.width(),
                       rect.top() + (1 - gain) / 9 * rect.height())

    def handles(self):
        attack, hold, release = (self.settings[key] for key in ('attack', 'hold', 'release'))
        depth = -min(6., self.settings['max_cut_db'])
        return [self.position(attack, depth * .95),
                self.position(attack + hold, depth * .95),
                self.position(attack + hold + release, depth * .05)]

    def paintEvent(self, event):
        from . import theme
        from .settings_material import base_color
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        background = base_color(self, 'card', None)
        brush = theme.qcolor(background) if background else self.palette().base()
        painter.fillRect(self.rect(), brush)
        rect = self.plot_rect()
        painter.setPen(self.palette().text().color())
        painter.drawText(12, 17, '增益 dB')
        for gain in (0, -3, -6):
            y = self.position(0, gain).y()
            color = self.palette().text().color()
            color.setAlpha(35)
            painter.setPen(color)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(self.palette().text().color())
            painter.drawText(QRectF(2, y - 10, 37, 20), Qt.AlignRight | Qt.AlignVCenter, str(gain))
        for index in range(5):
            instant = self._xmax * index / 4
            x = self.position(instant, 0).x()
            painter.drawText(QRectF(x - 24, rect.bottom() + 7, 48, 20), Qt.AlignCenter, f'{instant:g}s')
        path = QPainterPath()
        for index, (instant, gain) in enumerate(response_preview(self.settings)):
            point = self.position(instant, gain)
            path.moveTo(point) if index == 0 else path.lineTo(point)
        accent = self.palette().highlight().color()
        painter.setPen(QPen(accent, 2.5))
        painter.drawPath(path)
        for index, point in enumerate(self.handles()):
            painter.setBrush(accent if index == self._drag else brush)
            painter.drawEllipse(point, 5, 5)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            distances = [(point - event.position()).manhattanLength() for point in self.handles()]
            closest = min(range(3), key=distances.__getitem__)
            if distances[closest] <= 20:
                self._drag = closest
                self.setCursor(Qt.SizeHorCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            instant = (event.position().x() - self.plot_rect().left()) / self.plot_rect().width() * self._xmax
            curve = dict(self.settings, preset='custom')
            key = ('attack', 'hold', 'release')[self._drag]
            previous = sum(curve[name] for name in ('attack', 'hold', 'release')[:self._drag])
            curve[key] = instant - previous
            self.changed.emit(normalize_curve(curve))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self.unsetCursor()
            self.set_settings(self.settings)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AudioNormalizationEditor(QWidget):
    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.curve = normalize_curve(settings)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)
        heading = QLabel('调整压低、保持和恢复速度')
        heading.setObjectName('PageTitle')
        outer.addWidget(heading)
        hint = QLabel('示意：声音短时变响后，增益压低并逐渐恢复。下图使用与播放相同的响应计算，不是实时音频。')
        hint.setWordWrap(True)
        outer.addWidget(hint)
        self.body = QBoxLayout(QBoxLayout.TopToBottom)
        outer.addLayout(self.body, 1)
        self.main_panel = QWidget()
        editor = QVBoxLayout(self.main_panel)
        editor.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.main_panel, 1)
        self.graph = ResponseGraph()
        self.graph.changed.connect(self.set_curve)
        editor.addWidget(self.graph, 1)
        controls = QGridLayout()
        editor.addLayout(controls)
        labels = ('目标响度', '最大放大', '最大压低', '压低时间（95%）', '保持时间', '恢复时间（95%）')
        tips = ('目标越高，整体声音越响；实际补偿受放大和压低上限约束。',
                '限制偏轻声音的放大量，也限制背景声被抬高的程度。',
                '限制偏响声音的压低量。',
                '声音变响时，达到目标增益变化95%所需的时间；越大越缓慢。',
                '恢复音量前保持当前增益，避免说话短暂停顿时抬高背景声。',
                '保持结束后，达到恢复变化95%所需的时间；越大越缓慢。')
        self.controls = {}
        for index, (key, limits, label) in enumerate(zip(FIELDS, LIMITS, labels)):
            row, column = divmod(index, 3)
            field = QVBoxLayout()
            field.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(*limits)
            spin.setDecimals(2)
            spin.setSingleStep(.1 if index >= 3 else 1.)
            spin.setSuffix(' s' if index >= 3 else ' LUFS' if index == 0 else ' dB')
            spin.setAccessibleName(label)
            spin.setToolTip(tips[index])
            spin.valueChanged.connect(self._edited)
            self.controls[key] = spin
            field.addWidget(spin)
            controls.addLayout(field, row, column)
        self.reference_panel = QWidget()
        side = QVBoxLayout(self.reference_panel)
        side.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.reference_panel)
        side.addWidget(QLabel('参考预设'))
        self.presets = QListWidget()
        self.presets.setAccessibleName('音量均衡参考预设')
        self.presets.setMaximumHeight(160)
        self._preset_names = [*PRESETS, 'custom']
        self.presets.addItems([value[0] for value in PRESETS.values()] + ['自定义'])
        self.presets.currentRowChanged.connect(self._select_preset)
        side.addWidget(self.presets)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setOpenExternalLinks(True)
        side.addWidget(self.description)
        note = QLabel('这些是本软件的参考预设，非平台官方算法。直播无法预先测完整节目，参数仍可自由调整。')
        note.setWordWrap(True)
        side.addWidget(note)
        side.addStretch()
        buttons = QHBoxLayout()
        outer.addLayout(buttons)
        reset = QPushButton('恢复平缓默认')
        reset.setObjectName('IconButton')
        reset.clicked.connect(self._reset)
        buttons.addWidget(reset)
        buttons.addStretch()
        self.set_curve(self.curve)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        stacked = self.width() < 650
        self.body.setDirection(QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self.reference_panel.setMinimumWidth(0 if stacked else 210)
        self.reference_panel.setMaximumWidth(16777215 if stacked else 210)
        self.main_panel.setMinimumHeight(self.main_panel.layout().minimumSize().height())
        self.layout().activate()
        self.setMinimumHeight(max(self.layout().minimumSize().height(),
                                  self.layout().totalHeightForWidth(self.width())))

    def _reset(self):
        self.set_curve(preset_curve())

    def _edited(self):
        self.set_curve(dict(preset='custom', **{key: control.value() for key, control in self.controls.items()}))

    def _select_preset(self, row):
        if 0 <= row < len(PRESETS):
            self.set_curve(preset_curve(self._preset_names[row]))
        elif row == len(PRESETS):
            self.set_curve(dict(self.curve, preset='custom'))

    def set_curve(self, curve):
        self.curve = normalize_curve(curve)
        for key, spin in self.controls.items():
            spin.blockSignals(True)
            spin.setValue(self.curve[key])
            spin.blockSignals(False)
        self.presets.blockSignals(True)
        self.presets.setCurrentRow(self._preset_names.index(self.curve['preset']))
        self.presets.blockSignals(False)
        description, url = REFERENCES[self.curve['preset']]
        self.description.setText(description + (f'<br><br><a href="{url}">查看公开说明 ↗</a>' if url else ''))
        self.graph.set_settings(self.curve)

    def values(self):
        return dict(self.curve)
