"""User-controlled scaling relative to a 720-pixel-high video viewport."""
import math


def scale_curve_points(points=None, strength=35):
    """Return editable points; the manual-size reference at (1, 1) is fixed."""
    if isinstance(points, (list, tuple)) and len(points) >= 3:
        try:
            values = [[float(x), float(y)] for x, y in points]
            if (all(math.isfinite(x) and math.isfinite(y) and 0 <= x <= 2 and .1 <= y <= 2
                    for x, y in values)
                    and values[0][0] == 0 and values[-1][0] == 2
                    and all(b[0] - a[0] >= .01 for a, b in zip(values, values[1:]))
                    and [1.0, 1.0] in values):
                return values
        except (TypeError, ValueError):
            pass
    return [[x, max(.1, viewport_scale(max(1, 720*x), strength))]
            for x in (0, .125, .25, .5, .75, 1, 1.5, 2)]


def viewport_scale(height, strength=35, points=None):
    if points is not None:
        values = scale_curve_points(points, strength)
        x = max(0, min(2, height / 720))
        for left, right in zip(values, values[1:]):
            if x <= right[0]:
                return left[1] + (right[1]-left[1]) * (x-left[0]) / (right[0]-left[0])
        return values[-1][1]
    # An exponent gives a smooth monotonic curve anchored at 720px. Zero keeps
    # the chosen size; 100 follows the viewport in direct proportion.
    strength = max(0, min(100, int(strength)))
    return (max(1, height) / 720) ** (strength / 100)
