"""Normalized caption placement within the current video safe area."""
from PySide6.QtCore import QRect


def caption_rect(area, style):
    width = max(1, min(area.width(), round(area.width() * style.width / 100)))
    height = max(1, min(area.height(), round(area.height() * style.height / 100)))
    return QRect(area.x() + round((area.width() - width) * style.x / 100),
                 area.y() + round((area.height() - height) * style.y / 100), width, height)


def edit_rect(area, start, delta, resize=False):
    rect = QRect(start)
    if resize:
        rect.setWidth(max(round(area.width() * .2), min(area.width(), start.width() + delta.x())))
        rect.setHeight(max(round(area.height() * .08), min(round(area.height() * .45), start.height() + delta.y())))
    else:
        rect.translate(delta)
    rect.moveLeft(max(area.left(), min(rect.left(), area.right() - rect.width() + 1)))
    rect.moveTop(max(area.top(), min(rect.top(), area.bottom() - rect.height() + 1)))
    return rect


def placement_values(area, rect):
    return {
        'x': round(100 * (rect.x() - area.x()) / max(1, area.width() - rect.width())),
        'y': round(100 * (rect.y() - area.y()) / max(1, area.height() - rect.height())),
        'width': round(100 * rect.width() / max(1, area.width())),
        'height': round(100 * rect.height() / max(1, area.height())),
    }
