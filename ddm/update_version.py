"""Public versions and internal hotfix revisions, shared by checks and installers."""
import json
from pathlib import Path
import re


def version_key(value):
    text = str(value).removeprefix('v')
    if not re.fullmatch(r'\d+(?:\.\d+){0,3}', text):
        raise ValueError('版本号必须使用数字，例如 0.3 或 0.3.1')
    parts = tuple(map(int, text.split('.')))
    return parts + (0,) * (4 - len(parts))


def revision(value=0):
    if type(value) is not int or value < 0:
        raise ValueError('更新修订号必须是非负整数')
    return value


def app_tag(value):
    match = re.fullmatch(r'v?(\d+(?:\.\d+){0,3})(-hotfix(?:\.(\d+))?)?', str(value))
    if match is None:
        raise ValueError('本体标签必须是正式版本或 -hotfix.N')
    number = int(match[3] or '1') if match[2] else 0
    if match[2] and not number:
        raise ValueError('Hotfix 标签修订号从 1 开始')
    return match[1], number


def update_key(version, number=0):
    return version_key(version), revision(number)


def installed_revision(root, current_version):
    try:
        build = json.loads((Path(root)/'ddm-build.json').read_text(encoding='utf-8-sig'))
        if version_key(build['version']) == version_key(current_version):
            return revision(build.get('revision', 0))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 0


def update_identity(offer):
    number = revision(offer.get('revision', 0))
    return offer['version'] + (f'+hotfix.{number}' if number else '')


def release_label(offer):
    return offer['version'] + (' 热修复' if revision(offer.get('revision', 0)) else '')
