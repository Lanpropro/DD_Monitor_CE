"""Calculate magnetic alignment in Qt logical screen coordinates."""
from PySide6.QtCore import QPoint, Qt


def snapped_position(frame, work_area, neighbors, distance=12):
    horizontal = [(work_area.left() - frame.left(), Qt.LeftEdge),
                  (work_area.right() - frame.right(), Qt.RightEdge)]
    vertical = [(work_area.top() - frame.top(), Qt.TopEdge),
                (work_area.bottom() - frame.bottom(), Qt.BottomEdge)]
    for other in neighbors:
        if frame.top() <= other.bottom() and other.top() <= frame.bottom():
            horizontal.extend(((other.right() + 1 - frame.left(), Qt.LeftEdge),
                               (other.left() - 1 - frame.right(), Qt.RightEdge)))
        if frame.left() <= other.right() and other.left() <= frame.right():
            vertical.extend(((other.bottom() + 1 - frame.top(), Qt.TopEdge),
                             (other.top() - 1 - frame.bottom(), Qt.BottomEdge)))

    def closest(candidates, start, stop, lower, upper):
        return min(((delta, edge) for delta, edge in candidates
                    if abs(delta) <= distance and lower <= start + delta and stop + delta <= upper),
                   key=lambda match: abs(match[0]), default=(0, Qt.Edge(0)))

    dx, x_edge = closest(horizontal, frame.left(), frame.right(), work_area.left(), work_area.right())
    dy, y_edge = closest(vertical, frame.top(), frame.bottom(), work_area.top(), work_area.bottom())
    return frame.topLeft() + QPoint(dx, dy), x_edge | y_edge
