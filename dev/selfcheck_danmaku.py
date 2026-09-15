"""自查：弹幕格的连接对象、消息进面板、换布局/换台时断开与重连。不联网。"""
import os
import sys
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def boom(room_id, quality=250):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


class FakeDanmakuClient(QThread):
    """顶掉真的弹幕客户端：不联网，手动喂消息。"""

    message = Signal(str, str, str)
    status = Signal(str)

    instances: list = []

    def __init__(self, room_id, parent=None):
        super().__init__(parent)
        self.room_id = str(room_id)
        self.stopped = False
        self._stop = False
        FakeDanmakuClient.instances.append(self)

    def run(self) -> None:
        self.status.emit("已连接")
        while not self._stop:
            time.sleep(0.03)

    def stop(self) -> None:
        self.stopped = True
        self._stop = True


ROOMS = [
    {"room_id": "1001", "uname": "Asaki大人", "title": "随便玩玩战狗", "live": True,
     "muted": True, "quality": 250},
    {"room_id": "1002", "uname": "七海Nana7mi", "title": "练习", "live": True,
     "muted": True, "quality": 250},
]


def settle(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def is_running(thread) -> bool:
    """线程已经被 Qt 回收时也算没在跑。"""
    try:
        return thread.isRunning()
    except RuntimeError:
        return False


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
    app_module.DanmakuClient = FakeDanmakuClient
    FakeDanmakuClient.instances = []
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow([dict(room) for room in ROOMS], [dict(room) for room in ROOMS],
                        layout_id="dm_pair")
    window.setGeometry(-8000, -8000, 1400, 800)
    window.show()
    settle(app, 1.0)
    panel = window.wall.danmaku

    print("=== 1. 弹幕布局：自动连主画面那一路 ===")
    print(f"  布局={window.wall.layout_id} 有弹幕格={window.wall.has_danmaku}"
          f" 连接数={len(FakeDanmakuClient.instances)}"
          f" 连的是={FakeDanmakuClient.instances[-1].room_id if FakeDanmakuClient.instances else '-'}")
    assert window.wall.has_danmaku
    assert len(FakeDanmakuClient.instances) == 1, "应该只连一路"
    assert FakeDanmakuClient.instances[-1].room_id == "1001", "要连主画面那一路"
    assert panel.count.text() == "已连接", f"状态应显示已连接，实际 {panel.count.text()!r}"

    print("\n=== 2. 收到消息会进面板（弹幕 / 礼物 / SC 上色）===")
    client = FakeDanmakuClient.instances[-1]
    client.message.emit("danmaku", "Asaki大人", "今天的直播好看")
    client.message.emit("gift", "路人甲", "投喂 辣条 ×2")
    client.message.emit("super_chat", "老板", "¥30　加油")
    settle(app, 0.4)
    text = panel.body.toPlainText()
    print(f"  条数={panel._received} 状态位={panel.count.text()!r}")
    print(f"  正文={text[:60]!r}")
    assert panel._received == 3
    assert "今天的直播好看" in text and "辣条" in text and "加油" in text
    assert panel.count.text() == "已连接 · 3"
    html = panel.body.toHtml()
    assert theme.PINK in html and theme.WARNING in html, "礼物/SC 应该有自己的颜色"

    print("\n=== 3. 换成普通布局：断开；切回弹幕布局：重新连，且不会重复连 ===")
    window.wall.set_layout("2x2")
    window._refresh_meta()                       # noqa: SLF001
    settle(app, 0.4)
    old = FakeDanmakuClient.instances[-1]
    print(f"  普通布局：旧连接已停={old.stopped} 连接总数={len(FakeDanmakuClient.instances)}")
    assert old.stopped and not is_running(old), "没有弹幕格就不该占着连接"
    assert window._danmaku is None               # noqa: SLF001

    window.wall.set_layout("dm_pair")
    window._refresh_meta()                       # noqa: SLF001
    settle(app, 0.4)
    window._refresh_meta()                       # noqa: SLF001
    window._refresh_meta()                       # noqa: SLF001
    settle(app, 0.3)
    print(f"  切回弹幕布局：连接总数={len(FakeDanmakuClient.instances)}"
          f" 连的是={FakeDanmakuClient.instances[-1].room_id}")
    assert len(FakeDanmakuClient.instances) == 2, "同一路不该反复重连"

    print("\n=== 4. 主画面换台：弹幕跟着换 ===")
    window.wall.tiles[0].set_room(dict(ROOMS[1]))
    window._refresh_meta()                       # noqa: SLF001
    settle(app, 0.5)
    latest = FakeDanmakuClient.instances[-1]
    print(f"  连接总数={len(FakeDanmakuClient.instances)}"
          f" 现在连的是={latest.room_id} 上一个已停={FakeDanmakuClient.instances[-2].stopped}")
    assert latest.room_id == "1002", "主画面换人，弹幕要跟着换"
    assert FakeDanmakuClient.instances[-2].stopped, "旧连接要断开"
    assert panel._received == 0, "换台后弹幕要清空"

    print("\n=== 5. 弹幕组件缺失时的降级 ===")
    from ddm import danmaku
    print(f"  blivedm 可用={danmaku.blivedm is not None} 导入错误={danmaku.IMPORT_ERROR or '（无）'!r}")
    assert danmaku.blivedm is not None, "本机应该能导入 blivedm（aiohttp + brotli）"

    print("\n=== 6. 关窗会断开弹幕 ===")
    alive = [item for item in FakeDanmakuClient.instances if not item.stopped]
    window.close()
    settle(app, 0.5)
    still_running = [item for item in alive if is_running(item)]
    print(f"  关窗前在跑={len(alive)} 关窗后还在跑={len(still_running)}")
    assert not still_running, "关窗要停掉弹幕线程"

    print("\n全部通过")


if __name__ == "__main__":
    main()
