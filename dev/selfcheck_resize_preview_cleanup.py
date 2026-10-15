"""Screen-pixel regression for fast native preview movement and cleanup; no network."""
import ctypes
import os
from pathlib import Path

if __name__ == "__main__":
    os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from selfcheck_corner_resize import WallGrid, border_for, theme
from selfcheck_corner_drag_updates import begin, move_to, release_at


def boundary_points(wall):
    rectangles = list(wall._divider_rects.values())
    for pane, border in wall._pane_borders.items():
        if border.isVisible():
            rectangles.extend(border._edge_rect(edge).translated(pane.pos())
                              for edge in border.targets)
    points = set()
    for rect in rectangles:
        vertical = rect.width() < rect.height()
        for x in range(rect.left(), rect.right() + 1, 1 if vertical else 3):
            for y in range(rect.top(), rect.bottom() + 1, 3 if vertical else 1):
                points.add((x, y))
    return [QPoint(x, y) for x, y in points]


def assert_clean(app, wall, label):
    app.processEvents()
    ctypes.windll.dwmapi.DwmFlush()
    screen = wall.screen()
    image = screen.grabWindow(0).toImage()
    origin = wall.mapToGlobal(QPoint(0, 0)) - screen.geometry().topLeft()
    ratio = image.devicePixelRatio()
    preview = wall._border_preview
    active = preview.mask() if preview.isVisible() else QRegion()
    for rect in preview.guides.values():
        point = (QPoint(rect.center().x(), rect.top() + 2) if rect.width() < rect.height()
                 else QPoint(rect.left() + 2, rect.center().y()))
        pixel = image.pixelColor(round((origin.x() + point.x()) * ratio),
                                 round((origin.y() + point.y()) * ratio))
        assert pixel == preview.COLOR, (label, "current guide missing", point, pixel.name())
    ghosts = []
    for point in boundary_points(wall):
        if active.contains(point):
            continue
        pixel = image.pixelColor(round((origin.x() + point.x()) * ratio),
                                 round((origin.y() + point.y()) * ratio))
        if pixel == preview.COLOR:
            ghosts.append((point.x(), point.y()))
    if ghosts:
        directory = Path(__file__).resolve().parents[1] / "work"
        image.copy(round(origin.x() * ratio), round(origin.y() * ratio),
                   round(wall.width() * ratio), round(wall.height() * ratio)).save(
                       str(directory / "resize-preview-ghost.png"))
    assert not ghosts, (label, len(ghosts), ghosts[:12])


def drag_target(wall, target):
    if target == "corner":
        handle = wall._pane_borders[wall.tiles[0]]
        point = handle.rect().bottomRight() - QPoint(1, 1)
        assert set(handle.edges_at(point)) == {"right", "bottom"}
        return handle, point, QPoint(1, 1)
    handle, point = border_for(wall, target)
    gap = wall._divider_rects[target]
    axis = QPoint(1, 0) if gap.width() < gap.height() else QPoint(0, 1)
    return handle, point, axis


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    wall = WallGrid([], layout_id="corner")
    wall.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    wall.setGeometry(40, 40, 1400, 950)
    wall.show()
    QTest.qWait(400)
    identities = [int(tile.video.winId()) for tile in wall.tiles]
    try:
        for identifier in ("corner", "3x3"):
            wall.set_layout(identifier)
            wall.reset_layout_ratios()
            QTest.qWait(80)
            for target in (("root/0", 0), ("root", 0), "corner"):
                handle, point, axis = drag_target(wall, target)
                for ending in ("origin", "escape", "release"):
                    origin = begin(handle, pos=point)
                    still = [tile.geometry() for tile in wall.visible_tiles()]
                    for frame in range(24):
                        sign = -1 if frame % 2 else 1
                        for sample in range(12):
                            move_to(handle, origin + axis * sign * (sample + 1))
                        QTest.qWait(36)
                        app.processEvents()
                        assert [tile.geometry() for tile in wall.visible_tiles()] == still
                        assert wall._border_preview.isVisible() and wall._border_preview.guides, (
                            identifier, target, ending, frame, wall._border_drag, wall._border_pending)
                        assert_clean(app, wall, (identifier, target, ending, frame))
                    if ending == "escape":
                        QTest.keyClick(handle, Qt.Key_Escape)
                        release_at(handle, origin)
                    else:
                        release_at(handle, origin if ending == "origin" else origin + axis * 20)
                    wall._set_hover_border()
                    QTest.qWait(50)
                    assert not wall._border_preview.isVisible()
                    assert_clean(app, wall, (identifier, target, ending, "done"))
                    wall.reset_layout_ratios()
                    QTest.qWait(40)
                    handle, point, axis = drag_target(wall, target)
                    assert [int(tile.video.winId()) for tile in wall.tiles[:len(identities)]] == identities
            print(f"PASS native preview cleanup: {identifier}", flush=True)
        print("PASS: fast alternating moves, old boundary pixels, origin/Esc/release cleanup and stable video IDs")
    finally:
        wall.close()
        app.processEvents()


if __name__ == "__main__":
    main()
