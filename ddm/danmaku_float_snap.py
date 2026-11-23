"""Calculate magnetic alignment in Qt logical screen coordinates."""
from PySide6.QtCore import QPoint, Qt


def _edge_offsets(frame, other):
    horizontal = ()
    vertical = ()
    if frame.top() <= other.bottom() and other.top() <= frame.bottom():
        horizontal = ((other.right() + 1 - frame.left(), Qt.LeftEdge),
                      (other.left() - 1 - frame.right(), Qt.RightEdge))
    if frame.left() <= other.right() and other.left() <= frame.right():
        vertical = ((other.bottom() + 1 - frame.top(), Qt.TopEdge),
                    (other.top() - 1 - frame.bottom(), Qt.BottomEdge))
    return horizontal, vertical


def touching_windows(window, frames):
    """Find the whole connected set, including windows touching another member."""
    remaining = dict(frames)
    connected = [remaining.pop(window)]
    followers = {}
    for frame in connected:
        for other, rect in tuple(remaining.items()):
            horizontal, vertical = _edge_offsets(frame, rect)
            if any(delta == 0 for delta, _ in (*horizontal, *vertical)):
                connected.append(remaining.pop(other))
                followers[other] = rect.topLeft()
    return followers


def snapped_position(frame, work_area, neighbors, distance=12, *, companions=()):
    members = (frame, *companions)
    neighbors = tuple(neighbors)
    bounds = frame
    for member in members[1:]:
        bounds = bounds.united(member)
    min_x, max_x = work_area.left() - bounds.left(), work_area.right() - bounds.right()
    min_y, max_y = work_area.top() - bounds.top(), work_area.bottom() - bounds.bottom()
    horizontal = [(min_x, Qt.LeftEdge, None), (max_x, Qt.RightEdge, None)]
    vertical = [(min_y, Qt.TopEdge, None), (max_y, Qt.BottomEdge, None)]
    for member in members:
        for other in neighbors:
            x, y = _edge_offsets(member, other)
            pair = (member, other)
            horizontal.extend((delta, edge, pair) for delta, edge in x)
            vertical.extend((delta, edge, pair) for delta, edge in y)

    def closest(candidates, lower, upper):
        return min((match for match in candidates if lower <= match[0] <= upper),
                   key=lambda match: (abs(match[0]), match[2] is None), default=(0, Qt.Edge(0), None))

    def clears_neighbors(x, y):
        for member in members:
            moved = member.translated(x, y)
            if any(moved.intersects(other) for other in neighbors):
                return False
        return True

    dx, x_edge, side_pair = closest(horizontal, max(min_x, -distance), min(max_x, distance))
    dy, y_edge, stack_pair = closest(vertical, max(min_y, -distance), min(max_y, distance))
    # Align along the shared side, using the contact window even when a group is moving.
    if side_pair is not None and stack_pair is None:
        member, other = side_pair
        aligned = ((other.top() - member.top(), Qt.TopEdge, None),
                   (other.bottom() - member.bottom(), Qt.BottomEdge, None))
        shift, edge, _ = closest((match for match in aligned if clears_neighbors(dx, match[0])), min_y, max_y)
        if edge:
            dy, y_edge = shift, edge
    elif stack_pair is not None and side_pair is None:
        member, other = stack_pair
        aligned = ((other.left() - member.left(), Qt.LeftEdge, None),
                   (other.right() - member.right(), Qt.RightEdge, None))
        shift, edge, _ = closest((match for match in aligned if clears_neighbors(match[0], dy)), min_x, max_x)
        if edge:
            dx, x_edge = shift, edge
    return frame.topLeft() + QPoint(dx, dy), x_edge | y_edge
