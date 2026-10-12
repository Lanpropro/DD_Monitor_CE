"""Pane edge/corner mouse hits, proportional limits, cancellation and stable video IDs."""
import os
import sys
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QRect

if "--native" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "windows"

from selfcheck_corner_resize import QApplication, QEvent, QPoint, QTest, Qt, WallGrid, QWidget, layouts, theme
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


def check_pane_ownership(app, wall):
    wall.set_layout("corner")
    wall.reset_layout_ratios()
    wall.resize(1400, 1000)
    app.processEvents()
    directory = Path(__file__).resolve().parents[1] / "work"
    lower, main = wall.tiles[3], wall.tiles[0]
    border = wall._pane_borders[lower]
    key = border.targets["top"]
    grip = wall._divider_grips[key]
    gap = wall._divider_rects[key]
    lower_point = wall.mapToGlobal(QPoint(lower.geometry().center().x(), gap.bottom()))
    upper_point = wall.mapToGlobal(QPoint(lower.geometry().center().x(), gap.top()))
    before = [pane.geometry() for pane in wall.visible_tiles()]
    assert 2 * border.BAND + gap.height() <= 11

    move_to(border, border.mapToGlobal(point_on(border, ["top"])))
    image = wall.grab().toImage()
    assert all(image.pixelColor(x, gap.bottom()).name() == "#38bdf8"
               for x in (lower.geometry().left(), lower.geometry().right()))
    assert image.pixelColor(wall.tiles[4].geometry().center().x(), gap.bottom()) == theme.qcolor(theme.BG)
    assert image.pixelColor(lower.geometry().center().x(), gap.top()) == theme.qcolor(theme.BG)
    wall.grab().save(str(directory / "pane-border-edge-owned.png"))

    for position, pane, edge in ((lower_point, lower, "top"), (upper_point, main, "bottom")):
        owner, edges = grip._hit_edges(position)
        assert owner is wall._pane_borders[pane] and edges == {edge: key}
        move_to(grip, position)
        assert wall._hover_border is owner
        assert wall._hover_dividers == {key}
        QTest.mousePress(grip, Qt.LeftButton, pos=grip.mapFromGlobal(position))
        assert wall._border_drag["border"] is owner and wall._border_drag["edges"] == {edge: key}
        release_at(grip, position)
        assert [pane.geometry() for pane in wall.visible_tiles()] == before

    middle = wall._pane_borders[wall.tiles[4]]
    move_to(middle, middle.mapToGlobal(point_on(middle, ["left", "top"])))
    assert len(middle.highlights) == 3
    assert wall._hover_dividers == set(middle.targets.values())
    assert all(middle.grab().toImage().pixelColor(point_on(middle, [edge])).name() == "#38bdf8"
               for edge in middle.targets)
    assert all(not candidate.highlights for candidate in wall._pane_borders.values() if candidate is not middle)
    wall.grab().save(str(directory / "pane-border-corner-owned.png"))
    wall._set_hover_border()
    print("PASS: thinner borders, corner layout pane-only edges, half-gap ownership and whole-pane corner highlight")


def check_resets(app, wall, identifiers):
    count = 0
    for identifier in identifiers:
        wall.set_layout(identifier)
        wall.resize(950 if layouts.is_portrait_layout(identifier) else 1400, 1300)
        app.processEvents()
        panes = wall.visible_tiles() + ([wall.danmaku] if wall.has_danmaku else [])
        for pane in panes:
            border = wall._pane_borders[pane]
            for edge in list(border.targets):
                wall.reset_layout_ratios()
                before = pane.size()
                point = point_on(border, [edge])
                grip = wall._divider_grips[border.targets[edge]]
                centre = grip.rect().center()
                wall._set_hover_border()
                assert border.grab().toImage().pixelColor(point) == theme.qcolor(theme.BG)
                assert grip.grab().toImage().pixelColor(centre) == theme.qcolor(theme.BG)
                move_to(border, border.mapToGlobal(point))
                assert border.grab().toImage().pixelColor(point).name() == "#38bdf8"
                hover = grip.mapFromGlobal(border.mapToGlobal(point))
                if grip.width() < grip.height():
                    hover.setX(grip.width() - 1 if edge == "left" else 0)
                else:
                    hover.setY(grip.height() - 1 if edge == "top" else 0)
                assert grip.grab().toImage().pixelColor(hover).name() == "#38bdf8"
                span = grip.width() if grip.width() < grip.height() else grip.height()
                image = grip.grab().toImage()
                colors = [image.pixelColor(
                    index if grip.width() < grip.height() else hover.x(),
                    hover.y() if grip.width() < grip.height() else index).name()
                    for index in range(span)]
                assert colors.count("#38bdf8") == span // 2, colors
                assert colors.count(theme.qcolor(theme.BG).name()) == span // 2, colors
                pane_start = grip.mapFromGlobal(pane.mapToGlobal(QPoint(0, 0)))
                pane_end = grip.mapFromGlobal(pane.mapToGlobal(pane.rect().bottomRight()))
                endpoints = ([QPoint(hover.x(), pane_start.y()), QPoint(hover.x(), pane_end.y())]
                             if grip.width() < grip.height() else
                             [QPoint(pane_start.x(), hover.y()), QPoint(pane_end.x(), hover.y())])
                assert all(image.pixelColor(endpoint).name() == "#38bdf8" for endpoint in endpoints)
                assert wall._hover_border is border
                assert wall._hover_dividers == {border.targets[edge]}
                assert all(not other.highlights for other in wall._pane_borders.values() if other is not border)
                QApplication.sendEvent(border, QEvent(QEvent.Leave))
                assert border.grab().toImage().pixelColor(point) == theme.qcolor(theme.BG)
                assert grip.grab().toImage().pixelColor(centre) == theme.qcolor(theme.BG)
                delta = {"left": QPoint(-18, 0), "right": QPoint(18, 0),
                         "top": QPoint(0, -18), "bottom": QPoint(0, 18)}[edge]
                resize(app, border, [edge], delta)
                resized = pane.size() != before
                signal = "cornerRatiosChanged" if identifier == "corner" else "layoutRatiosChanged"
                with patch.object(wall, signal) as changed:
                    point = point_on(border, [edge])
                    QTest.mouseDClick(border, Qt.LeftButton, pos=point)
                    assert changed.emit.call_count <= 1
                    if resized:
                        changed.emit.assert_called_once()
                    assert wall._border_drag is None and wall._border_pending is None
                    assert not wall._border_drag_timer.isActive()
                    assert abs(pane.width() - before.width()) <= 1, (identifier, edge, before, pane.size())
                    assert abs(pane.height() - before.height()) <= 1, (identifier, edge, before, pane.size())
                    changed.emit.reset_mock()
                    QTest.mouseDClick(border, Qt.LeftButton, pos=point_on(border, [edge]))
                    changed.emit.assert_not_called()
                check(wall)
                count += 1

    for identifier in ("corner", "3x3"):
        wall.set_layout(identifier)
        wall.resize(1400, 1000)
        wall.reset_layout_ratios()
        app.processEvents()
        pane = wall.tiles[0]
        border = wall._pane_borders[pane]
        before = pane.size()
        resize(app, border, ["right", "bottom"], QPoint(-35, -35))
        origin = press(border, ["right", "bottom"])
        move_to(border, origin + QPoint(15, 15))
        QTest.qWait(80)
        signal = "cornerRatiosChanged" if identifier == "corner" else "layoutRatiosChanged"
        with patch.object(wall, signal) as changed:
            QTest.mouseDClick(border, Qt.LeftButton, pos=point_on(border, ["right", "bottom"]))
            changed.emit.assert_called_once()
            assert wall._border_drag is None and wall._border_pending is None
            QTest.qWait(80)
            assert abs(pane.width() - before.width()) <= 1
            assert abs(pane.height() - before.height()) <= 1
            changed.emit.assert_called_once()
        check(wall)
        ratios = wall.corner_ratios() if identifier == "corner" else wall.layout_ratios()
        wall.set_fullscreen_tile(pane)
        QTest.mouseDClick(border, Qt.LeftButton, pos=point_on(border, ["right", "bottom"]))
        assert (wall.corner_ratios() if identifier == "corner" else wall.layout_ratios()) == ratios
        wall.set_fullscreen_tile(None)
    print(f"PASS: {count} edge double-click resets, idle background, repeat no-op, two-axis reset/save/cancel/fullscreen")


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [dict(room_id=str(1000 + i), uname=f"Border fixture {i}", live=False) for i in range(16)]
    wall = WallGrid(rooms, layout_id="corner")
    wall.setGeometry(40 if "--native" in sys.argv else -9000, 40, 1400, 1000)
    if "--native" in sys.argv:
        wall.setWindowFlag(Qt.WindowStaysOnTopHint, True)
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
            assert not wall.findChildren(QWidget, "WallResizeHandle")
            for pane in panes:
                border = wall._pane_borders[pane]
                if border.targets:
                    assert not border.mask().contains(border.rect().center()), (
                        identifier, pane.geometry(), border.targets)
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
            for key in wall._divider_rects:
                grip = wall._divider_grips[key]
                owner, edge = grip._owner()
                assert grip.isVisible() and owner is not None and owner.targets[edge] == key
            print(f"PASS borders {identifier}", flush=True)

        check_resets(app, wall, identifiers)
        check_pane_ownership(app, wall)

        wall.set_layout("3x3")
        wall.reset_layout_ratios()
        wall.resize(1400, 1000)
        app.processEvents()
        corner_pane = wall.tiles[4]
        corner_border = wall._pane_borders[corner_pane]
        snap_point = QPoint(corner_border.width() - corner_border.BAND + 1,
                            corner_border.height() // 2)
        assert corner_border.mask().contains(snap_point)
        assert set(corner_border.edges_at(snap_point)) == {"right"}
        corner_point = QPoint(corner_border.width() - 2,
                              corner_border.height() - corner_border.CORNER + 2)
        assert corner_border.mask().contains(corner_point)
        assert set(corner_border.edges_at(corner_point)) == {"right", "bottom"}
        assert not corner_border.mask().contains(QPoint(corner_border.width() - 10,
                                                       corner_border.height() - 10))
        vertical_key = corner_border.targets["right"]
        horizontal_key = corner_border.targets["bottom"]
        corner_grip = wall._divider_grips[vertical_key]
        near_corner = wall.mapToGlobal(QPoint(corner_pane.geometry().right() + 2,
                                              corner_pane.geometry().bottom() - 2))
        assert corner_grip.geometry().contains(wall.mapFromGlobal(near_corner))
        owner, edges = corner_grip._hit_edges(near_corner)
        assert owner is corner_border and set(edges.values()) == {vertical_key, horizontal_key}
        corner_grip._hover_at(near_corner)
        assert wall._hover_dividers == set(corner_border.targets.values())
        assert len(corner_border.highlights) == 4
        for divider_key in wall._hover_dividers:
            local = wall._divider_grips[divider_key].highlight
            assert not local.isEmpty()
            gap = wall._divider_rects[divider_key]
            assert (local.width() if gap.width() < gap.height() else local.height()) == wall.grid.spacing() // 2
        QTest.mousePress(corner_grip, Qt.LeftButton, pos=corner_grip.mapFromGlobal(near_corner))
        assert set(wall._border_drag["edges"].values()) == {vertical_key, horizontal_key}
        release_at(corner_grip, near_corner)
        assert wall._border_drag is None
        key = ("root", 0)
        grip = wall._divider_grips[key]
        before_grip = QRect(grip.geometry())
        before_panes = [tile.geometry() for tile in wall.visible_tiles()]
        axis = QPoint(18, 0) if grip.width() < grip.height() else QPoint(0, 18)
        centre = grip.rect().center()
        origin = grip.mapToGlobal(centre)
        move_to(grip, origin)
        assert grip.grab().toImage().pixelColor(centre).name() == "#38bdf8"
        with patch.object(wall, "layoutRatiosChanged") as changed:
            QTest.mousePress(grip, Qt.LeftButton, pos=centre)
            move_to(grip, origin + axis)
            QTest.qWait(80)
            assert wall._border_preview.isVisible()
            assert [tile.geometry() for tile in wall.visible_tiles()] == before_panes
            release_at(grip, origin + axis)
            changed.emit.assert_called_once()
        after_grip = grip.geometry()
        assert (after_grip.left() - before_grip.left() if axis.x() else
                after_grip.top() - before_grip.top()) == 18
        assert not wall._border_preview.isVisible()
        QTest.mouseDClick(grip, Qt.LeftButton, pos=grip.rect().center())
        assert abs(grip.geometry().left() - before_grip.left() if axis.x() else
                   grip.geometry().top() - before_grip.top()) <= 1
        check(wall)
        unchanged = [tile.geometry() for tile in wall.visible_tiles()]
        centre = grip.rect().center()
        origin = grip.mapToGlobal(centre)
        QTest.mousePress(grip, Qt.LeftButton, pos=centre)
        move_to(grip, origin + axis)
        QTest.qWait(80)
        assert wall._border_preview.isVisible()
        QTest.keyClick(grip, Qt.Key_Escape)
        release_at(grip, origin + axis)
        assert [tile.geometry() for tile in wall.visible_tiles()] == unchanged
        assert wall._border_drag is None and not wall._border_preview.isVisible()

        wall.set_layout("3x3")
        wall.reset_layout_ratios()
        wall.resize(1400, 1000)
        app.processEvents()
        pane = wall.tiles[4]
        border = wall._pane_borders[pane]
        before = pane.geometry()
        unchanged = {cell: item.geometry() for cell, item in wall._preset_widgets().items()}
        unchanged_dividers = dict(wall._divider_rects)
        with patch.object(wall, "_relayout_preset", wraps=wall._relayout_preset) as relayout, \
                patch.object(wall, "layoutRatiosChanged") as changed:
            origin = press(border, ["right", "bottom"])
            for i in range(1, 121):
                move_to(border, origin + QPoint(i, i))
            assert relayout.call_count == 0
            QTest.qWait(80)
            assert relayout.call_count == 0
            assert wall._border_preview.isVisible()
            assert border.grab().toImage().pixelColor(point_on(border, ["right"])) == theme.qcolor(theme.BG)
            assert set(wall._border_preview.rectangles) == set(unchanged)
            guides = wall._border_preview.guides
            assert guides and len(guides) < len(unchanged_dividers)
            for key, rect in guides.items():
                previous = unchanged_dividers[key]
                vertical = rect.width() < rect.height()
                assert (rect.left() if vertical else rect.top()) != (
                    previous.left() if vertical else previous.top())
                first = QPoint(rect.center().x(), rect.top() + 1) if vertical else QPoint(
                    rect.left() + 1, rect.center().y())
                gap = first + (QPoint(0, wall._border_preview.DASH + 1) if vertical
                               else QPoint(wall._border_preview.DASH + 1, 0))
                assert wall._border_preview.mask().contains(first)
                assert not wall._border_preview.mask().contains(gap)
            assert all(item.geometry() == unchanged[cell]
                       for cell, item in wall._preset_widgets().items())
            preview = dict(wall._border_preview.rectangles)
            assert preview[4].width() > before.width()
            changed.emit.assert_not_called()
            release_at(border, origin + QPoint(120, 120))
            assert relayout.call_count == 1
            changed.emit.assert_called_once()
            assert not wall._border_preview.isVisible()
            assert all(item.geometry() == preview[cell]
                       for cell, item in wall._preset_widgets().items())
            proportional(before, pane.geometry())
            assert pane.width() > before.width() and pane.height() > before.height()
            QTest.qWait(80)
            assert relayout.call_count == 1
        final = pane.geometry()
        origin = press(border, ["right", "bottom"])
        move_to(border, origin + QPoint(-30, -30))
        QTest.qWait(80)
        assert wall._border_preview.isVisible()
        assert pane.geometry() == final
        QTest.keyClick(border, Qt.Key_Escape)
        assert pane.geometry() == final
        assert not wall._border_preview.isVisible()
        assert wall._border_drag is None
        assert not wall._border_drag_timer.isActive()

        origin = press(border, ["right", "bottom"])
        move_to(border, origin + QPoint(60, 60))
        wall.resize(wall.width() + 10, wall.height() + 10)
        QTest.qWait(80)
        assert wall._border_drag is None and wall._border_pending is None
        assert not wall._border_preview.isVisible()
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
            assert not wall._border_preview.isVisible()
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
        border = wall._pane_borders[wall.tiles[0]]
        edge_point = point_on(border, ["right"])
        move_to(border, border.mapToGlobal(edge_point))
        app.processEvents()
        gap = wall._divider_rects[border.targets["right"]]
        y = wall.tiles[0].y() + edge_point.y()
        image = wall.grab().toImage()
        midpoint = gap.left() + gap.width() // 2
        assert all(image.pixelColor(x, y).name() == "#38bdf8"
                   for x in range(gap.left() - border.BAND, midpoint))
        assert all(image.pixelColor(x, y) == theme.qcolor(theme.BG)
                   for x in range(midpoint, gap.right() + border.BAND + 1))
        assert image.pixelColor(gap.left(), gap.top() + 1).name() == "#38bdf8"
        directory = Path(__file__).resolve().parents[1] / "work"
        wall.grab().save(str(directory / "pane-borders-hover.png"))
        if "--native" in sys.argv:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.WindowFromPoint.argtypes = (wintypes.POINT,)
            user32.WindowFromPoint.restype = wintypes.HWND
            point = border.mapToGlobal(point_on(border, ["right", "bottom"]))
            assert user32.WindowFromPoint(wintypes.POINT(point.x(), point.y())) == int(border.winId())
            gap_center = wall._divider_rects[("root/0", 0)].center()
            point = wall.mapToGlobal(gap_center)
            assert user32.WindowFromPoint(wintypes.POINT(point.x(), point.y())) == int(
                wall._divider_grips[("root/0", 0)].winId())
        wall.grab().save(str(directory / "pane-borders.png"))
        wall.reset_layout_ratios()
        assert not wall.layout_ratios().get("2x2")
        move_to(border, border.mapToGlobal(point_on(border, ["right"])))
        assert wall._hover_border is border
        wall._drop_tile(border.parentWidget())
        assert wall._hover_border is None and not wall._hover_dividers
        wall.relayout(force=True)
        app.processEvents()
        print(f"PASS: {edge_count} edges, {corner_count} corners, limits/ratio/cursors/masks/coalescing/cancel/reveal/IDs ({app.platformName()})")
    finally:
        wall.close()
        app.processEvents()


if __name__ == "__main__":
    main()
