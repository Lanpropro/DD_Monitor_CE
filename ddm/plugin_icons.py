"""Validate small package PNGs before decoding them in plugin cards."""
import base64
import binascii


ICON_MAX_BYTES = 64 * 1024
ICON_MAX_PIXELS = 512
_PNG_IHDR = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'


def _valid_icon(data):
    return (33 <= len(data) <= ICON_MAX_BYTES and data.startswith(_PNG_IHDR)
            and all(0 < int.from_bytes(data[offset:offset + 4], 'big') <= ICON_MAX_PIXELS
                    for offset in (16, 20)))


def package_icon(folder, name):
    if (not isinstance(name, str) or not name.lower().endswith('.png')
            or any(char in name for char in ('\\', ':', '\x00', '\r', '\n'))
            or any(part in ('', '.', '..') for part in name.split('/'))):
        return ''
    try:
        folder = folder.resolve()
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            return ''
        with path.open('rb') as source:
            data = source.read(ICON_MAX_BYTES + 1)
    except OSError:
        return ''
    return base64.b64encode(data).decode('ascii') if _valid_icon(data) else ''


def decode_catalog_icon(value):
    if not isinstance(value, str) or not 0 < len(value) <= 4 * ((ICON_MAX_BYTES + 2) // 3):
        return b''
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return b''
    return data if _valid_icon(data) else b''
