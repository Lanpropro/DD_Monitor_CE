"""自查：暂停图形按钮、标题浮窗、关注列表刷新图标、弹幕独立格（含拖动）。全程不联网。"""
import os
import sys
import time

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, images, layouts, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def boom(room_id, quality=250):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


def fake_status(room_ids):             # noqa: ANN001, ANN201
    time.sleep(0.5)                    # 慢一点，方便看按钮的刷新中状态
    return {}


def fake_pixmap(url):                  # noqa: ANN001, ANN201
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#3b6ea5"))
    return pixmap


ROOMS = [
    {"room_id": "1001", "uname": "主播A", "title": "房间A的直播标题", "live": True,
     "viewers": "1.2万", "muted": True, "quality": 250, "face": "http://x/a.jpg"},
    {"room_id": "1002", "uname": "主播B", "title": "房间B的直播标题", "live": True,
     "viewers": "3456", "muted": True, "quality": 250, "face": "http://x/b.jpg"},
    {"room_id": "1003", "uname": "主播C", "title": "房间C的直播标题", "live": True,
     "viewers": "78", "muted": True, "quality": 250, "face": "http://x/c.jpg"},
]


class FakePlayer:
    def __init__(self):
        self.paused = False
        self.calls = []

    def set_paused(self, paused):
        self.paused = bool(paused)
        self.calls.append(bool(paused))

    def release(self):
        pass


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
    bili.rooms_status = fake_status
    images.load_pixmap = fake_pixmap

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = MainWindow([dict(room) for room in ROOMS], [dict(room) for room in ROOMS],
                        layout_id="dm_main3")
    window.setGeometry(-8000, -8000, 1500, 860)
    window.show()
    settle(app, 1.5)

    print("=== 1. 带弹幕布局：弹幕占独立一格，不挤压画面 ===")
    print(f"  布局={window.wall.layout_id} 弹幕格={window.wall.danmaku_geometry_cell()}"
          f" 可见={window.wall.danmaku.isVisible()}")
    print(f"  画面路数={len(window.wall.tiles)}（布局格子总数=4）")
    for index, tile in enumerate(window.wall.tiles):
        print(f"  画面{index} cell={window.wall.cell_of(tile)} 视频宽={tile.video.width()}"
              f" 格宽={tile.width()}")
    assert window.wall.danmaku.isVisible()
    assert len(window.wall.tiles) == 3, "主画面 + 2 小 + 弹幕 = 3 路画面"
    main_tile = window.wall.tiles[0]
    assert main_tile.video.width() >= main_tile.width() - 2, "画面不应该被弹幕挤窄"

    print("\n=== 2. 弹幕格可以拖动换位 ===")
    before_danmaku = window.wall.danmaku_geometry_cell()
    before_cells = [window.wall.cell_of(tile) for tile in window.wall.tiles]
    target = window.wall.tiles[2]
    window.wall.move_danmaku_to_tile(target)
    settle(app, 0.3)
    after_danmaku = window.wall.danmaku_geometry_cell()
    after_cells = [window.wall.cell_of(tile) for tile in window.wall.tiles]
    print(f"  弹幕格：{before_danmaku} -> {after_danmaku}")
    print(f"  画面格：{before_cells} -> {after_cells}")
    assert after_danmaku == before_cells[2], "弹幕应该挪到被拖过去的那一格"
    assert after_cells[2] == before_danmaku, "那一路应该挪到弹幕原来的位置"
    assert [c for c in after_cells if c is not None] == sorted(after_cells, key=lambda c: (c[0], c[1]))

    print("\n=== 3. 普通布局没有弹幕格 ===")
    window.wall.set_layout("2x2")
    settle(app, 0.3)
    print(f"  2x2: 弹幕可见={window.wall.danmaku.isVisible()}"
          f" 画面路数={len(window.wall.tiles)}")
    assert not window.wall.danmaku.isVisible()
    assert len(window.wall.tiles) == 4
    window.wall.set_layout("dm_main3")
    settle(app, 0.3)

    print("\n=== 4. 暂停按钮（图形按钮 + 左下角） ===")
    tile = window.wall.tiles[0]
    assert tile.volume_button.objectName() == "BiliVolumeButton", "音量按钮应使用独立的 B 站风格外观"
    fake = FakePlayer()
    window.players[tile] = fake
    tile._player_active = True
    window._on_pause_toggled(tile.room)
    settle(app, 0.2)
    print(f"  点击后：paused={tile.paused} 按钮图标状态={tile.pause_button.paused}"
          f" 提示={tile.pause_button.toolTip()!r} 播放器={fake.calls}")
    assert tile.paused and tile.pause_button.paused and fake.calls == [True]
    window._on_pause_toggled(tile.room)
    settle(app, 0.2)
    print(f"  再点击：paused={tile.paused} 按钮图标状态={tile.pause_button.paused}"
          f" 提示={tile.pause_button.toolTip()!r}")
    assert not tile.paused and fake.calls == [True, False]
    bottom = tile.pause_button.geometry()
    print(f"  位置：x={bottom.x()} y={bottom.y()} 信息条高={tile.bottom.height()}"
          f" 是否在信息条里={tile.pause_button.parent() is tile.bottom}"
          f" 是否贴左={bottom.x() <= 12}")
    assert tile.pause_button.parent() is tile.bottom and bottom.x() <= 12

    print("\n=== 5. 主播名 + 直播间标题变成 LIVE 右侧的浮窗 ===")
    badge = tile.title_badge
    print(f"  可见={badge.isVisible()} 位置=({badge.x()},{badge.y()})"
          f" 宽度={badge.width()} LIVE 浮标宽={tile.stream_badge.width()}")
    print(f"  文本={badge._name_text!r} + {badge._title_text!r}")
    assert badge.isVisible()
    assert badge.x() > tile.stream_badge.x() + tile.stream_badge.width() - 2
    assert badge.y() < 40, "应该浮在画面上方"
    assert badge._name_text and badge._title_text

    print("\n=== 6. 右上角控制区只保留圆角按钮，横向划过能稳定高亮 ===")
    tile.set_controls_visible(True)
    tile._layout_controls()
    controls_mask = tile.controls.mask()
    buttons = (tile.quality_button, tile.reload_button, tile.close_button)
    centres = [button.geometry().center() for button in buttons]
    gap = QPoint((buttons[0].geometry().right() + buttons[1].geometry().left()) // 2,
                 buttons[0].geometry().center().y())
    print(f"  控制区遮罩为空={controls_mask.isEmpty()} 按钮中心="
          f"{[controls_mask.contains(point) for point in centres]}"
          f" 按钮间隙={controls_mask.contains(gap)}")
    assert not controls_mask.isEmpty()
    assert all(controls_mask.contains(point) for point in centres)
    assert not controls_mask.contains(gap), "按钮间隙不能残留矩形黑底"
    geometries = [button.geometry() for button in buttons]
    print(f"  按钮坐标={[rect.getRect() for rect in geometries]}")
    assert len({rect.y() for rect in geometries}) == 1, "三个按钮应在同一水平线上"
    assert all(rect.top() >= 0 and rect.bottom() < tile.controls.height()
               for rect in geometries), "按钮不能超出控制区"
    assert all(geometries[index + 1].left() - geometries[index].right() - 1 == 6
               for index in range(len(geometries) - 1)), "按钮间距应稳定为 6px"

    # 「×」宽度曾经被样式表的 min-width + padding 撑到和画质按钮一样宽（81px），
    # 整条控制条看起来就是错位的。现在宽度由代码算好，必须是个方钮。
    print(f"  按钮宽度：画质={tile.quality_button.width()} "
          f"刷新={tile.reload_button.width()} 关闭={tile.close_button.width()}")
    assert tile.close_button.width() == theme.TILE_CONTROL_HEIGHT, \
        f"关闭按钮应是 {theme.TILE_CONTROL_HEIGHT}px 的方钮，实际 {tile.close_button.width()}px"
    assert tile.close_button.height() == theme.TILE_CONTROL_HEIGHT
    assert tile.close_button.width() != tile.quality_button.width() or \
        tile.quality_button.text() == "×", "关闭按钮不该被撑成画质按钮那么宽"
    assert tile.quality_button.width() == tile._quality_button_width(), \
        "画质按钮宽度应该正好按文本算出来"
    assert tile.quality_button.width() > theme.TILE_CONTROL_HEIGHT, \
        "画质按钮要比方钮宽，才放得下档位文字"
    # 再调一次布局，宽度必须完全不变（这是原来「hover 之后错位」的可测形式）
    widths_before = [button.width() for button in buttons]
    tile._layout_controls()
    settle(app, 0.2)
    widths_after = [button.width() for button in buttons]
    print(f"  重排前后宽度：{widths_before} -> {widths_after}")
    assert widths_before == widths_after, "重复布局不能让控制按钮宽度变化"
    assert all(tile.controls.mask().contains(button.geometry()) for button in buttons), \
        "重排后遮罩仍要覆盖三个按钮"
    for button in buttons:
        tile._sync_control_hover(button.mapToGlobal(button.rect().center()))
        states = [candidate.property("hovered") is True for candidate in buttons]
        print(f"  划过 {button.toolTip()}：{states}")
        assert states == [candidate is button for candidate in buttons]
        assert [candidate.width() for candidate in buttons] == widths_before, \
            "悬停不能改变按钮宽度"
    tile.set_controls_visible(False)

    print("\n=== 7. 关注列表刷新按钮是图形按钮 ===")
    button = window.sidebar.refresh_button
    print(f"  类型={type(button).__name__} 文案={button.text()!r}"
          f" 尺寸={button.width()}x{button.height()}")
    assert type(button).__name__ == "RefreshButton"
    button.click()
    settle(app, 0.2)
    print(f"  点击后可用={button.isEnabled()} 提示={button.toolTip()!r}")
    assert not button.isEnabled()
    settle(app, 1.5)
    print(f"  刷新完成：可用={button.isEnabled()} 提示={button.toolTip()!r}")
    assert button.isEnabled()

    print("\n=== 8. 布局菜单分组 ===")
    for name, group in layouts.GROUPS:
        print(f"  {name}: {len(group)} 个 -> "
              + " / ".join(item["name"] for item in group[:3]) + " …")
    assert len(layouts.GROUPS) == 2
    for item in layouts.DANMAKU_LAYOUTS:
        assert item["danmaku"] is not None
        assert "danmaku" not in layouts.LAYOUTS[0]
        cells = item["spec"][2]
        assert 0 <= item["danmaku"] < len(cells)
    print(f"  带弹幕布局的规格都合法（{len(layouts.DANMAKU_LAYOUTS)} 个）")

    window.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
