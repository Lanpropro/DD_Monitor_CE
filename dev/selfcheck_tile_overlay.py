"""回归自检：竖屏窄格子里，浮层不许错位。

用户截图报的：竖屏下「超清」画质按钮跑到格子中间，还压在画面中间的
状态文字（「连接失败」）上。

根因：`_layout_areas()` 以前在「LIVE 浮标 + 控制条」放不下第一行时，会把控制条
**折到第二行**（y = 8 + BADGE_HEIGHT + 6 = 38）。竖屏小格子普遍 282 宽，必然
触发：按钮跑出了右上角，还压住画面中间的封面文字。而且判定浮标要不要收窄时
只算了浮标自己（`width < full_width() + 20`），**没把控制条算进去**，所以明明
两者加起来放不下，却判定成放得下。

现在反过来：控制条永远钉在右上角，空间不够让**浮标**让位（先收起人数，再整个
收起）。这里钉住三件事：
  1. 控制条始终贴在格子右上角（y 就是那条固定的上边距）；
  2. 控制条不压底部信息条、也不横向溢出格子；
  3. 浮标露出来的时候，它和控制条不重叠（横向留缝隙）。
"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [{"room_id": f"95{index:02d}", "uname": f"主播{index}", "title": f"标题{index}",
          "live": True, "muted": True, "volume": 40, "quality": 250}
         for index in range(1, 9)]
LAYOUTS = ("portrait_main6", "portrait_main2", "portrait_dm6")


def settle(app, seconds: float = 0.4) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    checked = 0
    for layout_id in LAYOUTS:
        window = MainWindow([dict(room) for room in ROOMS],
                            [dict(room) for room in ROOMS],
                            layout_id=layout_id, state={})
        window.setGeometry(-9000, -9000, 520, 1000)
        window.show()
        settle(app, 0.5)
        try:
            assert window.orientation == "portrait", \
                f"{layout_id}: 520x1000 该判成竖屏，实际 {window.orientation}"
            print(f"\n=== {layout_id}　窗口 520x1000　"
                  f"实际布局={window.wall.layout_id} ===")
            for index, tile in enumerate(window.wall.tiles):
                if not tile.isVisible():
                    continue
                tile.set_controls_visible(True)        # 等价于鼠标停在格子上
                settle(app, 0.1)
                controls = tile.controls.geometry()
                bottom = tile.bottom.geometry()
                badge = tile.stream_badge
                print(f"  格{index} {tile.width()}x{tile.height()}　"
                      f"controls={controls.getRect()}　bottom={bottom.getRect()}　"
                      f"浮标可见={badge.isVisible()} "
                      f"宽={badge.width() if badge.isVisible() else '-'}")
                assert controls.y() <= 10, \
                    f"控制条该钉在右上角（y≈8），实际 y={controls.y()}：" \
                    f"它被折到第二行了"
                assert not controls.intersects(bottom), \
                    f"控制条压到底部信息条上了：{controls.getRect()} vs {bottom.getRect()}"
                assert controls.right() <= tile.width() and controls.left() >= 0, \
                    f"控制条横向溢出格子：{controls.getRect()} vs 宽 {tile.width()}"
                if badge.isVisible():
                    assert badge.x() + badge.width() <= controls.x(), \
                        f"浮标和控制条重叠：浮标右边界 " \
                        f"{badge.x() + badge.width()} vs 控制条左边界 {controls.x()}"
                checked += 1
        finally:
            window.close()
            settle(app, 0.3)
    assert checked >= 12, f"检查的格子太少（{checked}），没覆盖到竖屏小格子"
    print(f"\n共检查 {checked} 个格子，全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
