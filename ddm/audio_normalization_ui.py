"""Time-response editor for playback loudness normalization."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QBoxLayout, QDoubleSpinBox, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .ui import SelectControl, StepperControl
from .audio_normalization import FIELDS, LIMITS, PRESETS, normalize_curve, preset_curve, response_preview


REFERENCES = {
    'gentle': ('缓慢接近整体音量，短暂停顿时保持增益。建议从这里开始试听。', ''),
    'spotify': ('参考不同歌曲之间响度接近的思路，目标为 −14 LUFS。时间响应由本软件设定。',
                'https://support.spotify.com/au/artists/article/loudness-normalization/'),
    'netflix': ('参考节目之间响度一致、保留动态的思路。本软件设为 −24 LUFS，不进行对白识别。',
                'https://netflixtechblog.com/optimizing-the-aural-experience-on-android-devices-with-xhe-aac-c27714292a33'),
    'apple_music': ('参考 Sound Check 的歌曲音量一致性目标。本软件设为 −18 LUFS，非 Apple 公布参数。',
                    'https://support.apple.com/en-us/109331'),
    'custom': ('拖动曲线上的时间节点，或修改参数。修改后自动保存，启用音量均衡后用于播放。', ''),
}


class ResponseGraph(QWidget):
    changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 220)
        self.setAccessibleName('音量均衡时间响应曲线')
        self.setToolTip('横向拖动三个节点，调整压低、保持和恢复时间；也可使用参数数值框。')
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
        from .ui.curve_surface import paint_curve_surface
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.plot_rect()
        paint_curve_surface(painter, self, rect)
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
            painter.setBrush(accent if index == self._drag else theme.qcolor('#ffffff'))
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
    changed = Signal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.curve = normalize_curve(settings)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.body = QBoxLayout(QBoxLayout.LeftToRight)
        self.body.setSpacing(24)
        outer.addLayout(self.body)
        self.parameters_panel = QWidget()
        self.parameters_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        editor = QVBoxLayout(self.parameters_panel)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setSpacing(12)
        self.body.addWidget(self.parameters_panel, 4, Qt.AlignTop)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel('参考预设'))
        preset_row.addStretch()
        self.presets = SelectControl()
        self.presets.setAccessibleName('音量均衡参考预设')
        for name, value in PRESETS.items():
            self.presets.addItem(value[0], name)
        self.presets.addItem('自定义', 'custom')
        self.presets.currentIndexChanged.connect(self._select_preset)
        preset_row.addWidget(self.presets)
        editor.addLayout(preset_row)
        self.description = QLabel()
        self.description.setObjectName('SettingsHint')
        self.description.setWordWrap(True)
        self.description.setOpenExternalLinks(True)
        editor.addWidget(self.description)
        controls = QGridLayout()
        controls.setHorizontalSpacing(12)
        controls.setVerticalSpacing(12)
        editor.addLayout(controls)
        labels = ('目标响度', '最大放大', '最大压低', '压低时间（95%）', '保持时间', '恢复时间（95%）')
        tips = ('目标越高，整体声音越响；实际补偿受放大和压低上限约束。',
                '限制偏轻声音的放大量，也限制背景声被抬高的程度。',
                '限制偏响声音的压低量。',
                '声音变响时，达到目标增益变化95%所需的时间；越大越缓慢。',
                '恢复音量前保持当前增益，避免说话短暂停顿时抬高背景声。',
                '保持结束后，达到恢复变化95%所需的时间；越大越缓慢。')
        self.controls = {}
        self.steppers = {}
        for index, (key, limits, label) in enumerate(zip(FIELDS, LIMITS, labels)):
            column, row = divmod(index, 3)
            field = QVBoxLayout()
            field.setSpacing(5)
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
            self.steppers[key] = StepperControl(spin)
            field.addWidget(self.steppers[key], 0, Qt.AlignRight)
            controls.addLayout(field, row, column, Qt.AlignRight)
        reset = QPushButton('恢复平缓默认')
        reset.setObjectName('IconButton')
        reset.clicked.connect(self._reset)
        editor.addWidget(reset, 0, Qt.AlignLeft)
        note = QLabel('这些是本软件的参考预设，非平台官方算法。直播无法预先测完整节目，参数仍可自由调整。')
        note.setObjectName('SettingsHint')
        note.setWordWrap(True)
        editor.addWidget(note)
        self.preview_panel = QWidget()
        self.preview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        preview = QVBoxLayout(self.preview_panel)
        preview.setContentsMargins(0, 0, 0, 0)
        preview.setSpacing(10)
        preview.addWidget(QLabel('时间响应预览'))
        hint = QLabel('声音短时变响后，增益压低并逐渐恢复。横向拖动节点可调整压低、保持和恢复时间。')
        hint.setObjectName('SettingsHint')
        hint.setWordWrap(True)
        preview.addWidget(hint)
        self.graph = ResponseGraph()
        self.graph.setFixedHeight(280)
        self.graph.changed.connect(self.set_curve)
        preview.addWidget(self.graph)
        caption = QLabel('示意曲线使用与播放相同的响应计算，并非实时音频。')
        caption.setObjectName('SettingsHint')
        caption.setWordWrap(True)
        preview.addWidget(caption)
        self.body.addWidget(self.preview_panel, 5, Qt.AlignTop)
        self.set_curve(self.curve)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        stacked = self.width() < 780
        self.body.setDirection(QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self.layout().activate()
        self.setMinimumHeight(max(self.layout().minimumSize().height(),
                                  self.layout().totalHeightForWidth(self.width())))

    def _reset(self):
        self.set_curve(preset_curve())

    def _edited(self):
        self.set_curve(dict(preset='custom', **{key: control.value() for key, control in self.controls.items()}))

    def _select_preset(self, index):
        name = self.presets.itemData(index)
        if name in PRESETS:
            self.set_curve(preset_curve(name))
        elif name == 'custom':
            self.set_curve(dict(self.curve, preset='custom'))

    def set_curve(self, curve):
        previous = self.curve
        self.curve = normalize_curve(curve)
        for key, spin in self.controls.items():
            spin.blockSignals(True)
            spin.setValue(self.curve[key])
            spin.blockSignals(False)
            self.steppers[key]._sync_buttons()
        self.presets.blockSignals(True)
        self.presets.setCurrentIndex(self.presets.findData(self.curve['preset']))
        self.presets.blockSignals(False)
        description, url = REFERENCES[self.curve['preset']]
        self.description.setText(description + (f'<br><br><a href="{url}">查看公开说明 ↗</a>' if url else ''))
        self.graph.set_settings(self.curve)
        if self.curve != previous:
            self.changed.emit()

    def values(self):
        return dict(self.curve)
