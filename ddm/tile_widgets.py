"""One video tile and its controls; player lifecycle remains with its existing host."""
import sys
import time

from PySide6.QtCore import (
    QEasingCurve, QEvent, QMimeData, QPoint, QRect, QRectF, QTimer, QVariantAnimation, Qt, Signal
)
from PySide6.QtGui import (
    QAction, QCursor, QDrag, QFont, QFontMetrics, QPainterPath, QPainterPathStroker, QPixmap,
    QRegion
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QSlider,
    QVBoxLayout, QWidget, QWidgetAction
)

from . import layouts, motion, theme
from .auto_quality import AUTO_QUALITY, OVERSEAS_PLATFORMS
from .config import (
    DEFAULT_SETTINGS, DEFAULT_VOLUME, VIDEO_DANMAKU_SETTING_KEYS, codec_overrides,
    video_danmaku_overrides
)
from .corner_geometry import continuous_path
from .fullscreen_bar import FullscreenBar
from .fullscreen_cursor import set_native_cursor
from .playback_badges import LoadingIndicator, StreamBadge, TimeBadge, TitleBadge
from .playback_controls import (
    DanmakuToggleButton, PauseButton, RecordingButton, RefreshButton, TileButton, VolumeButton,
    VolumePopup
)
from .sidebar_drag import ROOM_MIME
from .ui.labels import ElidedLabel
from .video_danmaku import VideoDanmaku
from .video_danmaku_settings import VideoDanmakuSettings
from .video_surface import VideoCorner, VideoSurface
from .widget_support import (
    DANMAKU_MIME, QUALITY_CHOICES, QUALITY_NAMES, TILE_BAR_HEIGHT, TILE_MIME, WATCHING_TEXT,
    _allow_shrink, _ignore_mouse, _repolish, rounded_pixmap
)


class Tile(QFrame):
    """一个播放格子：画面 + 底部信息条 + 独立控制。"""

    CONTROL_IDLE_SECONDS = 3.0

    clicked = Signal(dict)
    qualityChanged = Signal(dict, int)
    muteToggled = Signal(dict, bool)
    reloadRequested = Signal(dict)
    fullscreenRequested = Signal(object)
    closeRequested = Signal(dict)
    roomDropped = Signal(str)
    tileDropped = Signal(str)          # 拖过来的来源房间号
    paneEditRequested = Signal()
    danmakuPaneDropped = Signal(int)
    danmakuDropped = Signal()          # 弹幕格被拖到本格上
    volumeChanged = Signal(dict, int)
    audioChannelChanged = Signal(dict, int)
    pauseToggled = Signal(dict)
    recordingRequested = Signal()
    codecSettingsRequested = Signal()
    streamInfoRequested = Signal()
    videoDanmakuChanged = Signal(bool)
    videoDanmakuSettingsChanged = Signal(dict)
    videoDanmakuAdvancedRequested = Signal()
    pluginMenuRequested = Signal()     # 右键菜单要弹了，请外部先把插件菜单项填好

    def __init__(self, room: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("Tile")
        #: 插件往本格右键菜单加的项目：[(显示文字, 回调), …]，由外层填
        self.plugin_actions: list = []
        #: 当前这一路的取流结果，插件（录像等）从这里拿
        self.stream_url = ""
        self.stream_profile = ""
        #: 这一路流的视频编码（avc / hevc / av1）。录制要靠它挑装得下的分段容器
        #: —— AV1 装不进 MOV，FFmpeg 会直接拒绝，所以得提前知道编码。
        self.stream_codec = ""
        self.stream_headers: dict = {}
        self.room = dict(room)
        self._cover_source = room.get("cover")
        self._status_text = ""
        self._interactive_resize = False
        self._video_mask_key = None
        self._controls_mask_key = None
        self._cover_key = None
        self._cover_cached = QPixmap()
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("focused", False)
        self.setProperty("empty", False)
        self.setProperty("dropActive", False)
        self.setAcceptDrops(True)
        self.muted = bool(room.get("muted", True))       # 默认静音
        self.quality = int(room.get("quality", AUTO_QUALITY
            if str(room.get("room_id", "")).partition(":")[0] in OVERSEAS_PLATFORMS else 250))
        self.volume = int(room.get("volume", DEFAULT_VOLUME))
        self.audio_channel = int(room.get("audio_channel", 0))
        self.codec_overrides = codec_overrides(room.get("codec_overrides"))
        self.video_danmaku_overrides = video_danmaku_overrides(room.get('video_danmaku_overrides'))
        self._video_danmaku_global_settings = dict(DEFAULT_SETTINGS)
        self.codec_reconnect_pending = False
        self.codec_probe_note = ""
        self._buffering = False
        self.actual_quality = 0
        self.quality_options: list[dict] = []

        # 画面区域：高度扣掉底部信息条，保证画面完整可见
        self.video = VideoSurface(self)
        self.video.setObjectName("TileVideo")
        self.video.setAttribute(Qt.WA_StyledBackground, True)
        self.cover = QLabel(self.video)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setObjectName("TilePlaceholder")
        self.cover.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.video_danmaku = VideoDanmaku(self)
        self.video_danmaku.actionsRequested.connect(self._show_danmaku_actions)
        self.video_corners = (VideoCorner(self), VideoCorner(self, right=True))

        # 信息条（在画面下方，不遮挡画面）：左侧暂停和音量，右侧录制和全屏
        self.bottom = FullscreenBar(self)
        self._bar_progress = 0.0
        self._bar_target = 0.0
        self._bar_animation = QVariantAnimation(self)
        self._bar_animation.setDuration(180)
        self._bar_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._bar_animation.valueChanged.connect(self._slide_fullscreen_bar)
        self._bar_clock = QTimer(self)
        self._bar_clock.setTimerType(Qt.PreciseTimer)
        self._bar_clock.setInterval(16)
        self._bar_clock.timeout.connect(self._advance_bar_animation)
        self.bottom.setObjectName("TileBottom")
        self.bottom.setAttribute(Qt.WA_StyledBackground, True)
        bottom_layout = QHBoxLayout(self.bottom)
        bottom_layout.setContentsMargins(10, 4, 10, 4)
        bottom_layout.setSpacing(8)

        # 左上角浮标：圆形镂空 + LIVE + 直播间人数
        self.stream_badge = StreamBadge(self)
        # 这里只放占位：room["viewers"] 是"人气值"，拿它当在线人数会显示成莫名其妙的好几万
        self.stream_badge.set_state(bool(room.get("live")),
                                    WATCHING_TEXT if room.get("live") and
                                    str(room.get("room_id", "")).isdigit() else "")
        # 左上角第二块浮标：主播名 + 直播间标题（跟在 LIVE 右边）
        self.title_badge = TitleBadge(self)
        self.title_badge.set_text(room.get("uname", ""), room.get("title", ""))
        # 右下角浮标：直播时长
        self.time_badge = TimeBadge(self)
        self.time_badge.setVisible(False)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._refresh_elapsed)

        # 左下角：暂停 / 继续（图形按钮，常驻不用悬停）
        self.pause_button = PauseButton(self)
        self.pause_button.clicked.connect(lambda: self.pauseToggled.emit(self.room))
        bottom_layout.addWidget(self.pause_button, 0, Qt.AlignVCenter)
        self.fullscreen_button = TileButton("⛶")
        self.fullscreen_button.setObjectName("TileCtrl")
        self.fullscreen_button.setFixedSize(28, 26)
        self.fullscreen_button.setToolTip("全屏查看这一路（F）")
        self.fullscreen_button.clicked.connect(lambda: self.fullscreenRequested.emit(self))
        self.recording_button = RecordingButton("● 录制")
        self.recording_button.setObjectName("TileCtrl")
        self.recording_button.setFixedSize(64, 26)
        self.recording_button.setToolTip("开始录制这一路（右键可保存即时回放）")
        self.recording_button.clicked.connect(self.recordingRequested)
        self.danmaku_button = DanmakuToggleButton("弹")
        self.danmaku_button.setObjectName("TileToggle")
        self.danmaku_button.setCheckable(True)
        self.danmaku_button.setFixedSize(34, 26)
        self.danmaku_button.setToolTip("切换这一路的画面弹幕（默认 B）；右侧齿轮可调整观看设置")
        self.danmaku_button.toggled.connect(self._toggle_video_danmaku)
        self.danmaku_button.setChecked(bool(room.get("video_danmaku_enabled", False)))
        self.danmaku_button.setToolTip("关闭画面弹幕（默认 B）" if self.danmaku_button.isChecked()
                                       else "开启画面弹幕（默认 B）")
        self.danmaku_settings_button = TileButton("⚙")
        self.danmaku_settings_button.setObjectName("TileCtrl")
        self.danmaku_settings_button.setFixedSize(26, 26)
        self.danmaku_settings_button.setToolTip("弹幕观看设置：大小、速度、不透明度、显示区域")
        self.danmaku_settings_menu = VideoDanmakuSettings(self)
        self.danmaku_settings_menu.settingsChanged.connect(self._change_video_danmaku_settings)
        self.danmaku_settings_menu.independentChanged.connect(self._set_video_danmaku_independent)
        self.apply_video_danmaku_settings()
        self.danmaku_settings_menu.advancedRequested.connect(self.videoDanmakuAdvancedRequested)
        self.danmaku_settings_button.clicked.connect(
            lambda: self.danmaku_settings_menu.open_at(self.danmaku_settings_button, self.video_danmaku.settings))
        # 「● REC」右边显示已录制时长（app 层每秒刷一次；没在录就藏起来）
        self.recording_time = QLabel("")
        self.recording_time.setObjectName("TileTitle")
        self.recording_time.setToolTip("这一路已经录了多久")
        self.recording_time.setVisible(False)
        _ignore_mouse(self.recording_time)
        # 信息条中间：常驻状态（连接中 / 缓冲中 / 断流重连 / 已下播…）
        # 画面被 VLC 原生窗口盖住时，这里也一定看得见
        self.status_label = ElidedLabel("")
        self.status_label.setObjectName("TileStatus")
        _ignore_mouse(self.status_label)
        _allow_shrink(self.status_label)
        self.status_label.setMinimumWidth(0)

        # 音量条直接放在信息条里，不用翻右键菜单
        # 音量图标按钮 + 滑条 + 数值，都在信息条里
        self.volume_button = VolumeButton(size=26)
        self.volume_button.set_state(self.muted, self.volume, self.audio_channel)
        self.volume_button.clicked.connect(self._volume_clicked)
        self.volume_button.volumeChanged.connect(self.set_volume)
        bottom_layout.addWidget(self.volume_button)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setFixedWidth(86)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.volume)
        self.volume_slider.setToolTip("这个格子的音量（更换主播后保持不变）")
        self.volume_slider.valueChanged.connect(self.set_volume)
        bottom_layout.addWidget(self.volume_slider)
        self.volume_menu = VolumePopup(self, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.volume_menu.setObjectName("TileVolumePopup")
        self.volume_menu.setAttribute(Qt.WA_TranslucentBackground)
        self.volume_menu.setAttribute(Qt.WA_StyledBackground)
        self.volume_menu.setAttribute(Qt.WA_ShowWithoutActivating)
        volume_layout = QVBoxLayout(self.volume_menu)
        volume_layout.setContentsMargins(4, 6, 4, 4)
        volume_layout.setSpacing(2)
        self.vertical_volume = QSlider(Qt.Vertical, self.volume_menu)
        self.vertical_volume.setFocusPolicy(Qt.NoFocus)
        self.vertical_volume.setRange(0, 100)
        self.vertical_volume.setFixedSize(20, 88)
        self.vertical_volume.setValue(self.volume)
        self.vertical_volume.setAccessibleName("当前格子的音量")
        self.vertical_volume.valueChanged.connect(self.set_volume)
        volume_layout.addWidget(self.vertical_volume)
        self.vertical_volume_label = QLabel(str(self.volume), self.volume_menu)
        self.vertical_volume_label.setAlignment(Qt.AlignCenter)
        volume_layout.addWidget(self.vertical_volume_label)
        self._volume_hide_timer = QTimer(self)
        self._volume_hide_timer.setSingleShot(True)
        self._volume_hide_timer.setInterval(140)
        self._volume_hide_timer.timeout.connect(self._hide_volume_popup_if_outside)
        self.volume_label = QLabel(str(self.volume))
        self.volume_label.setObjectName("TileTitle")
        self.volume_label.setFixedWidth(24)
        _ignore_mouse(self.volume_label)
        bottom_layout.addWidget(self.volume_label)
        bottom_layout.addWidget(self.status_label, 1)
        bottom_layout.addWidget(self.danmaku_button, 0, Qt.AlignVCenter)
        bottom_layout.addWidget(self.danmaku_settings_button, 0, Qt.AlignVCenter)
        bottom_layout.addWidget(self.recording_button, 0, Qt.AlignVCenter)
        bottom_layout.addWidget(self.recording_time, 0, Qt.AlignVCenter)
        bottom_layout.addWidget(self.fullscreen_button, 0, Qt.AlignVCenter)

        # 悬停时才出现的单窗口控制：与浮标同款样式，浮在画面右上角
        self.controls = QWidget(self)
        self.controls.setObjectName("TileControls")
        self.controls.setAttribute(Qt.WA_StyledBackground, False)
        self.quality_button = self._make_control(self._quality_text(), "选择这一路的画质")
        self.quality_button.clicked.connect(self._open_quality_menu)
        self.reload_button = RefreshButton(object_name="TileCtrl")
        self.reload_button.setToolTip("重新连接这一路")
        self.reload_button.clicked.connect(lambda: self.reloadRequested.emit(self.room))
        self.close_button = self._make_control("×", "关闭这一路")
        # 固定成方钮：宽度不再依赖样式表，免得被 min-width 撑成画质按钮那么宽
        self.close_button.setFixedSize(theme.TILE_CONTROL_HEIGHT, theme.TILE_CONTROL_HEIGHT)
        self.close_button.clicked.connect(lambda: self.closeRequested.emit(self.room))
        for button in (self.quality_button, self.reload_button, self.close_button):
            button.setParent(self.controls)
        for button in (self.quality_button, self.reload_button, self.close_button,
                       self.pause_button, self.volume_button, self.fullscreen_button,
                       self.danmaku_button, self.danmaku_settings_button, self.recording_button):
            button.setFocusPolicy(Qt.TabFocus)
            button.setProperty('tileButton', True)
        self.controls.setVisible(False)
        #: 悬停才露的浮层（LIVE 浮标 + 标题）：和控制条同一套显隐（用户要求：
        #: 「live 和人数改成和右上角悬浮按钮一样，自动消失、鼠标移上出现」）
        self._overlay_visible = False
        self._normal_hover_active = False
        self._normal_cursor_hidden = False
        self._normal_cursor = None
        self._control_pointer = None
        self._control_last_move = time.monotonic()
        self._control_hover_timer = QTimer(self)
        self._control_hover_timer.setInterval(35)
        self._control_hover_timer.timeout.connect(self._poll_control_hover)
        self._controls_hide_timer = QTimer(self)
        self._controls_hide_timer.setSingleShot(True)
        self._controls_hide_timer.setInterval(90)
        self._controls_hide_timer.timeout.connect(self._hide_controls_if_outside)
        self.paused = False
        self._player_active = False
        self.spinner = LoadingIndicator(self)
        self.pause_overlay = LoadingIndicator(self, text="已暂停", icon=False)
        self.pause_overlay.setObjectName("PauseOverlay")
        #: 悬停浮层相关的控件都建好了，之后 set_controls_visible 才能重摆布局
        self._overlay_ready = True
        self._move_repaint_timer = QTimer(self)
        self._move_repaint_timer.setSingleShot(True)
        self._move_repaint_timer.timeout.connect(self._refresh_moved_overlays)
        self._mask_refresh_timer = QTimer(self)
        self._mask_refresh_timer.setSingleShot(True)
        self._mask_refresh_timer.timeout.connect(self._refresh_overlay_masks)
        self.video.installEventFilter(self)
        self.controls.installEventFilter(self)
        self.volume_button.installEventFilter(self)
        self.volume_menu.installEventFilter(self)
        self.set_recording_state("")
        if not room.get("room_id"):
            self.set_room(None)          # 空格子：显示"拖入直播间"

    # ---- 播放状态 ----
    def set_room(self, room: dict | None, cover: QPixmap | None = None) -> None:
        """换这一个格子播放的房间；音量和静音属于格子，不跟着房间移动。"""
        self.room = dict(room or {})
        controls = getattr(self, '_plugin_controls', None)
        if controls is not None:
            controls.set_room(self.room)
        self.codec_probe_note = ""
        self.codec_reconnect_pending = False
        self.video_danmaku.clear()
        self.quality_options = []          # 换平台/直播间后不能沿用上一个房间的档位
        self.actual_quality = 0
        self.stream_url = ""
        self.stream_headers = {}
        self.set_recording_state("")
        empty = not self.room.get("room_id")
        self.setProperty("empty", empty)
        _repolish(self)
        self.set_controls_visible(False)
        self.set_paused(False)
        self.set_video_active(False)
        self.set_buffering(False)
        # 开关属于当前房间；新主播默认关闭，换位则恢复该房间保存的开关。
        self.danmaku_button.setChecked(bool(self.room.get("video_danmaku_enabled", False)))
        self._layout_areas()

        if empty:
            # 平台画质编号属于房间，空格子不能把它作为分辨率显示或继续保存。
            self.quality = 250
            self.quality_button.setText(self._quality_text())
            self.quality_button.setToolTip("选择这一路的画质")
            self._layout_controls()
            self._cover_source = None
            self.title_badge.set_text("", "")
            self.title_badge.setVisible(False)
            self.stream_badge.setVisible(False)
            self.set_status("拖入直播间")
            return

        self.room["volume"] = self.volume
        self.room["muted"] = self.muted
        self._sync_stream_badge()
        self._cover_source = cover if cover is not None else self.room.get("cover")
        self.title_badge.set_text(self.room.get("uname", ""), self.room.get("title", ""))
        self.title_badge.setVisible(bool(self.room.get("uname")) and self._overlay_visible)
        self._refresh_badge()
        self.quality = int(self.room.get("quality", AUTO_QUALITY
            if str(self.room.get("room_id", "")).partition(":")[0] in OVERSEAS_PLATFORMS else 250))
        # 声道和音量 / 静音一样属于**格子**，不跟着房间走：换台不该把用户调好的
        # 「只播左 / 只播右」丢掉。房间自带的那份只在第一次上墙时用（_prepare_room）。
        self.room["audio_channel"] = self.audio_channel
        self.quality_button.setText(self._quality_text())
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(self.volume)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(str(self.volume))
        self.volume_button.set_state(self.muted, self.volume, self.audio_channel)
        self.set_status("" if self.room.get("live") else "未开播")
        self.stop_elapsed_timer()
        self._layout_cover()

    def _toggle_video_danmaku(self, enabled: bool) -> None:
        self.room["video_danmaku_enabled"] = bool(enabled)
        self.danmaku_button.setToolTip("关闭画面弹幕（默认 B）" if enabled
                                       else "开启画面弹幕（默认 B）")
        self.video_danmaku.set_enabled(enabled)
        if getattr(self, "_overlay_ready", False):
            self.raise_overlays()
            # Creating the layered danmaku HWND can expose Qt's rectangular
            # backing masks; restore native overlay contours after it settles.
            self._mask_refresh_timer.start(0)
        self.videoDanmakuChanged.emit(enabled)

    def _change_video_danmaku_settings(self, values: dict) -> None:
        global_values = dict(values)
        if self.video_danmaku_overrides is not None:
            for key in VIDEO_DANMAKU_SETTING_KEYS:
                if key in global_values:
                    self.video_danmaku_overrides[key] = global_values.pop(key)
        self._video_danmaku_global_settings.update(global_values)
        self.apply_video_danmaku_settings()
        self.videoDanmakuSettingsChanged.emit(global_values)

    def apply_video_danmaku_settings(self, settings=None) -> None:
        if settings is not None:
            self._video_danmaku_global_settings = dict(settings)
        effective = {**self._video_danmaku_global_settings, **(self.video_danmaku_overrides or {})}
        self.video_danmaku.apply_settings(effective)
        self.danmaku_settings_menu.apply_settings(
            effective, independent=self.video_danmaku_overrides is not None)

    def _set_video_danmaku_independent(self, enabled: bool) -> None:
        self.video_danmaku_overrides = (
            video_danmaku_overrides(self._video_danmaku_global_settings) if enabled else None)
        self.apply_video_danmaku_settings()
        self.videoDanmakuSettingsChanged.emit({})

    def plugin_interaction_active(self) -> bool:
        controls = getattr(self, '_plugin_controls', None)
        return controls.interaction_active() if controls is not None else False

    def _volume_controls_width(self):
        from .wall_widgets import WallGrid
        wall = self.parentWidget()
        if (not isinstance(wall, WallGrid) or wall.fullscreen_tile is not None
                or wall.picture_in_picture_tiles is not None):
            return self.width()
        spec = layouts.BY_ID.get(wall.layout_id, {}).get('spec')
        if spec is None:
            return self.width()
        rows, columns, cells = spec
        ratios = wall._layout_ratios.get(wall.layout_id, {})
        if (cells != layouts.even_cells(rows, columns)
                or any(node.axis == Qt.Horizontal and len(set(ratios.get(node.key, node.weights))) > 1
                       for node in wall._partitions[wall.layout_id].nodes())):
            return self.width()
        # Equal cells may differ by one pixel. Choose the style for the smallest
        # cell from the target wall geometry, not siblings still awaiting resize.
        return (wall._corner_area().width() - wall.grid.spacing() * (columns - 1)) // columns

    def _bottom_layout_signature(self):
        """影响底栏布局的输入；没变就不用重排（悬停会频繁触发 _layout_areas）。"""
        return (self.width(), self._volume_controls_width(),
                self.bottom.width(),
                tuple((e.owner, e.key, e.control.widget.isHidden(),
                       e.control.minimum_width, e.control.preferred_width)
                      for e in getattr(getattr(self, '_plugin_controls', None), 'entries', ())),
                self.isVisible(),
                bool(getattr(self, "_fullscreen_controls_hidden", False)),
                self.recording_time.text(),
                bool(getattr(self, "_recording_available", True)),
                self.status_label.text(),
                theme.mode())

    def _layout_bottom_controls(self) -> None:
        width = self.width()
        signature = self._bottom_layout_signature()
        if signature == getattr(self, "_bottom_layout_signature_value", None):
            return
        self._bottom_layout_signature_value = signature
        volume_width = self._volume_controls_width()
        compact = width < 420
        layout = self.bottom.layout()
        margin, spacing = (6, 4) if compact else (10, 8)
        if width < 260:
            margin, spacing = 4, 2
        # 间距不因为输入区而变：底栏原有按钮的位置必须和没有输入区时一模一样。
        layout.setContentsMargins(margin, 4, margin, 4)
        layout.setSpacing(spacing)
        self.pause_button.setFixedWidth(26 if width < 260 else 34)
        # 弹幕开关只显示「弹」字图标，开关状态由右下角的勾表示（B 站播放器同款），
        # 不再用整块底色区分开/关。
        self.danmaku_button.setFixedWidth(26 if compact else 34)
        self.danmaku_button.setText("弹")
        # 保留原有功能入口；小格子的音量改由向上展开的竖向滑条调整。
        self.volume_label.setVisible(volume_width >= 600)
        self.recording_time.setVisible(bool(self.recording_time.text()) and width >= 360
                                       and getattr(self, "_recording_available", True))
        self.volume_slider.setVisible(volume_width >= 600)
        self.volume_button.compact_popup = volume_width < 600
        self.volume_button._update_tooltip()
        if volume_width >= 600:
            self.volume_menu.hide()
        self.status_label.setVisible(True)
        self.danmaku_settings_button.setVisible(True)
        self.recording_button.setVisible(getattr(self, "_recording_available", True))
        layout.activate()       # 让上面定的固定宽度立刻生效，下面算剩余宽度才准
        others = [self.pause_button, self.volume_button, self.volume_label,
                  self.danmaku_button, self.danmaku_settings_button,
                  self.recording_button, self.recording_time, self.fullscreen_button]
        visible = [widget for widget in others if not widget.isHidden()]
        fixed = sum(widget.sizeHint().width() if widget is self.recording_time else widget.width()
                    for widget in visible)
        # 原有控件的宽度完全按「没有输入区」时算，按钮位置因此不会变。
        available = width - fixed - margin * 2 - spacing * (len(visible) + 1)
        slider_width = max(18, min(86, available - 8))
        self.volume_slider.setFixedWidth(slider_width)
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status_label.setMinimumWidth(0)
        self.status_label.setMaximumWidth(16777215)
        layout.setStretchFactor(self.status_label, 1)
        extensions = getattr(self, '_plugin_controls', None)
        if extensions is not None and not extensions._disposed:
            # Existing player actions determine the free interval; extensions
            # share one centered, bounded region without moving those actions.
            extensions.spacer.setFixedWidth(0)
            layout.activate()
            left_controls = [w for w in (self.pause_button, self.volume_button,
                self.volume_slider, self.volume_label) if not w.isHidden()]
            right_controls = [w for w in (self.danmaku_button, self.danmaku_settings_button,
                self.recording_button, self.recording_time, self.fullscreen_button) if not w.isHidden()]
            left = margin + sum(w.width() for w in left_controls) + spacing * len(left_controls)
            right = (self.bottom.width() - margin - sum(w.width() for w in right_controls)
                     - spacing * max(0, len(right_controls) - 1))
            cap = min(520, max(300, int(width * 0.45)))
            fitted = extensions.allocate(min(cap, max(0, right - left - 3 * spacing)))
            if fitted:
                x = max(left + spacing, min((self.bottom.width() - fitted) // 2,
                                            right - 2 * spacing - fitted))
                self.status_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                self.status_label.setFixedWidth(max(0, x - left - spacing))
                layout.setStretchFactor(self.status_label, 0)
                extensions.spacer.setFixedWidth(max(0, right - 2 * spacing - x - fitted))
        layout.activate()

    def set_recording_state(self, state: str) -> None:
        self._recording_state = state
        self._update_recording_button()
        self.recording_button.setProperty("recording", state == "record")
        _repolish(self.recording_button)
        self.recording_button.setToolTip(
            "停止录制这一路" if state == "record" else
            "即时回放缓存中；点击开始完整录制" if state == "cache" else
            "开始录制这一路（右键可保存即时回放）")

    def set_recording_elapsed(self, text: str) -> None:
        """更新「● REC」旁边的已录制时长；空串就把标签收起来。"""
        if not hasattr(self, "recording_time"):
            return
        self.recording_time.setText(text)
        self._layout_bottom_controls()

    def set_recording_available(self, available: bool) -> None:
        """录制功能总开关：关掉时把底栏的「● 录制」按钮收起来。"""
        self._recording_available = bool(available)
        self._update_recording_button()

    def _update_recording_button(self, *, layout: bool = True) -> None:
        if not hasattr(self, "recording_button"):
            return
        # 录制功能总开关关掉时，整个「● 录制」按钮收起来（见 set_recording_available）。
        # 放在这里而不是 set_recording_available 里：录制状态每次变都会走这个方法，
        # 各处刷新不会把按钮又露出来。
        available = getattr(self, "_recording_available", True)
        self.recording_button.setVisible(available)
        if not available:
            if layout:
                self._layout_bottom_controls()
            return
        narrow = self.width() < 320
        state = getattr(self, "_recording_state", "")
        self.recording_button.setProperty('replayOnly', state == 'cache')
        self.recording_button.setAccessibleName(
            '即时回放缓存中；点击开始完整录制' if state == 'cache' else
            '停止录制这一路' if state == 'record' else '开始录制这一路')
        labels = ({"record": "●", "cache": "●", "": "●"} if narrow else
                  {"record": "● REC", "cache": "● REC", "": "● 录制"})
        self.recording_button.setFixedWidth(26 if narrow else 64)
        self.recording_button.setText(labels.get(state, "●"))
        self.recording_button.update()
        if layout:
            self._layout_bottom_controls()

    # ---- 接收拖拽 ----
    def dragEnterEvent(self, event) -> None:
        if (event.mimeData().hasFormat(ROOM_MIME) or event.mimeData().hasFormat(TILE_MIME)
                or event.mimeData().hasFormat(DANMAKU_MIME)):
            event.acceptProposedAction()
            self.setProperty("dropActive", True)
            _repolish(self)

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dropActive", False)
        _repolish(self)

    def dropEvent(self, event) -> None:
        self.setProperty("dropActive", False)
        _repolish(self)
        if event.mimeData().hasFormat(ROOM_MIME):
            room_id = bytes(event.mimeData().data(ROOM_MIME)).decode("utf-8", "ignore")
            event.acceptProposedAction()
            self.roomDropped.emit(room_id)
        elif event.mimeData().hasFormat(DANMAKU_MIME):
            event.acceptProposedAction()
            if event.mimeData().hasFormat("application/x-ddm-danmaku-cell"):
                self.danmakuPaneDropped.emit(int(bytes(event.mimeData().data("application/x-ddm-danmaku-cell"))))
            else:
                self.danmakuDropped.emit()
        elif event.mimeData().hasFormat(TILE_MIME):
            source = bytes(event.mimeData().data(TILE_MIME)).decode("utf-8", "ignore")
            event.acceptProposedAction()
            self.tileDropped.emit(source)

    def mousePressEvent(self, event) -> None:
        self._press_pos = event.pos() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """拖动画面本身可以和其他格子交换位置。"""
        room_id = str(self.room.get("room_id") or "")
        if not room_id or not (event.buttons() & Qt.LeftButton):
            self._press_pos = None
            return
        start = getattr(self, "_press_pos", None)
        if start is None or (event.pos() - start).manhattanLength() < QApplication.startDragDistance():
            return
        self._press_pos = None
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            import ctypes
            if not ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000:
                return  # A queued move can retain Qt's left-button flag after physical release.
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(TILE_MIME, room_id.encode("utf-8"))
        mime.setText(room_id)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def raise_overlays(self) -> None:
        """把浮层重新抬到**原生视频窗口**之上。

        画面是原生子窗口（HWND），默认压在所有 Qt 子控件上面；浮层只有也是原生
        窗口、并且被 raise 过，才既画得出来也点得到。所以每次摆完位都要再抬一次
        —— 用户报过「竖屏 1+4 里最下面两个格子的 ✕ 点不动」，就是浮层被视频盖住。
        """
        compact = bool(self.property('pictureInPicture'))
        self.video_danmaku.raise_()
        for corner in self.video_corners:
            if not compact or corner.isVisible():
                corner.raise_()
        for widget in (self.controls, self.stream_badge, self.title_badge,
                       self.time_badge, self.spinner, self.pause_overlay, self.bottom):
            if not compact or widget.isVisible():
                widget.raise_()
        self._update_quick_danmaku_mask()
        wall = self.parentWidget()
        quick_layer = getattr(wall, "_quick_danmaku_layer", None)
        if quick_layer is not None:
            quick_layer.raise_()
        border = getattr(wall, '_pane_borders', {}).get(self)
        if border is not None and border.isVisible():
            border.raise_()

    def _update_quick_danmaku_mask(self) -> None:
        self.video_danmaku.update_quick_mask((
            self.controls, self.stream_badge, self.title_badge, self.time_badge,
            self.spinner, self.pause_overlay, self.bottom))

    def set_video_active(self, active: bool) -> None:
        self._player_active = active
        self.video_danmaku.set_active(active)
        self.cover.setVisible(not active)
        if not active:
            self._layout_cover()
        if active:
            self.spinner.stop()
            self._connecting = False
        else:
            self.pause_overlay.stop()
        self.raise_overlays()

    def set_status(self, text: str) -> None:
        self._status_text = text
        self._connecting = text.startswith("连接中")
        self._sync_status_label()
        if not self._player_active:
            if self._connecting:
                self.spinner.start()
            else:
                self.spinner.stop()
            self._layout_cover()              # 让封面文字随状态刷新（连接时不显示文字）

    def set_offline(self) -> None:
        """下播：画面清成黑的，格子继续留给这个直播间。"""
        self.room["live"] = False
        self._cover_source = None
        self.set_video_active(False)
        self.set_buffering(False)
        self.set_paused(False)
        self.stop_elapsed_timer()
        self._refresh_badge()
        self.stream_badge.set_offline()
        self.set_status("已下播")
        # The cover already hides the last frame; let Qt coalesce the clearing
        # with pending startup/layout paints instead of flushing the whole wall.
        self.video.update()

    def set_buffering(self, active: bool) -> None:
        """卡顿/缓冲中：显示缓冲动画（和连接时同一套样式）。"""
        self._connecting = active
        self._buffering = bool(active)
        self._sync_status_label()
        if active:
            self.spinner.start()
        else:
            self.spinner.stop()
        if not self._player_active:
            self._layout_cover()

    def _sync_status_label(self) -> None:
        """底栏保留空白布局区域；状态仍用于封面、加载图形及内部判断。"""
        self.status_label.setText("")

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self.pause_button.set_paused(self.paused)
        self.video_danmaku.set_paused(self.paused)
        if self.paused and self._player_active:
            self.pause_overlay.start()
            self.pause_overlay.raise_()
        else:
            self.pause_overlay.stop()
        self._update_quick_danmaku_mask()
        self._layout_controls()

    def set_live(self, live: bool, viewers: str = "") -> None:
        self.room["live"] = live
        if viewers:
            self.room["viewers"] = viewers
        if not live:
            self.room.pop("online", None)      # 下播后旧的在线人数不能再留着显
            self.stop_elapsed_timer()          # 右下角的时长浮标也立刻收掉
        self._refresh_badge()

    def set_uname_title(self, uname: str, title: str) -> None:
        """补上主播名/标题：启动占位后由状态刷新补齐（悬停浮标显示用）。"""
        self.room["uname"] = uname or ""
        self.room["title"] = title or ""
        self.title_badge.set_text(self.room["uname"], self.room["title"])
        self.title_badge.setVisible(bool(self.room["uname"]) and self._overlay_visible)

    def set_watched(self, watched_text: str) -> None:
        """实时在线人数（高能榜 onlineNum，和 B 站页面一致）。"""
        if watched_text:
            self.room["online"] = watched_text
        self._refresh_badge()

    def _refresh_badge(self) -> None:
        supports_count = str(self.room.get("room_id", "")).isdigit()
        watched = (self.room.get("online") or "") if supports_count else ""
        popularity = (self.room.get("viewers") or "") if supports_count else ""
        live = bool(self.room.get("live"))
        # 优先显示实时在线人数；还没拉到就别拿人气值顶上（那个数看着很像异常）
        self.stream_badge.set_state(live, watched or (WATCHING_TEXT if live and supports_count else ""))
        # 悬停才露（和控制条同步）；不然一屏好几格的 LIVE 一直挂着太吵。
        # 宽度够不够同时放下它和控制条，交给 _sync_stream_badge() 一起算
        self._sync_stream_badge()
        self._layout_areas()          # 浮标宽度会变（人数位数不同），标题要跟着重新让位
        if not supports_count:
            self.stream_badge.setToolTip("直播中" if live else "未开播")
        elif watched and popularity:
            self.stream_badge.setToolTip(f"{watched} 人在线 · 人气 {popularity}")
        elif watched:
            self.stream_badge.setToolTip(f"{watched} 人在线")
        elif live and popularity:
            self.stream_badge.setToolTip(f"正在获取在线人数…（当前人气 {popularity}）")
        elif live:
            self.stream_badge.setToolTip("正在获取在线人数…")
        elif popularity:
            self.stream_badge.setToolTip(f"人气 {popularity}")

    # ---- 控制 ----
    def _make_control(self, text: str, tip: str) -> QPushButton:
        button = TileButton(text)
        button.setObjectName("TileCtrl")
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def _quality_text(self) -> str:
        if self.quality == AUTO_QUALITY:
            return "自动" + (" · " + self._quality_name(self.actual_quality, short=True)
                           if self.actual_quality else "")
        return self._quality_name(self.actual_quality or self.quality, short=True)

    def _quality_name(self, qn: int, *, short: bool = False) -> str:
        if qn == AUTO_QUALITY:
            return "自动" if short else "自动（根据网络选择流畅的最高画质）"
        for item in self.quality_options:
            if int(item.get("qn") or 0) == int(qn):
                return str((item.get("label") if short else None) or item.get("desc") or qn)
        if ":" in str(self.room.get("room_id") or ""):
            return "最高可用" if int(qn) == 10000 else "获取画质…"
        return QUALITY_NAMES.get(int(qn), f"{qn}P")

    def _quality_choices(self) -> list[tuple[str, int]]:
        """优先用接口给的档位：直播间只提供哪些，菜单里就只留哪些。"""
        if self.quality_options:
            return [(self._quality_name(int(item["qn"])), int(item["qn"]))
                    for item in self.quality_options]
        if ":" in str(self.room.get("room_id") or ""):
            return []                     # 接口返回前不展示 B 站的固定画质菜单
        return list(QUALITY_CHOICES)

    def set_quality_options(self, options: list) -> None:
        if not options:
            return
        self.quality_options = [dict(item) for item in options]
        self.quality_button.setText(self._quality_text())
        self._layout_controls()

    def set_actual_quality(self, quality: int) -> None:
        """接口实际给的画质（未登录时通常只有 720P）。"""
        self.actual_quality = int(quality or 0)
        self.quality_button.setText(self._quality_text())
        self._layout_controls()
        if ":" in str(self.room.get("room_id") or ""):
            self.quality_button.setToolTip(("自动画质，当前：" if self.quality == AUTO_QUALITY else "")
                                          + self._quality_name(self.actual_quality))
        elif self.actual_quality and self.actual_quality < self.quality:
            self.quality_button.setToolTip(
                f"请求 {self._quality_name(self.quality)}，"
                f"实际 {self._quality_name(self.actual_quality)}"
                f"（该直播间/当前账号最高只提供这一档）")
        else:
            self.quality_button.setToolTip("选择这一路的画质")

    def _open_quality_menu(self) -> None:
        menu = QMenu(self)
        for name, value in self._quality_choices():
            action = QAction(name, menu)
            action.setCheckable(True)
            action.setChecked(value == self.quality)
            action.triggered.connect(lambda _checked=False, v=value: self.set_quality(v))
            menu.addAction(action)
        try:
            menu.exec(self.quality_button.mapToGlobal(self.quality_button.rect().bottomLeft()))
        finally:
            menu.deleteLater()

    def set_quality(self, value: int) -> None:
        if getattr(self, "quality_locked", False) and value != 10000:
            return
        self.quality = value
        self.actual_quality = 0
        self.quality_button.setText(self._quality_text())
        self.quality_button.setToolTip("选择这一路的画质")
        self._layout_controls()
        self.qualityChanged.emit(self.room, value)

    def _volume_clicked(self) -> None:
        self._toggle_mute()

    def _show_volume_popup(self) -> None:
        if not self.volume_button.isVisible() or not self.volume_slider.isHidden():
            return
        self._volume_hide_timer.stop()
        self.volume_menu.ensurePolished()
        self.volume_menu.adjustSize()
        anchor = self.volume_button.mapToGlobal(QPoint(self.volume_button.width() // 2, 0))
        screen = self.screen().availableGeometry()
        x = max(screen.left(), min(anchor.x() - self.volume_menu.width() // 2,
                                  screen.right() - self.volume_menu.width() + 1))
        self.volume_menu.move(x, max(screen.top(), anchor.y() - self.volume_menu.height() - 4))
        self.volume_menu.show()
        self.volume_menu.raise_()

    def _hide_volume_popup_if_outside(self) -> None:
        if self.vertical_volume.isSliderDown():
            self._volume_hide_timer.start()
            return
        point = QCursor.pos()
        if any(widget.rect().contains(widget.mapFromGlobal(point))
               for widget in (self.volume_button, self.volume_menu)):
            return
        self.volume_menu.hide()

    def _toggle_mute(self) -> None:
        self.set_muted(not self.muted)

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        self.room["muted"] = self.muted
        self.volume_button.set_state(muted, self.volume, self.audio_channel)
        self._layout_controls()
        self.muteToggled.emit(self.room, muted)

    def set_fullscreen_controls_hidden(self, hidden: bool, *, hide_bar: bool = True) -> None:
        target = 1.0 if hidden and hide_bar and self.property("fullscreen") else 0.0
        if hidden == getattr(self, "_fullscreen_controls_hidden", False) and target == self._bar_target:
            return
        self._bar_clock.stop()
        self._bar_animation.stop()
        self._fullscreen_controls_hidden = hidden
        self._bar_target = target
        self.set_controls_visible(not hidden)
        if self.property("fullscreen") and motion.enabled():
            self.bottom.show()
            self._layout_areas()
            self._bar_animation.blockSignals(True)
            self._bar_animation.setCurrentTime(0)
            self._bar_animation.setStartValue(self._bar_progress)
            self._bar_animation.setEndValue(target)
            self._bar_animation.blockSignals(False)
            self._bar_animation.start()
            # Advance this QWidget slide independently of Quick's shared
            # animation clock, which stopped ticking in captured re-entries.
            self._bar_animation.pause()
            self._bar_started = time.monotonic()
            self._bar_clock.start()
        else:
            self._slide_fullscreen_bar(target)
            self._layout_areas()

    def _advance_bar_animation(self) -> None:
        duration = self._bar_animation.duration()
        elapsed = min(duration, round((time.monotonic() - self._bar_started) * 1000))
        self._bar_animation.setCurrentTime(elapsed)
        if elapsed >= duration:
            self._bar_clock.stop()
            self._bar_animation.stop()

    def _slide_fullscreen_bar(self, progress) -> None:
        self._bar_progress = float(progress)
        offset = round(TILE_BAR_HEIGHT * self._bar_progress)
        self.bottom.set_tile_geometry(0, self.height() - TILE_BAR_HEIGHT
                                      + offset,
                                      self.bottom.width(), self.bottom.height())
        if self.bottom.qt_composited:
            self.bottom.setWindowOpacity(1.0 - self._bar_progress)
        self.bottom.setVisible(self._bar_progress < 1.0 or self._bar_target == 0.0)
        self._layout_time_badge()
        self.bottom.raise_()

    def set_controls_visible(self, visible: bool) -> None:
        visible = (visible and not self.property('pictureInPicture')
                   and not getattr(self, "_fullscreen_controls_hidden", False))
        visible = bool(visible)
        self.controls.setVisible(visible)
        # LIVE 浮标和标题跟着一起显隐（用户要求：别一直挂在画面上）
        self._overlay_visible = visible
        self._sync_stream_badge()
        # 右下角的直播时长和它们一样：鼠标在格子上才露出来
        self.time_badge.setVisible(self._elapsed_visible())
        if visible and getattr(self, "_overlay_ready", False):
            # 露出来之前按当前宽度重摆一遍（标题要重新让位）。
            # 构造过程中（spinner 等还没建好）不能走这里，否则会碰空控件。
            self._layout_areas()
        if visible:
            self.raise_overlays()          # 视频是原生窗口，浮层要重新抬上来
            self._round_video()            # 控制条那块从视频遮罩里挖掉
            self._controls_hide_timer.stop()
            # 显示之前先按文本把按钮宽度摆好：否则会沿用上一次的尺寸，
            # 画质文字换了之后整条控制条看起来就是错位的。
            self._layout_controls()
            self._sync_control_hover()
            self._control_hover_timer.start()
        else:
            if self.property("fullscreen") or not self._normal_hover_active:
                self._control_hover_timer.stop()
            self._set_control_hover(None)
            self.title_badge.setVisible(False)   # 收起时标题一起收
            self._round_video()                  # 收起来就把视频遮罩补回圆角

    def _set_control_hover(self, hovered: QPushButton | None) -> None:
        """同步一份不依赖原生窗口 enter/leave 的悬停状态。"""
        for button in (self.quality_button, self.reload_button, self.close_button):
            active = button is hovered
            if button.property("hovered") is active:
                continue
            button.setProperty("hovered", active)
            _repolish(button)
            button.update()

    def _sync_control_hover(self, global_pos: QPoint | None = None) -> None:
        global_pos = global_pos or QCursor.pos()
        hovered = None
        for button in (self.quality_button, self.reload_button, self.close_button):
            local = button.mapFromGlobal(global_pos)
            if button.rect().contains(local):
                hovered = button
                break
        self._set_control_hover(hovered)

    def _poll_control_hover(self) -> None:
        if self.property('pictureInPicture'):
            self._restore_normal_cursor()
            self._normal_hover_active = False
            self.set_controls_visible(False)
            self._control_hover_timer.stop()
            return
        if not self.isVisible():
            self._restore_normal_cursor()
            self._normal_hover_active = False
            self._control_hover_timer.stop()
            return
        if self.property("fullscreen"):
            self._restore_normal_cursor()
            self._normal_hover_active = False
            self._sync_control_hover()
            return
        position, now = QCursor.pos(), time.monotonic()
        protected = (self.plugin_interaction_active() or QApplication.activePopupWidget() is not None
                     or QApplication.activeModalWidget() is not None or bool(QApplication.mouseButtons())
                     or QApplication.overrideCursor() is not None)
        if protected:
            self._restore_normal_cursor()
            self._control_last_move = now
            return
        if not self.rect().contains(self.mapFromGlobal(position)):
            self._restore_normal_cursor()
            self._normal_hover_active = False
            self.set_controls_visible(False)
            return
        moved = not self._normal_hover_active or position != self._control_pointer
        self._normal_hover_active = True
        self._control_pointer = position
        over_controls = any(widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(position))
                            for widget in (self.controls, self.stream_badge, self.title_badge, self.bottom))
        if moved or over_controls:
            self._restore_normal_cursor()
            self._control_last_move = now
            if not self._overlay_visible:
                self.set_controls_visible(True)
        elif now - self._control_last_move >= self.CONTROL_IDLE_SECONDS:
            if self._overlay_visible:
                self.set_controls_visible(False)
            if self.video.rect().contains(self.video.mapFromGlobal(position)):
                if not self._normal_cursor_hidden:
                    self._normal_cursor = self.video.cursor() if self.video.testAttribute(Qt.WA_SetCursor) else None
                    self.video.setCursor(Qt.BlankCursor)
                    self._normal_cursor_hidden = True
                set_native_cursor(Qt.BlankCursor, self.video)
        if self._overlay_visible:
            self._sync_control_hover(position)

    def _restore_normal_cursor(self) -> None:
        if not self._normal_cursor_hidden:
            return
        if self._normal_cursor is None:
            self.video.unsetCursor()
        else:
            self.video.setCursor(self._normal_cursor)
        self._normal_cursor_hidden = False
        self._normal_cursor = None
        if (self.isVisible() and QApplication.overrideCursor() is None
                and self.video.rect().contains(self.video.mapFromGlobal(QCursor.pos()))):
            set_native_cursor(self.video.cursor().shape(), self.video)

    def _hide_controls_if_outside(self) -> None:
        if (self.plugin_interaction_active() or QApplication.activePopupWidget() is not None
                or QApplication.activeModalWidget() is not None or QApplication.mouseButtons()):
            return
        local = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(local):
            return
        self.set_controls_visible(False)

    def _show_danmaku_actions(self, text, position):
        from .danmaku_actions import show_comment_menu
        self.video_danmaku._menu_open = True
        def finished():
            self.video_danmaku._menu_open = False
            self.video_danmaku._poll_hover()
        show_comment_menu(self, text, getattr(self, '_plugin_controls', None), position, finished)

    def _open_clicked_danmaku(self, event):
        start = getattr(self, '_press_pos', None)
        if event.button() == Qt.LeftButton:
            self._press_pos = None
        position = event.globalPosition().toPoint()
        return (event.button() == Qt.LeftButton and start is not None
                and (self.mapFromGlobal(position) - start).manhattanLength() < QApplication.startDragDistance()
                and self.video_danmaku.open_actions_at(position))

    def focus_danmaku_input(self) -> None:
        controls = getattr(self, '_plugin_controls', None)
        if controls is not None:
            # The fullscreen bar is a separate tool window. setFocus alone
            # only records a pending focus child while the video stays active.
            if self.bottom.isWindow() and controls.widget.isVisible():
                self.bottom.activateWindow()
            controls.focus_input()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self.property("fullscreen"):
            self.set_controls_visible(True)
        else:
            self._poll_control_hover()
            self._control_hover_timer.start()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        # VLC 画面和控制条都是原生子窗口，横向划过时会产生短暂 leave；
        # 稍后按全局坐标复核，避免按钮还在鼠标下却被提前隐藏。
        self._controls_hide_timer.start()

    # ---- 画面 ----
    def set_cover(self, pixmap: QPixmap | None) -> None:
        self._cover_source = pixmap
        self._layout_cover()

    def set_interactive_resize(self, active: bool) -> None:
        active = bool(active)
        if active == self._interactive_resize:
            return
        self._interactive_resize = active
        if not active and self.isVisible():
            self._layout_cover()

    def _layout_cover(self) -> None:
        self.cover.setGeometry(self.video.rect())
        source = getattr(self, "_cover_source", None)
        if self.cover.isHidden():
            return
        if source and not source.isNull():
            radius = 0 if self.property('pictureInPicture') else 8
            key = (source.cacheKey(), self.video.width(), self.video.height(),
                   self.devicePixelRatioF(), bool(self.property("fullscreen")), radius)
            if key == self._cover_key:
                self.cover.setScaledContents(False)
                return
            if self._interactive_resize:
                if not self._cover_cached.isNull():
                    self.cover.setScaledContents(True)
                    self.cover.setPixmap(self._cover_cached)
                return
            self._cover_cached = rounded_pixmap(source, self.video.size(), radius)
            self._cover_key = key
            self.cover.setScaledContents(False)
            self.cover.setPixmap(self._cover_cached)
        else:
            self._cover_key = None
            self._cover_cached = QPixmap()
            self.cover.setScaledContents(False)
            self.cover.setPixmap(QPixmap())
            if self._player_active or getattr(self, "_connecting", False):
                self.cover.setText("")        # 播放中 / 连接中都不显示文字，避免和动画重叠
            else:
                fallback = self.room.get("uname", "") if self.room.get("live") else "未开播"
                self.cover.setText(self._status_text or fallback)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_areas()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._move_repaint_timer.start(0)
        parent = self.parentWidget()
        if parent is not None:
            parent.update(QRect(event.oldPos(), self.size()))
        # 等大格子换位不会移动内部浮层，共享弹幕组仍需更新墙内坐标。
        self.video_danmaku.schedule_quick_geometry()

    def _refresh_moved_overlays(self) -> None:
        # Native child windows can retain old backing-store text after only their parent moved.
        self._move_repaint_timer.stop()
        if not self.isVisible():
            return
        for widget in (self.video_danmaku, self.stream_badge, self.title_badge, self.time_badge,
                       self.controls, self.spinner, self.pause_overlay, self.bottom):
            if widget.isVisible():
                widget.repaint()
        for widget in self.bottom.findChildren(QWidget):
            if widget.isVisible() and widget.testAttribute(Qt.WA_NativeWindow):
                widget.repaint()
        self.update()

    def _layout_areas(self) -> None:
        """统一摆放：视频区、浮标、控制条、信息条。"""
        if getattr(self, '_presentation_changing', False):
            return
        width, height = self.width(), self.height()
        scale = 1.0
        if self.property('pictureInPicture'):
            natural = self.spinner.natural_size()
            scale = min(.75, max(1, width - 12) / natural.width(), max(1, height - 12) / natural.height())
        self.spinner.set_presentation_scale(scale)
        if self.property('pictureInPicture'):
            # PiP has no per-tile bar, badges or text controls. Keep their native
            # windows out of the synchronous resize path while retaining video,
            # comments, SC, loading and pause presentation.
            self.bottom.hide()
            self.video.setGeometry(self.rect())
            self.video_danmaku.setGeometry(self.rect())
            self._round_video()
            self.spinner.move(max(0, (width - self.spinner.width()) // 2),
                              max(8, (height - self.spinner.height()) // 2))
            self.pause_overlay.move(max(0, (width - self.pause_overlay.width()) // 2),
                                    max(8, (height - self.pause_overlay.height()) // 2))
            self._layout_cover()
            self.raise_overlays()
            return
        self._update_recording_button(layout=False)
        # 全屏底栏覆盖视频，收起时不改变原生视频尺寸。
        fullscreen = bool(self.property("fullscreen"))
        compact = bool(self.property('pictureInPicture'))
        self.bottom.set_fullscreen(fullscreen)
        if not fullscreen:
            self._bar_clock.stop()
            self._bar_animation.stop()
            self._bar_progress = self._bar_target = 0.0
            self.bottom.setVisible(not compact)
        video_height = max(1, height if fullscreen or compact else height - TILE_BAR_HEIGHT)
        # 普通格子留边框，全屏视频贴齐窗口边缘。
        inset = 0 if fullscreen or compact else 1
        self.video.setGeometry(inset, inset, max(1, width - inset * 2),
                               max(1, video_height - inset))
        self._round_video()
        video_right = self.video.geometry().right() + 1
        self.stream_badge.move(10, 8)
        self._layout_controls()
        # 第一行要同时站得下「LIVE 浮标」和「控制条」，控制条永远钉在右上角。
        # 以前是让控制条折到第二行去给浮标腾地方，结果它跑出了右上角、还压在
        # 画面中间的封面文字上（用户报的「竖屏格子右上角按钮错位」）。现在反过来
        # 让浮标让位：先收起人数（浮标变短），实在不够再整个收起来。
        # 浮标的宽度和显隐只由 _sync_stream_badge() 决定 —— 别在这里再写一套
        # 「if overlay: setVisible(...)」，那样 overlay 收起来时它就不受控了
        # （放不下的浮标会一直露着，压住右上角控制条）。
        self._sync_stream_badge()
        # 标题浮标紧跟在 LIVE 右边，剩下的宽度让给控制条那一行
        controls_left = (video_right - 10
                         if self.controls.y() > 20 else self.controls.x())
        title_left = self.stream_badge.x() + self.stream_badge.width() + 6
        room = max(0, controls_left - title_left - 8)
        show_title = bool(self.room.get("uname")) and room >= 110 and self._overlay_visible and not compact
        self.title_badge.setVisible(show_title)
        if show_title:
            self.title_badge.set_max_width(room)
            self.title_badge.move(title_left, 8)
        # 摆位和显隐放在一起：重排（改窗口大小、切布局）之后状态不会走丢
        self.time_badge.setVisible(self._elapsed_visible())
        self.spinner.move(max(0, (self.video.width() - self.spinner.width()) // 2),
                          max(8, (video_height - self.spinner.height()) // 2))
        self.pause_overlay.move(
            max(0, (self.video.width() - self.pause_overlay.width()) // 2),
            max(8, (video_height - self.pause_overlay.height()) // 2))
        bar_y = (height - TILE_BAR_HEIGHT + round(TILE_BAR_HEIGHT * self._bar_progress)
                 if fullscreen else video_height)
        bar_height = TILE_BAR_HEIGHT if fullscreen else max(1, height - video_height - inset)
        self.bottom.set_tile_geometry(inset, bar_y, max(1, width - inset * 2), bar_height)
        self._layout_time_badge()
        self.video_danmaku.setGeometry(self.video.geometry())
        self._layout_bottom_controls()
        self._layout_cover()
        self.raise_overlays()

    def _layout_time_badge(self) -> None:
        video_right = self.video.geometry().right() + 1
        bottom = min(self.video.geometry().bottom() + 1, self.bottom.tile_y())
        self.time_badge.move(max(10, video_right - self.time_badge.width() - 10),
                             max(8, bottom - self.time_badge.height() - 10))

    def _sync_stream_badge(self) -> bool:
        """收窄 / 显隐 LIVE 浮标，让它和右上角的控制条在同一行站得下。

        返回「浮标露出来了没有」。

        第一行右边是控制条（画质 / 重连 / 关闭）—— 它是操作入口，必须钉在右上角，
        跑掉了就点不准。所以空间不够时让浮标让位：先收起人数（`set_compact`），
        再不够就整个收起来。

        注意别再用「格子够不够宽放下浮标自己」来判定：浮标放得下、加上控制条就
        不一定放得下，那正是控制条被挤到第二行的原因。

        **可见性只在这里决定**：以前好几处各设各的（`set_room` / `_refresh_badge` /
        `set_controls_visible`），漏一处就会出现「放不下却还露着」；`_layout_areas`
        那句还带了个 `if self._overlay_visible`，overlay 收起来时干脆不设，浮标就
        一直保持默认的可见。
        """
        room = self.width() - 10 - self.controls.width() - 12 - 10
        self.stream_badge.set_compact(self.stream_badge.full_width() > room)
        visible = (not self.property('pictureInPicture') and self._overlay_visible and bool(self.room.get("room_id"))
                   and self.stream_badge.width() <= room)
        self.stream_badge.setVisible(visible)
        return visible

    def _round_video(self) -> None:
        """视频窗口的圆角遮罩。

        **不要**在这里挖掉控制条那一块：挖了就露出格子底色，按钮周围会出现
        一条长方形黑底（用户报过好几次的老问题，`_update_controls_mask()` 那套
        「只留按钮轮廓」的机制才是治它的）。让控制条能点到靠的是
        `raise_overlays()` 把浮层重新抬到原生视频窗口之上。
        """
        square_corners = bool(self.property("fullscreen") or self.property('pictureInPicture'))
        self.video.square_corners = square_corners
        self.video_danmaku.set_quick_rounded(not square_corners)
        for index, corner in enumerate(self.video_corners):
            corner.move(self.video.x() if index == 0 else
                        self.video.geometry().right() - corner.width() + 1, self.video.y())
            corner.setVisible(not square_corners)
        key = (self.video.width(), self.video.height(), self.devicePixelRatioF(),
               square_corners, int(self.video.internalWinId()))
        if key == self._video_mask_key and not self.video.mask().isEmpty():
            self._update_quick_danmaku_mask()
            return
        self._video_mask_key = key
        path = QPainterPath()
        rect = QRectF(0, 0, max(1, self.video.width()), max(1, self.video.height()))
        if square_corners:
            path.addRect(rect)
        else:
            path.addPath(continuous_path(rect, 9))
            bottom = QPainterPath()
            bottom.addRect(QRectF(0, max(0, self.video.height() - 9), self.video.width(), 9))
            path = path.united(bottom)
            # Leave one physical pixel under the alpha-blended corner edge.
            stroke = QPainterPathStroker()
            stroke.setWidth(2 / self.devicePixelRatioF())
            bounds = QPainterPath()
            bounds.addRect(rect)
            path = path.united(stroke.createStroke(path)).intersected(bounds)
        self.video.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.video_danmaku.setMask(self.video.mask())
        for corner in self.video_corners:
            corner.update()
        self._update_quick_danmaku_mask()

    def _quality_button_width(self) -> int:
        """按画质文字算按钮宽度。

        用样式表里那号字来量，不能拿 button.fontMetrics()：QSS 的 font-size 不会
        改到控件的 QFont，量出来是默认字号的宽度，几个画质档位会算出同一个数，
        按钮就宽得离谱、文字也没居中。
        """
        font = QFont(theme.FONT_DEFAULT)
        font.setPixelSize(theme.FONT_CAPTION)
        font.setBold(True)                     # #TileCtrl 是 font-weight: 600
        advance = QFontMetrics(font).horizontalAdvance(self.quality_button.text())
        return max(theme.TILE_CONTROL_HEIGHT, advance + 16)

    def _layout_controls(self) -> None:
        """控制条浮在画面右上角，只显示按钮本身。

        按文本量宽后直接摆放三个按钮，让原生窗口遮罩和按钮始终使用同一组坐标。
        原生视频窗口上的 Qt 布局可能在显示或缩放后延迟更新子按钮的位置。
        """
        # 高度统一由代码给：样式表不再写 min-height，交给布局量出来会矮一截
        self.quality_button.setFixedHeight(theme.TILE_CONTROL_HEIGHT)
        self.quality_button.setFixedWidth(self._quality_button_width())
        self.close_button.setFixedSize(theme.TILE_CONTROL_HEIGHT, theme.TILE_CONTROL_HEIGHT)
        x = 0
        for button in (self.quality_button, self.reload_button, self.close_button):
            button.move(x, 0)
            x += button.width() + 6
        width = x - 6
        self.controls.resize(width, theme.TILE_CONTROL_HEIGHT)
        video_right = self.video.width() + 1
        self.controls.move(max(10, video_right - width - 10), 8)
        self._update_controls_mask()

    def event(self, event) -> bool:
        result = super().event(event)
        if (event.type() == QEvent.Type.DevicePixelRatioChange
                and getattr(self, "_overlay_ready", False)):
            # 等原生子窗口都切换到新屏幕比例后再重做遮罩。
            self._video_mask_key = self._controls_mask_key = self._cover_key = None
            self._mask_refresh_timer.start(0)
        return result

    def eventFilter(self, watched, event) -> bool:
        if watched is self.video:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                if self.property('fullscreen'):
                    # Native video clicks do not take Qt focus by default.
                    # End input mode so idle hiding and shortcuts can resume.
                    self.activateWindow()
                    self.setFocus(Qt.MouseFocusReason)
                self._press_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            elif event.type() == QEvent.MouseButtonRelease and self._open_clicked_danmaku(event):
                event.accept()
                return True
        if watched in (self.volume_button, self.volume_menu):
            if event.type() == QEvent.Enter:
                self._volume_hide_timer.stop()
                if watched is self.volume_button:
                    self._show_volume_popup()
            elif event.type() == QEvent.Leave and self.volume_menu.isVisible():
                # Allow crossing the small gap between the button and its popup.
                self._volume_hide_timer.start()
            elif event.type() == QEvent.Hide:
                self._volume_hide_timer.stop()
                if watched is self.volume_button:
                    self.volume_menu.hide()
        if event.type() in (QEvent.Type.WinIdChange, QEvent.Type.DevicePixelRatioChange):
            if watched is self.video:
                self._video_mask_key = None
            elif watched is self.controls:
                self._controls_mask_key = None
            if self.isVisible():
                self._mask_refresh_timer.start(0)
        return super().eventFilter(watched, event)

    def hideEvent(self, event) -> None:
        self._mask_refresh_timer.stop()
        self._move_repaint_timer.stop()
        self._volume_hide_timer.stop()
        self._control_hover_timer.stop()
        self._normal_hover_active = False
        self._restore_normal_cursor()
        self.volume_menu.hide()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._mask_refresh_timer.stop()
        self._move_repaint_timer.stop()
        super().closeEvent(event)

    def _refresh_overlay_masks(self) -> None:
        """所有原生浮层都要重新换算遮罩，文字不变时 Qt 不会自动更新它。"""
        self._video_mask_key = self._controls_mask_key = self._cover_key = None
        for widget in (self.video, self.video_danmaku, self.controls, self.stream_badge,
                       self.title_badge, self.time_badge):
            mask = widget.mask()
            widget.clearMask()
            if not mask.isEmpty():
                widget.setMask(mask)
        self._layout_areas()

    def _update_controls_mask(self) -> None:
        """裁掉原生控制窗口的矩形底，只留下三个圆角按钮的轮廓。"""
        scale = self.controls.devicePixelRatioF()
        key = (tuple(button.geometry().getRect() for button in
                     (self.quality_button, self.reload_button, self.close_button)), scale,
               int(self.controls.internalWinId()))
        if key == self._controls_mask_key and not self.controls.mask().isEmpty():
            return
        self._controls_mask_key = key
        if getattr(self, "_controls_mask_scale", None) != scale:
            # 跨屏后逻辑轮廓相同，Qt 会跳过 setMask，留下按旧 DPI 换算的原生区域。
            self.controls.clearMask()
        self._controls_mask_scale = scale
        region = QRegion()
        for button in (self.quality_button, self.reload_button, self.close_button):
            rect = QRectF(button.geometry())
            path = QPainterPath()
            radius = min(rect.height() / 2, theme.TILE_CONTROL_HEIGHT / 2)
            # 原生底色只能按整数区域裁切；扩张轮廓会露出圆角外的黑色底层。
            path.addPath(continuous_path(rect, radius))
            region = region.united(QRegion(path.toFillPolygon().toPolygon()))
        if (sys.platform == "win32" and QApplication.platformName() == "windows"
                and self.controls.internalWinId()):
            # Let Qt paint the complete antialiased edge; clip the native backing
            # at physical-pixel resolution instead of scaling a logical region.
            paint_region = QRegion()
            for button in (self.quality_button, self.reload_button, self.close_button):
                paint_region = paint_region.united(QRegion(button.geometry()))
            self.controls.setMask(paint_region)
            if self._apply_native_controls_mask(scale):
                return
        self.controls.setMask(region)

    def _apply_native_controls_mask(self, scale: float) -> bool:
        import ctypes
        from ctypes import wintypes

        gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateRectRgn.restype = wintypes.HANDLE
        gdi32.CreateRoundRectRgn.argtypes = (ctypes.c_int,) * 6
        gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
        gdi32.CombineRgn.argtypes = (wintypes.HANDLE,) * 3 + (ctypes.c_int,)
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        if not region:
            return False
        try:
            for button in (self.quality_button, self.reload_button, self.close_button):
                rect = button.geometry()
                diameter = round(rect.height() * scale)
                part = gdi32.CreateRoundRectRgn(
                    round(rect.x() * scale), round(rect.y() * scale),
                    round((rect.x() + rect.width()) * scale),
                    round((rect.y() + rect.height()) * scale), diameter, diameter)
                if not part:
                    return False
                try:
                    if not gdi32.CombineRgn(region, region, part, 2):  # RGN_OR
                        return False
                finally:
                    gdi32.DeleteObject(part)
            if user32.SetWindowRgn(int(self.controls.winId()), region, True):
                region = None          # Windows owns the successfully assigned region.
                return True
            return False
        finally:
            if region:
                gdi32.DeleteObject(region)

    def showEvent(self, event) -> None:
        # 需要在窗口真正显示之后再设为原生窗口，否则 Qt 会抱怨不是顶层窗口
        super().showEvent(event)
        for widget in (self.stream_badge, self.title_badge,
                       self.time_badge, self.controls,
                       self.spinner, self.pause_overlay):
            if not widget.testAttribute(Qt.WA_NativeWindow):
                widget.setAttribute(Qt.WA_NativeWindow, True)
            widget.raise_()
        self._round_video()
        self._update_controls_mask()
        self._layout_cover()

    # ---- 直播时长 ----
    def _elapsed_visible(self) -> bool:
        """直播时长浮标该不该露出来。

        用户要求：它和 LIVE 浮标、标题、控制条一样**自动隐藏** —— 鼠标在格子上
        才露，移开就跟着一起收（以前是只要在播就一直挂在右下角）。
        """
        return bool(not self.property('pictureInPicture') and self._overlay_visible
                    and getattr(self, "_elapsed_timer", None) is not None
                    and self._elapsed_timer.isActive()
                    and self.room.get("live")
                    and self.room.get("live_start_ts"))

    def _refresh_elapsed(self) -> None:
        start = int(self.room.get("live_start_ts") or 0)
        if not start or not self.room.get("live"):
            self.time_badge.setVisible(False)
            self._elapsed_timer.stop()
            return
        seconds = max(0, int(time.time()) - start)
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        text = f"{hours}:{minutes:02d}:{secs:02d}"
        self.time_badge.set_text(text)
        self.time_badge.setVisible(self._elapsed_visible())

    def start_elapsed_timer(self) -> None:
        if self.room.get("live_start_ts"):
            self._refresh_elapsed()
            self._elapsed_timer.start()

    def stop_elapsed_timer(self) -> None:
        self._elapsed_timer.stop()
        self.time_badge.setVisible(False)

    # ---- 右键菜单 ----
    def contextMenuEvent(self, event) -> None:
        if not self.room.get("room_id"):
            menu = QMenu(self)
            menu.addAction("切换为弹幕", self.paneEditRequested.emit)
            menu.exec(event.globalPos())
            menu.deleteLater()
            return
        # 插件要先把自己那一组菜单项登记进来（本体不认识它们）
        self.pluginMenuRequested.emit()
        menu = self.build_menu()
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()

    def build_menu(self) -> QMenu:
        """右键菜单：音量滑条 + 画质 + 声道 + 常规操作。"""
        menu = QMenu(self)

        # 音量（菜单里嵌滑条）
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(10, 6, 10, 4)
        holder_layout.setSpacing(4)
        volume_label = QLabel(f"音量 {self.volume}")
        volume_label.setObjectName("AppSubtitle")
        holder_layout.addWidget(volume_label)
        slider = QSlider(Qt.Horizontal, holder)
        slider.setRange(0, 100)
        slider.setValue(self.volume)
        slider.setFixedWidth(170)
        slider.valueChanged.connect(lambda value: (
            volume_label.setText(f"音量 {value}"), self.set_volume(value)))
        holder_layout.addWidget(slider)
        wrapper = QWidgetAction(menu)
        wrapper.setDefaultWidget(holder)
        menu.addAction(wrapper)
        menu.addSeparator()

        quality_menu = menu.addMenu("画质")
        for name, value in self._quality_choices():
            action = quality_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(value == self.quality)
            action.triggered.connect(lambda _checked=False, v=value: self.set_quality(v))

        menu.addAction("当前窗口编解码设置…", self.codecSettingsRequested.emit)
        info = menu.addAction("直播流信息…", lambda: QTimer.singleShot(0, self, self.streamInfoRequested.emit))
        info.setEnabled(bool(self.room.get('room_id')))

        # 声道：0 默认、3 只左、4 只右、2 反向立体声、5 杜比。
        # 只有「只左 / 只右」能把两路画面分到两只耳朵，其余是原程序的音效档。
        audio_menu = menu.addMenu("声道")
        for name, value in (("默认（跟随片源）", 0), ("只播左声道", 3),
                            ("只播右声道", 4), ("反向立体声", 2), ("杜比矩阵下混（多声道源）", 5)):
            action = audio_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(value == self.audio_channel)
            action.triggered.connect(lambda _checked=False, v=value: self.set_audio_channel(v))
        menu.addSeparator()
        menu.addAction("取消静音" if self.muted else "静音", self._toggle_mute)
        menu.addAction("弹幕观看设置…", lambda: QTimer.singleShot(0, self,
            lambda: self.danmaku_settings_menu.open_at(
                self.danmaku_button, self.video_danmaku.settings)))
        menu.addAction("刷新重连", lambda: self.reloadRequested.emit(self.room))
        menu.addAction("全屏查看", lambda: self.fullscreenRequested.emit(self))
        if self.plugin_actions:
            # 插件加的一项占一行；组与组之间用分隔线断开，免得和本体的项混在一起
            menu.addSeparator()
            for label, callback in self.plugin_actions:
                menu.addAction(label, callback)
        menu.addSeparator()
        if not (self.property("pictureInPicture") or self.property("fullscreen")):
            menu.addAction("切换为弹幕", self.paneEditRequested.emit)
        menu.addAction("关闭这一路", lambda: self.closeRequested.emit(self.room))
        return menu

    def set_volume(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self.volume = value
        self.room["volume"] = value
        self.volume_label.setText(str(value))
        self.volume_button.set_state(self.muted, value, self.audio_channel)
        self._sync_vertical_volume()
        if self.volume_slider.value() != value:
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(value)
            self.volume_slider.blockSignals(False)
        self.volumeChanged.emit(self.room, value)
        if self.muted and value > 0:
            # Apply the new level before making the player's audio audible.
            self.set_muted(False)

    def _sync_vertical_volume(self) -> None:
        blocked = self.vertical_volume.blockSignals(True)
        self.vertical_volume.setValue(self.volume)
        self.vertical_volume.blockSignals(blocked)
        self.vertical_volume_label.setText(str(self.volume))

    def sync_audio_ui(self) -> None:
        """按自己的 volume / muted / audio_channel 重画音量条（不发信号）。

        「秒切」把音量 / 静音 / 声道在对调的两个格子之间换了位，但只改了
        ``self.volume`` 这几个值、没重画控件 —— 用户看到的就是「音量条跟着画面
        跑过去，跟实际听到的声音对不上」。
        """
        self._sync_vertical_volume()
        if self.volume_slider.value() != self.volume:
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(self.volume)
            self.volume_slider.blockSignals(False)
        self.volume_label.setText(str(self.volume))
        self.volume_button.set_state(self.muted, self.volume, self.audio_channel)
        self._layout_controls()

    def set_audio_channel(self, value: int) -> None:
        if self.audio_channel != int(value):
            print(f"[声道切换] 房间={self.room.get('room_id', '')} "
                  f"{self.audio_channel} -> {int(value)} 来源={sys._getframe(1).f_code.co_name}",
                  file=sys.stderr, flush=True)
        if self.muted:
            self.set_muted(False)
        self.audio_channel = int(value)
        self.room["audio_channel"] = int(value)
        self.volume_button.set_state(self.muted, self.volume, self.audio_channel)
        self.audioChannelChanged.emit(self.room, int(value))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self._open_clicked_danmaku(event):
                event.accept()
                return
            self.clicked.emit(self.room)

    def set_focused(self, focused: bool) -> None:
        self.setProperty("focused", focused)
        _repolish(self)
