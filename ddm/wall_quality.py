"""Match wall-wide quality requests against each room's advertised tiers."""
import re

from .widget_support import QUALITY_CHOICES


WALL_QUALITY_CHOICES = ((0, '最高可用'), (1080, '1080P'), (720, '720P'), (480, '480P'), (360, '360P'))
_BILI_TIERS = {1080: 400, 720: 250, 480: 150, 360: 80}
_NAMED_TIERS = (('4k', 2160), ('2k', 1440), ('蓝光', 1080), ('超清', 720),
                ('高清', 540), ('标清', 480), ('流畅', 360))


def _tier_size(option, quality, *, bili):
    name = ' '.join(str(option.get(key) or '') for key in ('desc', 'label', 'resolution')).lower()
    dimensions = re.search(r'(\d{3,4})\s*[x×]\s*(\d{3,4})', name)
    if dimensions:
        return min(map(int, dimensions.groups()))
    pixels = re.search(r'(?<!\d)(\d{3,4})\s*p', name)
    if pixels:
        return int(pixels[1])
    if bili:
        nominal = next((size for size, qn in _BILI_TIERS.items() if qn == quality), None)
        if nominal is not None:
            return nominal
    # Providers with no dimensions may still give a comparable quality tier name.
    return next((size for name_part, size in _NAMED_TIERS if name_part in name), None)


def closest_wall_quality(tile, height):
    """Return the provider's quality ID, or None when there is no comparable tier."""
    bili = str(tile.room.get('room_id') or '').isdigit()
    options = tile.quality_options
    if not options and bili:
        options = [{'qn': quality, 'desc': label} for label, quality in QUALITY_CHOICES]
    tiers = []
    for item in options:
        try:
            quality = int(item['qn'])
        except (KeyError, TypeError, ValueError):
            continue
        if quality > 0:
            tiers.append((quality, item))
    if not tiers:
        return None
    if height == 0:
        return tiers[0][0]
    sized = [(quality, size) for quality, item in tiers
             if (size := _tier_size(item, quality, bili=bili)) is not None]
    if not sized:
        return tiers[0][0] if len(tiers) == 1 else None
    return min(sized, key=lambda tier: (abs(tier[1] - height), tier[1]))[0]
