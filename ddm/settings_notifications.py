"""Settings notifications; owned page implementations with legacy exports in dialogs."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
)
from . import theme
from .ui import SettingsSlider, SettingsValueLabel, SettingsSurface, ToggleSwitch, page_header as _page_head
from .settings_layout import SettingsColumns


class NotificationSwitch(ToggleSwitch):
    """Compatibility name for the shared settings switch."""


class NoticeBlurPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        from .room_artwork import RoomArtwork
        self.setFixedSize(180, 86)
        self.setAccessibleName('通知 Banner 模糊效果示例')
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

    def set_strength(self, value):
        self.strength = value
        self.update()

    def paintEvent(self, event):
        from .room_artwork import paint_room_background
        painter = QPainter(self)
        paint_room_background(painter, self.rect(), self.artwork.source, 8,
                              focus=False, frost=self.artwork.frosted(self.strength))
        painter.setPen(QColor('#ffffff'))
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(12, 10, -8, -8), Qt.AlignLeft | Qt.AlignTop, '开播提醒')
        painter.drawText(self.rect().adjusted(12, 32, -8, -8), Qt.AlignLeft | Qt.AlignTop, '示例主播开播了')


class NotificationSettingsPage(QWidget):
    ITEMS = [
        ('notifications_enabled', '开启通知'),
        ('live_alert', '启用开播提醒（顶部提示与关注栏动效）'),
        ('notice_hide_fullscreen', '全屏时不弹出通知'),
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
        descriptions = (
            '显示软件、开播、更新和操作结果等浮动通知；关闭后仍可在通知面板查看历史。',
            '主播开播时显示浮动提醒，并突出关注卡片。',
            '全屏观看时不显示浮动通知，仍可在通知面板查看。',
            '发现新版本时，保留更新入口。',
            '重要主播的开播提醒不自动消失。',
            '未置顶主播的开播提醒是否持续显示。',
            '保留异常提示，方便稍后查看与处理。',
            '录制、保存等操作结果是否持续显示。',
        )
        for index, (key, label) in enumerate(self.ITEMS):
            if index in (0, 3):
                card = SettingsSurface()
                card.setObjectName('NotificationSettingsGroup')
                rows = QVBoxLayout(card)
                rows.setContentsMargins(14, 12, 14, 10)
                rows.setSpacing(6)
                heading = QLabel('通知与开播提醒' if index == 0 else '浮动通知停留方式')
                heading.setObjectName('NotificationSettingsHeading')
                rows.addWidget(heading)
                if index == 3:
                    hint = QLabel('关闭常驻后自动收起，仍可在通知面板查看。')
                    hint.setObjectName('SettingsHint')
                    hint.setWordWrap(True)
                    rows.addWidget(hint)
                groups.addWidget(card)
            if index not in (0, 3):
                separator = QFrame()
                separator.setObjectName('NotificationSettingsDivider')
                separator.setFixedHeight(1)
                rows.addWidget(separator)
            row = QHBoxLayout()
            row.setContentsMargins(0, 6, 0, 6)
            row.setSpacing(8)
            text = QVBoxLayout()
            text.setSpacing(3)
            title = QLabel('接收开播提醒' if index == 1 else label)
            title.setWordWrap(True)
            text.addWidget(title)
            description = QLabel(descriptions[index])
            description.setWordWrap(True)
            description.setObjectName('SettingsHint')
            text.addWidget(description)
            row.addLayout(text, 1)
            state = QLabel()
            state.setObjectName('NotificationSettingsState')
            row.addWidget(state)
            box = NotificationSwitch(title.text())
            box.setAccessibleDescription(descriptions[index])
            box.setChecked(bool(settings.get(key, DEFAULT_SETTINGS[key])))
            def update_state(checked, state=state,
                             simple=key in ('notifications_enabled', 'live_alert', 'notice_hide_fullscreen')):
                state.setText(('已启用' if checked else '已关闭') if simple
                              else ('手动关闭' if checked else '自动收起'))
            box.toggled.connect(update_state)
            update_state(box.isChecked())
            self._checks[key] = box
            self._states[key] = state
            row.addWidget(box)
            rows.addLayout(row)
        card = SettingsSurface()
        card.setObjectName('NotificationSettingsGroup')
        blur_layout = QVBoxLayout(card)
        blur_layout.setContentsMargins(14, 12, 14, 12)
        row = QHBoxLayout()
        controls = QVBoxLayout()
        controls.addWidget(QLabel('Banner 毛玻璃模糊强度'))
        slider_row = QHBoxLayout()
        self.banner_blur = SettingsSlider()
        self.banner_blur.setRange(0, 40)
        self.banner_blur.setAccessibleName('Banner 毛玻璃模糊强度')
        self.banner_blur.setValue(int(settings.get('notice_banner_blur', DEFAULT_SETTINGS['notice_banner_blur'])))
        slider_row.addWidget(self.banner_blur, 1)
        self.banner_blur_value = SettingsValueLabel()
        slider_row.addWidget(self.banner_blur_value)
        slider_row.addStretch(1)
        controls.addLayout(slider_row)
        row.addLayout(controls, 1)
        self.banner_preview = NoticeBlurPreview()
        row.addWidget(self.banner_preview)
        self.banner_blur.valueChanged.connect(self._update_banner_blur)
        self._update_banner_blur(self.banner_blur.value())
        blur_layout.addLayout(row)
        hint = QLabel('数值越大，通知背景越模糊；0 为关闭，文字和头像保持清晰。')
        hint.setObjectName('SettingsHint')
        hint.setWordWrap(True)
        blur_layout.addWidget(hint)
        cards = [groups.itemAt(index).widget() for index in range(groups.count())]
        for existing in cards:
            groups.removeWidget(existing)
            existing.layout().addStretch(1)
        self.sections = SettingsColumns()
        self.sections.add_section('background', card, wide=True)
        self.sections.add_section('live', cards[0])
        self.sections.add_section('persistence', cards[1])
        groups.addWidget(self.sections)
        groups.addStretch(1)

    def _update_banner_blur(self, value):
        self.banner_blur_value.setText(str(value) if value else '关闭')
        self.banner_preview.set_strength(value)

    def reset(self):
        from .config import DEFAULT_SETTINGS
        for key, box in self._checks.items():
            box.setChecked(DEFAULT_SETTINGS[key])
        self.banner_blur.setValue(DEFAULT_SETTINGS['notice_banner_blur'])

    def values(self):
        return {**{key: box.isChecked() for key, box in self._checks.items()},
                'notice_banner_blur': self.banner_blur.value()}
