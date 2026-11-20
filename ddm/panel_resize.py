"""Pointer geometry shared by frameless resizable panels."""
from PySide6.QtCore import QRect, Qt


def resize_edges(widget, point):
    edges = Qt.Edge(0)
    if point.x() < 8:
        edges |= Qt.LeftEdge
    elif point.x() >= widget.width() - 8:
        edges |= Qt.RightEdge
    if point.y() < 8:
        edges |= Qt.TopEdge
    elif point.y() >= widget.height() - 8:
        edges |= Qt.BottomEdge
    return edges


def set_resize_cursor(widget, edges):
    if edges in (Qt.TopEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge):
        widget.setCursor(Qt.SizeFDiagCursor)
    elif edges in (Qt.TopEdge | Qt.RightEdge, Qt.BottomEdge | Qt.LeftEdge):
        widget.setCursor(Qt.SizeBDiagCursor)
    elif edges & (Qt.LeftEdge | Qt.RightEdge):
        widget.setCursor(Qt.SizeHorCursor)
    elif edges:
        widget.setCursor(Qt.SizeVerCursor)
    else:
        widget.unsetCursor()


def resized_rect(original, edges, delta, area, minimum):
    result = QRect(original)
    if edges & Qt.LeftEdge:
        result.setLeft(max(area.left(), min(original.left() + delta.x(), original.right() - minimum.width() + 1)))
    elif edges & Qt.RightEdge:
        result.setRight(min(area.right(), max(original.right() + delta.x(), original.left() + minimum.width() - 1)))
    if edges & Qt.TopEdge:
        result.setTop(max(area.top(), min(original.top() + delta.y(), original.bottom() - minimum.height() + 1)))
    elif edges & Qt.BottomEdge:
        result.setBottom(min(area.bottom(), max(original.bottom() + delta.y(), original.top() + minimum.height() - 1)))
    return result
