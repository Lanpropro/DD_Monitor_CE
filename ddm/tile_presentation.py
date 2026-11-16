"""Tile presentation; mutable state and Qt ownership stay with Tile."""
import sys
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainterPath, QPainterPathStroker, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget
from . import layouts, theme
from .corner_geometry import continuous_path
from .widget_support import TILE_BAR_HEIGHT, _repolish, rounded_pixmap


class TilePresentation:
    def __init__(self, host):
        self.host = host

    def volume_controls_width(self):
        host = self.host
        from .wall_widgets import WallGrid
        wall = host.parentWidget()
        if (not isinstance(wall, WallGrid) or wall.fullscreen_tile is not None
                or wall.picture_in_picture_tiles is not None):
            return host.width()
        spec = layouts.BY_ID.get(wall.layout_id, {}).get('spec')
        if spec is None:
            return host.width()
        rows, columns, cells = spec
        ratios = wall._layout_ratios.get(wall.layout_id, {})
        if (cells != layouts.even_cells(rows, columns)
                or any(node.axis == Qt.Horizontal and len(set(ratios.get(node.key, node.weights))) > 1
                       for node in wall._partitions[wall.layout_id].nodes())):
            return host.width()
        # Equal cells may differ by one pixel. Choose the style for the smallest
        # cell from the target wall geometry, not siblings still awaiting resize.
        return (wall._corner_area().width() - wall.grid.spacing() * (columns - 1)) // columns

    def bottom_layout_signature(self):
        """影响底栏布局的输入；没变就不用重排（悬停会频繁触发 _layout_areas）。"""
        host = self.host
        return (host.width(), host._volume_controls_width(),
                host.bottom.width(),
                tuple((e.owner, e.key, e.control.widget.isHidden(),
                       e.control.minimum_width, e.control.preferred_width)
                      for e in getattr(getattr(host, '_plugin_controls', None), 'entries', ())),
                host.isVisible(),
                bool(getattr(host, "_fullscreen_controls_hidden", False)),
                host.recording_time.text(),
                bool(getattr(host, "_recording_available", True)),
                host.status_label.text(),
                theme.mode())

    def layout_bottom_controls(self) -> None:
        host = self.host
        width = host.width()
        signature = host._bottom_layout_signature()
        if signature == getattr(host, "_bottom_layout_signature_value", None):
            return
        host._bottom_layout_signature_value = signature
        volume_width = host._volume_controls_width()
        compact = width < 420
        layout = host.bottom.layout()
        margin, spacing = (6, 4) if compact else (10, 8)
        if width < 260:
            margin, spacing = 4, 2
        # 间距不因为输入区而变：底栏原有按钮的位置必须和没有输入区时一模一样。
        layout.setContentsMargins(margin, 4, margin, 4)
        layout.setSpacing(spacing)
        host.pause_button.setFixedWidth(26 if width < 260 else 34)
        # 弹幕开关只显示「弹」字图标，开关状态由右下角的勾表示（B 站播放器同款），
        # 不再用整块底色区分开/关。
        host.danmaku_button.setFixedWidth(26 if compact else 34)
        host.danmaku_button.setText("弹")
        # 保留原有功能入口；小格子的音量改由向上展开的竖向滑条调整。
        host.volume_label.setVisible(volume_width >= 600)
        host.recording_time.setVisible(bool(host.recording_time.text()) and width >= 360
                                       and getattr(host, "_recording_available", True))
        host.volume_slider.setVisible(volume_width >= 600)
        host.volume_button.compact_popup = volume_width < 600
        host.volume_button._update_tooltip()
        if volume_width >= 600:
            host.volume_menu.hide()
        host.status_label.setVisible(True)
        host.danmaku_settings_button.setVisible(True)
        host.recording_button.setVisible(getattr(host, "_recording_available", True))
        layout.activate()       # 让上面定的固定宽度立刻生效，下面算剩余宽度才准
        others = [host.pause_button, host.volume_button, host.volume_label,
                  host.danmaku_button, host.danmaku_settings_button,
                  host.recording_button, host.recording_time, host.fullscreen_button]
        visible = [widget for widget in others if not widget.isHidden()]
        fixed = sum(widget.sizeHint().width() if widget is host.recording_time else widget.width()
                    for widget in visible)
        # 原有控件的宽度完全按「没有输入区」时算，按钮位置因此不会变。
        available = width - fixed - margin * 2 - spacing * (len(visible) + 1)
        slider_width = max(18, min(86, available - 8))
        host.volume_slider.setFixedWidth(slider_width)
        host.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        host.status_label.setMinimumWidth(0)
        host.status_label.setMaximumWidth(16777215)
        layout.setStretchFactor(host.status_label, 1)
        extensions = getattr(host, '_plugin_controls', None)
        if extensions is not None and not extensions._disposed:
            # Existing player actions determine the free interval; extensions
            # share one centered, bounded region without moving those actions.
            extensions.spacer.setFixedWidth(0)
            layout.activate()
            left_controls = [w for w in (host.pause_button, host.volume_button,
                host.volume_slider, host.volume_label) if not w.isHidden()]
            right_controls = [w for w in (host.danmaku_button, host.danmaku_settings_button,
                host.recording_button, host.recording_time, host.fullscreen_button) if not w.isHidden()]
            left = margin + sum(w.width() for w in left_controls) + spacing * len(left_controls)
            right = (host.bottom.width() - margin - sum(w.width() for w in right_controls)
                     - spacing * max(0, len(right_controls) - 1))
            cap = min(520, max(300, int(width * 0.45)))
            fitted = extensions.allocate(min(cap, max(0, right - left - 3 * spacing)))
            if fitted:
                x = max(left + spacing, min((host.bottom.width() - fitted) // 2,
                                            right - 2 * spacing - fitted))
                host.status_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                host.status_label.setFixedWidth(max(0, x - left - spacing))
                layout.setStretchFactor(host.status_label, 0)
                extensions.spacer.setFixedWidth(max(0, right - 2 * spacing - x - fitted))
        layout.activate()

    def raise_overlays(self) -> None:
        """把浮层重新抬到**原生视频窗口**之上。

        画面是原生子窗口（HWND），默认压在所有 Qt 子控件上面；浮层只有也是原生
        窗口、并且被 raise 过，才既画得出来也点得到。所以每次摆完位都要再抬一次
        —— 用户报过「竖屏 1+4 里最下面两个格子的 ✕ 点不动」，就是浮层被视频盖住。
        """
        host = self.host
        compact = bool(host.property('pictureInPicture'))
        host.video_danmaku.raise_()
        for corner in host.video_corners:
            if not compact or corner.isVisible():
                corner.raise_()
        for widget in (host.controls, host.stream_badge, host.title_badge,
                       host.time_badge, host.spinner, host.pause_overlay, host.bottom):
            if not compact or widget.isVisible():
                widget.raise_()
        host._update_quick_danmaku_mask()
        wall = host.parentWidget()
        quick_layer = getattr(wall, "_quick_danmaku_layer", None)
        if quick_layer is not None:
            quick_layer.raise_()
        border = getattr(wall, '_pane_borders', {}).get(host)
        if border is not None and border.isVisible():
            border.raise_()

    def update_quick_danmaku_mask(self) -> None:
        host = self.host
        host.video_danmaku.update_quick_mask((
            host.controls, host.stream_badge, host.title_badge, host.time_badge,
            host.spinner, host.pause_overlay, host.bottom))

    def set_cover(self, pixmap: QPixmap | None) -> None:
        host = self.host
        host._cover_source = pixmap
        host._layout_cover()

    def set_interactive_resize(self, active: bool) -> None:
        host = self.host
        active = bool(active)
        if active == host._interactive_resize:
            return
        host._interactive_resize = active
        if not active:
            if host.isVisible():
                host._layout_cover()
                if host._resize_raise_pending:
                    host.raise_overlays()
                if host._move_repaint_pending:
                    host._move_repaint_timer.start(0)
            host._resize_raise_pending = False
            host._move_repaint_pending = False

    def layout_cover(self, *, render_pixmap) -> None:
        rounded_pixmap = render_pixmap
        host = self.host
        host.cover.setGeometry(host.video.rect())
        source = getattr(host, "_cover_source", None)
        if host.cover.isHidden():
            return
        if source and not source.isNull():
            radius = 0 if host.property('pictureInPicture') else 8
            key = (source.cacheKey(), host.video.width(), host.video.height(),
                   host.devicePixelRatioF(), bool(host.property("fullscreen")), radius)
            if key == host._cover_key:
                host.cover.setScaledContents(False)
                return
            if host._interactive_resize:
                if not host._cover_cached.isNull():
                    host.cover.setScaledContents(True)
                    host.cover.setPixmap(host._cover_cached)
                return
            host._cover_cached = rounded_pixmap(source, host.video.size(), radius)
            host._cover_key = key
            host.cover.setScaledContents(False)
            host.cover.setPixmap(host._cover_cached)
        else:
            host._cover_key = None
            host._cover_cached = QPixmap()
            host.cover.setScaledContents(False)
            host.cover.setPixmap(QPixmap())
            if host._player_active or getattr(host, "_connecting", False):
                host.cover.setText("")        # 播放中 / 连接中都不显示文字，避免和动画重叠
            else:
                fallback = host.room.get("uname", "") if host.room.get("live") else "未开播"
                host.cover.setText(host._status_text or fallback)

    def refresh_moved_overlays(self) -> None:
        # Native child windows can retain old backing-store text after only their parent moved.
        host = self.host
        host._move_repaint_timer.stop()
        if not host.isVisible():
            return
        # Keep normal Qt paints during native resizing; flushing each native
        # child separately stalls the next size message. Force a final repaint
        # on release so the existing moved-text repair remains in effect.
        host._move_repaint_pending = host._interactive_resize
        for widget in (host.video_danmaku, host.stream_badge, host.title_badge, host.time_badge,
                       host.controls, host.spinner, host.pause_overlay, host.bottom):
            if widget.isVisible():
                widget.update() if host._interactive_resize else widget.repaint()
        for widget in host.bottom.findChildren(QWidget):
            if widget.isVisible() and widget.testAttribute(Qt.WA_NativeWindow):
                widget.update() if host._interactive_resize else widget.repaint()
        host.update()

    def layout_areas(self) -> None:
        """统一摆放：视频区、浮标、控制条、信息条。"""
        host = self.host
        if getattr(host, '_presentation_changing', False):
            return
        width, height = host.width(), host.height()
        scale = 1.0
        if host.property('pictureInPicture'):
            natural = host.spinner.natural_size()
            scale = min(.75, max(1, width - 12) / natural.width(), max(1, height - 12) / natural.height())
        host.spinner.set_presentation_scale(scale)
        if host.property('pictureInPicture'):
            # PiP has no per-tile bar, badges or text controls. Keep their native
            # windows out of the synchronous resize path while retaining video,
            # comments, SC, loading and pause presentation.
            host.bottom.hide()
            host.video.setGeometry(host.rect())
            host.video_danmaku.setGeometry(host.rect())
            host._round_video()
            host.spinner.move(max(0, (width - host.spinner.width()) // 2),
                              max(8, (height - host.spinner.height()) // 2))
            host.pause_overlay.move(max(0, (width - host.pause_overlay.width()) // 2),
                                    max(8, (height - host.pause_overlay.height()) // 2))
            host._layout_cover()
            host.raise_overlays()
            return
        host._update_recording_button(layout=False)
        # 全屏底栏覆盖视频，收起时不改变原生视频尺寸。
        fullscreen = bool(host.property("fullscreen"))
        compact = bool(host.property('pictureInPicture'))
        host.bottom.set_fullscreen(fullscreen)
        if not fullscreen:
            host._bar_clock.stop()
            host._bar_animation.stop()
            host._bar_progress = host._bar_target = 0.0
            host.bottom.setVisible(not compact)
        video_height = max(1, height if fullscreen or compact else height - TILE_BAR_HEIGHT)
        # 普通格子留边框，全屏视频贴齐窗口边缘。
        inset = 0 if fullscreen or compact else 1
        host.video.setGeometry(inset, inset, max(1, width - inset * 2),
                               max(1, video_height - inset))
        host._round_video()
        video_right = host.video.geometry().right() + 1
        host.stream_badge.move(10, 8)
        host._layout_controls()
        # 第一行要同时站得下「LIVE 浮标」和「控制条」，控制条永远钉在右上角。
        # 以前是让控制条折到第二行去给浮标腾地方，结果它跑出了右上角、还压在
        # 画面中间的封面文字上（用户报的「竖屏格子右上角按钮错位」）。现在反过来
        # 让浮标让位：先收起人数（浮标变短），实在不够再整个收起来。
        # 浮标的宽度和显隐只由 _sync_stream_badge() 决定 —— 别在这里再写一套
        # 「if overlay: setVisible(...)」，那样 overlay 收起来时它就不受控了
        # （放不下的浮标会一直露着，压住右上角控制条）。
        host._sync_stream_badge()
        # 标题浮标紧跟在 LIVE 右边，剩下的宽度让给控制条那一行
        controls_left = (video_right - 10
                         if host.controls.y() > 20 else host.controls.x())
        title_left = host.stream_badge.x() + host.stream_badge.width() + 6
        room = max(0, controls_left - title_left - 8)
        show_title = bool(host.room.get("uname")) and room >= 110 and host._overlay_visible and not compact
        host.title_badge.setVisible(show_title)
        if show_title:
            host.title_badge.set_max_width(room)
            host.title_badge.move(title_left, 8)
        # 摆位和显隐放在一起：重排（改窗口大小、切布局）之后状态不会走丢
        host.time_badge.setVisible(host._elapsed_visible())
        host.spinner.move(max(0, (host.video.width() - host.spinner.width()) // 2),
                          max(8, (video_height - host.spinner.height()) // 2))
        host.pause_overlay.move(
            max(0, (host.video.width() - host.pause_overlay.width()) // 2),
            max(8, (video_height - host.pause_overlay.height()) // 2))
        bar_y = (height - TILE_BAR_HEIGHT + round(TILE_BAR_HEIGHT * host._bar_progress)
                 if fullscreen else video_height)
        bar_height = TILE_BAR_HEIGHT if fullscreen else max(1, height - video_height - inset)
        host.bottom.set_tile_geometry(inset, bar_y, max(1, width - inset * 2), bar_height)
        host._layout_time_badge()
        host.video_danmaku.setGeometry(host.video.geometry())
        host._layout_bottom_controls()
        host._layout_cover()
        if host._interactive_resize:
            # Resizing existing HWNDs preserves their stacking order. Keep the
            # Quick clip current, then restore the complete order on release.
            host._update_quick_danmaku_mask()
            host._resize_raise_pending = True
        else:
            host.raise_overlays()

    def layout_time_badge(self) -> None:
        host = self.host
        video_right = host.video.geometry().right() + 1
        bottom = min(host.video.geometry().bottom() + 1, host.bottom.tile_y())
        host.time_badge.move(max(10, video_right - host.time_badge.width() - 10),
                             max(8, bottom - host.time_badge.height() - 10))

    def sync_stream_badge(self) -> bool:
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
        host = self.host
        room = host.width() - 10 - host.controls.width() - 12 - 10
        host.stream_badge.set_compact(host.stream_badge.full_width() > room)
        visible = (not host.property('pictureInPicture') and host._overlay_visible and bool(host.room.get("room_id"))
                   and host.stream_badge.width() <= room)
        host.stream_badge.setVisible(visible)
        return visible

    def round_video(self) -> None:
        """视频窗口的圆角遮罩。

        **不要**在这里挖掉控制条那一块：挖了就露出格子底色，按钮周围会出现
        一条长方形黑底（用户报过好几次的老问题，`_update_controls_mask()` 那套
        「只留按钮轮廓」的机制才是治它的）。让控制条能点到靠的是
        `raise_overlays()` 把浮层重新抬到原生视频窗口之上。
        """
        host = self.host
        square_corners = bool(host.property("fullscreen") or host.property('pictureInPicture'))
        host.video.square_corners = square_corners
        host.video_danmaku.set_quick_rounded(not square_corners)
        for index, corner in enumerate(host.video_corners):
            corner.move(host.video.x() if index == 0 else
                        host.video.geometry().right() - corner.width() + 1, host.video.y())
            corner.setVisible(not square_corners)
        key = (host.video.width(), host.video.height(), host.devicePixelRatioF(),
               square_corners, int(host.video.internalWinId()))
        if key == host._video_mask_key and not host.video.mask().isEmpty():
            host._update_quick_danmaku_mask()
            return
        host._video_mask_key = key
        path = QPainterPath()
        rect = QRectF(0, 0, max(1, host.video.width()), max(1, host.video.height()))
        if square_corners:
            path.addRect(rect)
        else:
            path.addPath(continuous_path(rect, 9))
            bottom = QPainterPath()
            bottom.addRect(QRectF(0, max(0, host.video.height() - 9), host.video.width(), 9))
            path = path.united(bottom)
            # Leave one physical pixel under the alpha-blended corner edge.
            stroke = QPainterPathStroker()
            stroke.setWidth(2 / host.devicePixelRatioF())
            bounds = QPainterPath()
            bounds.addRect(rect)
            path = path.united(stroke.createStroke(path)).intersected(bounds)
        host.video.setMask(QRegion(path.toFillPolygon().toPolygon()))
        host.video_danmaku.setMask(host.video.mask())
        for corner in host.video_corners:
            corner.update()
        host._update_quick_danmaku_mask()

    def quality_button_width(self) -> int:
        """按画质文字算按钮宽度。

        用样式表里那号字来量，不能拿 button.fontMetrics()：QSS 的 font-size 不会
        改到控件的 QFont，量出来是默认字号的宽度，几个画质档位会算出同一个数，
        按钮就宽得离谱、文字也没居中。
        """
        host = self.host
        font = QFont(theme.FONT_DEFAULT)
        font.setPixelSize(theme.FONT_CAPTION)
        font.setBold(True)                     # #TileCtrl 是 font-weight: 600
        advance = QFontMetrics(font).horizontalAdvance(host.quality_button.text())
        return max(theme.TILE_CONTROL_HEIGHT, advance + 16)

    def layout_controls(self) -> None:
        """控制条浮在画面右上角，只显示按钮本身。

        按文本量宽后直接摆放三个按钮，让原生窗口遮罩和按钮始终使用同一组坐标。
        原生视频窗口上的 Qt 布局可能在显示或缩放后延迟更新子按钮的位置。
        """
        host = self.host
        # 高度统一由代码给：样式表不再写 min-height，交给布局量出来会矮一截
        host.quality_button.setFixedHeight(theme.TILE_CONTROL_HEIGHT)
        host.quality_button.setFixedWidth(host._quality_button_width())
        host.close_button.setFixedSize(theme.TILE_CONTROL_HEIGHT, theme.TILE_CONTROL_HEIGHT)
        x = 0
        for button in (host.quality_button, host.reload_button, host.close_button):
            button.move(x, 0)
            x += button.width() + 6
        width = x - 6
        host.controls.resize(width, theme.TILE_CONTROL_HEIGHT)
        video_right = host.video.width() + 1
        host.controls.move(max(10, video_right - width - 10), 8)
        host._update_controls_mask()

    def refresh_overlay_masks(self) -> None:
        """所有原生浮层都要重新换算遮罩，文字不变时 Qt 不会自动更新它。"""
        host = self.host
        host._video_mask_key = host._controls_mask_key = host._cover_key = None
        for widget in (host.video, host.video_danmaku, host.controls, host.stream_badge,
                       host.title_badge, host.time_badge):
            mask = widget.mask()
            widget.clearMask()
            if not mask.isEmpty():
                widget.setMask(mask)
        host._layout_areas()

    def update_controls_mask(self) -> None:
        """裁掉原生控制窗口的矩形底，只留下三个圆角按钮的轮廓。"""
        host = self.host
        scale = host.controls.devicePixelRatioF()
        key = (tuple(button.geometry().getRect() for button in
                     (host.quality_button, host.reload_button, host.close_button)), scale,
               int(host.controls.internalWinId()))
        if key == host._controls_mask_key and not host.controls.mask().isEmpty():
            return
        host._controls_mask_key = key
        if getattr(host, "_controls_mask_scale", None) != scale:
            # 跨屏后逻辑轮廓相同，Qt 会跳过 setMask，留下按旧 DPI 换算的原生区域。
            host.controls.clearMask()
        host._controls_mask_scale = scale
        region = QRegion()
        for button in (host.quality_button, host.reload_button, host.close_button):
            rect = QRectF(button.geometry())
            path = QPainterPath()
            radius = min(rect.height() / 2, theme.TILE_CONTROL_HEIGHT / 2)
            # 原生底色只能按整数区域裁切；扩张轮廓会露出圆角外的黑色底层。
            path.addPath(continuous_path(rect, radius))
            region = region.united(QRegion(path.toFillPolygon().toPolygon()))
        if (sys.platform == "win32" and QApplication.platformName() == "windows"
                and host.controls.internalWinId()):
            # Let Qt paint the complete antialiased edge; clip the native backing
            # at physical-pixel resolution instead of scaling a logical region.
            paint_region = QRegion()
            for button in (host.quality_button, host.reload_button, host.close_button):
                paint_region = paint_region.united(QRegion(button.geometry()))
            host.controls.setMask(paint_region)
            if host._apply_native_controls_mask(scale):
                return
        host.controls.setMask(region)

    def apply_native_controls_mask(self, scale: float) -> bool:
        host = self.host
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
            for button in (host.quality_button, host.reload_button, host.close_button):
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
            if user32.SetWindowRgn(int(host.controls.winId()), region, True):
                region = None          # Windows owns the successfully assigned region.
                return True
            return False
        finally:
            if region:
                gdi32.DeleteObject(region)

    def set_focused(self, focused: bool) -> None:
        host = self.host
        host.setProperty("focused", focused)
        _repolish(host)
