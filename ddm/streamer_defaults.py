"""Saved room defaults and resolution matching for playback and recording."""
import re


QUALITY_LEVELS = ((0, '最高可用'), (2160, '4K · 2160P'), (1440, '2K · 1440P'),
                  (1080, '1080P'), (720, '720P'), (540, '540P'), (480, '480P'), (360, '360P'))
QUALITY_LABELS = dict(QUALITY_LEVELS)
BILI_SIZES = {20000: 2160, 15000: 1440, 400: 1080, 250: 720, 150: 480, 80: 360}
NAMED_TIERS = (('4k', 2160), ('2k', 1440), ('蓝光', 1080), ('超清', 720),
               ('高清', 540), ('标清', 480), ('流畅', 360))


def room_defaults(settings, room_id):
    saved = settings.get('streamer_defaults')
    row = saved.get(str(room_id)) if isinstance(saved, dict) else None
    if not isinstance(row, dict):
        return {}
    values = {key: True for key in ('auto_record', 'windows_recording_notice', 'windows_live_notice')
              if row.get(key) is True}
    if isinstance(row.get('monitor_live'), bool) or monitors_live(row):
        values['monitor_live'] = monitors_live(row)
    mode = row.get('auto_record_mode')
    if mode in ('normal', 'clip'):
        values['auto_record_mode'] = mode
    for key in ('playback', 'recording'):
        level = row.get(key)
        if isinstance(level, dict):
            qn = level.get('qn')
            if type(qn) is int and (0 < qn < 2 ** 31 or key == 'playback' and qn == -1):
                values[key] = {'qn': qn, 'label': str(level.get('label') or qn)}
        elif type(level) is int and level in QUALITY_LABELS:
            values[key] = level
    volume = row.get('volume')
    if type(volume) is int and 0 <= volume <= 100:
        values['volume'] = volume
    return values


def monitors_live(row):
    enabled = row.get('monitor_live')
    if isinstance(enabled, bool):
        return enabled
    return row.get('auto_record') is True or row.get('windows_live_notice') is True


def monitored_streamers(settings):
    saved = settings.get('streamer_defaults')
    if not isinstance(saved, dict):
        return {}
    return {room_id: row for room_id, row in saved.items()
            if isinstance(room_id, str) and room_id and isinstance(row, dict) and monitors_live(row)}


def streamer_profile_group(row):
    """Match the settings cards by their displayed quality and recording preferences."""
    qualities = []
    for key in ('playback', 'recording'):
        value = row.get(key)
        label = value['label'] if isinstance(value, dict) else QUALITY_LABELS.get(value, '继承')
        qualities.append(label.strip().casefold() if key in row else None)
    return (*qualities, row.get('volume'), monitors_live(row), bool(row.get('auto_record')),
            bool(row.get('windows_recording_notice')), bool(row.get('windows_live_notice')),
            row.get('auto_record_mode'))


def source_quality_option(options):
    """A sole zero entry describes source-controlled quality without a manual tier."""
    if options and len(options) == 1 and options[0].get('qn') == 0:
        return options[0]
    return None


def native_quality_options(options):
    choices = {}
    for item in options or ():
        try:
            qn = int(item['qn'])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if qn == -1 or 0 < qn < 2 ** 31:
            label = str(item.get('desc') or item.get('label') or qn)
            choices.setdefault(qn, {'qn': qn, 'label': label})
    return list(choices.values())


def tier_size(option, quality, *, bili):
    name = ' '.join(str(option.get(key) or '') for key in ('desc', 'label', 'resolution')).lower()
    dimensions = re.search(r'(\d{3,4})\s*[x×]\s*(\d{3,4})', name)
    if dimensions:
        return min(map(int, dimensions.groups()))
    pixels = re.search(r'(?<!\d)(\d{3,4})\s*p', name)
    if pixels:
        return int(pixels[1])
    if bili and quality in BILI_SIZES:
        return BILI_SIZES[quality]
    return next((size for prefix, size in NAMED_TIERS if prefix in name), None)


def quality_tiers(room_id, options, height, *, allow_lower):
    bili = str(room_id).isdigit()
    comparable = []
    for option in options or ():
        try:
            quality = int(option['qn'])
        except (KeyError, TypeError, ValueError):
            continue
        if quality <= 0:
            continue
        size = tier_size(option, quality, bili=bili)
        if height == 0 or size == height or (allow_lower and size is not None and size < height):
            comparable.append((quality, size))
    if height == 0:
        # Plugin menus may put a synthetic “最高可用” selector ahead of their real tiers.
        return tuple(dict.fromkeys(quality for quality, size in comparable
                                   if bili or quality != 10000 or size is not None)) or tuple(
                                       quality for quality, _ in comparable)
    comparable.sort(key=lambda row: -row[1])
    return tuple(dict.fromkeys(quality for quality, _ in comparable))
