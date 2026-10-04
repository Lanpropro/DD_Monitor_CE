"""画面格右下角的弹幕观看设置，拖动时实时生效。"""
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QMenu, QSlider, QWidget, QWidgetAction

from . import theme
from .config import DEFAULT_SETTINGS


class VideoDanmakuSettings(QMenu):
    settingsChanged = Signal(dict)
    advancedRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VideoDanmakuSettings")
        self.setStyleSheet(f"""
            QSlider::sub-page:horizontal {{ background: {theme.PINK}; }}
            QSlider::handle:horizontal {{ background: {theme.TEXT1}; }}
        """)
        holder = QWidget(self)
        grid = QGridLayout(holder)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(14)
        self.controls = {}
        self.labels = {}
        for row, (key, label, low, high, suffix) in enumerate((
                ("video_danmaku_area", "显示区域", 10, 100, "%"),
                ("video_danmaku_opacity", "不透明度", 10, 100, "%"),
                ("video_danmaku_size", "字体大小", 12, 64, " px"),
                ("video_danmaku_speed", "弹幕速度", 50, 200, "%"))):
            grid.addWidget(QLabel(label), row, 0)
            slider = QSlider(Qt.Horizontal, holder)
            slider.setRange(low, high)
            slider.setMinimumWidth(140)
            self.controls[key] = slider
            value_label = QLabel()
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value_label.setMinimumWidth(48)
            self.labels[key] = value_label
            slider.valueChanged.connect(
                lambda value, k=key, s=suffix: self._change_value(k, value, s))
            grid.addWidget(slider, row, 1)
            grid.addWidget(value_label, row, 2)
        self.controls["video_danmaku_area"].setToolTip("从画面顶部起占用的高度")
        self.controls["video_danmaku_size"].setToolTip("随屏幕缩放开启时，以 720 像素高的画面为基准")
        self.controls["video_danmaku_speed"].setToolTip("100% 为适中，约 8 秒穿过画面")
        self.scale = QCheckBox("弹幕随屏幕缩放", holder)
        self.scale.toggled.connect(lambda checked: self.settingsChanged.emit({"video_danmaku_scale": checked}))
        grid.addWidget(self.scale, 4, 0, 1, 3)
        hint = QLabel("观看设置应用于所有格子")
        hint.setObjectName("SettingsHint")
        grid.addWidget(hint, 5, 0, 1, 3)
        wrapper = QWidgetAction(self)
        wrapper.setDefaultWidget(holder)
        self.addAction(wrapper)
        self.addSeparator()
        self.addAction("更多弹幕设置", self.advancedRequested.emit)

    def _change_value(self, key: str, value: int, suffix: str) -> None:
        self.labels[key].setText(f"{value}{suffix}")
        self.settingsChanged.emit({key: value})

    def apply_settings(self, settings: dict) -> None:
        for key, slider in self.controls.items():
            value = int(settings.get(key) or DEFAULT_SETTINGS[key])
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
            suffix = " px" if key == "video_danmaku_size" else "%"
            self.labels[key].setText(f"{slider.value()}{suffix}")
        self.scale.blockSignals(True)
        self.scale.setChecked(bool(settings.get("video_danmaku_scale", True)))
        self.scale.blockSignals(False)

    def open_at(self, button, settings: dict) -> None:
        self.apply_settings(settings)
        self.ensurePolished()
        self.adjustSize()
        anchor = button.mapToGlobal(QPoint(button.width(), 0))
        screen = button.screen().availableGeometry()
        x = max(screen.left(), min(anchor.x() - self.width(), screen.right() - self.width() + 1))
        y = anchor.y() - self.height() - 6
        if y < screen.top():
            y = button.mapToGlobal(button.rect().bottomLeft()).y() + 6
        self.popup(QPoint(x, min(y, screen.bottom() - self.height() + 1)))
