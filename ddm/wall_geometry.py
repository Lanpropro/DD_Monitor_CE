"""Video wall automatic column selection."""
import math
from .widget_support import TILE_BAR_HEIGHT


def best_columns(count: int, width: int, height: int, gap: int = 8, aspect: float = 16 / 9) -> int:
    """在给定区域内挑一个让画面尽量大的列数。"""
    if count <= 1:
        return 1
    best_score = -1.0
    best = 1
    for columns in range(1, count + 1):
        rows = math.ceil(count / columns)
        tile_width = (width - gap * (columns - 1)) / columns
        tile_height = (height - gap * (rows - 1)) / rows
        if tile_width <= 0 or tile_height <= 0:
            continue
        score = min(tile_width, (tile_height - TILE_BAR_HEIGHT) * aspect)
        if score > best_score:
            best_score = score
            best = columns
    return best
