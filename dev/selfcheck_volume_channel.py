"""自查：音量按钮的静音 ×、L/R 声道标记，以及收起侧栏后点头像的入口。

音乐/网络都不需要，只渲染控件与检查菜单项。不联网。
"""
import os
import sys
import time

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import VolumeButton  # noqa: E402

ROOMS = [
    {"room_id": "7001", "uname": "主播甲", "title": "房间甲", "live": True,
     "muted": True, "volume": 42, "quality": 250},
    {"room_id": "7002", "uname": "主播乙", "title": "房间乙", "live": True,
     "muted": True, "volume": 42, "quality": 250},
]


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def count_icon_pixels(image):
    """数一下「画出来」的像素（非透明、非纯背景），用来判断图标有没有内容。"""
    hits = 0
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() > 40 and (colour.red() + colour.green() + colour.blue()) > 60:
                hits += 1
    return hits


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    print("=== 1. 音量按钮：静音是喇叭右边一个 ×，不是划掉整只喇叭 ===")
    button = VolumeButton(size=26)
    button.resize(button.width(), button.height())
    button.show()
    settle(app, 0.3)
    button.set_state(False, 42, 0)
    settle(app, 0.2)
    normal = count_icon_pixels(button.grab().toImage())
    button.set_state(True, 0, 0)
    settle(app, 0.2)
    muted = count_icon_pixels(button.grab().toImage())
    print(f"  未静音图标像素={normal} 静音图标像素={muted} 按钮宽={button.width()}")
    assert normal > 40, "未静音时应该有喇叭图标"
    assert muted > 40, "静音时应该有喇叭 + ×"
    assert "声道：左" not in button.toolTip() and "声道：右" not in button.toolTip()
    print(f"  静音提示={button.toolTip()!r}")

    print("\n=== 2. L / R 标记与提示同步 ===")
    # 提示只说「当前选的是哪一路」，不宣称「已经只出这一路」：这台机器上
    # VLC 的声道模式还没确认生效，别让提示替它打包票。
    for value, expect in ((0, None), (VolumeButton.CHANNEL_LEFT, "声道：左"),
                          (VolumeButton.CHANNEL_RIGHT, "声道：右")):
        button.set_state(False, 42, value)
        settle(app, 0.15)
        tip = button.toolTip()
        print(f"  audio_channel={value} 提示={tip!r}")
        if expect is None:
            assert "声道：左" not in tip and "声道：右" not in tip
        else:
            assert expect in tip, f"{value} 的提示里应该有「{expect}」"
    # 三种状态都要画得出来（不抛异常）且有内容
    for value in (0, VolumeButton.CHANNEL_LEFT, VolumeButton.CHANNEL_RIGHT):
        button.set_state(False, 42, value)
        settle(app, 0.15)
        assert count_icon_pixels(button.grab().toImage()) > 40, f"声道 {value} 应该画得出图标"

    print("\n=== 3. 右键菜单三个声道选项 ===")
    from ddm import bili
    bili.play_url = lambda room_id, quality=250, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("selfcheck：不联网"))
    window = MainWindow([dict(r) for r in ROOMS], [dict(r) for r in ROOMS], layout_id="1x2")
    window.setGeometry(-8000, -8000, 1000, 620)
    window.show()
    settle(app, 1.2)
    tile = window.wall.tiles[0]
    menu = tile.build_menu()
    audio_menu = next((a.menu() for a in menu.actions() if a.menu() is not None
                       and "声道" in a.text()), None)
    assert audio_menu is not None, "右键菜单里应该有「声道」子菜单"
    entries = [a.text() for a in audio_menu.actions()]
    print(f"  声道菜单: {entries}")
    assert entries == ["默认（跟随片源）", "只播左声道", "只播右声道",
                       "反向立体声", "杜比音效"], entries

    print("\n=== 4. 切声道写回格子，并在播放中重新下发 ===")
    class StubPlayer:
        """不联网时格子拿不到真播放器，这里塞一个替身，只记录调用。"""

        def __init__(self):
            self.calls: list = []
            self.restart = False

        def set_audio_channel(self, value):
            self.calls.append(("set", int(value)))

        def needs_audio_restart(self, _value):
            return self.restart

        def reapply_audio_channel(self):
            self.calls.append(("reapply",))

    stub = StubPlayer()
    window.players[tile] = stub
    tile.set_audio_channel(VolumeButton.CHANNEL_LEFT)
    settle(app, 0.3)
    print(f"  tile.audio_channel={tile.audio_channel} room={tile.room.get('audio_channel')} "
          f"按钮={tile.volume_button.audio_channel} 播放器调用={stub.calls}")
    assert tile.audio_channel == VolumeButton.CHANNEL_LEFT
    assert tile.room.get("audio_channel") == VolumeButton.CHANNEL_LEFT, "要写回 room，才能持久化"
    assert tile.volume_button.audio_channel == VolumeButton.CHANNEL_LEFT, "按钮要跟着显示 L/R"
    assert ("set", VolumeButton.CHANNEL_LEFT) in stub.calls, "要把声道下发给播放器"
    assert ("reapply",) in stub.calls, \
        "设置之后还要再下发一次（play() 之前的设置会被音频输出模块初始化冲掉）"

    print("\n=== 4b. 原生输出与左右路由之间切换要安全重启该格 ===")
    stopped = []
    restarted = []
    original_stop = window._stop_tile  # noqa: SLF001
    original_start = window.start_tile
    window._stop_tile = lambda item: stopped.append(item)  # noqa: SLF001
    window.start_tile = lambda item: restarted.append(item)
    stub.restart = True
    stub.calls.clear()
    tile.set_audio_channel(0)
    settle(app, 0.2)
    print(f"  停止={len(stopped)} 重启={len(restarted)} 旧播放器调用={stub.calls}")
    assert stopped == [tile] and restarted == [tile], \
        "切换音频输出路径时必须重建该格播放器"
    assert stub.calls == [], "不能在运行中的旧播放器上硬换 audio callbacks"
    window._stop_tile = original_stop  # noqa: SLF001
    window.start_tile = original_start
    del window.players[tile]

    print("\n=== 4c. 音频输出起来之后再补一次静音/音量（预览会出声的那个坑）===")
    from ddm.player import TilePlayer

    class FakeVlc:
        """替身播放器：只回答「音频输出起来没有」，并记录静音/音量下发。"""

        def __init__(self, tracks: int = 0):
            self.calls: list = []
            self.tracks = tracks

        def audio_get_track_count(self):
            return self.tracks

        def audio_set_mute(self, muted):
            self.calls.append(("mute", bool(muted)))

        def audio_set_volume(self, volume):
            self.calls.append(("volume", int(volume)))

        def set_hwnd(self, _hwnd):
            pass

        def set_media(self, _media):
            pass

        def play(self):
            pass

    holder = TilePlayer(QWidget())
    real_player = holder.player
    fake = FakeVlc(tracks=0)
    holder.player = fake
    holder.set_muted(True)          # 预览：永远静音
    holder.set_volume(0)
    fake.calls.clear()
    holder._audio_ready = False      # noqa: SLF001
    holder._ensure_audio_settings()  # noqa: SLF001
    print(f"  aout 还没起来：{fake.calls}（应该什么都不下发）")
    assert fake.calls == [] and holder._audio_ready is False      # noqa: SLF001

    fake.tracks = 2                  # 音轨出来了 = aout 建好了
    holder._ensure_audio_settings()  # noqa: SLF001
    print(f"  aout 起来之后：{fake.calls}")
    assert ("mute", True) in fake.calls and ("volume", 0) in fake.calls, \
        "aout 起来之后要补静音/音量，否则预览第二次起会带着 42 的音量出声"
    assert holder._audio_ready is True                            # noqa: SLF001

    fake.calls.clear()
    holder._ensure_audio_settings()  # noqa: SLF001
    print(f"  再补一次：{fake.calls}（每次播放只补一次，不刷调用）")
    assert fake.calls == []

    print("\n=== 4d. 静音的格子：光靠 mute 不保险，音量也压到 0 ===")
    holder.set_volume(42)
    fake.calls.clear()
    holder.set_muted(True)
    print(f"  静音时下发：{fake.calls}")
    assert ("mute", True) in fake.calls and ("volume", 0) in fake.calls, \
        "静音要同时把音量压到 0：个别机器上 audio_set_mute 不生效，静音的格子照样出声"
    fake.calls.clear()
    holder.set_muted(False)
    print(f"  取消静音：{fake.calls}")
    assert ("mute", False) in fake.calls and ("volume", 75) in fake.calls, \
        "取消静音要把用户音量恢复回去（42 先立方根成 75 抵消 VLC 三次方，不能停在 0）"

    holder.play("https://example.invalid/x.flv")     # 重新播放要重新补
    print(f"  play() 之后：_audio_ready={holder._audio_ready}")    # noqa: SLF001
    assert holder._audio_ready is False                            # noqa: SLF001
    holder._watch.stop()             # noqa: SLF001
    holder._picture_watch.stop()     # noqa: SLF001
    holder.player = real_player
    holder.release()

    print("\n=== 5. 声道随配置保存 / 恢复 ===")
    state = {"version": 1, "rooms": ["7001"], "wall": [
        {"room_id": "7001", "muted": True, "volume": 42, "quality": 250,
         "audio_channel": VolumeButton.CHANNEL_RIGHT}]}
    from ddm import config as config_module
    _, wall = config_module.build_rooms(state)
    print(f"  读回 audio_channel={wall[0].get('audio_channel')}")
    assert wall[0].get("audio_channel") == VolumeButton.CHANNEL_RIGHT, "声道要能从配置恢复"

    print("\n=== 6. 收起侧栏后点头像：菜单里有布局预设和设置 ===")
    sidebar = window.sidebar
    sidebar.set_account("测试账号")
    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.4)
    print(f"  收起={sidebar.collapsed} 工具行可见={sidebar.tool_row.isVisible()} "
          f"头像可见={sidebar.account_row.isVisible()}")
    assert sidebar.collapsed
    assert not sidebar.tool_row.isVisible(), "收起后布局/设置按钮本来是藏起来的"

    # 菜单构造单独抽成了 account_menu()，自检直接取内容（exec 一弹就是模态）
    shrunk = sidebar.account_menu()
    texts = [a.text() for a in shrunk.actions() if a.text()]
    print(f"  收起时菜单项: {texts}")
    assert "退出登录" in texts
    assert "布局预设…" in texts, "收起后要点得到布局预设"
    assert "设置…" in texts, "收起后要点得到设置"

    print("\n=== 7. 展开时菜单不塞这两个入口（按钮本来就在） ===")
    sidebar.set_collapsed(False, animate=False)
    settle(app, 0.4)
    texts = [a.text() for a in sidebar.account_menu().actions() if a.text()]
    print(f"  展开时菜单项: {texts}")
    assert texts == ["退出登录"], texts

    print("\n=== 8. 收起时布局选择器从头像位置弹出，且一定落在屏幕里 ===")
    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.3)
    sidebar.open_layout_picker()
    settle(app, 0.3)
    picker = sidebar._picker
    rect = picker.frameGeometry()
    screen = (QApplication.screenAt(rect.center())
              or QApplication.screenAt(QCursor.pos())
              or QApplication.primaryScreen())
    area = screen.availableGeometry() if screen is not None else QRect()
    print(f"  选择器={rect.getRect()} 可见={picker.isVisible()} 屏幕可用区域={area.getRect()}")
    assert picker.isVisible()
    # 关键不变量：它必须完全落在某个屏幕的可用区域内。
    # （不要拿「头像右边缘」比大小：窗口被摆到屏幕外做离屏测试时，
    #   头像坐标和屏幕坐标根本不是一个坐标系，比出来没有意义。）
    if area.isValid():
        assert rect.left() >= area.left() and rect.right() <= area.right(), \
            f"选择器横向超出屏幕：{rect.getRect()} vs {area.getRect()}"
        assert rect.top() >= area.top() and rect.bottom() <= area.bottom(), \
            f"选择器纵向超出屏幕：{rect.getRect()} vs {area.getRect()}"
    picker.close()

    window.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
