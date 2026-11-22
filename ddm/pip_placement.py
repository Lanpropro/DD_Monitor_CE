"""Free picture-in-picture placement in a shared, scale-independent canvas."""
from math import log, sqrt
from PySide6.QtCore import QPoint, QRect


def initial_placement(aspects):
    """Give landscape and portrait videos equal area at their own aspect ratios."""
    if not aspects:
        return []
    sizes = [(max(1, round(240 * sqrt(aspect))), max(1, round(240 / sqrt(aspect))))
             for aspect in aspects]

    def rows_for(columns):
        return [sizes[index:index + columns] for index in range(0, len(sizes), columns)]

    def extent(rows):
        return max(sum(w for w, _h in row) for row in rows), sum(max(h for _w, h in row) for row in rows)

    def fit_score(rows):
        width, height = extent(rows)
        return abs(log(width / height / (16 / 9)))

    rows = rows_for(len(sizes)) if len(sizes) <= 2 else min(
        (rows_for(columns) for columns in range(1, len(sizes) + 1)), key=fit_score)
    width, _height = extent(rows)
    boxes = []
    y = 0
    for row in rows:
        height = max(h for _w, h in row)
        x = (width - sum(w for w, _h in row)) // 2
        for w, h in row:
            boxes.append((x, y + (height - h) // 2, w, h))
            x += w
        y += height
    return boxes


def placement_bounds(rects):
    bounds = QRect(*rects[0])
    for rect in rects[1:]:
        bounds = bounds.united(QRect(*rect))
    return bounds


def validate_placement(values, count=None):
    if not isinstance(values, (tuple, list)) or (count is not None and len(values) != count):
        return ()
    if any(not isinstance(rect, (tuple, list)) or len(rect) != 4
           or any(type(n) is not int or abs(n) > 100_000 for n in rect)
           or min(rect[2:]) <= 0 for rect in values):
        return ()
    boxes = [QRect(*rect) for rect in values]
    if any(first.intersects(second) for index, first in enumerate(boxes) for second in boxes[index + 1:]):
        return ()
    return tuple(tuple(rect) for rect in values)


def fit_placement(values, area):
    bounds = placement_bounds(values)
    scale = min(area.width() / bounds.width(), area.height() / bounds.height())
    origin = QPoint(area.x() + round((area.width() - bounds.width() * scale) / 2),
                    area.y() + round((area.height() - bounds.height() * scale) / 2))
    boxes = []
    for x, y, width, height in values:
        left, top = round((x - bounds.x()) * scale), round((y - bounds.y()) * scale)
        right = round((x + width - bounds.x()) * scale)
        bottom = round((y + height - bounds.y()) * scale)
        boxes.append(QRect(origin.x() + left, origin.y() + top, right - left, bottom - top))
    return boxes, scale


def snap_position(rect, neighbours, tolerance):
    """Prefer nearby shared edges, then align the top, bottom, or centre."""
    x_moves, y_moves = {0: 0}, {0: 0}
    for other in neighbours:
        if rect.adjusted(-tolerance, -tolerance, tolerance, tolerance).intersects(other):
            for moves, leading, trailing, start, end in (
                    (x_moves, rect.left(), rect.right(), other.left(), other.right()),
                    (y_moves, rect.top(), rect.bottom(), other.top(), other.bottom())):
                for shift in (start - leading, end - trailing, (start + end - leading - trailing) // 2):
                    if abs(shift) <= tolerance:
                        moves[shift] = max(moves.get(shift, 0), 1)
                for shift in (start - trailing - 1, end - leading + 1):
                    if abs(shift) <= tolerance:
                        moves[shift] = 2
    choices = []
    for dx, x_priority in x_moves.items():
        for dy, y_priority in y_moves.items():
            candidate = rect.translated(dx, dy)
            if not any(candidate.intersects(other) for other in neighbours):
                choices.append((-(x_priority + y_priority), dx * dx + dy * dy, dx, dy))
    if not choices:
        return None
    _priority, _distance, dx, dy = min(choices)
    return rect.translated(dx, dy)
