"""自查：音量按钮的静音 ×、L/R 声道标记，以及收起侧栏后点头像的入口。

音乐/网络都不需要，只渲染控件与检查菜单项。不联网。
"""
import os
import sys
import time

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

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
    assert "仅左声道" not in button.toolTip() and "仅右声道" not in button.toolTip()
    print(f"  静音提示={button.toolTip()!r}")

    print("\n=== 2. L / R 标记与提示同步 ===")
    for value, expect in ((0, None), (VolumeButton.CHANNEL_LEFT, "仅左声道"),
                          (VolumeButton.CHANNEL_RIGHT, "仅右声道")):
        button.set_state(False, 42, value)
        settle(app, 0.15)
        tip = button.toolTip()
        print(f"  audio_channel={value} 提示={tip!r}")
        if expect is None:
            assert "仅左声道" not in tip and "仅右声道" not in tip
        else:
            assert expect in tip, f"{value} 的提示里应该有「{expect}」"
    # 三种状态都要画得出来（不抛异常）且有内容
    for value in (0, VolumeButton.CHANNEL_LEFT, VolumeButton.CHANNEL_RIGHT):
        button.set_state(False, 42, value)
        settle(app, 0.15)
        assert count_icon_pixels(button.grab().toImage()) > 40, f"声道 {value} 应该画得出图标"

    print("\n=== 3. 右键菜单三个声道选项 ===")
    from ddm import bili
    bili.play_url = lambda room_id, quality=250: (_ for _ in ()).throw(
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

        def set_audio_channel(self, value):
            self.calls.append(("set", int(value)))

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
    del window.players[tile]

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

    print("\n=== 8. 收起时布局选择器从头像位置弹出 ===")
    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.3)
    sidebar.open_layout_picker()
    settle(app, 0.3)
    picker = sidebar._picker
    avatar_right = sidebar.account_row.mapToGlobal(
        QPoint(sidebar.account_row.width(), 0)).x()
    print(f"  选择器位置=({picker.x()},{picker.y()}) 头像右边缘x={avatar_right} "
          f"可见={picker.isVisible()}")
    assert picker.isVisible()
    assert picker.x() > avatar_right, "收起时选择器应该在头像右边弹出来，不能压住头像"
    picker.close()

    window.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
