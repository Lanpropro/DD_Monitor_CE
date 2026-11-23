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
    bounds = frame
    for member in companions:
        bounds = bounds.united(member)
    horizontal = [(work_area.left() - bounds.left(), Qt.LeftEdge),
                  (work_area.right() - bounds.right(), Qt.RightEdge)]
    vertical = [(work_area.top() - bounds.top(), Qt.TopEdge),
                (work_area.bottom() - bounds.bottom(), Qt.BottomEdge)]
    for member in (frame, *companions):
        for other in neighbors:
            x, y = _edge_offsets(member, other)
            horizontal.extend(x)
            vertical.extend(y)

    def closest(candidates, start, stop, lower, upper):
        return min(((delta, edge) for delta, edge in candidates
                    if abs(delta) <= distance and lower <= start + delta and stop + delta <= upper),
                   key=lambda match: abs(match[0]), default=(0, Qt.Edge(0)))

    dx, x_edge = closest(horizontal, bounds.left(), bounds.right(), work_area.left(), work_area.right())
    dy, y_edge = closest(vertical, bounds.top(), bounds.bottom(), work_area.top(), work_area.bottom())
    return frame.topLeft() + QPoint(dx, dy), x_edge | y_edge
