"""预设的矩形分区树：只计算坐标，不创建或移动视频的父窗口。"""
from dataclasses import dataclass, field
import math

from PySide6.QtCore import QRect, QSize, Qt


@dataclass
class Partition:
    cell: int | None = None
    axis: object = None
    children: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    key: str = "root"

    def nodes(self):
        if self.children:
            yield self
            for child in self.children:
                yield from child.nodes()

    def minimum(self, gap, leaf_minimum):
        if not self.children:
            return leaf_minimum(self.cell)
        sizes = [child.minimum(gap, leaf_minimum) for child in self.children]
        if self.axis == Qt.Horizontal:
            return QSize(sum(size.width() for size in sizes) + gap * (len(sizes) - 1),
                         max(size.height() for size in sizes))
        return QSize(max(size.width() for size in sizes),
                     sum(size.height() for size in sizes) + gap * (len(sizes) - 1))


def build_partition(cells, key="root"):
    """优先分行，再分列；合法切口不能穿过任何跨行/跨列画面。"""
    indexed = list(enumerate(cells))

    def build(items, path):
        if len(items) == 1:
            return Partition(cell=items[0][0], key=path)
        for axis, position, span in ((Qt.Vertical, 0, 2), (Qt.Horizontal, 1, 3)):
            start = min(cell[position] for _, cell in items)
            end = max(cell[position] + cell[span] for _, cell in items)
            cuts = [point for point in range(start + 1, end)
                    if not any(cell[position] < point < cell[position] + cell[span]
                               for _, cell in items)]
            if not cuts:
                continue
            edges = [start, *cuts, end]
            groups = [[item for item in items if left <= item[1][position] < right]
                      for left, right in zip(edges, edges[1:])]
            if any(not group for group in groups):
                continue
            return Partition(axis=axis,
                             children=[build(group, f"{path}/{index}")
                                       for index, group in enumerate(groups)],
                             weights=[right - left for left, right in zip(edges, edges[1:])],
                             key=path)
        raise ValueError("预设无法沿画面边界分区")

    return build(indexed, key)


def portrait_partition(small, with_danmaku, columns=2):
    """主画面、小画面区、底部弹幕；小画面区每行独立分列。"""
    rows = []
    for row in range(math.ceil(small / columns)):
        children = [Partition(cell=1 + index)
                    for index in range(row * columns, min(small, (row + 1) * columns))]
        rows.append(Partition(axis=Qt.Horizontal, children=children,
                              weights=[1] * len(children), key=f"root/1/{row}"))
    small_group = Partition(axis=Qt.Vertical, children=rows, weights=[1] * len(rows), key="root/1")
    children = [Partition(cell=0), small_group]
    if with_danmaku:
        children.append(Partition(cell=small + 1))
    return Partition(axis=Qt.Vertical, children=children, weights=[1] * len(children))


def validated_weights(saved, partition):
    """仅接受已知分区的完整、有限、正比例数组，忽略旧配置及损坏字段。"""
    result = {}
    if not isinstance(saved, dict):
        return result
    for node in partition.nodes():
        values = saved.get(node.key)
        try:
            if (isinstance(values, (list, tuple)) and len(values) == len(node.children)
                    and all(type(value) in (int, float) and math.isfinite(value) and value > 0
                            for value in values)):
                total = sum(values)
                if math.isfinite(total) and total > 0:
                    normalized = [value / total for value in values]
                    if all(value > 0 for value in normalized):
                        result[node.key] = normalized
        except OverflowError:
            pass
    return result


def allocate(length, weights, minimums):
    """按比例分配像素，锁定达到最小值的区域，余下像素继续按比例分配。"""
    length = max(sum(minimums), length)
    sizes = [0] * len(weights)
    active = set(range(len(weights)))
    remaining = length
    while active:
        total = sum(weights[index] for index in active)
        locked = [index for index in active
                  if remaining * weights[index] / total < minimums[index]]
        if not locked:
            exact = {index: remaining * weights[index] / total for index in active}
            for index in active:
                sizes[index] = int(exact[index])
            missing = remaining - sum(sizes[index] for index in active)
            for index in sorted(active, key=lambda index: (-(exact[index] - sizes[index]), index))[:missing]:
                sizes[index] += 1
            break
        for index in locked:
            sizes[index] = minimums[index]
            remaining -= sizes[index]
            active.remove(index)
    return sizes


def geometry(partition, area, gap, leaf_minimum, saved, defaults=None):
    """返回叶子矩形及分隔线（分区、相邻下标、矩形、区域、实际分配）。"""
    leaves, dividers = {}, []

    def place(node, rect):
        if not node.children:
            leaves[node.cell] = rect
            return
        horizontal = node.axis == Qt.Horizontal
        length = rect.width() if horizontal else rect.height()
        mins = [child.minimum(gap, leaf_minimum) for child in node.children]
        weights = saved.get(node.key) or (defaults(node, rect) if defaults else node.weights)
        sizes = allocate(length - gap * (len(node.children) - 1), weights,
                         [size.width() if horizontal else size.height() for size in mins])
        offset = rect.x() if horizontal else rect.y()
        for index, (child, size) in enumerate(zip(node.children, sizes)):
            child_rect = (QRect(offset, rect.y(), size, rect.height()) if horizontal
                          else QRect(rect.x(), offset, rect.width(), size))
            place(child, child_rect)
            offset += size
            if index < len(node.children) - 1:
                handle = (QRect(offset, rect.y(), gap, rect.height()) if horizontal
                          else QRect(rect.x(), offset, rect.width(), gap))
                dividers.append((node, index, handle, rect, sizes))
                offset += gap

    place(partition, area)
    return leaves, dividers


def border_targets(rect, dividers):
    """Map each movable pane edge to its adjacent partition boundary."""
    targets = {}
    for node, index, handle, _area, _sizes in dividers:
        key = (node.key, index)
        if node.axis == Qt.Horizontal:
            if handle.top() <= rect.top() and handle.bottom() >= rect.bottom():
                if handle.right() + 1 == rect.left():
                    targets["left"] = key
                if rect.right() + 1 == handle.left():
                    targets["right"] = key
        elif handle.left() <= rect.left() and handle.right() >= rect.right():
            if handle.bottom() + 1 == rect.top():
                targets["top"] = key
            if rect.bottom() + 1 == handle.top():
                targets["bottom"] = key
    return targets


def resize_borders(tree, area, gap, minimum, saved, defaults, cell, edges, original, delta):
    """Resize one/two boundaries from the press snapshot; clamp corners as a unit."""
    horizontal = next((edge for edge in edges if edge in ("left", "right")), None)
    vertical = next((edge for edge in edges if edge in ("top", "bottom")), None)
    sx = -1 if horizontal == "left" else 1
    sy = -1 if vertical == "top" else 1

    def trial(width, height):
        weights = {key: list(values) for key, values in saved.items()}
        # Ancestors must move first so descendants use their updated available area.
        for edge, key in sorted(edges.items(), key=lambda item: len(item[1][0])):
            _, dividers = geometry(tree, area, gap, minimum, weights, defaults)
            node, index, _handle, _node_area, current = next(
                divider for divider in dividers if (divider[0].key, divider[1]) == key)
            is_horizontal = node.axis == Qt.Horizontal
            sign = -1 if edge in ("left", "top") else 1
            sizes = list(current)
            mins = [child.minimum(gap, minimum) for child in node.children]
            lower = mins[index].width() if is_horizontal else mins[index].height()
            pair = sizes[index] + sizes[index + 1]
            upper = pair - (mins[index + 1].width() if is_horizontal else mins[index + 1].height())
            wanted = width if is_horizontal else height

            def candidate(value):
                sizes[index], sizes[index + 1] = value, pair - value
                weights[node.key] = [size / sum(sizes) for size in sizes]
                placed, _ = geometry(tree, area, gap, minimum, weights, defaults)
                rect = placed[cell]
                return rect.width() if is_horizontal else rect.height()

            # An edge can belong to an ancestor: changing its span by N may only
            # change this leaf by a fraction of N. Solve against the leaf itself.
            low, high = lower, upper
            while low < high:
                middle = (low + high) // 2
                if sign * candidate(middle) < sign * wanted:
                    low = middle + 1
                else:
                    high = middle
            options = {low, max(lower, low - 1)}
            best = min(options, key=lambda value: (abs(candidate(value) - wanted), abs(value - current[index])))
            candidate(best)
        leaves, _ = geometry(tree, area, gap, minimum, weights, defaults)
        return weights, leaves[cell]

    if not (horizontal and vertical):
        return trial(original.width() + sx * delta.x() if horizontal else original.width(),
                     original.height() + sy * delta.y() if vertical else original.height())[0]
    width, height = original.width(), original.height()
    scale = max(0.0, 1 + (sx * delta.x() * width + sy * delta.y() * height)
                / (width * width + height * height))

    cache = {}

    def scaled(value):
        wanted_w, wanted_h = round(width * value), round(height * value)
        if (wanted_w, wanted_h) in cache:
            return cache[(wanted_w, wanted_h)]
        weights, rect = trial(wanted_w, wanted_h)
        valid = abs(rect.width() - wanted_w) <= 1 and abs(rect.height() - wanted_h) <= 1
        cache[(wanted_w, wanted_h)] = weights, valid
        return weights, valid

    result, valid = scaled(scale)
    if valid:
        return result
    # Find the furthest feasible scale before either axis reaches a neighbour's minimum.
    feasible, blocked = 1.0, scale
    result, _ = scaled(feasible)
    for _ in range(24):
        middle = (feasible + blocked) / 2
        candidate, valid = scaled(middle)
        if valid:
            feasible, result = middle, candidate
        else:
            blocked = middle
    return result
