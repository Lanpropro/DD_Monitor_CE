"""Compact quality labels for menus and playback controls."""
from collections import Counter
import re

from .streamer_defaults import BILI_SIZES


_DIMENSIONS = re.compile(r'(?<!\d)(\d{3,4})\s*[x×]\s*(\d{3,4})(?!\d)', re.IGNORECASE)
_RESOLUTION = re.compile(r'(?<!\d)(?:(\d{3,4})\s*p|([24])\s*k)', re.IGNORECASE)
_FPS = re.compile(r'(?<!\d)(\d{2,3}(?:\.\d+)?)\s*(?:fps|帧)', re.IGNORECASE)
_JOINED_FPS = re.compile(r'^(?:\s*@\s*)?(\d{2,3}(?:\.\d+)?)(?![a-z\d.])', re.IGNORECASE)
_QUALIFIER = re.compile(r'原画|蓝光|高码率|低码率|\d+(?:\.\d+)?\s*(?:Mbps|kbps|M)(?![a-z\d])', re.IGNORECASE)


def compact_quality_label(option, *, bili=False, actual_resolution=''):
    raw = str(option.get('label') or option.get('desc') or option['qn'])
    details = ' '.join(str(option.get(key) or '') for key in ('resolution', 'desc', 'label'))
    advertised = _RESOLUTION.search(details)
    dimensions = _DIMENSIONS.search(actual_resolution) or _DIMENSIONS.search(details)
    if dimensions:
        height = min(map(int, dimensions.groups()))
    elif advertised:
        pixels, k = advertised.groups()
        height = int(pixels) if pixels else (1440 if k == '2' else 2160)
    else:
        height = BILI_SIZES.get(int(option['qn'])) if bili else None
    if not height:
        return raw if len(raw) <= 18 else raw[:18] + '…'
    label = {1440: '2K', 2160: '4K'}.get(height, f'{height}P')
    fps = _FPS.search(details)
    if fps is None and advertised:
        fps = _JOINED_FPS.match(details[advertised.end():])
    if not fps:
        return label
    rate = fps[1].rstrip('0').rstrip('.') if '.' in fps[1] else fps[1]
    return f'{label} · {rate}FPS'


def distinguish_quality_labels(labels, options):
    """Keep different options selectable when they share a resolution and frame rate."""
    counts = Counter(labels)
    results = []
    for label, option in zip(labels, options):
        if counts[label] > 1:
            details = str(option.get('desc') or option.get('label') or '')
            qualifier = _QUALIFIER.search(details)
            label = f'{label} · {qualifier[0] if qualifier else option["qn"]}'
        results.append(label)
    remaining = Counter(results)
    return [f'{label} · {option["qn"]}' if remaining[label] > 1 else label
            for label, option in zip(results, options)]
