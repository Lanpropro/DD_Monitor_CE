"""Cached static wallpaper material; no widget capture or video-frame blur."""
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QColor


def paint_backdrop(painter, widget, clip, tint, *, card=False):
    from .skin_parts import values_for
    from .ui.settings_surface import _frosted_image
    window = widget.window()
    path = values_for('settings').get('image') or window.property('settings_backdrop_path') or ''
    try:
        stat = Path(path).stat()
    except (OSError, ValueError):
        return False
    image = _frosted_image(path, stat.st_mtime_ns, stat.st_size,
                           int(window.property('settings_glass_blur') or 0))
    if image.isNull():
        return False
    painter.save()
    painter.setClipPath(clip)
    offset = widget.mapTo(window, QPoint())
    scale = max(window.width() / image.width(), window.height() / image.height())
    width, height = image.width() * scale, image.height() * scale
    target = QRectF((window.width() - width) / 2 - offset.x(),
                    (window.height() - height) / 2 - offset.y(), width, height)
    painter.drawPixmap(target, image, QRectF(image.rect()))
    color = QColor(tint)
    opacity = int(window.property('settings_glass_opacity') or 0)
    color.setAlpha(round(255 * min(100, opacity + (10 if card else 0)) / 100))
    painter.fillPath(clip, color)
    painter.restore()
    return True
