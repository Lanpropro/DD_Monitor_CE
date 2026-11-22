"""Plugin package identity rules and metadata validation."""
import json
import os
import re
from dataclasses import field


PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_]*$")


PLUGIN_INVENTORY = '.ddm-plugin-files.txt'


RETIRED_BUNDLED_PLUGINS = frozenset({"danmaku_log", "bili_live"})


RENAMED_PLUGINS = {"huya_watch": "domestic_live"}


def read_manifest(folder: str, expected_id: str) -> dict | None:
    """读取新格式元数据；没有清单的旧插件仍可按原方式装载。"""
    path = os.path.join(folder, "plugin.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("id") != expected_id:
        raise ValueError("plugin.json 的 id 必须与目录名一致")
    for field in ("name", "description", "version"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"plugin.json 缺少非空字符串 {field}")
    for key in ('platforms', 'replaces_platforms', 'inherit_settings'):
        if key in data and (not isinstance(data[key], list) or
                not all(isinstance(value, str) and value and '\n' not in value for value in data[key]) or
                len(set(data[key])) != len(data[key])):
            raise ValueError(f'plugin.json 的 {key} 必须是不重复的非空字符串列表')
    if 'replaces' in data and (not isinstance(data['replaces'], str) or
            not PLUGIN_ID.fullmatch(data['replaces']) or data['replaces'] == expected_id or
            not data.get('platforms')):
        raise ValueError('plugin.json 的 replaces 必须指向其他插件并声明 platforms')
    if 'skin' in data:
        from types import SimpleNamespace
        from .skins import plugin_skin
        plugin_skin(SimpleNamespace(skin=data['skin'], name=data['name'],
            context=SimpleNamespace(name=expected_id)), folder)
    return data
