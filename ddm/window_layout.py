"""Window orientation and layout coordination; geometry and session state belong to the host."""
import sys

from PySide6.QtWidgets import QApplication, QBoxLayout

from . import layouts


class WindowLayout:
    def __init__(self, host):
        self.host = host

    def build_arrangement(self, orientation: str) -> None:
        """按方向重新摆放侧栏和画面墙。

        横屏：侧栏在左（固定宽）+ 右侧画面墙。
        竖屏：侧栏变成顶部横栏（撑满宽）+ 下面画面墙。
        """
        host = self.host
        layout = host._root_layout
        # 只改变同一个根布局的排列方向。侧栏和画面墙始终挂在 root 下，
        # 播放器 正在使用的原生视频 HWND 就不会因换父窗口而被 Qt 销毁。
        layout.setDirection(
            QBoxLayout.TopToBottom if orientation == "portrait"
            else QBoxLayout.LeftToRight
        )
        if layout.indexOf(host.sidebar) < 0:
            layout.addWidget(host.sidebar)
        if layout.indexOf(host._content) < 0:
            layout.addWidget(host._content, 1)
        layout.setStretch(layout.indexOf(host.sidebar), 0)
        layout.setStretch(layout.indexOf(host._content), 1)
        if orientation == "landscape":
            host.sidebar.setMaximumHeight(16_777_215)
        host.sidebar.set_side("top" if orientation == "portrait" else "left")
        # 换完排布再同步一次可见性：收起/展开只影响「露哪些控件」，
        # 而 set_collapsed 在换排布之前就设过了，不补这一下头像排不会露出来。
        host.sidebar._sync_top_mode()      # noqa: SLF001

    def saved_layout(self, orientation: str) -> str:
        host = self.host
        ui = host.state.get("ui") or {}
        saved = str(ui.get(f"layout_{orientation}") or "")
        if not saved:
            # 配置里还没有这一项 = 第一次启动（或从很老的配置升上来）：
            # 用第一次启动的默认布局，别退成兜底的九分
            return (layouts.FIRST_LAYOUT if orientation == "landscape"
                    else layouts.PORTRAIT_AUTO)
        # 老配置里的 "auto"（以及任何已经删掉的布局 id）折算成兜底布局：
        # 「自动」已经按用户要求从菜单里去掉了
        if saved not in layouts.BY_ID:
            return layouts.DEFAULT_LAYOUT
        return saved

    def apply_orientation(self, orientation: str | None = None) -> None:
        """按窗口方向换排布（顶部横栏 / 左侧栏）和布局预设。"""
        host = self.host
        if host._applying_room_preset or (getattr(host, 'picture_in_picture', None)
                                         and host.picture_in_picture.active):
            return
        # Side/header reparenting activates ancestor layouts synchronously.
        # Commit their final arrangement once; DPI and painting remain enabled.
        layout_enabled = host._root_layout.isEnabled()
        host._root_layout.setEnabled(False)
        try:
            orientation = orientation or ("portrait" if host.is_portrait() else "landscape")
            # 启动后第一次定方向？**要在下面写 host.orientation 之前取**，
            # 否则 first 永远是 False，第一次也会走「对映」那条路。
            first = not host.orientation
            changed = orientation != host.orientation
            if changed:
                host.hover_preview.cancel()
                host._build_arrangement(orientation)
            # 切走之前正在用的那套，记在**原来那个方向**名下：用户转个方向逛一圈再转回来，
            # 原来那边的布局得原样还在，不能靠「按容量折算」猜回来。
            if host.orientation and changed:
                host._layout_by_orientation[host.orientation] = host.wall.layout_id
            host.orientation = orientation
            portrait = orientation == "portrait"

            # 竖屏不再强制「收起」：顶部横栏本来就只占一条，横屏的收起语义（60px 窄条）
            # 混进来会在拖回横屏时留下一堆隐藏控件。竖屏保持展开（头像排 + 按钮行）。
            host.sidebar.set_collapsed(False, animate=False)

            saved = host._saved_layout(orientation)
            # 调用方显式指定的布局：只认和当前方向匹配的那次，认完就清掉
            pending = getattr(host, "_pending_layout", "")
            if pending and host._layout_fits(pending, portrait):
                layout_id = pending
                host._pending_layout = ""
            elif first:
                # 启动：配置里存过哪套就用哪套（第一次启动就是 FIRST_LAYOUT /
                # PORTRAIT_AUTO）；只有存的那套跟当前方向不匹配（老配置、
                # 或者上次是在另一个方向下用的）才按「对映」折算一套出来。
                layout_id = saved if host._layout_fits(saved, portrait) else (
                    layouts.counterpart(host.wall.layout_id, portrait)
                    or (layouts.PORTRAIT_AUTO if portrait else layouts.FIRST_LAYOUT))
            else:
                # 回自己待过的方向：先把「切走之前在用的那套」摆回来。横屏的
                # 「主画面 + 5 小环绕」和「六分」都是 6 路，只按容量折算的话，从竖屏
                # 切回来会被换成六分 —— 用户报的「布局被改了」就是这个。
                remembered = host._layout_by_orientation.get(orientation, "")
                if remembered and host._layout_fits(remembered, portrait):
                    layout_id = remembered
                else:
                    # 本次会话第一次进这个方向：跟着当前这套找最相似的那套
                    # （横屏 1+2 ↔ 竖屏 1+2，弹幕对弹幕），不能退成「自动」。
                    # 这一步要压过配置里存的那个值 —— 用户报的正是这个：
                    # 横屏 1+2 拖成竖屏，结果用了以前在竖屏存过的「1+2+弹幕」。
                    mapped = layouts.counterpart(host.wall.layout_id, portrait)
                    if mapped:
                        layout_id = mapped
                    elif host._layout_fits(saved, portrait):
                        layout_id = saved
                    else:
                        layout_id = layouts.PORTRAIT_AUTO if portrait else layouts.DEFAULT_LAYOUT
            if layout_id != host.wall.layout_id:
                if not first:
                    host._clear_expanded_slots(layout_id)
                host.wall.set_layout(layout_id, relayout=False)
                host.sidebar.set_layout_name(layout_id)
            # 换了排布/换了布局，画面墙的尺寸和格子可见性都要重算一次
            if host._settling_resize:
                host.wall.set_interactive_resize(True)
        finally:
            host._root_layout.setEnabled(layout_enabled)
            if layout_enabled:
                host._root_layout.invalidate()
        host._root_layout.activate()
        host._content.layout().activate()
        host.wall.relayout(force=True)
        host._sync_tile_playback()
        print(f"[方向] {'竖屏' if portrait else '横屏'}　布局={layout_id}",
              file=sys.stderr, flush=True)

    def clear_expanded_slots(self, layout_id: str) -> None:
        host = self.host
        current = host.wall._capacity() or len(host.wall.tiles)
        target = (layouts.capacity(layout_id)
                  - int(layouts.danmaku_cell(layout_id) is not None and
                        layout_id not in host.wall.pane_danmaku.settings)) or len(host.wall.tiles)
        if target <= current:
            return
        # 扩大布局只补空位，先前隐藏的房间不能自动回到画面墙。
        for tile in host.wall.tiles[current:]:
            if tile.room.get("room_id"):
                host._clear_tile_room(tile)

    def prioritize_live_tiles(self, layout_id: str) -> None:
        """缩小布局时，用后面的开播格子填前面的未开播位置。"""
        host = self.host
        capacity = layouts.capacity(layout_id) - int(layouts.danmaku_cell(layout_id) is not None and
                        layout_id not in host.wall.pane_danmaku.settings)
        tiles = host.wall.tiles
        if (capacity <= 0 or capacity >= len(tiles)
                or capacity >= (host.wall._capacity() or len(tiles))):
            return
        live = lambda tile: bool(tile.room.get("room_id") and tile.room.get("live"))
        vacant = [index for index in range(capacity) if not live(tiles[index])]
        waiting = [index for index in range(capacity, len(tiles)) if live(tiles[index])]
        for visible_index, hidden_index in zip(vacant, waiting):
            visible, hidden = tiles[visible_index], tiles[hidden_index]
            tiles[visible_index], tiles[hidden_index] = hidden, visible
            # 音量、静音和声道属于位置；画面随格子移动，声音设置留在原位置。
            visible.volume, hidden.volume = hidden.volume, visible.volume
            visible.muted, hidden.muted = hidden.muted, visible.muted
            visible.audio_channel, hidden.audio_channel = hidden.audio_channel, visible.audio_channel
            for tile in (visible, hidden):
                tile.room["volume"] = tile.volume
                tile.room["muted"] = tile.muted
                tile.room["audio_channel"] = tile.audio_channel
                tile.sync_audio_ui()
                player = host.players.get(tile)
                if player is not None:
                    player.set_volume(int(tile.volume))
                    player.set_muted(tile.muted)
                    player.set_audio_channel(int(tile.audio_channel))
                    player.reapply_audio_channel()

    def on_layout_changed(self, layout_id: str) -> None:
        host = self.host
        host.picture_in_picture.restore()
        host._cancel_interactive_resize()
        panes_reset = host.wall.pane_danmaku.reset_preset(layout_id)
        want_portrait = layouts.is_portrait_layout(layout_id)
        reshape = (want_portrait != (host.orientation == "portrait")
                   or want_portrait != (host._resize_orientation() == "portrait"))
        if layout_id == host.wall.layout_id and not reshape:
            host.wall.reset_layout_ratios()
            if panes_reset:
                host.wall.relayout(force=True)
                host.apply_quality_policy()
                host._sync_tile_playback(start_visible=True)
                host._refresh_meta()
                host._save_timer.start()
            return
        host._prioritize_live_tiles(layout_id)
        host._clear_expanded_slots(layout_id)
        # 换画面墙摆放方式；**选了另一个方向的布局就把窗口也改成那个形状** ——
        # 用户要的是「切成竖屏后，alt+tab 里的窗口预览也是竖的」，
        # 而不是把一个竖屏排布塞在横屏窗口里（那样 alt+tab 就是一张拉伸的横屏）。
        if reshape:
            print(f"[布局] {layout_id} 是给{'竖屏' if want_portrait else '横屏'}的，"
                  f"把窗口也改成{'竖屏' if want_portrait else '横屏'}的",
                  file=sys.stderr, flush=True)
            # 转窗口会同步触发 _apply_orientation，而那里会把「切走前的记忆」摆回来，
            # 把用户刚选的这套顶掉 —— 先挂成 pending，让它认这个选择
            host._pending_layout = layout_id
            previous_orientation, previous_layout = host.orientation, host.wall.layout_id
            # resize 时必须按目标预设计算最小尺寸，避免旧的密集网格挡住转方向。
            host.wall.set_layout(layout_id, relayout=False)
            host._reshape_window(want_portrait)
            host._resize_idle_timer.stop()
            host._resize_dirty = False
            host._apply_orientation("portrait" if want_portrait else "landscape")
            if previous_orientation:
                host._layout_by_orientation[previous_orientation] = previous_layout
        host.wall.set_layout(layout_id)
        host.wall.relayout(force=True)
        host.sidebar.set_layout_name(host.wall.layout_id)
        # 记在**当前方向**名下：横屏选的布局不该被竖屏覆盖，反之亦然
        key = f"layout_{host.orientation or 'landscape'}"
        host.state.setdefault("ui", {})[key] = layout_id
        host.apply_quality_policy()
        host._sync_tile_playback(start_visible=True)
        host._refresh_meta()

    def reshape_window(self, portrait: bool) -> None:
        """把主窗口改成竖屏/横屏的形状（宽高对调，并夹在当前屏幕里）。

        窗口尺寸系统（Alt+Tab / 任务栏预览）拿的是**窗口本身**的形状：竖屏排布
        塞在横屏窗口里，预览就是一张拉伸的横屏。所以选另一个方向的布局时顺手把
        窗口也摆成那个方向；最大化状态下先还原，否则改不动尺寸。
        """
        host = self.host
        if host.isMaximized():
            host.showNormal()
        screen = host.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        width, height = max(host.width(), 480), max(host.height(), 360)
        if portrait:
            new_height = max(height, width)                 # 高的那一维当高度
            if area is not None:
                new_height = min(new_height, area.height())  # 先夹进屏幕
            new_width = max(360, int(new_height * 9 / 16))   # 再按 9:16 算宽度
            if area is not None:
                new_width = min(new_width, area.width())
        else:
            new_width = max(width, height)                  # 宽的那一维当宽度
            if area is not None:
                new_width = min(new_width, area.width())
            new_height = max(360, int(new_width * 9 / 16))
            if area is not None:
                new_height = min(new_height, area.height())
        # 别让窗口跑到屏幕外：贴进可用区域
        left, top = host.x(), host.y()
        if area is not None:
            left = min(max(left, area.left()), max(area.left(), area.right() - new_width))
            top = min(max(top, area.top()), max(area.top(), area.bottom() - new_height))
            host.move(left, top)
        # 拖动布局有自己的最小尺寸；转方向前先解除旧预设的约束，
        # 否则横屏最小宽度会挡住变窄，resizeEvent 无法进入竖屏排布。
        host.wall.setMinimumSize(0, 0)
        host._build_arrangement("portrait" if portrait else "landscape")
        host._content.layout().invalidate()
        host._content.layout().activate()
        host._root_layout.invalidate()
        host._root_layout.activate()
        host.resize(new_width, new_height)
        print(f"[窗口] 改成 {'竖屏' if portrait else '横屏'} {new_width}x{new_height}",
              file=sys.stderr, flush=True)
