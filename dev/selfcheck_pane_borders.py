"""Pane edge/corner mouse hits, proportional limits, cancellation and stable video IDs."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

if "--native" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "windows"

from selfcheck_corner_resize import QApplication, QPoint, QTest, Qt, WallGrid, layouts, theme
from selfcheck_corner_drag_updates import move_to, release_at
from selfcheck_preset_resize import check


def point_on(border, edges):
    x, y = border.width() // 2, border.height() // 2
    if "left" in edges:
        x = 2
    if "right" in edges:
        x = border.width() - 3
    if "top" in edges:
        y = 2
    if "bottom" in edges:
        y = border.height() - 3
    return QPoint(x, y)


def press(border, edges):
    point = point_on(border, edges)
    assert set(border.edges_at(point)) == set(edges)
    assert border.mask().contains(point)
    origin = border.mapToGlobal(point)
    move_to(border, origin)
    if len(edges) == 2:
        assert border.cursor().shape() in (Qt.SizeFDiagCursor, Qt.SizeBDiagCursor)
    else:
        assert border.cursor().shape() == (Qt.SizeHorCursor if edges[0] in ("left", "right") else Qt.SizeVerCursor)
    QTest.mousePress(border, Qt.LeftButton, pos=point)
    assert border.wall._border_drag is not None
    return origin


def resize(app, border, edges, delta):
    origin = press(border, edges)
    move_to(border, origin + delta)
    release_at(border, origin + delta)
    app.processEvents()


def proportional(before, after):
    assert abs(before.width() * after.height() - before.height() * after.width()) <= 2 * (before.width() + before.height()), (before, after)


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [dict(room_id=str(1000 + i), uname=f"Border fixture {i}", live=False) for i in range(16)]
    wall = WallGrid(rooms, layout_id="corner")
    wall.setGeometry(40 if "--native" in sys.argv else -9000, 40, 1400, 1000)
    wall.show()
    app.processEvents()
    identities = [(tile, int(tile.video.winId())) for tile in wall.tiles]
    edge_count = corner_count = 0
    try:
        identifiers = ("1x1", "2x1", "1x2", "2x2", "corner", "main2", "dm_left", "portrait_dm6") if "--native" in sys.argv else layouts.BY_ID
        for identifier in identifiers:
            wall.set_layout(identifier)
            wall.resize(950 if layouts.is_portrait_layout(identifier) else 1400, 1300)
            app.processEvents()
            panes = wall.visible_tiles() + ([wall.danmaku] if wall.has_danmaku else [])
            for pane in panes:
                border = wall._pane_borders[pane]
                assert not border.mask().contains(border.rect().center())
                for edge in list(border.targets):
                    wall.reset_layout_ratios()
                    app.processEvents()
                    before = pane.geometry()
                    delta = {"left": QPoint(-18, 0), "right": QPoint(18, 0),
                             "top": QPoint(0, -18), "bottom": QPoint(0, 18)}[edge]
                    resize(app, border, [edge], delta)
                    after = pane.geometry()
                    if edge in ("left", "right"):
                        assert 0 <= after.width() - before.width() <= 19, (identifier, edge, before, after)
                        assert after.height() == before.height()
                    else:
                        assert 0 <= after.height() - before.height() <= 19, (identifier, edge, before, after)
                        assert after.width() == before.width()
                    check(wall)
                    edge_count += 1
                for xedge, yedge in (("left", "top"), ("right", "top"),
                                     ("left", "bottom"), ("right", "bottom")):
                    if xedge not in border.targets or yedge not in border.targets:
                        continue
                    for amount in (26, -26, 10000, -10000):
                        wall.reset_layout_ratios()
                        before = pane.geometry()
                        delta = QPoint(amount * (-1 if xedge == "left" else 1),
                                       amount * (-1 if yedge == "top" else 1))
                        resize(app, border, [xedge, yedge], delta)
                        proportional(before, pane.geometry())
                        if abs(amount) < 100:
                            sign = 1 if amount > 0 else -1
                            assert sign * (pane.width() - before.width()) >= 0
                            assert sign * (pane.height() - before.height()) >= 0
                        check(wall)
                    corner_count += 1
            print(f"PASS borders {identifier}", flush=True)

        wall.set_layout("3x3")
        wall.reset_layout_ratios()
        wall.resize(1400, 1000)
        app.processEvents()
        pane = wall.tiles[4]
        border = wall._pane_borders[pane]
        before = pane.geometry()
        with patch.object(wall, "_relayout_preset", wraps=wall._relayout_preset) as relayout, \
                patch.object(wall, "layoutRatiosChanged") as changed:
            origin = press(border, ["right", "bottom"])
            for i in range(1, 121):
                move_to(border, origin + QPoint(i, i))
            assert relayout.call_count == 0
            QTest.qWait(80)
            assert relayout.call_count == 1
            changed.emit.assert_not_called()
            release_at(border, origin + QPoint(125, 125))
            assert relayout.call_count == 2
            changed.emit.assert_called_once()
            proportional(before, pane.geometry())
            assert pane.width() > before.width() and pane.height() > before.height()
            QTest.qWait(80)
            assert relayout.call_count == 2
        final = pane.geometry()
        origin = press(border, ["right", "bottom"])
        move_to(border, origin + QPoint(-30, -30))
        QTest.qWait(80)
        QTest.keyClick(border, Qt.Key_Escape)
        assert pane.geometry() == final
        assert wall._border_drag is None
        assert not wall._border_drag_timer.isActive()

        origin = press(border, ["right", "bottom"])
        move_to(border, origin + QPoint(60, 60))
        wall.resize(wall.width() + 10, wall.height() + 10)
        QTest.qWait(80)
        assert wall._border_drag is None and wall._border_pending is None
        with patch.object(wall, "layoutRatiosChanged") as changed:
            origin = press(border, ["right", "bottom"])
            release_at(border, origin)
            changed.emit.assert_not_called()

        for interrupt in (lambda: wall.set_layout("corner"),
                          lambda: wall.set_fullscreen_tile(pane),
                          wall.reset_layout_ratios):
            wall.set_layout("3x3")
            origin = press(border, ["right", "bottom"])
            move_to(border, origin + QPoint(80, 80))
            interrupt()
            QTest.qWait(80)
            assert wall._border_drag is None and wall._border_pending is None
            assert not wall._border_drag_timer.isActive()
            wall.set_fullscreen_tile(None, stagger=True, first=pane)
            wall.reveal_tiles_staggered()
            for _ in range(10):
                app.processEvents()
            assert all(wall._pane_borders[tile].isVisible() for tile in wall.visible_tiles())

        # The centre remains available to playback controls and room drag/drop.
        for tile, video_id in identities:
            assert int(tile.video.winId()) == video_id
            assert tile.parentWidget() is wall
        wall.set_layout("2x2")
        wall.resize(1100, 750)
        app.processEvents()
        if "--native" in sys.argv:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.WindowFromPoint.argtypes = (wintypes.POINT,)
            user32.WindowFromPoint.restype = wintypes.HWND
            border = wall._pane_borders[wall.tiles[0]]
            point = border.mapToGlobal(point_on(border, ["right", "bottom"]))
            assert user32.WindowFromPoint(wintypes.POINT(point.x(), point.y())) == int(border.winId())
        directory = Path(__file__).resolve().parents[1] / "work"
        wall.grab().save(str(directory / "pane-borders.png"))
        wall.reset_layout_ratios()
        assert not wall.layout_ratios().get("2x2")
        print(f"PASS: {edge_count} edges, {corner_count} corners, limits/ratio/cursors/masks/coalescing/cancel/reveal/IDs ({app.platformName()})")
    finally:
        wall.close()
        app.processEvents()


if __name__ == "__main__":
    main()
