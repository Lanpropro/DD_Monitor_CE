"""Resolve a wall-wide resolution ceiling to each room's ordered quality IDs."""
from dataclasses import dataclass
import re

from .widget_support import QUALITY_CHOICES


WALL_QUALITY_CHOICES = ((0, '最高可用'), (2160, '4K · 2160P'), (1440, '2K · 1440P'),
                        (1080, '1080P'), (720, '720P'), (480, '480P'), (360, '360P'))
_BILI_SIZES = {20000: 2160, 15000: 1440, 400: 1080, 250: 720, 150: 480, 80: 360}
_NAMED_TIERS = (('4k', 2160), ('2k', 1440), ('蓝光', 1080), ('超清', 720),
                ('高清', 540), ('标清', 480), ('流畅', 360))


@dataclass(frozen=True)
class WallQualityRequest:
    ceiling: int
    tiers: tuple[int, ...]


def _tier_size(option, quality, *, bili):
    name = ' '.join(str(option.get(key) or '') for key in ('desc', 'label', 'resolution')).lower()
    dimensions = re.search(r'(\d{3,4})\s*[x×]\s*(\d{3,4})', name)
    if dimensions:
        return min(map(int, dimensions.groups()))
    pixels = re.search(r'(?<!\d)(\d{3,4})\s*p', name)
    if pixels:
        return int(pixels[1])
    if bili and quality in _BILI_SIZES:
        return _BILI_SIZES[quality]
    # Providers with no dimensions may still give a comparable quality tier name.
    return next((size for name_part, size in _NAMED_TIERS if name_part in name), None)


def _tiers(options):
    for item in options:
        try:
            quality = int(item['qn'])
        except (KeyError, TypeError, ValueError):
            continue
        if quality > 0:
            yield quality, item


def wall_quality_request(tile, height):
    bili = str(tile.room.get('room_id') or '').isdigit()
    options = tile.quality_options
    if not options and bili:
        options = [{'qn': quality, 'desc': label} for label, quality in
                   (*QUALITY_CHOICES[:1], ('4K', 20000), ('2K', 15000), *QUALITY_CHOICES[1:])]
    tiers = list(_tiers(options))
    if height == 0:
        return WallQualityRequest(height, tuple(dict.fromkeys(quality for quality, _ in tiers)))
    allowed = [(quality, size) for quality, item in tiers
               if (size := _tier_size(item, quality, bili=bili)) is not None and size <= height]
    allowed.sort(key=lambda tier: -tier[1])
    return WallQualityRequest(height, tuple(dict.fromkeys(quality for quality, _ in allowed)))


def allows_wall_quality(tile, request, quality, options):
    if not request.ceiling or not quality:
        return True
    bili = str(tile.room.get('room_id') or '').isdigit()
    sizes = dict(_BILI_SIZES) if bili else {}
    for candidate, item in _tiers([*tile.quality_options, *(options or ())]):
        if (size := _tier_size(item, candidate, bili=bili)) is not None:
            sizes[candidate] = size
    ceiling = min(request.ceiling, sizes.get(request.tiers[0], request.ceiling))
    if quality in sizes:
        size = sizes[quality]
        return size <= ceiling and not any(sizes.get(candidate, 0) > size for candidate in request.tiers[1:])
    return quality in request.tiers
