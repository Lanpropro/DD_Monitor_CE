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
from .tile_state import TileState
from .tile_controls import TileControls
from .tile_presentation import TilePresentation
from .tile_context_menu import TileContextMenu


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
        self.menu_control = TileContextMenu(self)
        self.presentation_control = TilePresentation(self)
        self.controls_control = TileControls(self)
        self.state_control = TileState(self)
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
        self._resize_raise_pending = False
        self._move_repaint_pending = False
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
        return self.state_control.set_room(room, cover)

    def _toggle_video_danmaku(self, enabled: bool) -> None:
        return self.state_control.toggle_video_danmaku(enabled)

    def _change_video_danmaku_settings(self, values: dict) -> None:
        return self.state_control.change_video_danmaku_settings(values)

    def apply_video_danmaku_settings(self, settings=None) -> None:
        return self.state_control.apply_video_danmaku_settings(settings)

    def _set_video_danmaku_independent(self, enabled: bool) -> None:
        return self.state_control.set_video_danmaku_independent(enabled)

    def plugin_interaction_active(self) -> bool:
        return self.controls_control.plugin_interaction_active()

    def _volume_controls_width(self):
        return self.presentation_control.volume_controls_width()

    def _bottom_layout_signature(self):
        """影响底栏布局的输入；没变就不用重排（悬停会频繁触发 _layout_areas）。"""
        return self.presentation_control.bottom_layout_signature()

    def _layout_bottom_controls(self) -> None:
        return self.presentation_control.layout_bottom_controls()

    def set_recording_state(self, state: str) -> None:
        return self.state_control.set_recording_state(state)

    def set_recording_elapsed(self, text: str) -> None:
        """更新「● REC」旁边的已录制时长；空串就把标签收起来。"""
        return self.state_control.set_recording_elapsed(text)

    def set_recording_available(self, available: bool) -> None:
        """录制功能总开关：关掉时把底栏的「● 录制」按钮收起来。"""
        return self.state_control.set_recording_available(available)

    def _update_recording_button(self, *, layout: bool = True) -> None:
        return self.state_control.update_recording_button(layout=layout)

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
            changed = str(self.room.get('room_id')) != room_id
            position = self.mapToGlobal(event.position().toPoint())
            event.acceptProposedAction()
            self.roomDropped.emit(room_id)
            if changed:
                from .card_drop import play_card_drop
                play_card_drop(self, event.mimeData(), position, room_id)
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
        return self.presentation_control.raise_overlays()

    def _update_quick_danmaku_mask(self) -> None:
        return self.presentation_control.update_quick_danmaku_mask()

    def set_video_active(self, active: bool) -> None:
        return self.state_control.set_video_active(active)

    def set_status(self, text: str) -> None:
        return self.state_control.set_status(text)

    def set_offline(self) -> None:
        """下播：画面清成黑的，格子继续留给这个直播间。"""
        return self.state_control.set_offline()

    def set_buffering(self, active: bool) -> None:
        """卡顿/缓冲中：显示缓冲动画（和连接时同一套样式）。"""
        return self.state_control.set_buffering(active)

    def _sync_status_label(self) -> None:
        """底栏保留空白布局区域；状态仍用于封面、加载图形及内部判断。"""
        return self.state_control.sync_status_label()

    def set_paused(self, paused: bool) -> None:
        return self.state_control.set_paused(paused)

    def set_live(self, live: bool, viewers: str = "") -> None:
        return self.state_control.set_live(live, viewers)

    def set_uname_title(self, uname: str, title: str) -> None:
        """补上主播名/标题：启动占位后由状态刷新补齐（悬停浮标显示用）。"""
        return self.state_control.set_uname_title(uname, title)

    def set_watched(self, watched_text: str) -> None:
        """实时在线人数（高能榜 onlineNum，和 B 站页面一致）。"""
        return self.state_control.set_watched(watched_text)

    def _refresh_badge(self) -> None:
        return self.state_control.refresh_badge()

    # ---- 控制 ----
    def _make_control(self, text: str, tip: str) -> QPushButton:
        button = TileButton(text)
        button.setObjectName("TileCtrl")
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def _quality_text(self) -> str:
        return self.state_control.quality_text()

    def _quality_name(self, qn: int, *, short: bool = False) -> str:
        return self.state_control.quality_name(qn, short=short)

    def _quality_choices(self) -> list[tuple[str, int]]:
        """优先用接口给的档位：直播间只提供哪些，菜单里就只留哪些。"""
        return self.state_control.quality_choices()

    def set_quality_options(self, options: list) -> None:
        return self.state_control.set_quality_options(options)

    def set_actual_quality(self, quality: int) -> None:
        """接口实际给的画质（未登录时通常只有 720P）。"""
        return self.state_control.set_actual_quality(quality)

    def _open_quality_menu(self) -> None:
        return self.state_control.open_quality_menu(menu_type=QMenu)

    def set_quality(self, value: int) -> None:
        return self.state_control.set_quality(value)

    def _volume_clicked(self) -> None:
        return self.controls_control.volume_clicked()

    def _show_volume_popup(self) -> None:
        return self.controls_control.show_volume_popup()

    def _hide_volume_popup_if_outside(self) -> None:
        return self.controls_control.hide_volume_popup_if_outside()

    def _toggle_mute(self) -> None:
        return self.state_control.toggle_mute()

    def set_muted(self, muted: bool) -> None:
        return self.state_control.set_muted(muted)

    def set_fullscreen_controls_hidden(self, hidden: bool, *, hide_bar: bool = True) -> None:
        return self.controls_control.set_fullscreen_controls_hidden(hidden, hide_bar=hide_bar)

    def _advance_bar_animation(self) -> None:
        return self.controls_control.advance_bar_animation()

    def _slide_fullscreen_bar(self, progress) -> None:
        return self.controls_control.slide_fullscreen_bar(progress)

    def set_controls_visible(self, visible: bool) -> None:
        return self.controls_control.set_controls_visible(visible)

    def _set_control_hover(self, hovered: QPushButton | None) -> None:
        """同步一份不依赖原生窗口 enter/leave 的悬停状态。"""
        return self.controls_control.set_control_hover(hovered)

    def _sync_control_hover(self, global_pos: QPoint | None = None) -> None:
        return self.controls_control.sync_control_hover(global_pos)

    def _poll_control_hover(self) -> None:
        return self.controls_control.poll_control_hover(native_cursor=set_native_cursor)

    def _restore_normal_cursor(self) -> None:
        return self.controls_control.restore_normal_cursor(native_cursor=set_native_cursor)

    def _hide_controls_if_outside(self) -> None:
        return self.controls_control.hide_controls_if_outside()

    def _show_danmaku_actions(self, text, position):
        return self.controls_control.show_danmaku_actions(text, position)

    def _open_clicked_danmaku(self, event):
        return self.controls_control.open_clicked_danmaku(event)

    def focus_danmaku_input(self) -> None:
        return self.controls_control.focus_danmaku_input()

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
        return self.presentation_control.set_cover(pixmap)

    def set_interactive_resize(self, active: bool) -> None:
        return self.presentation_control.set_interactive_resize(active)

    def _layout_cover(self) -> None:
        return self.presentation_control.layout_cover(render_pixmap=rounded_pixmap)

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
        return self.presentation_control.refresh_moved_overlays()

    def _layout_areas(self) -> None:
        """统一摆放：视频区、浮标、控制条、信息条。"""
        return self.presentation_control.layout_areas()

    def _layout_time_badge(self) -> None:
        return self.presentation_control.layout_time_badge()

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
        return self.presentation_control.sync_stream_badge()

    def _round_video(self) -> None:
        """视频窗口的圆角遮罩。

        **不要**在这里挖掉控制条那一块：挖了就露出格子底色，按钮周围会出现
        一条长方形黑底（用户报过好几次的老问题，`_update_controls_mask()` 那套
        「只留按钮轮廓」的机制才是治它的）。让控制条能点到靠的是
        `raise_overlays()` 把浮层重新抬到原生视频窗口之上。
        """
        return self.presentation_control.round_video()

    def _quality_button_width(self) -> int:
        """按画质文字算按钮宽度。

        用样式表里那号字来量，不能拿 button.fontMetrics()：QSS 的 font-size 不会
        改到控件的 QFont，量出来是默认字号的宽度，几个画质档位会算出同一个数，
        按钮就宽得离谱、文字也没居中。
        """
        return self.presentation_control.quality_button_width()

    def _layout_controls(self) -> None:
        """控制条浮在画面右上角，只显示按钮本身。

        按文本量宽后直接摆放三个按钮，让原生窗口遮罩和按钮始终使用同一组坐标。
        原生视频窗口上的 Qt 布局可能在显示或缩放后延迟更新子按钮的位置。
        """
        return self.presentation_control.layout_controls()

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
        return self.presentation_control.refresh_overlay_masks()

    def _update_controls_mask(self) -> None:
        """裁掉原生控制窗口的矩形底，只留下三个圆角按钮的轮廓。"""
        return self.presentation_control.update_controls_mask()

    def _apply_native_controls_mask(self, scale: float) -> bool:
        return self.presentation_control.apply_native_controls_mask(scale)

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
        return self.state_control.elapsed_visible()

    def _refresh_elapsed(self) -> None:
        return self.state_control.refresh_elapsed()

    def start_elapsed_timer(self) -> None:
        return self.state_control.start_elapsed_timer()

    def stop_elapsed_timer(self) -> None:
        return self.state_control.stop_elapsed_timer()

    # ---- 右键菜单 ----
    def contextMenuEvent(self, event) -> None:
        if not self.room.get("room_id"):
            menu = QMenu(self)
            menu.addAction("切换为弹幕", self.paneEditRequested.emit).setData('switch_danmaku')
            from .tile_menu import arrange_menu
            arrange_menu(menu, self._video_danmaku_global_settings.get('tile_context_menu'))
            if not menu.isEmpty():
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
        return self.menu_control.build_menu(menu_type=QMenu)

    def set_volume(self, value: int) -> None:
        return self.state_control.set_volume(value)

    def _sync_vertical_volume(self) -> None:
        return self.state_control.sync_vertical_volume()

    def sync_audio_ui(self) -> None:
        """按自己的 volume / muted / audio_channel 重画音量条（不发信号）。

        「秒切」把音量 / 静音 / 声道在对调的两个格子之间换了位，但只改了
        ``self.volume`` 这几个值、没重画控件 —— 用户看到的就是「音量条跟着画面
        跑过去，跟实际听到的声音对不上」。
        """
        return self.state_control.sync_audio_ui()

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
        return self.presentation_control.set_focused(focused)
