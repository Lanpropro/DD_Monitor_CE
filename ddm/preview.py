"""悬停预览：鼠标在关注列表的已开播直播间上停 2 秒，旁边弹一个小画面。

小窗是独立的无边框窗口（不抢焦点），静音、低画质；鼠标离开条目就收掉，
播放器同时释放，不会一直占着带宽和 CPU。
"""
import sys

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from .bili import StreamResolver
from .player import TilePlayer

PREVIEW_WIDTH = 360
PREVIEW_HEIGHT = PREVIEW_WIDTH * 9 // 16
PREVIEW_QUALITY = 80        # 流畅：小画面看得清就够了，省带宽
CORNER_RADIUS = 10          # 圆角半径


class StreamPreview(QWidget):
    """预览小窗：整个窗口就是画面（圆角），不放标题栏。"""

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setObjectName("PreviewWindow")
        self.setFixedSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self._round_corners()
        self.room_id = ""
        self.state = "连接中…"          # 只用来记日志/排查，不显示在界面上
        self._player: TilePlayer | None = None
        self._resolver: StreamResolver | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.video = QFrame(self)
        self.video.setObjectName("PreviewVideo")
        self.video.setAttribute(Qt.WA_StyledBackground, True)
        layout.addWidget(self.video, 1)

    def _round_corners(self) -> None:
        """给整个窗口套一个圆角遮罩：这样连 VLC 画上去的画面也会一起裁圆。"""
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), CORNER_RADIUS, CORNER_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._round_corners()

    # ---- 对外 ----
    def show_room(self, room: dict, position: QPoint) -> None:
        """换一个直播间预览：先把窗口摆好，再异步取流。"""
        self.stop()
        self.room_id = str(room.get("room_id") or "")
        self.state = "连接中…"          # 小窗里不显示任何文字，状态只写日志
        self.move(position)
        self.show()
        self.raise_()

        resolver = StreamResolver(self.room_id, PREVIEW_QUALITY, self)
        resolver.resolved.connect(self._on_resolved)
        resolver.failed.connect(self._on_failed)
        resolver.finished.connect(lambda: setattr(self, "_resolver", None))
        resolver.finished.connect(resolver.deleteLater)
        self._resolver = resolver
        resolver.start()

    def stop(self) -> None:
        """收掉小窗并释放播放器/取流线程。"""
        if self._resolver is not None:
            try:
                if self._resolver.isRunning():
                    self._resolver.terminate()
            except RuntimeError:
                pass
            self._resolver = None
        if self._player is not None:
            self._player.release()
            self._player = None
        self.hide()

    # ---- 取流 ----
    def _on_resolved(self, room_id: str, url: str, quality: int, profile: str,
                     options: list | None) -> None:
        if room_id != self.room_id or not self.isVisible():
            return
        if self._player is None:
            self._player = TilePlayer(self.video, self)
            self._player.freeze_watch = False      # 预览不用卡死检测
            self._player.stateChanged.connect(self._on_player_state)
        self._player.set_muted(True)               # 预览永远静音
        self._player.set_volume(0)
        self._player.play(url, profile)

    def _on_failed(self, room_id: str, reason: str) -> None:
        if room_id == self.room_id:
            self.state = "取流失败"
            print(f"[预览取流失败] {room_id}: {reason}", file=sys.stderr, flush=True)

    def _on_player_state(self, state: str) -> None:
        text = {"connecting": "连接中…", "playing": "预览中（静音）",
                "buffering": "缓冲中…", "error": "播放失败"}.get(state, "")
        if text:
            self.state = text


class HoverPreview(QObject):
    """管悬停计时：停够 2 秒才弹，离开就收（留一点点宽限，避免手抖闪一下）。"""

    DELAY_MS = 1000
    GRACE_MS = 120
    SIDEBAR_OVERLAP = 3         # 小窗往左压住侧栏约 1/3 宽度

    def __init__(self, sidebar, parent=None):
        super().__init__(parent)
        self.sidebar = sidebar
        self.enabled = True
        self.widget = StreamPreview()
        self._room: dict = {}
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.setInterval(self.DELAY_MS)
        self._delay.timeout.connect(self._show_now)
        self._grace = QTimer(self)
        self._grace.setSingleShot(True)
        self._grace.setInterval(self.GRACE_MS)
        self._grace.timeout.connect(self.widget.stop)

    # ---- 悬停事件 ----
    def on_hover(self, room: dict) -> None:
        if not self.enabled or self.sidebar.select_mode:
            return
        if not room.get("live"):
            return                                 # 没开播就没什么可看的
        self._grace.stop()
        if (self.widget.isVisible()
                and str(room.get("room_id")) != self.widget.room_id):
            self.widget.stop()                     # 换到别人身上了：立刻收掉旧画面
        self._room = room
        self._delay.start()

    def on_unhover(self, room: dict) -> None:
        if str(room.get("room_id") or "") != str(self._room.get("room_id") or ""):
            return                                 # 已经换到别的条目上了
        self._delay.stop()
        if self.widget.isVisible():
            self._grace.start()                    # 手抖一下不立刻收

    # ---- 弹出 ----
    def _show_now(self) -> None:
        room = self._room
        if not room.get("room_id") or not room.get("live"):
            return
        position = self._anchor(room)
        print(f"[预览] {room.get('uname')}", file=sys.stderr, flush=True)
        self.widget.show_room(room, position)

    def _anchor(self, room: dict, clamp: bool = True) -> QPoint:
        """跟条目对齐，往左压住侧栏约 1/3；贴边时往回收，别跑出屏幕。"""
        item = next((entry for entry in self.sidebar.items()
                     if str(entry.room.get("room_id")) == str(room.get("room_id"))), None)
        if item is not None:
            corner = item.mapToGlobal(QPoint(item.width() + 6, 0))
        else:
            corner = self.sidebar.mapToGlobal(QPoint(self.sidebar.width() + 6, 0))
        overlap = max(0, self.sidebar.width() // self.SIDEBAR_OVERLAP)
        x = corner.x() - overlap
        if not clamp:
            return QPoint(x, corner.y())
        screen = self.sidebar.screen()
        if screen is not None:
            area = screen.availableGeometry()
            width = self.widget.width()
            height = self.widget.height()
            x = min(x, area.right() - width - 8)
            y = min(max(corner.y(), area.top() + 8), area.bottom() - height - 8)
            return QPoint(max(area.left() + 8, x), y)
        return QPoint(x, corner.y())

    def stop(self) -> None:
        self._delay.stop()
        self._grace.stop()
        self._room = {}
        self.widget.stop()
