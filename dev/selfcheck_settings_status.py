"""自查：人数占位、卡顿/状态提示、侧栏收起头像居中、设置菜单与全局设置。不联网。"""
import os
import sys
import time
from unittest import mock

from PySide6.QtCore import QEvent, QPoint, QPointF, QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QKeyEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, config as config_module, theme  # noqa: E402
from ddm import app as app_module              # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import SettingsDialog  # noqa: E402
from ddm.player import TilePlayer  # noqa: E402


def boom(room_id, quality=250, **_kwargs):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


class SilentPoller(QThread):
    """自检里别真的轮询：有网络时假的房间号会被查成"未开播"，把断言搞乱。"""

    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


ROOMS = [
    {"room_id": "1001", "uname": "示例主播A", "title": "示例直播标题", "live": True,
     "viewers": "3.1万", "muted": True, "quality": 250},
    {"room_id": "1002", "uname": "示例主播B", "title": "示例标题二", "live": True,
     "viewers": "1.8万", "muted": True, "quality": 250},
]


def settle(app, seconds):
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
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow([dict(room) for room in ROOMS], [dict(room) for room in ROOMS],
                        layout_id="1x2")
    window.setGeometry(-8000, -8000, 1400, 800)
    window.show()
    settle(app, 1.2)

    print("=== 1. 在线人数没拉到之前不显示人气值 ===")
    tile = window.wall.tiles[0]
    tile.room.pop("online", None)
    tile._refresh_badge()
    settle(app, 0.3)
    badge_text = tile.stream_badge._text() + " " + (tile.stream_badge.viewers or "")
    print(f"  浮标文字={tile.stream_badge._text()!r} 人数位={tile.stream_badge.viewers!r}"
          f" 提示={tile.stream_badge.toolTip()!r}")
    assert tile.stream_badge.viewers == "正在获取人数", "还没拿到人数时应该显示占位"
    assert "3.1万" not in tile.stream_badge.viewers, "人气值不能当在线人数显示"
    tile.set_watched("7124")
    settle(app, 0.3)
    print(f"  拉到之后：人数位={tile.stream_badge.viewers!r}"
          f" 提示={tile.stream_badge.toolTip()!r}")
    assert tile.stream_badge.viewers == "7124"
    assert "人气 3.1万" in tile.stream_badge.toolTip()
    # 换一路进格子（拖进画面墙走的就是这里）也不能把人气值当在线人数
    tile.set_room({"room_id": "1003", "uname": "新来的", "title": "试试", "live": True,
                   "viewers": "7.2万"})
    settle(app, 0.3)
    print(f"  换台后：人数位={tile.stream_badge.viewers!r}")
    assert tile.stream_badge.viewers == "正在获取人数"
    # 下播后旧的在线人数要清掉，重新开播不能显示上一场的数字
    tile.set_watched("8888")
    tile.set_live(False, "7.2万")
    tile.set_live(True, "7.2万")
    settle(app, 0.3)
    print(f"  下播再开播：人数位={tile.stream_badge.viewers!r}")
    assert tile.stream_badge.viewers == "正在获取人数"

    print("\n=== 2. 卡住 / 状态都写在信息条里（不会被画面盖住）===")
    tile.set_status("连接中…")
    print(f"  连接中: 标签={tile.status_label.text()!r} 转圈={tile.spinner.isVisible()}")
    assert tile.status_label.text() == "连接中…"
    tile.set_buffering(True)
    print(f"  缓冲中: 标签={tile.status_label.text()!r} 转圈={tile.spinner.isVisible()}")
    assert tile.status_label.text() == "缓冲中…" and tile.spinner.isVisible()
    tile.set_buffering(False)
    assert not tile.spinner.isVisible()
    tile.set_status("断流，10 秒后重连（第 2 次）")
    print(f"  断流: 标签={tile.status_label.text()!r}")
    assert "重连" in tile.status_label.text()
    tile.set_status("")
    assert tile.status_label.text() == ""

    print("\n=== 3. 画面卡死检测（时钟在走但画面不变）===")
    holder = QWidget()
    tp = TilePlayer(holder)
    tp.freeze_watch = True
    tp._picture_signature = lambda: (1234, "same")     # 画面一直不变
    results = [tp._check_picture(True) for _ in range(3)]
    print(f"  每秒检查、连续约 2 秒相同画面 -> 判定卡住: {results}")
    assert results == [False, False, True]
    tp._picture_signature = lambda: (time.time(), "changing")   # 画面在变
    print(f"  画面恢复变化 -> {tp._check_picture(True)}")
    assert tp._check_picture(True) is False
    tp.freeze_watch = False
    tp._picture_signature = lambda: (1, "same")
    assert [tp._check_picture(True) for _ in range(6)] == [False] * 6
    print("  关掉检测后不再判定")

    print("  指纹来源：VLC 解码计数，不再截图（用户机器上就是崩在截图那条路上）")
    assert not hasattr(tp, "_shot_path"), "不该再往临时目录写截图"
    del tp._picture_signature            # 把上面打桩的 lambda 摘掉，看真实现
    print(f"    没在播时指纹={tp._picture_signature()!r}（None）")
    assert tp._picture_signature() is None
    import io as _io
    _player_source = _io.open(os.path.join(REPO, "ddm", "player.py"),
                              encoding="utf-8").read()
    assert ".video_take_snapshot(" not in _player_source, \
        "截图判定会在用户机器上卡 7 秒 + access violation，别再回来"

    print("\n=== 3b. 静止画面自动刷新与恢复 ===")
    restarts = []
    status_checks = []
    original_start_tile = window.start_tile
    original_refresh_status = window.refresh_status
    window.start_tile = lambda target: restarts.append(target)
    window.refresh_status = lambda: status_checks.append(True)
    window._on_player_state(tile, "frozen")
    print(f"  首次静止：立即刷新={len(restarts)} 状态确认={len(status_checks)}"
          f" 状态={tile.status_label.text()!r}")
    assert restarts == [tile]
    assert status_checks == [True], "画面静止时应立即查询真实直播状态"
    assert tile in window._freeze_refreshed
    window._on_player_state(tile, "frozen")
    timer = window._freeze_retry_timers.get(tile)
    print(f"  刷新后仍静止：5 秒定时器={timer is not None} 状态={tile.status_label.text()!r}")
    assert timer is not None and timer.isActive()
    assert "5 秒后再次刷新" in tile.status_label.text()
    window._on_picture_activity(tile)
    print(f"  画面恢复：定时器已取消={tile not in window._freeze_retry_timers}")
    assert tile not in window._freeze_retry_timers
    assert tile not in window._freeze_refreshed
    window.start_tile = original_start_tile
    window.refresh_status = original_refresh_status

    print("\n=== 3c. 画面格与侧栏共享数据时也要刷新侧栏徽标 ===")
    item = window.sidebar.items()[0]
    tile.set_room(item.room)
    item.set_live(True)
    room_id = str(item.room["room_id"])
    window.settings["live_alert"] = False
    started = []
    original_start_tile = window.start_tile
    window.start_tile = lambda target: started.append(target)
    before = time.perf_counter()
    window._on_status_updated({room_id: {
        "live": False, "viewers": "", "title": item.room.get("title", ""),
        "cover_url": "", "face": "",
    }})
    offline_ms = (time.perf_counter() - before) * 1000
    print(f"  下播刷新：画面 live={tile.room.get('live')} 侧栏徽标={item.badge.text()!r}"
          f" 用时={offline_ms:.1f}ms")
    assert tile.room is item.room
    assert tile.room.get("live") is False
    assert item.badge.text() == "未开播"
    before = time.perf_counter()
    window._on_status_updated({room_id: {
        "live": True, "viewers": "1.2万", "title": item.room.get("title", ""),
        "cover_url": "", "face": "",
    }})
    online_ms = (time.perf_counter() - before) * 1000
    print(f"  开播刷新：画面 live={tile.room.get('live')} 侧栏徽标={item.badge.text()!r}"
          f" 用时={online_ms:.1f}ms 自动播放={started == [tile]}")
    assert tile.room.get("live") is True
    assert item.badge.text() == "直播中"
    assert started == [tile]
    assert max(offline_ms, online_ms) < 100, "拿到状态结果后，界面切换应在 100ms 内完成"
    window.start_tile = original_start_tile
    window.settings["live_alert"] = True

    print("\n=== 3d. 音量属于格子：换主播不变，并写入重启配置 ===")
    first, second = window.wall.tiles[:2]
    first.set_volume(40)
    second.set_volume(73)
    first.set_muted(False)
    second.set_muted(True)
    assert window._save_timer.isActive(), "调整格子音量后应排队保存配置"
    first_room_id = str(first.room.get("room_id"))
    second_room_id = str(second.room.get("room_id"))
    original_start_tile = window.start_tile
    original_stop_tile = window._stop_tile
    window.start_tile = lambda _target: None
    window._stop_tile = lambda _target: None
    window._on_tile_swapped(first_room_id, second)
    window.start_tile = original_start_tile
    window._stop_tile = original_stop_tile
    saved_wall = window.current_state()["wall"]
    print(f"  交换后：格1={first.volume}/静音{first.muted}（房间 {first.room.get('room_id')}）"
          f" 格2={second.volume}/静音{second.muted}（房间 {second.room.get('room_id')}）"
          f" 保存值={[slot['volume'] for slot in saved_wall[:2]]}")
    assert str(first.room.get("room_id")) == second_room_id
    assert str(second.room.get("room_id")) == first_room_id
    assert (first.volume, second.volume) == (40, 73), "音量必须留在原格子"
    assert (first.muted, second.muted) == (False, True), "静音状态必须留在原格子"
    assert [slot["muted"] for slot in saved_wall[:2]] == [False, True]
    assert [slot["volume"] for slot in saved_wall[:2]] == [40, 73]
    _, empty_wall = config_module.build_rooms({
        "rooms": [], "wall": [{"room_id": "", "volume": 61, "muted": True}],
    })
    assert empty_wall[0]["volume"] == 61, "空格子的音量也必须在重启后恢复"

    print("\n=== 3e. 交换画面「秒切」：播放器直接搬过去，不重新取流 ===")
    first, second = window.wall.tiles[:2]
    for tile, room_id, uname in ((first, "1001", "主播甲"), (second, "1002", "主播乙")):
        tile.set_room({"room_id": room_id, "uname": uname, "title": "", "live": True,
                       "muted": True, "quality": 250})
        tile.set_video_active(True)
    first.set_volume(41)
    second.set_volume(77)
    first.set_muted(False)
    second.set_muted(True)
    player_a = TilePlayer(first.video, window)
    player_b = TilePlayer(second.video, window)
    for tile, player in ((first, player_a), (second, player_b)):
        window.players[tile] = player
        player.bind()
        player.actual_quality = 400
        player.stream_url = f"https://example.invalid/{tile.room['room_id']}.flv"
        player.stream_profile = "app"
        player.stream_headers = {"User-Agent": "x"}
        tile.stream_url = player.stream_url
    ids = (id(player_a), id(player_b))
    order_before = list(window.wall.tiles)
    moved: list = []                       # 秒切**不该**去搬播放器的原生窗口
    real_move = getattr(TilePlayer, "move_to", None)

    started: list = []
    original_start = window.start_tile
    window.start_tile = lambda target: started.append(target)
    try:
        window._on_tile_swapped("1001", second)          # noqa: SLF001
    finally:
        window.start_tile = original_start
    same_players = (id(player_a), id(player_b)) == ids
    swapped = (window.wall.tiles[0] is second and window.wall.tiles[1] is first)
    print(f"  交换后：第 1 格={window.wall.tiles[0].room.get('room_id')}"
          f" 第 2 格={window.wall.tiles[1].room.get('room_id')}"
          f" 重新取流次数={len(started)} 播放器原样={same_players}")
    print(f"  格子换位置={swapped}（原来是 {[t.room.get('room_id') for t in order_before[:2]]}）")
    players_kept_widgets = (player_a.video_widget is first.video
                            and player_b.video_widget is second.video)
    print(f"  音量/静音按位置下发：甲格={player_a.volume}/{player_a.muted}"
          f" 乙格={player_b.volume}/{player_b.muted}"
          f" 播放器没搬家={players_kept_widgets}")
    print(f"  取流结果跟着画面：格2 url={second.stream_url.rsplit('/', 1)[-1]}"
          f" | move_to 已删除={real_move is None}")
    assert str(first.room.get("room_id")) == "1001"
    assert str(second.room.get("room_id")) == "1002"
    assert window.wall.tiles[0] is second and window.wall.tiles[1] is first, \
        "秒切靠两个格子换位置实现"
    assert same_players, "秒切不许重建播放器"
    assert not started, "秒切不应该重新取流（用户要的就是不黑屏）"
    assert player_a.video_widget is first.video and player_b.video_widget is second.video, \
        "播放器不许换原生窗口（实测 set_hwnd 搬不动画面，还会冒出 VLC 悬浮窗）"
    assert real_move is None, "move_to 那套已经证明不能用，别再出现在代码里"
    assert player_a.volume == 77 and player_a.muted is True, "声音按格子（位置）下发"
    assert player_b.volume == 41 and player_b.muted is False
    assert (first.volume, second.volume) == (77, 41), "音量留在原来的位置上"
    assert first.volume_slider.value() == 77 and first.volume_label.text() == "77", \
        "秒切后音量条要重画：不然显示的数字跟着画面跑、和实际声音对不上"
    assert second.volume_slider.value() == 41 and second.volume_label.text() == "41"
    print(f"  音量条：甲格滑条={first.volume_slider.value()}"
          f" 乙格滑条={second.volume_slider.value()}（跟实际下发一致）")
    assert second.stream_url.endswith("1002.flv"), "取流结果跟着格子一起走"

    print("  迟到的取流结果不能播到已经换台的格子上：")
    stale_before = str(first.stream_url)
    window._play_on(first, "https://example.invalid/stale.flv", 250, "web",
                    room_id="1002")                       # noqa: SLF001
    print(f"    格子上是 1001，塞一个 1002 的取流结果："
          f"{stale_before.rsplit('/', 1)[-1]} → 还是 "
          f"{first.stream_url.rsplit('/', 1)[-1]}")
    assert "stale" not in str(first.stream_url), "不属于这个格子的取流结果必须丢掉"
    player_a.release()
    player_b.release()
    window.players.pop(first, None)
    window.players.pop(second, None)

    print("\n=== 4. 侧栏收起后头像居中、底部还能看到账号 ===")
    sidebar = window.sidebar
    sidebar.set_account("示例主播A")
    item = sidebar.items()[0]
    face_pixmap = QPixmap(64, 64)
    face_pixmap.fill(QColor("#fb7299"))
    cover_pixmap = QPixmap(160, 90)
    cover_pixmap.fill(QColor("#223344"))
    item.thumb.set_face(face_pixmap)
    item.thumb.set_cover(cover_pixmap)
    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.5)
    avatar = item.thumb                    # 条目左边现在是封面缩略图
    left = avatar.x()
    right = item.width() - (avatar.x() + avatar.width())
    print(f"  侧栏宽={sidebar.width()} 卡片宽={item.width()} 头像={avatar.geometry().getRect()}"
          f" 左边距={left} 右边距={right}")
    assert avatar.x() >= 0 and avatar.x() + avatar.width() <= item.width(), "头像不能被裁"
    assert abs(left - right) <= 2, "头像要左右居中"
    assert item.thumb.face.isVisible(), "收起关注栏后必须显示主播头像"
    assert not item.thumb.cover.isVisible(), "收起关注栏后不能继续显示封面缩略图"
    assert item.thumb.face.size() == item.thumb.size(), "收起后的主播头像要占满 32px 方框"
    account = sidebar.account_row
    account_avatar = account.avatar
    acc_left = account_avatar.x()
    acc_right = account.width() - (account_avatar.x() + account_avatar.width())
    print(f"  账号行 可见={account.isVisible()} 收起态={account.width()}x{account.height()}"
          f" 头像={account_avatar.geometry().getRect()} 左边距={acc_left} 右边距={acc_right}")
    assert account.isVisible(), "收起后底部要保留账号头像"
    assert account_avatar.isVisible() and not account.name.isVisible(), "收起后只留头像"
    assert abs(acc_left - acc_right) <= 2, "账号头像要居中"
    assert account_avatar.width() == avatar.width() == theme.AVATAR_SIZE, "账号头像要和主播头像一样大"
    assert account_avatar.x() == avatar.x(), "账号头像的横向位置要和主播头像一致"
    sidebar.set_collapsed(False, animate=False)
    settle(app, 0.5)
    print(f"  展开后卡片宽={item.width()} 头像 x={avatar.x()}（回到左边正常排布）")
    assert avatar.x() <= 12
    assert item.thumb.width() >= 170, "展开后的封面应铺满条目可用宽度"
    assert item.thumb.cover.isVisible(), "展开关注栏后要恢复封面缩略图"
    assert item.thumb.face.width() == item.thumb.AVATAR_SIZE, "展开后恢复封面上的小头像"
    assert item.name_label.parentWidget() is item.thumb
    assert item.sub.parentWidget() is item.thumb
    assert item.badge.parentWidget() is item.thumb, "名字、标题和状态都应叠在封面上"
    assert item.name_label.isVisible() and item.sub.isVisible() and item.badge.isVisible()
    assert account.name.isVisible(), "展开后要恢复昵称"

    # 列表长到必须滚动时，滚动条不能把头像挤歪（上下两排要在同一条竖线上）
    for index in range(12):
        sidebar.add_room({"room_id": f"90{index:02d}", "uname": f"主播{index}", "live": False,
                          "title": "长列表测试"})
    settle(app, 0.5)
    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.5)
    scrollbar = sidebar.scroll.verticalScrollBar()
    items = sidebar.items()
    centers = [entry.thumb.x() + entry.thumb.width() / 2 for entry in items]
    account_center = account_avatar.x() + account_avatar.width() / 2
    print(f"  列表 {len(items)} 项 视口宽={sidebar.scroll.viewport().width()}"
          f" 卡片宽={items[0].width()} 滚动范围={scrollbar.maximum()}"
          f" 滚动条可见={scrollbar.isVisible()}")
    print(f"  列表头像中心={sorted(set(round(value, 1) for value in centers))}"
          f" 账号头像中心={account_center:.1f}")
    assert scrollbar.maximum() > 0, "这个用例要能触发滚动"
    assert len(set(round(value) for value in centers)) == 1, "列表里的头像要在同一条竖线上"
    assert abs(centers[0] - account_center) <= 1, "账号头像要和主播头像对齐"

    # 滚动条藏起来了，滚轮必须还能滚
    viewport = sidebar.scroll.viewport()
    position = viewport.rect().center()
    before = scrollbar.value()
    QApplication.sendEvent(viewport, QWheelEvent(
        QPointF(position), QPointF(viewport.mapToGlobal(position)),
        QPoint(0, -120), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    settle(app, 0.3)
    print(f"  滚轮滚动：{before} -> {scrollbar.value()}")
    assert scrollbar.value() > before, "收起后滚轮还要能滚列表"
    sidebar.set_collapsed(False, animate=False)
    settle(app, 0.4)

    print("\n=== 5. 设置窗口（左侧类别 + 右侧内容）===")
    assert sidebar.settings_button.menu() is None, "设置不该再弹二级菜单"
    dialog = SettingsDialog(window.settings, window.shortcuts)
    pages = [dialog.nav.item(i).text() for i in range(dialog.nav.count())]
    print(f"  左侧类别={pages} 当前页={dialog.stack.currentIndex()}")
    assert pages == ["常规", "弹幕", "录制", "快捷键"] and dialog.stack.currentIndex() == 0
    dialog.nav.setCurrentRow(3)
    assert dialog.stack.currentIndex() == 3
    dialog.nav.setCurrentRow(2)
    assert dialog.stack.currentIndex() == 2
    dialog.nav.setCurrentRow(1)
    assert dialog.stack.currentIndex() == 1, "弹幕页要在中间"
    dialog.nav.setCurrentRow(0)

    general = dialog.general_page
    defaults = dialog.settings()
    print(f"  读到的设置={defaults}")
    assert set(defaults) == set(config_module.DEFAULT_SETTINGS), "设置窗口要覆盖每个设置项"
    for key, value in window.settings.items():
        if key not in defaults or key == "danmaku_font":
            continue      # 字体下拉会把「跟主题走」写成当前字体名，这一项单独看
        assert defaults[key] == value, f"{key} 不该被设置窗口改掉：{defaults[key]!r} != {value!r}"
    assert dialog.shortcuts() == window.shortcuts
    general.poll_spin.setValue(5)
    general._checks["auto_quality"].setChecked(False)     # noqa: SLF001
    general._checks["default_muted"].setChecked(False)    # noqa: SLF001
    general._checks["sidebar_card_mode"].setChecked(False)  # noqa: SLF001
    general._checks["sidebar_auto_compact"].setChecked(True)  # noqa: SLF001
    general.compact_threshold_spin.setValue(12)
    general.volume_slider.setValue(30)
    changed = dialog.settings()
    print(f"  改过之后={changed}")
    assert changed["poll_minutes"] == 5 and changed["auto_quality"] is False
    assert changed["default_volume"] == 30 and changed["default_muted"] is False
    assert changed["sidebar_card_mode"] is False
    assert changed["sidebar_auto_compact"] is True
    assert changed["sidebar_compact_threshold"] == 12

    danmaku_page = dialog.danmaku_page
    danmaku_page.size_spin.setValue(20)
    danmaku_page.keep_spin.setValue(150)
    danmaku_page.block_edit.setPlainText("广告\n\n   \n打卡")
    danmaku_page.font_box.setCurrentFont(QFont("Consolas"))
    changed_danmaku = dialog.settings()
    print(f"  弹幕页：字号={changed_danmaku['danmaku_font_size']}"
          f" 最多保留={changed_danmaku['danmaku_max_blocks']}"
          f" 屏蔽词={changed_danmaku['danmaku_block_words']}"
          f" 字体={changed_danmaku['danmaku_font']!r}")
    assert changed_danmaku["danmaku_font_size"] == 20
    assert changed_danmaku["danmaku_max_blocks"] == 150
    assert changed_danmaku["danmaku_block_words"] == ["广告", "打卡"], "空行要去掉"
    if "Consolas" in QFontDatabase.families():        # 没有字体数据库的环境里跳过
        assert changed_danmaku["danmaku_font"].startswith("Consolas")
    else:
        print("  （这台机器读不到系统字体，字体下拉的断言跳过）")
    changed = changed_danmaku
    dialog.deleteLater()

    print("\n=== 6. 设置真的生效 ===")
    window.settings.update(changed)
    window.state["settings"] = dict(window.settings)
    assert window.poll_interval_ms() == 5 * 60_000
    # 硬件解码开关：关掉时每一路的 media 要带 :avcodec-hw=none（用户那边的
    # libvlc 调用卡 6.5 秒 + 访问违例，第一步就是让他们能一键换成软解）
    from ddm.player import HW_DECODE_OFF_OPTION, PlayerPool
    window.settings["hw_decode"] = True
    print(f"  硬解开：media 选项={window.media_options()}")
    assert window.media_options() == ()
    window.settings["hw_decode"] = False
    print(f"  硬解关：media 选项={window.media_options()}")
    assert window.media_options() == (HW_DECODE_OFF_OPTION,), "关硬解要真的下发软解选项"
    print("  （这条设置也要能从设置窗口里读到）")
    assert "hw_decode" in defaults, "「硬件解码」要出现在常规页里"
    window.settings["hw_decode"] = True
    print(f"  libvlc 预热：同一个实例={PlayerPool.instance() is PlayerPool.instance()}"
          f" 版本={TilePlayer.vlc_version()!r}")
    assert PlayerPool.instance() is PlayerPool.instance(), "预热和正常取用必须是同一个实例"
    assert TilePlayer.vlc_version() not in ("", "?"), "要能读出版本号，日志里好对齐"
    print("  画面墙的播放器不是 silent（只有预览才是）：")
    plain = TilePlayer(QWidget())
    print(f"    silent={plain.silent} muted={plain.muted} volume={plain.volume}")
    assert plain.silent is False and plain.muted is False and plain.volume == 42
    plain.release()
    calls: list = []
    original = window.apply_quality_policy
    window.apply_quality_policy()
    print(f"  关掉主画面自动原画后：格子画质仍然={[t.quality for t in window.wall.tiles]}")
    assert window.settings["auto_quality"] is False
    window.settings["auto_reconnect"] = False
    window._schedule_retry(window.wall.tiles[0])          # noqa: SLF001
    print(f"  关掉自动重连后状态={window.wall.tiles[0].status_label.text()!r}"
          f" 有重连定时器={'有' if window.wall.tiles[0] in window._retry_timers else '没有'}")
    assert "自动重连已关闭" in window.wall.tiles[0].status_label.text()
    assert window.wall.tiles[0] not in window._retry_timers
    window._prepare_room({"room_id": "9999", "uname": "新房间"})   # noqa: SLF001
    room = {"room_id": "9999"}
    window._prepare_room(room)                             # noqa: SLF001
    print(f"  新房间默认: muted={room['muted']} volume={room['volume']}")
    assert room["muted"] is False and room["volume"] == 30

    window.apply_preview_settings()
    print(f"  关注列表模式：{'大卡片' if sidebar.card_mode else '头像＋文字'}")
    assert sidebar.card_mode is False
    window.settings["sidebar_card_mode"] = True
    window.settings["sidebar_auto_compact"] = True
    window.settings["sidebar_compact_threshold"] = len(sidebar.items())
    window.apply_preview_settings()
    assert sidebar.card_mode is False, "达到阈值时应自动使用紧凑列表"
    window.settings["sidebar_compact_threshold"] = len(sidebar.items()) + 1
    window.apply_preview_settings()
    assert sidebar.card_mode is True, "阈值调高后应恢复用户选择的大卡片"
    window.settings["sidebar_auto_compact"] = False
    window.settings["sidebar_compact_threshold"] = 2
    window.apply_preview_settings()
    assert sidebar.card_mode is True, "关闭自动切换后不应受阈值影响"

    window.apply_danmaku_settings()
    panel = window.wall.danmaku
    print(f"  弹幕面板：字号={panel._base_size} 滑块={panel.font_slider.value()}"
          f" 字体={panel._font_family!r}")
    assert panel._base_size == 20 and panel.font_slider.value() == 20
    assert window._danmaku_blocked("我要发广告了") is True      # noqa: SLF001
    assert window._danmaku_blocked("正常的弹幕") is False       # noqa: SLF001

    print("\n=== 7. 弹幕字号滑块（在面板上实时改）===")
    panel.font_slider.setValue(24)
    settle(app, 0.3)
    print(f"  拖到 24：面板字号={panel._base_size} 标签={panel.font_value.text()!r}"
          f" 设置里={window.settings['danmaku_font_size']}")
    assert panel._base_size == 24 and panel.font_value.text() == "24"
    assert window.settings["danmaku_font_size"] == 24, "拖滑块要同步进设置"

    print("\n=== 8. 关注列表排序 ===")
    sidebar.set_sort_mode("live", notify=False)
    settle(app, 0.3)
    lives = [bool(item.room.get("live")) for item in sidebar.items()]
    print(f"  开播优先：前 4 项={'直播' if lives[0] else '未开播'}…"
          f"（共 {sum(lives)} 个直播中）")
    assert lives == sorted(lives, reverse=True), "开播的要排在前面"
    assert sidebar.sort_mode == "live"

    sidebar.set_sort_mode("imported", notify=False)
    settle(app, 0.3)
    order = [str(item.room.get("room_id")) for item in sidebar.items()]
    pinned_ids = list(sidebar.pinned)
    expected = pinned_ids + [room_id for room_id in sidebar.import_order
                             if room_id not in pinned_ids]
    print(f"  导入顺序：前 4 项={order[:4]} 置顶={pinned_ids} 记录数={len(sidebar.import_order)}")
    assert order == expected, "导入顺序要按加入的先后"

    sidebar.set_sort_mode("custom", notify=False)
    settle(app, 0.3)
    print(f"  自定义：保持当前顺序（{len(sidebar.items())} 项）")

    print("\n=== 9. 快捷键：M 静音这一路，Alt+M 只留这一路 ===")
    print(f"  默认值：mute={window.shortcuts.get('mute')!r} "
          f"solo={window.shortcuts.get('solo')!r}")
    assert window.shortcuts.get("mute") == "M", "静音当前窗口的默认键是 M"
    assert window.shortcuts.get("solo") == "Alt+M", "只留这一路的默认键要让给 Alt+M"
    dialog = SettingsDialog(window.settings, window.shortcuts)
    edits = dialog.shortcut_page._edits                      # noqa: SLF001
    print(f"  设置窗口里读到：mute={edits['mute'].keySequence().toString()!r} "
          f"solo={edits['solo'].keySequence().toString()!r}")
    assert edits["mute"].keySequence().toString() == "M"
    assert edits["solo"].keySequence().toString() == "Alt+M"

    target, other = window.wall.tiles[0], window.wall.tiles[1]
    target.set_muted(False)
    other.set_muted(True)

    def press(key, modifiers=Qt.NoModifier):
        QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, key, modifiers))

    with mock.patch.object(window, "_tile_under_cursor", return_value=target):
        press(Qt.Key_M)
        print(f"  按 M：这一路 muted={target.muted}（别的路 muted={other.muted}）")
        assert target.muted is True and other.muted is True, "M 只动鼠标下那一路"
        press(Qt.Key_M)
        assert target.muted is False, "再按一次 M 要取消静音"
        press(Qt.Key_M, Qt.AltModifier)
        print(f"  按 Alt+M：这一路 muted={target.muted} 别的路 muted={other.muted}")
        assert target.muted is False, "Alt+M 要让鼠标下那一路出声"
        assert other.muted is True, "Alt+M 要把别的路静音"
        other.set_muted(False)
        press(Qt.Key_M, Qt.AltModifier)
        assert other.muted is True, "Alt+M 每次都要把别的路压成静音"
    # 鼠标不在任何格子上：Alt+M 等于「全部静音」
    with mock.patch.object(window, "_tile_under_cursor", return_value=None):
        target.set_muted(False)
        other.set_muted(False)
        press(Qt.Key_M, Qt.AltModifier)
        print(f"  鼠标不在画面上按 Alt+M：全静音={target.muted and other.muted}")
        assert target.muted is True and other.muted is True

    print("\n=== 9b. 鼠标压在画面上时，也要认得出是哪一格 ===")
    # 画面区是 VLC 的原生窗口，不是 Qt 控件：以前用 QApplication.widgetAt 找格子，
    # 鼠标停在画面上时它给回主窗口，F / M / Alt+M 就全按不动（用户报「切换画布失效」）。
    from PySide6.QtCore import QPoint as _QPoint
    window.resize(1200, 700)
    settle(app, 0.4)
    for index, tile in enumerate(window.wall.tiles[:2]):
        tile.set_room({"room_id": f"77{index}", "uname": f"格子{index}",
                       "title": "", "live": True, "muted": True, "quality": 250})
    settle(app, 0.4)

    class FakeCursor:
        point = _QPoint(0, 0)

        @classmethod
        def pos(cls):
            return cls.point

    with mock.patch.object(app_module, "QCursor", FakeCursor), \
            mock.patch.object(QApplication, "widgetAt",
                              side_effect=AssertionError("不许再靠 widgetAt 找格子")):
        hits = []
        for index, tile in enumerate(window.wall.tiles[:2]):
            # 取画面区正中（不是信息条）：以前正是这个位置认不出来
            local = _QPoint(tile.video.width() // 2, tile.video.height() // 2)
            FakeCursor.point = tile.video.mapToGlobal(local)
            found = window._tile_under_cursor()                 # noqa: SLF001
            hits.append(found is tile)
            print(f"  光标在格{index + 1}画面上：认出来={found is tile}"
                  f" 房间={getattr(getattr(found, 'room', {}), 'get', lambda *_: '')('room_id')}")
        assert all(hits), "鼠标压在画面上时必须认出对应格子"
        FakeCursor.point = _QPoint(-5000, -5000)
        print(f"  光标在窗口外：{window._tile_under_cursor()}（应该是 None）")   # noqa: SLF001
        assert window._tile_under_cursor() is None                   # noqa: SLF001

    window.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
