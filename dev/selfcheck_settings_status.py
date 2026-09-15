"""自查：人数占位、卡顿/状态提示、侧栏收起头像居中、设置菜单与全局设置。不联网。"""
import os
import sys
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QWidget

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, config as config_module, theme  # noqa: E402
from ddm import app as app_module              # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import SettingsDialog  # noqa: E402
from ddm.player import TilePlayer  # noqa: E402


def boom(room_id, quality=250):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


class SilentPoller(QThread):
    """自检里别真的轮询：有网络时假的房间号会被查成"未开播"，把断言搞乱。"""

    updated = Signal(dict)

    def run(self) -> None:
        return


ROOMS = [
    {"room_id": "1001", "uname": "Asaki大人", "title": "随便玩玩战狗", "live": True,
     "viewers": "3.1万", "muted": True, "quality": 250},
    {"room_id": "1002", "uname": "七海Nana7mi", "title": "和队友最后练一次大米", "live": True,
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
    results = [tp._check_picture(True) for _ in range(6)]
    print(f"  连续 6 次相同画面 -> 判定卡住: {results}")
    assert results[:4] == [False] * 4 and results[-1] is True
    tp._picture_signature = lambda: (time.time(), "changing")   # 画面在变
    print(f"  画面恢复变化 -> {tp._check_picture(True)}")
    assert tp._check_picture(True) is False
    tp.freeze_watch = False
    tp._picture_signature = lambda: (1, "same")
    assert [tp._check_picture(True) for _ in range(6)] == [False] * 6
    print("  关掉检测后不再判定")

    print("\n=== 4. 侧栏收起后头像居中、底部还能看到账号 ===")
    sidebar = window.sidebar
    sidebar.set_account("Asaki大人")
    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.5)
    item = sidebar.items()[0]
    avatar = item.avatar
    left = avatar.x()
    right = item.width() - (avatar.x() + avatar.width())
    print(f"  侧栏宽={sidebar.width()} 卡片宽={item.width()} 头像={avatar.geometry().getRect()}"
          f" 左边距={left} 右边距={right}")
    assert avatar.x() >= 0 and avatar.x() + avatar.width() <= item.width(), "头像不能被裁"
    assert abs(left - right) <= 2, "头像要左右居中"
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
    centers = [entry.avatar.x() + entry.avatar.width() / 2 for entry in items]
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
    assert pages == ["常规", "弹幕", "快捷键"] and dialog.stack.currentIndex() == 0
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
    general.volume_slider.setValue(30)
    changed = dialog.settings()
    print(f"  改过之后={changed}")
    assert changed["poll_minutes"] == 5 and changed["auto_quality"] is False
    assert changed["default_volume"] == 30 and changed["default_muted"] is False

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

    window.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
