"""高频鼠标事件合并、松开最终位置、切布局取消待处理拖动；不联网。"""
from unittest.mock import patch

from selfcheck_corner_resize import (
    QApplication, QEvent, QMouseEvent, QPoint, QPointF, QTest, Qt,
    WallGrid, check_geometry, theme,
)


def move_to(handle, global_position):
    event = QMouseEvent(QEvent.MouseMove,
                        QPointF(handle.mapFromGlobal(global_position)),
                        QPointF(global_position), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(handle, event)


def release_at(handle, global_position):
    QTest.mouseRelease(handle, Qt.LeftButton, pos=handle.mapFromGlobal(global_position))


def begin(handle):
    start = handle.rect().center()
    origin = handle.mapToGlobal(start)
    QTest.mousePress(handle, Qt.LeftButton, pos=start)
    return origin


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    wall = WallGrid([], layout_id="corner")
    wall.resize(1200, 800)
    wall.show()
    app.processEvents()
    video_ids = [int(tile.video.winId()) for tile in wall.tiles]
    try:
        handle = wall._corner_width_handle
        before = wall.tiles[0].width()
        origin = begin(handle)
        with patch.object(wall, "_relayout_corner", wraps=wall._relayout_corner) as layout:
            for offset in range(1, 81):
                move_to(handle, origin + QPoint(offset, 0))
            assert layout.call_count == 0, "事件突发必须合并，不能逐条重排六格"
            QTest.qWait(80)
            assert layout.call_count == 1, "按住鼠标期间也必须应用最新位置"
            assert wall.tiles[0].width() == before + 80
            for offset in range(81, 121):
                move_to(handle, origin + QPoint(offset, 0))
            assert layout.call_count == 1
            # 松开位置比最后一次移动还远：压缩事件时不能丢失最终坐标。
            release_at(handle, origin + QPoint(125, 0))
            assert layout.call_count == 2
            assert wall.tiles[0].width() == before + 125
            QTest.qWait(80)
            assert layout.call_count == 2, "松开后不能再执行旧坐标"
        check_geometry(wall)
        # 空隙由画面墙自己填充，不继承已经移动的分隔线或视频的旧背景。
        image = wall.grab().toImage()
        assert image.pixelColor(4, 4) == theme.qcolor(theme.BG)

        handle = wall._corner_height_handle
        before = wall.tiles[0].height()
        origin = begin(handle)
        move_to(handle, origin + QPoint(0, -25))
        release_at(handle, origin + QPoint(0, -30))
        assert wall.tiles[0].height() == before - 30
        check_geometry(wall)

        origin = begin(handle)
        move_to(handle, origin + QPoint(0, 40))
        QTest.mouseDClick(handle, Qt.LeftButton, pos=handle.rect().center())
        QTest.qWait(80)
        assert wall._corner_height_ratio == 2 / 3

        handle = wall._corner_width_handle
        for interrupt in (lambda: wall.set_layout("3x3"),
                          lambda: wall.set_fullscreen_tile(wall.tiles[0])):
            ratio = wall._corner_width_ratio
            origin = begin(handle)
            move_to(handle, origin + QPoint(-80, 0))
            interrupt()
            QTest.qWait(80)
            assert wall._corner_width_ratio == ratio, "切布局或全屏必须取消旧拖动"
            assert handle._press_offset is None
            assert not wall._corner_drag_timer.isActive()
            assert wall._corner_pending_drag is None
            wall.set_fullscreen_tile(None)
            wall.set_layout("corner")
            app.processEvents()
            check_geometry(wall)
        assert [int(tile.video.winId()) for tile in wall.tiles[:6]] == video_ids
        print("PASS: 120 moves -> two layout updates, live feedback, exact release, "
              "reset/layout/fullscreen cancellation and stable video handles")
    finally:
        wall.close()
        app.processEvents()


if __name__ == "__main__":
    main()
