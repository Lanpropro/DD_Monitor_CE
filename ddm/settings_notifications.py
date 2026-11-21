"""Settings notifications; owned page implementations with legacy exports in dialogs."""
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
)
from . import theme
from .ui import SegmentedControl, SettingsSlider, SettingsValueLabel, ToggleSwitch, page_header as _page_head
from .settings_layout import SettingsColumns, SettingsSection


class NotificationSwitch(ToggleSwitch):
    """Compatibility name for the shared settings switch."""


class NotificationRetentionControl(SegmentedControl):
    """Keep boolean settings compatibility with the shared two-choice control."""
    toggled = Signal(bool)

    def __init__(self, title):
        super().__init__((('auto', '自动收起'), ('manual', '手动关闭')))
        self.setAccessibleName(title)
        self.valueChanged.connect(lambda _value: self.toggled.emit(self.isChecked()))

    def minimumSizeHint(self):
        return self.sizeHint()

    def isChecked(self):
        return self.value() == 'manual'

    def setChecked(self, checked):
        self.setValue('manual' if checked else 'auto')

    def click(self):
        self.setChecked(not self.isChecked())


class NoticeBlurPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        from .room_artwork import RoomArtwork
        self.setFixedHeight(100)
        self.setMaximumWidth(260)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setAccessibleName('通知背景模糊效果示例')
        self.artwork = RoomArtwork(())
        self.artwork.banner = QPixmap(640, 280)
        painter = QPainter(self.artwork.banner)
        from PySide6.QtGui import QLinearGradient, QPainterPath
        gradient = QLinearGradient(0, 0, 640, 280)
        gradient.setColorAt(0, QColor('#e7a968'))
        gradient.setColorAt(1, QColor('#6858a8'))
        painter.fillRect(self.artwork.banner.rect(), gradient)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#ffe2b4'))
        painter.drawEllipse(440, 34, 80, 80)
        painter.setBrush(QColor('#344f75'))
        hills = QPainterPath()
        hills.moveTo(0, 280)
        for x, y in ((0, 170), (150, 84), (290, 204), (420, 120), (640, 210), (640, 280)):
            hills.lineTo(x, y)
        painter.drawPath(hills)
        painter.end()
        self.strength = 16
        self.banner_enabled = True

    def sizeHint(self):
        return QSize(260, 100)

    def set_strength(self, value):
        self.strength = value
        self.update()

    def set_banner_enabled(self, enabled):
        self.banner_enabled = enabled
        self.update()

    def paintEvent(self, event):
        from .room_artwork import paint_room_background
        painter = QPainter(self)
        if self.banner_enabled:
            paint_room_background(painter, self.rect(), self.artwork.source, 8,
                                  focus=False, frost=self.artwork.frosted(self.strength))
        else:
            from .corner_geometry import continuous_path
            painter.fillPath(continuous_path(QRectF(self.rect()), 8), theme.qcolor(theme.ELEVATED))
        painter.setPen(QColor('#ffffff') if self.banner_enabled else theme.qcolor(theme.TEXT1))
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(12, 10, -8, -8), Qt.AlignLeft | Qt.AlignTop, '开播提醒')
        painter.drawText(self.rect().adjusted(12, 32, -8, -8), Qt.AlignLeft | Qt.AlignTop, '示例主播开播了')


class NotificationSettingsPage(QWidget):
    ITEMS = [
        ('notifications_enabled', '显示应用内通知'),
        ('live_alert', '启用开播提醒（顶部提示与关注栏动效）'),
        ('notice_hide_fullscreen', '全屏时不弹出通知'),
        ('notice_windows_recording', '使用 Windows 通知'),
        ('notice_persist_updates', '软件和插件更新'),
        ('notice_persist_pinned_live', '置顶主播开播'),
        ('notice_persist_live', '其他主播开播'),
        ('notice_persist_warning', '警告和失败提示'),
        ('notice_persist_info', '普通操作结果'),
    ]

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        from .config import DEFAULT_SETTINGS
        self.setObjectName('SettingsPage')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(_page_head('通知', '决定哪些提醒及时出现，以及哪些提示需要你手动关闭。'))
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)
        groups = QVBoxLayout(content)
        groups.setContentsMargins(0, 0, 6, 0)
        groups.setSpacing(12)
        self._checks = {}
        self._states = {}
        self.sections = SettingsColumns(content)
        groups.addWidget(self.sections)

        reception = SettingsSection('接收通知')
        persistence = SettingsSection('停留方式')
        for card in (reception, persistence):
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
            card.grid.setColumnStretch(0, 1)
            card.grid.setColumnStretch(1, 0)
        descriptions = (
            '显示更新、开播和操作结果；关闭后仍可在通知菜单查看历史。',
            '主播开播时显示通知，并突出关注卡片。',
            '全屏观看时隐藏浮动通知，仍可在通知菜单查看。',
            '将主播开播并开启自动录制、下播并停止自动录制同步到 Windows 通知中心。',
            '发现新版本时保留更新入口。',
            '置顶主播开播后保留提醒。',
            '其他主播开播后保留提醒。',
            '保留异常提示，方便稍后处理。',
            '保留录制、保存等操作结果。',
        )
        reception_count = 4
        for index, (key, label) in enumerate(self.ITEMS):
            simple = index < reception_count
            card = reception if simple else persistence
            title = QLabel('接收开播提醒' if index == 1 else label)
            title.setWordWrap(True)
            box = NotificationSwitch(title.text()) if simple else NotificationRetentionControl(title.text())
            title.setBuddy(box if simple else box.buttons['auto'])
            box.setAccessibleDescription(descriptions[index])
            box.setChecked(bool(settings.get(key, DEFAULT_SETTINGS[key])))
            state = QLabel(card)
            state.setObjectName('SettingsHint')
            def update_state(checked, state=state, simple=simple):
                state.setText(('已启用' if checked else '已关闭') if simple
                              else ('手动关闭' if checked else '自动收起'))
            box.toggled.connect(update_state)
            update_state(box.isChecked())
            controls = QHBoxLayout()
            controls.setSpacing(10)
            if simple:
                controls.addWidget(state)
            else:
                state.hide()
            controls.addWidget(box)
            row = index if simple else index - reception_count
            card.grid.addWidget(title, row, 0)
            card.grid.addLayout(controls, row, 1, Qt.AlignRight)
            self._checks[key] = box
            self._states[key] = state
        for card, row, text in (
                (reception, reception_count, 'Windows 通知只发送已启用自动录制的主播的开录和下播收尾提醒。应用内通知仍保留历史。'),
                (persistence, 5, '选择自动收起后提示会自行消失；手动关闭会持续保留，两种方式均可在通知菜单查看记录。')):
            hint = QLabel(text)
            hint.setObjectName('SettingsHint')
            hint.setWordWrap(True)
            card.grid.addWidget(hint, row, 0, 1, 2)

        background = SettingsSection('背景预览')
        background.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        self.background_columns = SettingsColumns(respect_preference=False)
        controls, example = QWidget(), QWidget()
        control_box, preview_box = QVBoxLayout(controls), QVBoxLayout(example)
        for box in (control_box, preview_box):
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(12)
        banner_row = QHBoxLayout()
        self.banner_enabled = ToggleSwitch('显示通知背景图')
        self.banner_enabled.setChecked(bool(settings.get('notice_banner_enabled', DEFAULT_SETTINGS['notice_banner_enabled'])))
        banner_label = QLabel('显示通知背景图')
        banner_label.setBuddy(self.banner_enabled)
        banner_row.addWidget(banner_label, 1)
        banner_row.addWidget(self.banner_enabled)
        control_box.addLayout(banner_row)
        control_box.addWidget(QLabel('背景模糊强度'))
        slider_row = QHBoxLayout()
        self.banner_blur = SettingsSlider()
        self.banner_blur.setRange(0, 40)
        self.banner_blur.setAccessibleName('通知背景模糊强度')
        self.banner_blur.setValue(int(settings.get('notice_banner_blur', DEFAULT_SETTINGS['notice_banner_blur'])))
        slider_row.addWidget(self.banner_blur)
        self.banner_blur_value = SettingsValueLabel()
        slider_row.addWidget(self.banner_blur_value)
        slider_row.addStretch(1)
        control_box.addLayout(slider_row)
        hint = QLabel('关闭背景图后使用普通通知底色；模糊强度为0时保留清晰背景图。')
        hint.setObjectName('SettingsHint')
        hint.setWordWrap(True)
        control_box.addWidget(hint)
        control_box.addStretch(1)
        self.banner_preview = NoticeBlurPreview()
        preview_box.addWidget(self.banner_preview, 0, Qt.AlignRight)
        preview_box.addStretch(1)
        self.background_columns.add_section('controls', controls)
        self.background_columns.add_section('example', example)
        background.grid.addWidget(self.background_columns, 0, 0, 1, 2)
        self.banner_blur.valueChanged.connect(self._update_banner_blur)
        self.banner_enabled.toggled.connect(self._update_banner_enabled)
        self._update_banner_enabled(self.banner_enabled.isChecked())
        self._update_banner_blur(self.banner_blur.value())
        self.sections.add_section('background', background, wide=True)
        self.sections.add_section('live', reception)
        self.sections.add_section('persistence', persistence)
        groups.addStretch(1)

    def _update_banner_blur(self, value):
        self.banner_blur_value.setText(str(value) if value else '关闭')
        self.banner_preview.set_strength(value)

    def _update_banner_enabled(self, enabled):
        self.banner_blur.setEnabled(enabled)
        self.banner_blur_value.setEnabled(enabled)
        self.banner_preview.set_banner_enabled(enabled)

    def reset(self):
        from .config import DEFAULT_SETTINGS
        for key, box in self._checks.items():
            box.setChecked(DEFAULT_SETTINGS[key])
        self.banner_blur.setValue(DEFAULT_SETTINGS['notice_banner_blur'])
        self.banner_enabled.setChecked(DEFAULT_SETTINGS['notice_banner_enabled'])

    def values(self):
        return {**{key: box.isChecked() for key, box in self._checks.items()},
                'notice_banner_enabled': self.banner_enabled.isChecked(),
                'notice_banner_blur': self.banner_blur.value()}
