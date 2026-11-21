"""Fixed grid coordinates for editable nine- and sixteen-cell layouts."""
from PySide6.QtCore import QRect

from .layouts import even_cells


def tiles_in(cell):
    row, col, height, width = cell
    return {(y, x) for y in range(row, row + height) for x in range(col, col + width)}


def validate(size, cells):
    if not isinstance(cells, (list, tuple)) or len(cells) != size * size:
        raise ValueError('网格布局无效')
    covered = set()
    result = []
    for cell in cells:
        if cell is None:
            result.append(None)
            continue
        if (not isinstance(cell, (list, tuple)) or len(cell) != 4
                or any(type(value) is not int for value in cell)):
            raise ValueError('网格位置无效')
        row, col, height, width = cell
        if not (0 <= row < row + height <= size and 0 <= col < col + width <= size):
            raise ValueError('网格位置越界')
        occupied = tiles_in(cell)
        if covered & occupied:
            raise ValueError('网格位置重叠')
        covered.update(occupied)
        result.append(tuple(cell))
    if len(covered) != size * size:
        raise ValueError('网格布局不完整')
    return result


def place(size, cells, index, target, protected):
    original = cells[index]
    if target == original:
        return cells
    occupied = tiles_in(target)
    hits = [i for i, cell in enumerate(cells) if i != index and cell and tiles_in(cell) & occupied]
    result = list(cells)
    result[index] = target
    if len(hits) == 1 and target == cells[hits[0]] and original[2:] == target[2:]:
        result[hits[0]] = original
        return result
    if any(i in protected or cells[i][2:] != (1, 1) for i in hits):
        return cells
    for i in hits:
        result[i] = None
    covered = set().union(*(tiles_in(cell) for cell in result if cell))
    available = iter(sorted((i for i, cell in enumerate(result) if cell is None), key=lambda i: i not in protected))
    for row, col, height, width in even_cells(size, size):
        if (row, col) not in covered:
            result[next(available)] = (row, col, height, width)
    return result


def geometry(size, cells, area, gap):
    width = max(1, area.width() - gap * (size - 1))
    height = max(1, area.height() - gap * (size - 1))
    x = [area.x() + round(width * i / size) + i * gap for i in range(size + 1)]
    y = [area.y() + round(height * i / size) + i * gap for i in range(size + 1)]
    rectangles = {}
    for index, cell in enumerate(cells):
        if cell is not None:
            row, col, rows, columns = cell
            rectangles[index] = QRect(x[col], y[row], x[col + columns] - x[col] - gap,
                                      y[row + rows] - y[row] - gap)
    return rectangles
