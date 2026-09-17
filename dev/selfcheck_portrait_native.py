"""回归自检：跨屏切竖屏不产生悬浮格子，已有播放器继续显示画面。"""
import os
import sys
import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import app as app_module  # noqa: E402
from ddm import bili, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import Tile  # noqa: E402


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


class SpyPlayer:
    def __init__(self):
        self.bind_count = 0
        self.release_count = 0

    def bind(self) -> None:
        self.bind_count += 1

    def release(self) -> None:
        self.release_count += 1


def boom(room_id, quality=250):  # noqa: ANN001, ARG001
    raise RuntimeError("selfcheck：不联网")


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def make_rooms(count: int) -> list[dict]:
    return [{
        "room_id": str(10000 + index),
        "uname": f"关注{index + 1}",
        "title": "标题",
        "live": True,
        "viewers": "1",
        "muted": True,
        "volume": 42,
        "quality": 250,
    } for index in range(count)]


def main() -> None:
    bili.play_url = boom
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    rooms = make_rooms(28)
    window = MainWindow(rooms, rooms[:3], layout_id="dm_main3")
    native_widgets = []
    for tile in window.wall.tiles:
        native_widgets.extend((tile, tile.video, tile.stream_badge, tile.title_badge,
                               tile.time_badge, tile.controls, tile.spinner,
                               tile.pause_overlay))
    assert not any(widget.testAttribute(Qt.WA_NativeWindow) for widget in native_widgets), \
        "主窗口显示前不能降级/提回 Tile 原生窗口；启动阶段应保持旧版生命周期"
    window.setGeometry(-9000, -9000, 1600, 900)
    window.show()
    settle(app, 0.8)

    tile = window.wall.tiles[0]
    original_room = dict(tile.room)
    original_start = window.start_tile
    original_stop = window._stop_tile  # noqa: SLF001
    original_lookup = window._room_dict  # noqa: SLF001
    original_refresh = window._refresh_meta  # noqa: SLF001
    starts = []
    window.start_tile = lambda item: starts.append(item)
    window._stop_tile = lambda _item: None  # noqa: SLF001
    window._room_dict = lambda _rid: {  # noqa: SLF001
        "room_id": "20000", "uname": "新主播", "title": "", "live": True,
        "viewers": "", "muted": True, "volume": 42, "quality": 250,
    }
    window._refresh_meta = lambda: None  # noqa: SLF001
    window._on_room_dropped(tile, "20000")  # noqa: SLF001
    assert starts.count(tile) == 1, "拖入主画面只能启动一次取流，不能被画质策略重复启动"
    window.start_tile = original_start
    window._stop_tile = original_stop  # noqa: SLF001
    window._room_dict = original_lookup  # noqa: SLF001
    window._refresh_meta = original_refresh  # noqa: SLF001
    tile.set_room(original_room)

    spy = SpyPlayer()
    window.players[tile] = spy
    tile.video.show()
    tile.set_video_active(True)
    tile.set_buffering(False)
    tile.set_paused(False)

    # 原生窗口降级/提回必须保留各叠层自己的状态，不能凭类型强制显隐。
    tile.set_controls_visible(True)
    window._demote_native_windows()  # noqa: SLF001
    window.wall.relayout(force=True)
    window._promote_native_windows()  # noqa: SLF001
    assert tile.controls.isVisible(), "切换排布不能吞掉正在显示的右上角控制条"
    assert not tile.spinner.isVisible(), "非连接状态不能凭空显示『连接中』"
    assert not tile.pause_overlay.isVisible(), "未暂停时不能凭空显示『已暂停』"
    tile.set_controls_visible(False)

    restarts = []
    window.start_tile = lambda item: restarts.append(item)
    window.resize(914, 1463)
    settle(app, 0.8)
    visible_strays = [widget for widget in app.topLevelWidgets()
                      if isinstance(widget, Tile) and widget.isVisible()]
    print(f"竖屏：格子={len(window.wall.tiles)} 顶层可见 Tile={len(visible_strays)} "
          f"播放器绑定={spy.bind_count} 视频可见={tile.video.isVisible()}")
    assert window.orientation == "portrait"
    assert all(item.parentWidget() is window.wall for item in window.wall.tiles), \
        "竖屏手动摆放的格子必须预先挂在 WallGrid 下"
    assert not visible_strays, "竖屏切换不能产生顶层悬浮格子"
    assert spy.release_count == 1, "换父容器前必须先完整释放正在使用旧 HWND 的 VLC"
    assert restarts == [tile], "新排布完成后必须重新启动原来正在播放的格子"
    assert tile.video.isVisible(), "方向切换后已有直播的视频区必须保持可见"
    assert not tile.spinner.isVisible(), "竖屏后不能残留『连接中』叠层"
    assert not tile.pause_overlay.isVisible(), "竖屏后不能残留『已暂停』叠层"

    window.resize(1600, 900)
    settle(app, 0.8)
    print(f"回横屏：方向={window.orientation} 播放器绑定={spy.bind_count} "
          f"视频可见={tile.video.isVisible()}")
    assert window.orientation == "landscape"
    assert spy.release_count == 1, "已释放的旧播放器不能再次参与回横屏重排"
    assert tile.video.isVisible(), "回横屏后已有直播的视频区必须保持可见"
    assert not tile.spinner.isVisible(), "回横屏后不能残留『连接中』叠层"
    assert not tile.pause_overlay.isVisible(), "回横屏后不能残留『已暂停』叠层"

    window.close()
    settle(app, 0.2)
    print("跨屏方向切换原生窗口/播放器回归通过")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
