"""Picture-in-picture composition geometry and aspect calculations."""
import math
from statistics import median
from PySide6.QtCore import QRect


from .pip_composition import FOCUS_LAYOUT, FREE_LAYOUT, GRID_LAYOUT, MAIN_LAYOUT
from .pip_placement import fit_placement, initial_placement, placement_bounds


def composition_rows(aspects, columns=0):
    def rows(cols):
        return [aspects[index:index + cols] for index in range(0, len(aspects), cols)]
    if not columns and len(aspects) == 3:
        columns = 2
    elif not columns:
        columns = min(range(1, len(aspects) + 1), key=lambda cols:
                      (abs(math.log(composition_aspect(rows(cols)) / (16 / 9))), math.ceil(len(aspects) / cols)))
    return rows(min(len(aspects), columns))


def composition_aspect(rows):
    return 1 / sum(1 / sum(row) for row in rows)


def _focus_parts(aspects, primary):
    order = [primary] + [index for index in range(6) if index != primary]
    values = [aspects[index] for index in order]
    right = 1 / (1 / values[1] + 1 / values[2])
    return order, values, values[0] + right, sum(values[3:])


def _grid_shape(count):
    columns = math.ceil(math.sqrt(count))
    return columns, math.ceil(count / columns)


def _main_parts(aspects, primary):
    sides = [aspect for index, aspect in enumerate(aspects) if index != primary]
    columns = math.ceil(len(sides) / 4)
    return sides, columns, composition_aspect(composition_rows(sides, columns))


def _uses_initial_placement(count, columns):
    return (columns == FREE_LAYOUT and count >= 3) or (columns == 0 and count > 3)


def composition_ratio(aspects, columns=0, primary=0, *, placement=()):
    if columns == FREE_LAYOUT and placement:
        bounds = placement_bounds(placement)
        return bounds.width() / bounds.height()
    if _uses_initial_placement(len(aspects), columns):
        bounds = placement_bounds(initial_placement(aspects))
        return bounds.width() / bounds.height()
    if columns == FOCUS_LAYOUT and len(aspects) == 6:
        _order, _values, top, bottom = _focus_parts(aspects, primary)
        return 1 / (1 / top + 1 / bottom)
    if columns == GRID_LAYOUT:
        across, rows = _grid_shape(len(aspects))
        return median(aspects) * across / rows
    if columns == MAIN_LAYOUT and len(aspects) > 1:
        _sides, _columns, side_ratio = _main_parts(aspects, primary)
        return aspects[primary] + side_ratio
    return composition_aspect(composition_rows(aspects, max(0, columns)))


def video_aspect(player):
    if player is not None:
        for name in ('video-out-params', 'video-params'):
            params = player._prop(name)
            if not isinstance(params, dict):
                continue
            width, height = params.get('dw', params.get('w')), params.get('dh', params.get('h'))
            aspect = params.get('aspect') or (width / height if width and height else 0)
            if isinstance(aspect, (int, float)) and math.isfinite(aspect) and aspect > 0:
                return 1 / aspect if params.get('rotate', 0) % 180 == 90 else float(aspect)
    return None


def pane_rectangles(count, area, columns=0, aspects=None, primary=0, *, placement=()):
    if not count:
        return []
    aspects = aspects or [16 / 9] * count
    if columns == FREE_LAYOUT and len(placement) == count:
        return fit_placement(placement, area)[0]
    if _uses_initial_placement(count, columns):
        return fit_placement(initial_placement(aspects), area)[0]
    aspect = composition_ratio(aspects, columns, primary)
    width = max(1, min(area.width(), round(area.height() * aspect)))
    height = max(1, min(area.height(), round(width / aspect)))
    canvas = QRect(0, 0, width, height)
    canvas.moveCenter(area.center())
    if columns == GRID_LAYOUT:
        across, rows = _grid_shape(count)
        rectangles = []
        for row in range(rows):
            items = min(across, count - row * across)
            start = (across - items) / 2
            top, bottom = round(row * height / rows), round((row + 1) * height / rows)
            for col in range(items):
                left = round((start + col) * width / across)
                right = round((start + col + 1) * width / across)
                rectangles.append(QRect(canvas.x() + left, canvas.y() + top, right - left, bottom - top))
        return rectangles
    if columns == MAIN_LAYOUT and count > 1:
        sides, side_columns, _side_ratio = _main_parts(aspects, primary)
        split = round(width * aspects[primary] / aspect)
        main = QRect(canvas.x(), canvas.y(), split, height)
        side_area = QRect(canvas.x() + split, canvas.y(), width - split, height)
        rectangles = pane_rectangles(count - 1, side_area, side_columns, sides)
        rectangles.insert(primary, main)
        return rectangles
    if columns == FOCUS_LAYOUT and count == 6:
        order, values, top_aspect, bottom_aspect = _focus_parts(aspects, primary)
        split_y = round(height * aspect / top_aspect)
        split_x = round(width * values[0] / top_aspect)
        right_y = round(split_y * values[2] / (values[1] + values[2]))
        arranged = [QRect(0, 0, split_x, split_y),
                    QRect(split_x, 0, width - split_x, right_y),
                    QRect(split_x, right_y, width - split_x, split_y - right_y)]
        left, offset = 0, 0.0
        for value in values[3:]:
            offset += value
            right = round(width * offset / bottom_aspect)
            arranged.append(QRect(left, split_y, right - left, height - split_y))
            left = right
        rectangles = [None] * count
        for index, rect in zip(order, arranged):
            rectangles[index] = rect.translated(canvas.topLeft())
        return rectangles
    rows = composition_rows(aspects, max(0, columns))
    rectangles, top, weight = [], 0, 0.0
    for row in rows:
        total = sum(row)
        weight += 1 / total
        bottom = round(height * weight * aspect)
        left, offset = 0, 0.0
        for value in row:
            offset += value
            right = round(width * offset / total)
            rectangles.append(QRect(canvas.x() + left, canvas.y() + top, right - left, bottom - top))
            left = right
        top = bottom
    return rectangles
