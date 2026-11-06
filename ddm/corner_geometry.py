"""Shared continuous corner geometry; no widgets or theme dependencies."""
from functools import lru_cache
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath


def continuous_path(rect, radius, *, corners=None):
    rect = QRectF(rect)
    return QPainterPath(_path(rect.getRect(), float(radius), tuple(corners) if corners else None))


@lru_cache(maxsize=512)
def _path(bounds, radius, corners):
    rect = QRectF(*bounds)
    path = QPainterPath()
    if rect.isEmpty():
        return path
    limit = min(rect.width(), rect.height()) / 2
    radius = max(0, min(float(radius), limit))
    if corners is None and radius >= limit:
        path.addRoundedRect(rect, radius, radius)  # Preserve circles and capsules.
        return path
    radii = [min(limit, max(0, r) * 1.3) for r in (corners or (radius,)*4)]
    x, y, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    # Two symmetric cubics per corner. At the straight joins both control
    # points lie on the edge (zero curvature); the diagonal joins share tangent
    # and curvature. This approximates the continuous Apple-style silhouette.
    a, b = .22, .64
    tl, tr, br, bl = radii
    path.moveTo(x+tl, y)
    path.lineTo(right-tr, y)
    path.cubicTo(right-b*tr, y, right-2*a*tr, y, right-a*tr, y+a*tr)
    path.cubicTo(right, y+2*a*tr, right, y+b*tr, right, y+tr)
    path.lineTo(right, bottom-br)
    path.cubicTo(right, bottom-b*br, right, bottom-2*a*br, right-a*br, bottom-a*br)
    path.cubicTo(right-2*a*br, bottom, right-b*br, bottom, right-br, bottom)
    path.lineTo(x+bl, bottom)
    path.cubicTo(x+b*bl, bottom, x+2*a*bl, bottom, x+a*bl, bottom-a*bl)
    path.cubicTo(x, bottom-2*a*bl, x, bottom-b*bl, x, bottom-bl)
    path.lineTo(x, y+tl)
    path.cubicTo(x, y+b*tl, x, y+2*a*tl, x+a*tl, y+a*tl)
    path.cubicTo(x+2*a*tl, y, x+b*tl, y, x+tl, y)
    path.closeSubpath()
    return path
