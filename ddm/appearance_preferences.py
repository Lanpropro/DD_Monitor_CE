"""Validated personal theme tokens, independent of playback and skin ownership."""
import re

DEFAULTS = {'appearance_accent': '', 'appearance_font': '', 'appearance_font_size': 13}


def normalize(values):
    accent = values.get('appearance_accent', '')
    font = values.get('appearance_font', '')
    try:
        size = max(11, min(20, int(values.get('appearance_font_size', 13))))
    except (TypeError, ValueError, OverflowError):
        size = 13
    return {
        'appearance_accent': accent.lower() if isinstance(accent, str) and
            re.fullmatch(r'#[0-9a-fA-F]{6}', accent) else '',
        'appearance_font': font.strip() if isinstance(font, str) and
            len(font) <= 100 and re.fullmatch(r'[\w .\-]*', font) else '',
        'appearance_font_size': size,
    }
