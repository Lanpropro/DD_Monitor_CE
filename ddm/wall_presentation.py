"""Fullscreen, picture-in-picture and native wall presentation modes; WallGrid retains Qt ownership."""
import sys
from PySide6.QtCore import QRect, QSize, QTimer, Qt, Signal
from .tile_widgets import Tile
from .widget_support import TILE_BAR_HEIGHT, _repolish


class WallPresentation:
    def __init__(self, host):
        self.host = host

    def ensure_quick_danmaku_layer(self):
        host = self.host
        if host._quick_danmaku_layer is not None or not host._quick_danmaku_requested:
            return host._quick_danmaku_layer
        if host._quick_danmaku_attempted:
            return None
        host._quick_danmaku_attempted = True
        try:
            from .video_danmaku_quick import QuickDanmakuLayer
            host._quick_danmaku_layer = QuickDanmakuLayer(host)
            for tile in host.tiles:
                tile.video_danmaku.attach_quick_layer(host._quick_danmaku_layer)
            if host.fullscreen_tile is not None and host.fullscreen_tile.isWindow():
                host._quick_danmaku_layer.set_presentation_window(host.fullscreen_tile)
                tile._update_quick_danmaku_mask()
            if host.isVisible():
                host._quick_danmaku_layer.show()
            motion = ("XAnimator" if host._quick_danmaku_layer.render_thread_animation
                      else "Python timer")
            print(f"[弹幕] Qt Quick共享层，位置更新：{motion}", file=sys.stderr)
        except Exception as exc:
            host._quick_danmaku_layer = None
            print(f"[弹幕] Qt Quick原型初始化失败，回退到QPainter：{exc}", file=sys.stderr)
        return host._quick_danmaku_layer

    def set_picture_in_picture(self, tiles, columns=0, aspects=None, primary=0):
        host = self.host
        host.set_interactive_resize(False)
        host._clear()
        host._resize_on_show = False
        host._relayout_timer.stop()
        host.picture_in_picture_tiles = list(tiles) if tiles is not None else None
        host.picture_in_picture_columns = columns
        host.picture_in_picture_primary = primary
        host.picture_in_picture_aspects = aspects or []
        selected = set(tiles or [])
        for tile in host.tiles:
            tile.setProperty('pictureInPicture', tile in selected)
            _repolish(tile)
            if tile in selected:
                tile.set_controls_visible(False)
            if tiles is not None:
                tile.setMinimumSize(0, 0)
        host._sync_danmaku_controls()
        host.relayout(force=True)
        for tile in host.tiles:
            tile._layout_areas()

    def relayout_picture_in_picture(self):
        host = self.host
        from .picture_in_picture import pane_rectangles
        host.setMinimumSize(0, 0)
        for panel in host.pane_danmaku.all_panels():
            panel.hide()
        host._divider_rects = {}
        for border in host._pane_borders.values():
            border.hide()
        selected = host.picture_in_picture_tiles
        for tile in host.tiles:
            tile.setVisible(tile in selected)
        window = host._quick_danmaku_layer.window if host._quick_danmaku_layer is not None else None
        if window is not None:
            window.begin_mask_batch()
        try:
            for tile, rect in zip(selected, pane_rectangles(
                    len(selected), host.rect(), host.picture_in_picture_columns,
                    host.picture_in_picture_aspects, host.picture_in_picture_primary)):
                tile.setGeometry(rect)
        finally:
            if window is not None:
                window.end_mask_batch()

    def set_fullscreen_tile(self, tile: Tile | None, *, stagger: bool = False,
                            first: Tile | None = None) -> None:
        """临时只显示一个格子，保持原布局和格子顺序。

        ``stagger=True``（退出全屏时用）只把布局算好，**不立刻显示**其余格子，
        它们交给 :meth:`reveal_tiles_staggered` 分批露面；``first`` 指定的那个
        格子仍然马上显示（用户刚从那格退出来，视线在它身上）。

        为什么要拆：一次把 9 个格子的 VLC 原生窗口全重配，4K 上实测约 190 ms，
        期间主线程完全僵住 —— 盖在上面的过渡图也就跟着"冻"在原地，看起来就是
        卡住再突然一跳。拆成几帧之后，帧与帧之间事件循环能跑，过渡图才淡得动。
        """
        host = self.host
        host.set_interactive_resize(False)
        host._resize_on_show = False
        host._cancel_border_drag()
        host._relayout_timer.stop()
        host._defer_show = bool(stagger)
        host._pending_reveal = []
        host._stagger_first = first
        previous = host.fullscreen_tile
        if previous is not tile and host._quick_danmaku_layer is not None:
            host._quick_danmaku_layer.reset_surface()
        host.fullscreen_tile = tile
        if previous is not None and previous is not tile:
            previous.setProperty("fullscreen", False)
            _repolish(previous)
            if not host._fullscreen_layout_pending:
                previous._layout_areas()
        if tile is not None:
            tile.setProperty("fullscreen", True)
            _repolish(tile)
            if not host._fullscreen_layout_pending:
                tile._layout_areas()
        margin = 0 if tile else 16
        host.grid.setContentsMargins(margin, margin, margin, margin)
        if not host._fullscreen_layout_pending:
            host.relayout(force=True)

    def reveal_tiles_staggered(self, chunk: int = 2) -> None:
        """把「布局算好了但还没露面」的格子分批显示，每批一帧。

        每批只放两格：4K 下单格 VLC 原生窗口重配约 23 ms（实测 9 格一起做是
        190 ms 上下），一批两格就是约 46 ms —— 差不多三帧，是可感知的上限；
        再大就又开始"僵住"。

        批次之间用 `singleShot(0)` 让出事件循环：一来下一批要等这一批的窗口
        重配落地，二来让遮盖图的淡出动画有机会推进（连着做完主线程一样是僵的，
        那就白拆了）。代价是"分批期间格子还没全部可见"，所以调用方如果要立刻
        读可见性，得先让事件循环跑完。
        """
        host = self.host
        if not host._pending_reveal:
            host._defer_show = False
            return
        batch, rest = host._pending_reveal[:chunk], host._pending_reveal[chunk:]
        host._pending_reveal = rest
        for tile in batch:
            tile.setVisible(True)
        if rest:
            QTimer.singleShot(0, lambda: host.reveal_tiles_staggered(chunk))
        else:
            host._defer_show = False

    def set_sidebar_animating(self, active: bool) -> None:
        """收缩期间保持原生视频窗口尺寸，结束后统一调整。"""
        host = self.host
        if host.picture_in_picture_tiles is not None:
            return
        if active == host._sidebar_animating:
            return
        host._sidebar_animating = active
        if active:
            host._sidebar_layout = (host.layout_id, tuple(host.tiles),
                                    host.fullscreen_tile, host._danmaku_cell)
            host._sidebar_updates_enabled = host.updatesEnabled()
            host.setUpdatesEnabled(False)
        host._resize_timer.stop()
        host._resize_pending = False
        host._relayout_timer.stop()
        host.grid.setEnabled(not active)
        if not active:
            try:
                layout_state = (host.layout_id, tuple(host.tiles),
                                host.fullscreen_tile, host._danmaku_cell)
                if (layout_state == host._sidebar_layout and host.fullscreen_tile is None
                        and (host.layout_id == 'corner' or host.layout_id in host._partitions)):
                    # Width-only settlement keeps pane visibility and native stacking intact.
                    host._resize_pending = True
                    host._flush_resize()
                    QTimer.singleShot(0, host._sync_danmaku_controls)
                else:
                    host.relayout(force=True)
                host.grid.activate()
                if host._quick_danmaku_layer is not None:
                    host._quick_danmaku_layer.resize()
            finally:
                host._sidebar_layout = None
                host.setUpdatesEnabled(host._sidebar_updates_enabled)
