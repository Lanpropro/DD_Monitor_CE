"""悬停预览：鼠标在关注列表的已开播直播间上停 1 秒，缩略图里直接放静音画面。

画面就播在该条目的缩略图（NavThumb）里，不再另开小窗；鼠标移开立刻收掉并释放播放器，
不会一直占带宽和 CPU。
"""
import sys

from PySide6.QtCore import QObject, QTimer

from .bili import StreamResolver

PREVIEW_QUALITY = 80        # 流畅：缩略图那么大，看得清就够了

#: 预览专用的 media 选项。预览是**静音的小画面**，两样都不需要：
#:   :no-audio        —— 干脆别建音频输出。省掉第二个 WASAPI/mmdevice 输出，
#:                       也就没有「两个播放器抢音频设备」这种卡死的机会。
#:   :avcodec-hw=none —— 走软解。缩略图只有两百来像素宽，软解毫无压力，
#:                       却少了一个和画面墙那一路抢 D3D11 解码器的实例
#:                       （用户机器上正好卡死在「预览开始播」这一步：
#:                        Windows 26200 + NVIDIA 616.64）。
#: 注意这只是第二道保险：预览播放器本身用的是 PlayerPool.preview_instance()
#: ——一个专门用 --aout=adummy / --no-audio 建出来的 libvlc 实例，见 ddm/player.py。
PREVIEW_MEDIA_OPTIONS = (":no-audio", ":avcodec-hw=none")


class HoverPreview(QObject):
    """管悬停计时，并把预览发到对应条目的缩略图上。"""

    DELAY_MS = 1000         # 停够 1 秒才播
    GRACE_MS = 120          # 移开后的宽限（手抖一下不立刻收）

    def __init__(self, sidebar, parent=None):
        super().__init__(parent)
        self.sidebar = sidebar
        self.enabled = True
        self._room: dict = {}
        self._item = None                       # 正在预览的条目
        self._resolver: StreamResolver | None = None
        self._generation = 0                    # 取流编号：旧编号的结果一律丢掉
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.setInterval(self.DELAY_MS)
        self._delay.timeout.connect(self._show_now)
        self._grace = QTimer(self)
        self._grace.setSingleShot(True)
        self._grace.setInterval(self.GRACE_MS)
        self._grace.timeout.connect(self._stop_now)

    # ---- 悬停事件 ----
    def on_hover(self, room: dict) -> None:
        if not self.enabled or self.sidebar.select_mode:
            return
        if not room.get("live"):
            return                              # 没开播就没什么可看的
        self._grace.stop()
        if self._item is not None and str(room.get("room_id")) != self._room_id():
            self._stop_now()                    # 换到别人身上了：旧预览立刻收掉
        self._room = room
        self._delay.start()

    def on_unhover(self, room: dict) -> None:
        if str(room.get("room_id") or "") != self._room_id():
            return                              # 已经换到别的条目上了
        self._delay.stop()
        if self._item is not None:
            self._grace.start()                 # 手抖一下不立刻收

    # ---- 起播 / 收掉 ----
    def _show_now(self) -> None:
        room = self._room
        if not room.get("room_id") or not room.get("live"):
            return
        item = self._item_of(room)
        if item is None:
            return
        self._stop_now()                        # 顺带把编号推进一格
        self._item = item
        try:
            item.thumb.set_hint("连接中…")
        except RuntimeError:                    # 条目已经被删掉
            self._item = None
            return
        print(f"[预览] {room.get('uname')} → 缩略图", file=sys.stderr, flush=True)
        generation = self._generation
        resolver = StreamResolver(str(room["room_id"]), PREVIEW_QUALITY, self)
        # 回调都带上编号：编号过期就说明这次取流早就作废了（鼠标移开、换了条目）
        resolver.resolved.connect(
            lambda room_id, url, quality, profile, options, gen=generation:
            self._on_resolved(gen, room_id, url, quality, profile, options))
        resolver.failed.connect(
            lambda room_id, reason, gen=generation: self._on_failed(gen, room_id, reason))
        resolver.finished.connect(lambda r=resolver: self._on_finished(r))
        resolver.finished.connect(resolver.deleteLater)
        self._resolver = resolver
        resolver.start()

    def _on_resolved(self, generation: int, room_id: str, url: str, quality: int,
                     profile: str, options: list | None) -> None:
        if generation != self._generation:
            return                              # 这次取流已经作废
        item = self._item
        if item is None or str(item.room.get("room_id")) != str(room_id):
            return
        try:
            item.thumb.play(url, profile, options=PREVIEW_MEDIA_OPTIONS)
        except RuntimeError:
            self._item = None

    def _on_failed(self, generation: int, room_id: str, reason: str) -> None:
        if generation != self._generation:
            return
        print(f"[预览取流失败] {room_id}: {reason}", file=sys.stderr, flush=True)
        item = self._item
        if item is not None:
            try:
                item.thumb.set_hint("取流失败")
            except RuntimeError:
                self._item = None

    def _on_finished(self, resolver) -> None:
        if self._resolver is resolver:           # 迟到的旧线程别把新线程顶掉
            self._resolver = None

    def _stop_now(self) -> None:
        """让缩略图回到封面，并让正在跑的取流作废。

        注意这里**不杀线程**：只 cancel()，线程自己跑完最后一步就结束。强杀
        （QThread.terminate）会带走线程本地存储和锁，主线程之后可能整个卡死。
        """
        self._generation += 1                   # 之前那次的结果从此一律作废
        resolver = self._resolver
        self._resolver = None
        if resolver is not None:
            try:
                resolver.cancel()
            except RuntimeError:                # 已经被 Qt 回收
                pass
        item = self._item
        self._item = None
        if item is None:
            return
        try:
            item.thumb.stop()
        except RuntimeError:                    # 条目已经被删掉
            pass

    def stop(self) -> None:
        """外面主动收掉（关窗、关掉开关）。"""
        self._delay.stop()
        self._grace.stop()
        self._room = {}
        self._stop_now()
        # 预览播放器平时留着复用（只有关窗 / 关掉开关时才真放掉）
        for item in self.sidebar.items():
            try:
                item.thumb.release_player()
            except RuntimeError:                    # 条目已经被删掉
                pass

    # ---- 小工具 ----
    def _room_id(self) -> str:
        return str(self._room.get("room_id") or "")

    def _item_of(self, room: dict):
        room_id = str(room.get("room_id") or "")
        return next((item for item in self.sidebar.items()
                     if str(item.room.get("room_id")) == room_id), None)
