"""User-controlled scaling relative to a 720-pixel-high video viewport."""


def viewport_scale(height, strength=35):
    # An exponent gives a smooth monotonic curve anchored at 720px. Zero keeps
    # the chosen size; 100 follows the viewport in direct proportion.
    strength = max(0, min(100, int(strength)))
    return (max(1, height) / 720) ** (strength / 100)
