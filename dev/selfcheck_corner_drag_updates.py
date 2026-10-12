"""拖动轮廓预览、松开最终位置、切布局取消待处理拖动；不联网。"""
from unittest.mock import patch

from selfcheck_corner_resize import (
    QApplication, QEvent, QMouseEvent, QPoint, QPointF, QTest, Qt,
    WallGrid, check_geometry, theme, border_for, CORNER_KEYS,
)


def move_to(handle, global_position):
    event = QMouseEvent(QEvent.MouseMove,
                        QPointF(handle.mapFromGlobal(global_position)),
                        QPointF(global_position), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(handle, event)


def release_at(handle, global_position):
    QTest.mouseRelease(handle, Qt.LeftButton, pos=handle.mapFromGlobal(global_position))


def begin(handle, *, pos=None):
    start = pos if pos is not None else handle.rect().center()
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
        handle, point = border_for(wall, CORNER_KEYS[Qt.Horizontal])
        before = wall.tiles[0].width()
        origin = begin(handle, pos=point)
        with patch.object(wall, "_relayout_corner", wraps=wall._relayout_corner) as layout:
            unchanged = [tile.geometry() for tile in wall.tiles[:6]]
            for offset in range(1, 81):
                move_to(handle, origin + QPoint(offset, 0))
            assert layout.call_count == 0, "事件突发必须合并，不能逐条重排六格"
            QTest.qWait(80)
            assert layout.call_count == 0, "按住鼠标期间不能重排视频窗口"
            assert [tile.geometry() for tile in wall.tiles[:6]] == unchanged
            assert wall._border_preview.isVisible()
            assert len(wall._border_preview.rectangles) == 6
            assert wall._border_preview.rectangles[0].width() == before + 80
            for offset in range(81, 121):
                move_to(handle, origin + QPoint(offset, 0))
            assert layout.call_count == 0
            # 松开位置比最后一次移动还远：压缩事件时不能丢失最终坐标。
            release_at(handle, origin + QPoint(125, 0))
            assert layout.call_count == 1
            assert wall.tiles[0].width() == before + 125
            assert not wall._border_preview.isVisible()
            QTest.qWait(80)
            assert layout.call_count == 1, "松开后不能再执行旧坐标"
        check_geometry(wall)
        # 空隙由画面墙自己填充，不继承已经移动的分隔线或视频的旧背景。
        image = wall.grab().toImage()
        assert image.pixelColor(4, 4) == theme.qcolor(theme.BG)

        handle, point = border_for(wall, CORNER_KEYS[Qt.Vertical])
        before = wall.tiles[0].height()
        origin = begin(handle, pos=point)
        move_to(handle, origin + QPoint(0, -25))
        release_at(handle, origin + QPoint(0, -30))
        assert wall.tiles[0].height() == before - 30
        check_geometry(wall)

        handle, point = border_for(wall, CORNER_KEYS[Qt.Vertical])
        origin = begin(handle, pos=point)
        move_to(handle, origin + QPoint(0, 40))
        QTest.mouseDClick(handle, Qt.LeftButton, pos=point)
        QTest.qWait(80)
        assert wall._corner_height_ratio == 2 / 3

        for interrupt in (lambda: wall.set_layout("3x3"),
                          lambda: wall.set_fullscreen_tile(wall.tiles[0])):
            ratio = wall._corner_width_ratio
            handle, point = border_for(wall, CORNER_KEYS[Qt.Horizontal])
            origin = begin(handle, pos=point)
            move_to(handle, origin + QPoint(-80, 0))
            interrupt()
            QTest.qWait(80)
            assert wall._corner_width_ratio == ratio, "切布局或全屏必须取消旧拖动"
            assert wall._border_drag is None
            assert not wall._border_drag_timer.isActive()
            assert wall._border_pending is None
            assert not wall._border_preview.isVisible()
            wall.set_fullscreen_tile(None)
            wall.set_layout("corner")
            app.processEvents()
            check_geometry(wall)
        assert [int(tile.video.winId()) for tile in wall.tiles[:6]] == video_ids
        print("PASS: 120 moves -> one layout update, outline preview, exact release, "
              "reset/layout/fullscreen cancellation and stable video handles")
    finally:
        wall.close()
        app.processEvents()


if __name__ == "__main__":
    main()
