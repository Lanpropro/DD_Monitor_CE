"""Resolve a wall-wide resolution ceiling to each room's ordered quality IDs."""
from dataclasses import dataclass

from .streamer_defaults import BILI_SIZES, tier_size
from .widget_support import QUALITY_CHOICES


WALL_QUALITY_CHOICES = ((0, '最高可用'), (2160, '4K · 2160P'), (1440, '2K · 1440P'),
                        (1080, '1080P'), (720, '720P'), (480, '480P'), (360, '360P'))


@dataclass(frozen=True)
class WallQualityRequest:
    ceiling: int
    tiers: tuple[int, ...]


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
               if (size := tier_size(item, quality, bili=bili)) is not None and size <= height]
    allowed.sort(key=lambda tier: -tier[1])
    return WallQualityRequest(height, tuple(dict.fromkeys(quality for quality, _ in allowed)))


def allows_wall_quality(tile, request, quality, options):
    if not request.ceiling or not quality:
        return True
    bili = str(tile.room.get('room_id') or '').isdigit()
    sizes = dict(BILI_SIZES) if bili else {}
    for candidate, item in _tiers([*tile.quality_options, *(options or ())]):
        if (size := tier_size(item, candidate, bili=bili)) is not None:
            sizes[candidate] = size
    ceiling = min(request.ceiling, sizes.get(request.tiers[0], request.ceiling))
    if quality in sizes:
        size = sizes[quality]
        return size <= ceiling and not any(sizes.get(candidate, 0) > size for candidate in request.tiers[1:])
    return quality in request.tiers
