"""回归自检：启动不再同步逐个拉房间信息（窗口立刻出现，状态后台补）。

来源：``ddm/config.py`` 的 ``build_rooms()`` 以前在启动时对每个房间逐个
``bili.room_info()``（单个超时 10 秒），房间一多主线程就要干等几十秒，窗口
迟迟不出现。现在改成只造占位条目、窗口立刻显示，真实信息由启动后的
``refresh_status()``（后台线程、批量一次请求）补上。

这里钉住三条不变量：
1. ``build_rooms()`` 不碰网络：对每个房间返回占位条目（room_id + uname「房间 X」
   + live=False），且不调用 ``bili.room_info``；
2. 格子设置（静音/音量/画质/声道）仍从配置恢复；
3. 状态刷新的回调 ``_on_status_updated`` 会把主播名/标题补到侧栏条目和画面格上。

不联网：打桩让任何 bili 房间接口一被调用就抛异常。
"""
import os
import sys
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, theme, version as version_module  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm import config as config_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def boom(*_a, **_k):  # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网")


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
    bili.room_info = boom
    bili.rooms_status = boom
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    print("=== 1. build_rooms 不碰网络，只造占位条目 ===")
    state = {
        "version": 1,
        "rooms": ["7001", "7002"],
        "wall": [{"room_id": "7001", "muted": True, "volume": 42, "quality": 250,
                  "audio_channel": 0}],
    }
    sidebar, wall = config_module.build_rooms(state)
    print(f"  侧栏 {len(sidebar)} 个，画面墙 {len(wall)} 个")
    assert [r["room_id"] for r in sidebar] == ["7001", "7002"]
    assert all(r["live"] is False for r in sidebar), "启动不该等直播状态"
    assert sidebar[0]["uname"] == "房间 7001", "占位条目该有「房间 X」名字"
    assert wall[0]["room_id"] == "7001" and wall[0]["volume"] == 42
    assert wall[0]["muted"] is True, "格子设置（静音/音量）要随配置恢复"

    print("\n=== 2. 源码钉住：build_rooms 不再逐个 room_info ===")
    import io as _io
    src = _io.open(os.path.join(REPO, "ddm", "config.py"), encoding="utf-8").read()
    assert "bili.room_info" not in src, \
        "启动时逐个 bili.room_info() 会让窗口干等几十秒，别再回来"

    print("\n=== 3. 状态刷新把真名/标题补到侧栏和画面格 ===")
    window = MainWindow([dict(r) for r in sidebar], [dict(r) for r in wall],
                        layout_id="1x1")
    assert window.windowTitle() == version_module.DISPLAY_NAME
    window.setGeometry(-9000, -9000, 900, 600)
    window.show()
    settle(app, 1.0)
    item = next(i for i in window.sidebar._items  # noqa: SLF001
                if i.room.get("room_id") == "7001")
    tile = window.wall.tiles[0]
    started = []
    window.start_tile = lambda t: started.append(t)
    window._on_status_updated({
        "7001": {"live": True, "title": "标题甲", "uname": "主播甲",
                 "face": "", "cover_url": "", "viewers": "1.2万",
                 "live_start_ts": 1700000000},
    })
    settle(app, 0.4)
    print(f"  侧栏：{item.room.get('uname')!r} / {item.room.get('title')!r} "
          f"画面格：{tile.room.get('uname')!r} live={tile.room.get('live')}")
    assert item.room["uname"] == "主播甲", "状态刷新后侧栏要补上主播名"
    assert item.room["title"] == "标题甲"
    assert tile.room["uname"] == "主播甲", "状态刷新后画面格要补上主播名"
    assert tile.room["title"] == "标题甲"
    assert tile.room["live"] is True
    assert tile.room["live_start_ts"] == 1700000000, "直播时长要跟着补上"
    assert started == [tile], "状态刷新发现开播后要自动开始播放"

    print("\n=== 3b. 启动时补上真实状态不算「刚开播」，不该冒开播提醒 ===")
    alerts: list = []
    window.sidebar.play_live_alerts = lambda items: alerts.extend(items)
    item2 = next(i for i in window.sidebar._items  # noqa: SLF001
                 if i.room.get("room_id") == "7002")
    print(f"  占位条目 live_known={item2.room.get('live_known')}")
    assert item2.room.get("live_known") is False, "占位条目要标成「状态还没拉过」"
    window._on_status_updated({
        "7002": {"live": True, "title": "标题乙", "uname": "主播乙",
                 "face": "", "cover_url": "", "viewers": ""},
    })
    assert alerts == [], "启动时补状态不该弹开播提醒（用户要的是「开播时」提醒）"
    assert item2.room.get("live") is True, "但徽标状态要摆正"
    # 之后真的下播再开播，才应该提醒
    window._on_status_updated({
        "7002": {"live": False, "title": "标题乙", "uname": "主播乙",
                 "face": "", "cover_url": "", "viewers": ""},
    })
    window._on_status_updated({
        "7002": {"live": True, "title": "标题乙", "uname": "主播乙",
                 "face": "", "cover_url": "", "viewers": ""},
    })
    print(f"  启动补状态提醒 {0} 次，之后真开播提醒 {len(alerts)} 次")
    assert len(alerts) == 1, "之后真的开播还是要提醒"

    print("\n=== 4. NavItem.set_uname 真把名字画出来 ===")
    item.set_uname("主播乙")
    assert item.name_label.text() == "主播乙"
    item.set_uname("")
    assert item.name_label.text() == "7001", "名字清空后回退到房间号"
    print(f"  set_uname -> {item.name_label.text()!r}（清空后回退房间号）")

    window.close()
    settle(app, 0.3)

    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
