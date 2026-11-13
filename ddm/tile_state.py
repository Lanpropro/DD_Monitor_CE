"""Tile state; mutable state and Qt ownership stay with Tile."""
import time
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import QMenu
from .auto_quality import AUTO_QUALITY, OVERSEAS_PLATFORMS
from .config import VIDEO_DANMAKU_SETTING_KEYS, video_danmaku_overrides
from .widget_support import QUALITY_CHOICES, QUALITY_NAMES, WATCHING_TEXT, _repolish


class TileState:
    def __init__(self, host):
        self.host = host

    def set_room(self, room: dict | None, cover: QPixmap | None = None) -> None:
        """换这一个格子播放的房间；音量和静音属于格子，不跟着房间移动。"""
        host = self.host
        host.room = dict(room or {})
        controls = getattr(host, '_plugin_controls', None)
        if controls is not None:
            controls.set_room(host.room)
        host.codec_probe_note = ""
        host.codec_reconnect_pending = False
        host.video_danmaku.clear()
        host.quality_options = []          # 换平台/直播间后不能沿用上一个房间的档位
        host.actual_quality = 0
        host.stream_url = ""
        host.stream_headers = {}
        host.set_recording_state("")
        empty = not host.room.get("room_id")
        host.setProperty("empty", empty)
        _repolish(host)
        host.set_controls_visible(False)
        host.set_paused(False)
        host.set_video_active(False)
        host.set_buffering(False)
        # 开关属于当前房间；新主播默认关闭，换位则恢复该房间保存的开关。
        host.danmaku_button.setChecked(bool(host.room.get("video_danmaku_enabled", False)))
        host._layout_areas()

        if empty:
            # 平台画质编号属于房间，空格子不能把它作为分辨率显示或继续保存。
            host.quality = 250
            host.quality_button.setText(host._quality_text())
            host.quality_button.setToolTip("选择这一路的画质")
            host._layout_controls()
            host._cover_source = None
            host.title_badge.set_text("", "")
            host.title_badge.setVisible(False)
            host.stream_badge.setVisible(False)
            host.set_status("拖入直播间")
            return

        host.room["volume"] = host.volume
        host.room["muted"] = host.muted
        host._sync_stream_badge()
        host._cover_source = cover if cover is not None else host.room.get("cover")
        host.title_badge.set_text(host.room.get("uname", ""), host.room.get("title", ""))
        host.title_badge.setVisible(bool(host.room.get("uname")) and host._overlay_visible)
        host._refresh_badge()
        host.quality = int(host.room.get("quality", AUTO_QUALITY
            if str(host.room.get("room_id", "")).partition(":")[0] in OVERSEAS_PLATFORMS else 250))
        # 声道和音量 / 静音一样属于**格子**，不跟着房间走：换台不该把用户调好的
        # 「只播左 / 只播右」丢掉。房间自带的那份只在第一次上墙时用（_prepare_room）。
        host.room["audio_channel"] = host.audio_channel
        host.quality_button.setText(host._quality_text())
        host.volume_slider.blockSignals(True)
        host.volume_slider.setValue(host.volume)
        host.volume_slider.blockSignals(False)
        host.volume_label.setText(str(host.volume))
        host.volume_button.set_state(host.muted, host.volume, host.audio_channel)
        host.set_status("" if host.room.get("live") else "未开播")
        host.stop_elapsed_timer()
        if host.room.get("live"):
            host.start_elapsed_timer()
        host._layout_cover()

    def toggle_video_danmaku(self, enabled: bool) -> None:
        host = self.host
        host.room["video_danmaku_enabled"] = bool(enabled)
        host.danmaku_button.setToolTip("关闭画面弹幕（默认 B）" if enabled
                                       else "开启画面弹幕（默认 B）")
        host.video_danmaku.set_enabled(enabled)
        if getattr(host, "_overlay_ready", False):
            host.raise_overlays()
            # Creating the layered danmaku HWND can expose Qt's rectangular
            # backing masks; restore native overlay contours after it settles.
            host._mask_refresh_timer.start(0)
        host.videoDanmakuChanged.emit(enabled)

    def change_video_danmaku_settings(self, values: dict) -> None:
        host = self.host
        global_values = dict(values)
        if host.video_danmaku_overrides is not None:
            for key in VIDEO_DANMAKU_SETTING_KEYS:
                if key in global_values:
                    host.video_danmaku_overrides[key] = global_values.pop(key)
        host._video_danmaku_global_settings.update(global_values)
        host.apply_video_danmaku_settings()
        host.videoDanmakuSettingsChanged.emit(global_values)

    def apply_video_danmaku_settings(self, settings=None) -> None:
        host = self.host
        if settings is not None:
            host._video_danmaku_global_settings = dict(settings)
        effective = {**host._video_danmaku_global_settings, **(host.video_danmaku_overrides or {})}
        host.video_danmaku.apply_settings(effective)
        host.danmaku_settings_menu.apply_settings(
            effective, independent=host.video_danmaku_overrides is not None)

    def set_video_danmaku_independent(self, enabled: bool) -> None:
        host = self.host
        host.video_danmaku_overrides = (
            video_danmaku_overrides(host._video_danmaku_global_settings) if enabled else None)
        host.apply_video_danmaku_settings()
        host.videoDanmakuSettingsChanged.emit({})

    def set_recording_state(self, state: str) -> None:
        host = self.host
        host._recording_state = state
        host._update_recording_button()
        host.recording_button.setProperty("recording", state == "record")
        _repolish(host.recording_button)
        host.recording_button.setToolTip(
            "停止录制这一路" if state == "record" else
            "即时回放缓存中；点击开始完整录制" if state == "cache" else
            "开始录制这一路（右键可保存即时回放）")

    def set_recording_elapsed(self, text: str) -> None:
        """更新「● REC」旁边的已录制时长；空串就把标签收起来。"""
        host = self.host
        if not hasattr(host, "recording_time"):
            return
        host.recording_time.setText(text)
        host._layout_bottom_controls()

    def set_recording_available(self, available: bool) -> None:
        """录制功能总开关：关掉时把底栏的「● 录制」按钮收起来。"""
        host = self.host
        host._recording_available = bool(available)
        host._update_recording_button()

    def update_recording_button(self, *, layout: bool = True) -> None:
        host = self.host
        if not hasattr(host, "recording_button"):
            return
        # 录制功能总开关关掉时，整个「● 录制」按钮收起来（见 set_recording_available）。
        # 放在这里而不是 set_recording_available 里：录制状态每次变都会走这个方法，
        # 各处刷新不会把按钮又露出来。
        available = getattr(host, "_recording_available", True)
        host.recording_button.setVisible(available)
        if not available:
            if layout:
                host._layout_bottom_controls()
            return
        narrow = host.width() < 320
        state = getattr(host, "_recording_state", "")
        host.recording_button.setProperty('replayOnly', state == 'cache')
        host.recording_button.setAccessibleName(
            '即时回放缓存中；点击开始完整录制' if state == 'cache' else
            '停止录制这一路' if state == 'record' else '开始录制这一路')
        labels = ({"record": "●", "cache": "●", "": "●"} if narrow else
                  {"record": "● REC", "cache": "● REC", "": "● 录制"})
        host.recording_button.setFixedWidth(26 if narrow else 64)
        host.recording_button.setText(labels.get(state, "●"))
        host.recording_button.update()
        if layout:
            host._layout_bottom_controls()

    def set_video_active(self, active: bool) -> None:
        host = self.host
        host._player_active = active
        host.video_danmaku.set_active(active)
        host.cover.setVisible(not active)
        if not active:
            host._layout_cover()
        if active:
            host.spinner.stop()
            host._connecting = False
        else:
            host.pause_overlay.stop()
        host.raise_overlays()

    def set_status(self, text: str) -> None:
        host = self.host
        host._status_text = text
        host._connecting = text.startswith("连接中")
        host._sync_status_label()
        if not host._player_active:
            if host._connecting:
                host.spinner.start()
            else:
                host.spinner.stop()
            host._layout_cover()              # 让封面文字随状态刷新（连接时不显示文字）

    def set_offline(self) -> None:
        """下播：画面清成黑的，格子继续留给这个直播间。"""
        host = self.host
        host.room["live"] = False
        host._cover_source = None
        host.set_video_active(False)
        host.set_buffering(False)
        host.set_paused(False)
        host.stop_elapsed_timer()
        host._refresh_badge()
        host.stream_badge.set_offline()
        host.set_status("已下播")
        # The cover already hides the last frame; let Qt coalesce the clearing
        # with pending startup/layout paints instead of flushing the whole wall.
        host.video.update()

    def set_buffering(self, active: bool) -> None:
        """卡顿/缓冲中：显示缓冲动画（和连接时同一套样式）。"""
        host = self.host
        host._connecting = active
        host._buffering = bool(active)
        host._sync_status_label()
        if active:
            host.spinner.start()
        else:
            host.spinner.stop()
        if not host._player_active:
            host._layout_cover()

    def sync_status_label(self) -> None:
        """底栏保留空白布局区域；状态仍用于封面、加载图形及内部判断。"""
        host = self.host
        host.status_label.setText("")

    def set_paused(self, paused: bool) -> None:
        host = self.host
        host.paused = bool(paused)
        host.pause_button.set_paused(host.paused)
        host.video_danmaku.set_paused(host.paused)
        if host.paused and host._player_active:
            host.pause_overlay.start()
            host.pause_overlay.raise_()
        else:
            host.pause_overlay.stop()
        host._update_quick_danmaku_mask()
        host._layout_controls()

    def set_live(self, live: bool, viewers: str = "") -> None:
        host = self.host
        host.room["live"] = live
        if viewers:
            host.room["viewers"] = viewers
        if not live:
            host.room.pop("online", None)      # 下播后旧的在线人数不能再留着显
            host.stop_elapsed_timer()          # 右下角的时长浮标也立刻收掉
        host._refresh_badge()

    def set_uname_title(self, uname: str, title: str) -> None:
        """补上主播名/标题：启动占位后由状态刷新补齐（悬停浮标显示用）。"""
        host = self.host
        host.room["uname"] = uname or ""
        host.room["title"] = title or ""
        host.title_badge.set_text(host.room["uname"], host.room["title"])
        host.title_badge.setVisible(bool(host.room["uname"]) and host._overlay_visible)

    def set_watched(self, watched_text: str) -> None:
        """实时在线人数（高能榜 onlineNum，和 B 站页面一致）。"""
        host = self.host
        if watched_text:
            host.room["online"] = watched_text
        host._refresh_badge()

    def refresh_badge(self) -> None:
        host = self.host
        supports_count = str(host.room.get("room_id", "")).isdigit()
        watched = (host.room.get("online") or "") if supports_count else ""
        popularity = (host.room.get("viewers") or "") if supports_count else ""
        live = bool(host.room.get("live"))
        # 优先显示实时在线人数；还没拉到就别拿人气值顶上（那个数看着很像异常）
        host.stream_badge.set_state(live, watched or (WATCHING_TEXT if live and supports_count else ""))
        # 悬停才露（和控制条同步）；不然一屏好几格的 LIVE 一直挂着太吵。
        # 宽度够不够同时放下它和控制条，交给 _sync_stream_badge() 一起算
        host._sync_stream_badge()
        host._layout_areas()          # 浮标宽度会变（人数位数不同），标题要跟着重新让位
        if not supports_count:
            host.stream_badge.setToolTip("直播中" if live else "未开播")
        elif watched and popularity:
            host.stream_badge.setToolTip(f"{watched} 人在线 · 人气 {popularity}")
        elif watched:
            host.stream_badge.setToolTip(f"{watched} 人在线")
        elif live and popularity:
            host.stream_badge.setToolTip(f"正在获取在线人数…（当前人气 {popularity}）")
        elif live:
            host.stream_badge.setToolTip("正在获取在线人数…")
        elif popularity:
            host.stream_badge.setToolTip(f"人气 {popularity}")

    def quality_text(self) -> str:
        host = self.host
        if host.quality == AUTO_QUALITY:
            return "自动" + (" · " + host._quality_name(host.actual_quality, short=True)
                           if host.actual_quality else "")
        return host._quality_name(host.actual_quality or host.quality, short=True)

    def quality_name(self, qn: int, *, short: bool = False) -> str:
        host = self.host
        if qn == AUTO_QUALITY:
            return "自动" if short else "自动（根据网络选择流畅的最高画质）"
        for item in host.quality_options:
            if int(item.get("qn") or 0) == int(qn):
                return str((item.get("label") if short else None) or item.get("desc") or qn)
        if ":" in str(host.room.get("room_id") or ""):
            return "最高可用" if int(qn) == 10000 else "获取画质…"
        return QUALITY_NAMES.get(int(qn), f"{qn}P")

    def quality_choices(self) -> list[tuple[str, int]]:
        """优先用接口给的档位：直播间只提供哪些，菜单里就只留哪些。"""
        host = self.host
        if host.quality_options:
            return [(host._quality_name(int(item["qn"])), int(item["qn"]))
                    for item in host.quality_options]
        if ":" in str(host.room.get("room_id") or ""):
            return []                     # 接口返回前不展示 B 站的固定画质菜单
        return list(QUALITY_CHOICES)

    def set_quality_options(self, options: list) -> None:
        host = self.host
        if not options:
            return
        host.quality_options = [dict(item) for item in options]
        host.quality_button.setText(host._quality_text())
        host._layout_controls()

    def set_actual_quality(self, quality: int) -> None:
        """接口实际给的画质（未登录时通常只有 720P）。"""
        host = self.host
        host.actual_quality = int(quality or 0)
        host.quality_button.setText(host._quality_text())
        host._layout_controls()
        if ":" in str(host.room.get("room_id") or ""):
            host.quality_button.setToolTip(("自动画质，当前：" if host.quality == AUTO_QUALITY else "")
                                          + host._quality_name(host.actual_quality))
        elif host.actual_quality and host.actual_quality < host.quality:
            host.quality_button.setToolTip(
                f"请求 {host._quality_name(host.quality)}，"
                f"实际 {host._quality_name(host.actual_quality)}"
                f"（该直播间/当前账号最高只提供这一档）")
        else:
            host.quality_button.setToolTip("选择这一路的画质")

    def open_quality_menu(self, *, menu_type) -> None:
        QMenu = menu_type
        host = self.host
        menu = QMenu(host)
        for name, value in host._quality_choices():
            action = QAction(name, menu)
            action.setCheckable(True)
            action.setChecked(value == host.quality)
            action.triggered.connect(lambda _checked=False, v=value: host.set_quality(v))
            menu.addAction(action)
        try:
            menu.exec(host.quality_button.mapToGlobal(host.quality_button.rect().bottomLeft()))
        finally:
            menu.deleteLater()

    def set_quality(self, value: int) -> None:
        host = self.host
        if getattr(host, "quality_locked", False) and value != 10000:
            return
        host.quality = value
        host.actual_quality = 0
        host.quality_button.setText(host._quality_text())
        host.quality_button.setToolTip("选择这一路的画质")
        host._layout_controls()
        host.qualityChanged.emit(host.room, value)

    def toggle_mute(self) -> None:
        host = self.host
        host.set_muted(not host.muted)

    def set_muted(self, muted: bool) -> None:
        host = self.host
        host.muted = bool(muted)
        host.room["muted"] = host.muted
        host.volume_button.set_state(muted, host.volume, host.audio_channel)
        host._layout_controls()
        host.muteToggled.emit(host.room, muted)

    def set_volume(self, value: int) -> None:
        host = self.host
        value = max(0, min(100, int(value)))
        host.volume = value
        host.room["volume"] = value
        host.volume_label.setText(str(value))
        host.volume_button.set_state(host.muted, value, host.audio_channel)
        host._sync_vertical_volume()
        if host.volume_slider.value() != value:
            host.volume_slider.blockSignals(True)
            host.volume_slider.setValue(value)
            host.volume_slider.blockSignals(False)
        host.volumeChanged.emit(host.room, value)
        if host.muted and value > 0:
            # Apply the new level before making the player's audio audible.
            host.set_muted(False)

    def sync_vertical_volume(self) -> None:
        host = self.host
        blocked = host.vertical_volume.blockSignals(True)
        host.vertical_volume.setValue(host.volume)
        host.vertical_volume.blockSignals(blocked)
        host.vertical_volume_label.setText(str(host.volume))

    def sync_audio_ui(self) -> None:
        """按自己的 volume / muted / audio_channel 重画音量条（不发信号）。

        「秒切」把音量 / 静音 / 声道在对调的两个格子之间换了位，但只改了
        ``self.volume`` 这几个值、没重画控件 —— 用户看到的就是「音量条跟着画面
        跑过去，跟实际听到的声音对不上」。
        """
        host = self.host
        host._sync_vertical_volume()
        if host.volume_slider.value() != host.volume:
            host.volume_slider.blockSignals(True)
            host.volume_slider.setValue(host.volume)
            host.volume_slider.blockSignals(False)
        host.volume_label.setText(str(host.volume))
        host.volume_button.set_state(host.muted, host.volume, host.audio_channel)
        host._layout_controls()

    def elapsed_visible(self) -> bool:
        """直播时长浮标该不该露出来。

        用户要求：它和 LIVE 浮标、标题、控制条一样**自动隐藏** —— 鼠标在格子上
        才露，移开就跟着一起收（以前是只要在播就一直挂在右下角）。
        """
        host = self.host
        return bool(not host.property('pictureInPicture') and host._overlay_visible
                    and getattr(host, "_elapsed_timer", None) is not None
                    and host._elapsed_timer.isActive()
                    and host.room.get("live")
                    and host.room.get("live_start_ts"))

    def refresh_elapsed(self) -> None:
        host = self.host
        start = int(host.room.get("live_start_ts") or 0)
        if not start or not host.room.get("live"):
            host.time_badge.setVisible(False)
            host._elapsed_timer.stop()
            return
        seconds = max(0, int(time.time()) - start)
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        text = f"{hours}:{minutes:02d}:{secs:02d}"
        host.time_badge.set_text(text)
        host.time_badge.setVisible(host._elapsed_visible())

    def start_elapsed_timer(self) -> None:
        host = self.host
        if host.room.get("live_start_ts"):
            host._elapsed_timer.start()
            host._refresh_elapsed()

    def stop_elapsed_timer(self) -> None:
        host = self.host
        host._elapsed_timer.stop()
        host.time_badge.setVisible(False)
