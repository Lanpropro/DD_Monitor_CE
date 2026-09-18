"""自查：浮标不再互相遮挡；下播黑屏但保留格子、回开播自动续播。不联网。"""
import os
import sys
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import app as app_module  # noqa: E402
from ddm import bili, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


class IdlePoller(QThread):
    """替掉真的轮询线程。

    `_on_resolve_failed()` 里会 `refresh_status()` 立刻去确认真实状态；不挡住的话
    这个自查会拿 1001/1002 这些**假房间号**去问 B 站，B 站说「没这个房间」，
    格子就被当成下播，断言 `live is True` 随机变红（这就是它一直不稳的原因）。
    """

    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


def boom(room_id, quality=250):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


ROOMS = [
    {"room_id": "1001", "uname": "示例主播A", "title": "示例直播标题", "live": True,
     "viewers": "3.1万", "muted": True, "quality": 250, "live_start_ts": int(time.time()) - 600},
    {"room_id": "1002", "uname": "示例主播B", "title": "示例标题二", "live": True,
     "viewers": "1.8万", "muted": True, "quality": 250, "live_start_ts": int(time.time()) - 300},
    {"room_id": "1003", "uname": "示例主播C", "title": "示例标题三", "live": True,
     "viewers": "6.1万", "muted": True, "quality": 250, "live_start_ts": int(time.time()) - 900},
]


class FakePlayer:
    def __init__(self):
        self.released = False
        self.paused = False

    def set_paused(self, paused):
        self.paused = bool(paused)

    def release(self):
        self.released = True


def settle(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def check_badges(tile, label) -> None:
    badge = tile.stream_badge
    title = tile.title_badge
    controls = tile.controls
    stacked = controls.y() > 20
    print(f"  [{label}] 格宽={tile.width()} LIVE={badge.geometry().getRect()}"
          f" 人数隐藏={getattr(badge, '_compact', False)}"
          f" 标题可见={title.isVisible()} 标题={title.geometry().getRect() if title.isVisible() else None}"
          f" 控制条=({controls.x()},{controls.y()}){'（换行）' if stacked else ''}")
    if stacked:
        assert badge.y() + badge.height() <= controls.y() - 2, "LIVE 浮标和控制条立体重叠"
    else:
        assert badge.x() + badge.width() <= controls.x() - 4, "LIVE 浮标压到控制条了"
    if title.isVisible():
        assert badge.x() + badge.width() <= title.x() - 2, "标题压到 LIVE 了"
        limit = controls.x() if not stacked else tile.video.width()
        assert title.x() + title.width() <= limit - 2, "标题压到控制条了"


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
    # 轮询线程换成空转：这个自查只关心状态机，不该去问真接口
    app_module.StatusPoller = IdlePoller
    app_module.StatsPoller = IdlePoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow([dict(room) for room in ROOMS], [dict(room) for room in ROOMS],
                        layout_id="main2")
    window.setGeometry(-8000, -8000, 1500, 860)
    window.show()
    settle(app, 1.2)

    print("=== 1. 宽窗口（1 大 + 2 小）===")
    for index, tile in enumerate(window.wall.tiles):
        check_badges(tile, f"格子{index}")

    print("\n=== 2. 把窗口拉窄，浮标要自动收缩 ===")
    for width in (1180, 980, 820):
        window.resize(width, 720)
        settle(app, 0.5)
        print(f"  窗口宽 {width}:")
        for index, tile in enumerate(window.wall.tiles):
            check_badges(tile, f"格子{index}")

    window.resize(1500, 860)
    settle(app, 0.5)

    print("\n=== 3. 下播：黑屏但保留格子 ===")
    tile = window.wall.tiles[0]
    fake = FakePlayer()
    window.players[tile] = fake
    tile._player_active = True
    tile.set_watched("7124")
    tile.start_elapsed_timer()
    settle(app, 0.4)
    room_id_before = tile.room.get("room_id")
    window._offline_tile(tile)
    settle(app, 0.5)
    print(f"  画面文字={tile.cover.text()!r} 封面图已清空={tile._cover_source is None}"
          f" 播放器已释放={fake.released} room_id={tile.room.get('room_id')}"
          f" live={tile.room.get('live')} 浮标={tile.stream_badge._text()}"
          f" 格子还在墙上={tile in window.wall.tiles}")
    assert tile.cover.text() == "已下播", "下播后画面要清成黑的并写已下播"
    assert tile._cover_source is None
    assert fake.released, "下播要停掉播放器（不然留着最后一帧）"
    assert tile.room.get("room_id") == room_id_before, "格子要继续留给这个直播间"
    assert tile in window.wall.tiles and tile.isVisible()
    assert tile.stream_badge._text() == "已下播"
    assert tile.time_badge.isVisible() is False, "下播后不再显示直播时长"

    print("\n=== 4. 重新开播：自动接上 ===")
    started: list = []
    original_start = window.start_tile
    window.start_tile = lambda t, _o=original_start, _s=started: (_s.append(t), _o(t))[1]
    status = {"1001": {"live": True, "title": "示例直播标题", "uname": "示例主播A",
                       "viewers": "2万", "face": ""}}
    window._on_status_updated(status)
    settle(app, 0.6)
    print(f"  live={tile.room.get('live')} 状态={tile._status_text!r}"
          f" 自动重新取流={tile in started}")
    if tile.room.get("live") is not True:
        items = {str(item.room.get("room_id")): item for item in window.sidebar.items()}
        it = items.get(str(tile.room.get("room_id")))
        print(f"  [诊断] 侧栏条目={it!r} 侧栏 live={it.room.get('live') if it else None} "
              f"侧栏 alert={it._alert if it else None} "
              f"侧栏 badge={it.badge.text() if it else None} "
              f"同一字典={it is not None and it.room is tile.room}")
    assert tile.room.get("live") is True
    assert tile in started, "回开播应该自动重新取流"
    assert tile._status_text != "已下播"
    # B3 的结论（用户 2026-09-18 用实机截图确认过）：**取流失败 ≠ 下播**。
    # 房间在不在播由接口说了算；取流失败只让这一格显示「连接失败」并继续重试，
    # 不能把房间标成已下播、也不能停掉自动接上的逻辑。
    assert tile.stream_badge._text() != "已下播", "取流失败不能当成已下播"
    print("  取流失败时：live 仍为接口给的值、浮标不是「已下播」✓")

    print("\n=== 5. 快捷键里没有隐藏顶栏了 ===")
    from ddm.dialogs import SHORTCUT_ACTIONS
    keys = [key for key, _label, _default in SHORTCUT_ACTIONS]
    print(f"  快捷键项={keys}")
    assert "hide_bar" not in keys
    assert not hasattr(window, "topbar"), "右侧顶栏已经去掉"

    window.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
