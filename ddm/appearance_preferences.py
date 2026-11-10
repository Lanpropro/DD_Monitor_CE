"""Validated personal theme tokens, independent of playback and skin ownership."""
import re

DEFAULTS = {'appearance_accent': '', 'appearance_font': ''}


def normalize(values):
    accent = values.get('appearance_accent', '')
    font = values.get('appearance_font', '')
    return {
        'appearance_accent': accent.lower() if isinstance(accent, str) and
            re.fullmatch(r'#[0-9a-fA-F]{6}', accent) else '',
        'appearance_font': font.strip() if isinstance(font, str) and
            len(font) <= 100 and re.fullmatch(r'[\w .\-]*', font) else '',
    }
