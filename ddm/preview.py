"""悬停预览：鼠标在关注列表的已开播直播间上停 0.5 秒，缩略图里直接放静音画面。

画面就播在该条目的缩略图（NavThumb）里，不再另开小窗；鼠标移开立刻收掉并释放播放器，
不会一直占带宽和 CPU。
"""
import sys

from PySide6.QtCore import QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFrame

from .bili import StreamResolver
from .player import TilePlayer
from .widgets import CAROUSEL_WIDTH, NavThumb

PREVIEW_QUALITY = 80        # 流畅：缩略图那么大，看得清就够了

#: 浮层预览的高度 = 展开卡片里那块封面的高度（116）。
#: 紧凑（长条）卡片的缩略图只有 `NavThumb.LIST_HEIGHT`(48) 高，预览塞进去会被压扁，
#: 所以在卡片旁边弹一个和**非紧凑卡片**上一样大的浮层（见 `_needs_popup`）。
PREVIEW_HEIGHT = NavThumb.HEIGHT
#: 竖屏时向下弹出，跟卡片底边留一点缝
PREVIEW_GAP = 6

PREVIEW_MEDIA_OPTIONS = ("audio=no", "hwdec=no")


class HoverPreview(QObject):
    """管悬停计时，并把预览发到对应条目的缩略图上。"""

    DELAY_MS = 500          # 停够 0.5 秒才播
    RESOLVE_DELAY_MS = 250  # 提前取流，快速划过时仍不发请求
    GRACE_MS = 120          # 移开后的宽限（手抖一下不立刻收）

    def __init__(self, sidebar, parent=None, *, platform_resolver=None):
        super().__init__(parent)
        self.sidebar = sidebar
        self._platform_resolver = platform_resolver
        self.enabled = True
        self._room: dict = {}
        self._item = None                       # 正在预览的条目
        self._resolver: StreamResolver | None = None
        self._resolvers_running = set()          # 包括已取消但还在请求中的线程
        self._generation = 0                    # 取流编号：旧编号的结果一律丢掉
        self._ready_to_show = False
        self._pending_result = None
        self._pending_failure = None
        # 共用一个浮层预览。父控件挂**主窗口**（不是滚动视口）：视口会把自己裁掉，
        # 而横屏要往卡片右侧弹、竖屏要向下弹，都会越出视口范围。
        self._popup = QFrame(sidebar.window())
        self._popup.setObjectName("NavPreviewPopup")
        self._popup.setAttribute(Qt.WA_StyledBackground, True)
        self._popup.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._popup_video = QFrame(self._popup)
        self._popup_video.setObjectName("NavPreviewPopupVideo")
        self._popup_video.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._size_popup(CAROUSEL_WIDTH)
        self._popup.hide()
        self._popup_player: TilePlayer | None = None
        self._popup_playing = False
        sidebar.scroll.horizontalScrollBar().valueChanged.connect(self._update_popup_position)
        # 横屏的列表是竖着滚的，不接上这一条，滚动时预览会停在原地
        sidebar.scroll.verticalScrollBar().valueChanged.connect(self._update_popup_position)
        sidebar._head_scroll.horizontalScrollBar().valueChanged.connect(  # noqa: SLF001
            self._update_popup_position)
        sidebar.collapsedChanged.connect(self.cancel)
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.setInterval(self.DELAY_MS)
        self._delay.timeout.connect(self._show_now)
        self._resolve_delay = QTimer(self)
        self._resolve_delay.setSingleShot(True)
        self._resolve_delay.setInterval(self.RESOLVE_DELAY_MS)
        self._resolve_delay.timeout.connect(self._begin_resolve)
        self._grace = QTimer(self)
        self._grace.setSingleShot(True)
        self._grace.setInterval(self.GRACE_MS)
        self._grace.timeout.connect(self._stop_now)
        self._hover_watch = QTimer(self)
        self._hover_watch.setInterval(50)
        self._hover_watch.timeout.connect(self._check_hover)

    # ---- 悬停事件 ----
    def on_hover(self, room: dict) -> None:
        if not self.enabled or self.sidebar.select_mode:
            return
        if not room.get("live"):
            return                              # 没开播就没什么可看的
        self._grace.stop()
        if self._item is not None:
            if str(room.get("room_id")) == self._room_id():
                return                          # 原生视频窗口引起重复进入时继续播放，不重新取流
            self._stop_now()                    # 换到别人身上了：旧预览立刻收掉
        self._room = room
        self._hover_watch.start()
        self._delay.start()
        self._resolve_delay.start()

    def on_unhover(self, room: dict) -> None:
        if str(room.get("room_id") or "") != self._room_id():
            return                              # 已经换到别的条目上了
        self._delay.stop()
        self._resolve_delay.stop()
        if self._item is not None:
            if self._ready_to_show:
                self._grace.start()             # 手抖一下不立刻收
            else:
                self._stop_now()

    # ---- 起播 / 收掉 ----
    def _show_now(self) -> None:
        item = self._item or self._item_of(self._room)
        if item is None or not self._cursor_on_item(item):
            self.cancel()
            return
        self._ready_to_show = True
        item = self._item
        if item is not None:
            try:
                item.thumb.set_hint("连接中…")
            except RuntimeError:
                self._stop_now()
                return
        if self._pending_result is not None:
            result = self._pending_result
            self._pending_result = None
            self._on_resolved(*result[:-1], headers=result[-1])
        elif self._pending_failure is not None:
            failure = self._pending_failure
            self._pending_failure = None
            self._on_failed(*failure)

    def _begin_resolve(self) -> None:
        room = self._room
        if (not self.enabled or self.sidebar.select_mode or
                not room.get("room_id") or not room.get("live")):
            return
        room_id = str(room["room_id"])
        platform = self._platform_resolver(room_id) if self._platform_resolver else None
        if not room_id.isdigit() and (platform is None or platform.playback_mode != "stream"):
            return                              # 网页插件或未启用的平台没有可预览的直播流
        item = self._item_of(room)
        if item is None:
            return
        if not self._cursor_on_item(item):
            self.cancel()
            return
        self._stop_now()                        # 顺带把编号推进一格
        self._item = item
        self._hover_watch.start()
        print(f"[预览] {room.get('uname')} → 缩略图", file=sys.stderr, flush=True)
        generation = self._generation
        kwargs = {"platform": platform, "preview": True} if platform is not None else {}
        resolver = StreamResolver(room_id, PREVIEW_QUALITY, self, **kwargs)
        # 回调都带上编号：编号过期就说明这次取流早就作废了（鼠标移开、换了条目）
        resolver.resolved.connect(
            lambda room_id, url, quality, profile, options, gen=generation, r=resolver:
            self._on_resolved(gen, room_id, url, quality, profile, options,
                              headers=dict(getattr(r, "headers", {}))))
        resolver.failed.connect(
            lambda room_id, reason, gen=generation: self._on_failed(gen, room_id, reason))
        resolver.finished.connect(lambda r=resolver: self._on_finished(r))
        resolver.finished.connect(resolver.deleteLater)
        self._resolver = resolver
        self._resolvers_running.add(resolver)
        resolver.start()
        # 取流在线程中进行；同时创建 mpv 核心，避免 URL 返回后才初始化播放器。
        try:
            if self._needs_popup():
                if self._popup_player is None:
                    self._popup_player = TilePlayer(self._popup_video, self, silent=True)
                    self._popup_player.freeze_watch = False
                self._popup_player.bind()
            else:
                item.thumb.prepare_preview()
        except RuntimeError:
            self._stop_now()

    def _on_resolved(self, generation: int, room_id: str, url: str, quality: int,
                     profile: str, options: list | None, *, headers=None) -> None:
        if generation != self._generation:
            return                              # 这次取流已经作废
        if not self._ready_to_show:
            self._pending_result = (generation, room_id, url, quality, profile,
                                    options, headers)
            return
        item = self._item
        if item is None or str(item.room.get("room_id")) != str(room_id):
            return
        if self._item_of(item.room) is not item:
            self._stop_now()
            return
        if not self._cursor_on_item(item):
            self.cancel()
            return
        try:
            anchor = self._anchor_of(item)
            if anchor is None or not anchor.isVisible():
                self._stop_now()
                return
            if self._needs_popup():
                item.thumb.set_hint("")
                self._place_popup(item)
                if self._popup_player is None:
                    self._popup_player = TilePlayer(self._popup_video, self, silent=True)
                    self._popup_player.freeze_watch = False
                self._popup_player.set_muted(True)
                self._popup_player.set_volume(0)
                self._popup.show()
                # 画面墙的格子是**原生子窗口**，会盖住普通子控件。预览要压在它们
                # 上面，自己也得是原生窗口；而且必须在 show() 之后再设，否则 Qt
                # 会抱怨「不是顶层窗口」。
                if not self._popup.testAttribute(Qt.WA_NativeWindow):
                    self._popup.setAttribute(Qt.WA_NativeWindow, True)
                self._popup.raise_()
                self._popup_playing = True
                self._popup_player.play(url, profile, headers=headers, options=PREVIEW_MEDIA_OPTIONS)
            else:
                item.thumb.play(url, profile, headers=headers, options=PREVIEW_MEDIA_OPTIONS)
        except RuntimeError:
            self._stop_now()

    def _needs_popup(self) -> bool:
        """什么时候用浮层预览，而不是直接播在卡片的缩略图里。

        非紧凑卡片上那块封面是**铺满条目**的（约 206x116），画面直接播在里面最
        自然；紧凑（长条）卡片的缩略图只有 `NavThumb.LIST_HEIGHT`(48) 高，塞进去
        画面会被压扁 —— 用户报的「紧凑布局下预览有问题」就是这个。收起后只剩头像，
        也要用浮层；竖屏展开的大卡片则直接在封面内播放。
        """
        return self.sidebar.collapsed or not self.sidebar.card_mode

    def _anchor_of(self, item):
        if self.sidebar.side == "top" and self.sidebar.collapsed:
            return self.sidebar._head_strip._avatars.get(  # noqa: SLF001
                str(item.room.get("room_id") or ""))
        return item

    def _size_popup(self, width: int) -> None:
        """把浮层设成和「非紧凑卡片上那块封面」一样大，视频区留 2px 边框。"""
        width = max(80, int(width))
        self._popup.setFixedSize(width, PREVIEW_HEIGHT)
        self._popup_video.setGeometry(
            2, 2, max(1, width - 4), max(1, PREVIEW_HEIGHT - 4))

    def _place_popup(self, item) -> None:
        """摆浮层：横屏压在卡片右侧 1/3 并垂直居中；竖屏改成向下弹。

        横屏的 x 沿用最早那版（``db226b2``）的算法：从卡片右边缘往回退**侧栏宽度的
        1/3**，于是浮层左边界正好压在卡片右边 1/3 的位置，其余部分探到侧栏外面 ——
        和用户在非紧凑布局里看惯的位置一致。
        """
        parent = self._popup.parentWidget()
        if parent is None:
            return
        # 横竖屏用**同一个尺寸**（用户要求两边对齐）：取展开卡片那个量级 ——
        # CAROUSEL_WIDTH(206) x NavThumb.HEIGHT(116)，正好 16:9。
        self._size_popup(CAROUSEL_WIDTH)
        anchor = self._anchor_of(item)
        if anchor is None:
            return
        origin = anchor.mapTo(parent, QPoint(0, 0))
        if self.sidebar.side == "top":
            # 竖屏：卡片是横排的、右边没空间，改成**向下弹**；左右跟卡片的竖直
            # 中线对齐（用户要求：放到和卡片中心对齐的位置，而不是贴着左边缘）
            x = origin.x() + (anchor.width() - self._popup.width()) // 2
            y = origin.y() + anchor.height() + PREVIEW_GAP
        else:
            # 左边界落在**卡片右侧 1/3** 处，其余部分探到侧栏外面
            # （最早那版是按「侧栏宽的 1/3」回退，两者差 7px 左右；按卡片算更贴合
            #   「占据卡片右侧 1/3」这个说法）
            x = origin.x() + anchor.width() * 2 // 3
            y = origin.y() + (anchor.height() - self._popup.height()) // 2
        x = max(0, min(x, parent.width() - self._popup.width()))
        y = max(0, min(y, parent.height() - self._popup.height()))
        self._popup.move(x, y)

    def _cursor_on_item(self, item) -> bool:
        """指针现在是不是还落在这个条目上。

        滚动之后就不一定了：鼠标没动、只是滚轮把卡片滚走了，指针底下已经换成
        别的卡片（或者成了空白）。
        """
        try:
            anchor = self._anchor_of(item)
            viewport = (self.sidebar._head_scroll.viewport()
                        if self.sidebar.side == "top" and self.sidebar.collapsed
                        else self.sidebar.scroll.viewport())
            pointer = QCursor.pos()
            return (anchor is not None and anchor.isVisible()
                    and viewport.isVisible()
                    and viewport.rect().contains(viewport.mapFromGlobal(pointer))
                    and anchor.rect().contains(anchor.mapFromGlobal(pointer)))
        except RuntimeError:                    # 条目已经被删掉
            return False

    def _check_hover(self) -> None:
        # Native video children may swallow Leave. Verify pending and playing previews.
        if self._item is None and not self._hover_watch.isActive():
            return
        item = self._item or self._item_of(self._room)
        if item is not None and self._cursor_on_item(item):
            self._grace.stop()
            item._set_hovered(True)
            return
        if item is not None:
            item._set_hovered(False)
        if self._ready_to_show:
            if not self._grace.isActive():
                self._grace.start()
        else:
            self.cancel()

    def _update_popup_position(self) -> None:
        """列表滚动时浮层跟着挪；卡片被滚出指针底下就收掉。

        用户报的：预览开着、指针不动，只用滚轮把卡片滚走，浮层还留着，而且被夹到
        软件上下边缘贴着 —— 因为 `_place_popup()` 末尾那句 clamp 会把已经跑到视口
        外的条目硬夹回边界。指针底下已经不是这张卡片了，这里该收掉。
        """
        self._check_hover()
        item = self._item
        if item is None or not self._popup.isVisible():
            return
        if not self._cursor_on_item(item):
            self.cancel()
            return
        self._place_popup(item)

    def _on_failed(self, generation: int, room_id: str, reason: str) -> None:
        if generation != self._generation:
            return
        if not self._ready_to_show:
            self._pending_failure = (generation, room_id, reason)
            return
        print(f"[预览取流失败] {room_id}: {reason}", file=sys.stderr, flush=True)
        item = self._item
        if item is not None:
            try:
                item.thumb.set_hint("取流失败")
            except RuntimeError:
                self._item = None

    def _on_finished(self, resolver) -> None:
        self._resolvers_running.discard(resolver)
        if self._resolver is resolver:           # 迟到的旧线程别把新线程顶掉
            self._resolver = None

    def _stop_now(self) -> None:
        """让缩略图回到封面，并让正在跑的取流作废。

        注意这里**不杀线程**：只 cancel()，线程自己跑完最后一步就结束。强杀
        （QThread.terminate）会带走线程本地存储和锁，主线程之后可能整个卡死。
        """
        self._generation += 1                   # 之前那次的结果从此一律作废
        self._hover_watch.stop()
        self._ready_to_show = False
        self._pending_result = None
        self._pending_failure = None
        resolver = self._resolver
        self._resolver = None
        if resolver is not None:
            try:
                resolver.cancel()
            except RuntimeError:                # 已经被 Qt 回收
                pass
        item = self._item
        self._item = None
        self._popup.hide()
        if self._popup_player is not None and self._popup_playing:
            self._popup_playing = False
            # One shared popup can reuse one idle core; per-card players still release theirs.
            self._popup_player.stop(keep_core=True)
        if item is None:
            return
        try:
            item.thumb.stop()
        except RuntimeError:                    # 条目已经被删掉
            pass

    def cancel(self) -> None:
        """切换侧栏形态时收掉预览，但保留播放器供下一次悬停复用。"""
        self._delay.stop()
        self._resolve_delay.stop()
        self._grace.stop()
        self._room = {}
        self._stop_now()

    def stop(self) -> None:
        """外面主动收掉（关窗、关掉开关）。"""
        self.cancel()
        # 预览播放器平时留着复用（只有关窗 / 关掉开关时才真放掉）
        for item in self.sidebar.items():
            try:
                item.thumb.release_player()
            except RuntimeError:                    # 条目已经被删掉
                pass
        if self._popup_player is not None:
            self._popup_player.release()
            self._popup_player = None

    # ---- 小工具 ----
    def _room_id(self) -> str:
        return str(self._room.get("room_id") or "")

    def _item_of(self, room: dict):
        room_id = str(room.get("room_id") or "")
        return next((item for item in self.sidebar.items()
                     if str(item.room.get("room_id")) == room_id), None)
