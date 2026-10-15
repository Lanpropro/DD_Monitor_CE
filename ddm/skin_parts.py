"""Declarative appearance slots shared by local settings and ordinary plugins."""
from copy import deepcopy
from pathlib import Path
import re
from functools import lru_cache

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (QDialog, QMenu, QPushButton, QStyle, QStyleOptionButton,
                              QStyleOptionToolButton, QToolButton)

PARTS = {
    'sidebar': '关注栏底板', 'folders': '文件夹', 'controls': '播放底部控制条',
    'settings': '设置窗口', 'settings.navigation': '设置导航', 'settings.content': '设置内容区',
    'menus': '菜单', 'layout_menu': '布局预设菜单', 'dialogs': '普通对话框', 'notices': '提示条', 'buttons': '通用按钮',
    'buttons.pause': '暂停／播放', 'buttons.volume': '音量／静音',
    'buttons.danmaku': '弹幕开关', 'buttons.danmaku_settings': '弹幕设置',
    'buttons.recording': '录制', 'buttons.fullscreen': '全屏',
    'buttons.sort': '关注排序', 'buttons.refresh': '关注刷新',
    'buttons.appearance': '深浅色切换', 'buttons.sidebar_toggle': '展开／收起关注栏',
    'buttons.settings': '打开设置', 'buttons.layout': '布局预设',
    'buttons.import': '导入关注', 'buttons.add': '添加直播间',
}
STATES = ('hover', 'pressed', 'checked', 'disabled', 'muted', 'paused')
COLORS = ('background', 'foreground', 'border_color')
ASSETS = ('image', 'icon')
NUMBERS = {'radius': (0, 32), 'border_width': (0, 4)}
_active = False
_package = {}
_personal = {}


@lru_cache(maxsize=128)
def _validate_image(path, modified, size):
    from .skins import validate_asset
    validate_asset(path)


def validate_parts(parts, root):
    """Validate both plugin-relative and local managed asset paths; never accept QSS."""
    from .skins import IMAGES
    if not isinstance(parts, dict):
        raise ValueError('parts 必须是分区对象')
    root = Path(root).resolve()
    def style(values, nested=True):
        if not isinstance(values, dict):
            raise ValueError('分区样式必须是对象')
        result = {}
        for key, value in values.items():
            if key == 'builtin' and nested:
                if type(value) is not bool:
                    raise ValueError('builtin 必须是布尔值')
            elif key in COLORS:
                if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?', value):
                    raise ValueError('颜色须为 #RRGGBB 或 #AARRGGBB')
            elif key in NUMBERS:
                low, high = NUMBERS[key]
                if type(value) is not int or not low <= value <= high:
                    raise ValueError(f'{key} 必须在 {low}–{high} 之间')
            elif key in ASSETS:
                if not isinstance(value, str):
                    raise ValueError('图片路径必须是字符串')
                relative = Path(value)
                path = (root / relative).resolve()
                if relative.is_absolute() or not path.is_relative_to(root):
                    raise ValueError('分区图片必须位于素材目录内')
                if path.suffix.lower() not in IMAGES or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError('分区素材须为不超过 8MB 的 PNG/JPEG/WebP/BMP 图片')
                stat = path.stat()
                _validate_image(str(path), stat.st_mtime_ns, stat.st_size)
                value = str(path)
            elif nested and key in (*STATES, 'dark', 'light'):
                value = style(value, nested=False)
            else:
                raise ValueError(f'不支持的样式字段：{key}')
            result[key] = value
        return result
    result = {}
    for part, values in parts.items():
        if part not in PARTS:
            raise ValueError(f'不支持的美化分区：{part}')
        result[part] = style(values)
        # 侧栏只开放底板，不能通过继承文字颜色改动关注卡片。
        if part == 'sidebar' and any('foreground' in entry for entry in
                [result[part], *(v for v in result[part].values() if isinstance(v, dict))]):
            raise ValueError('关注栏底板不支持修改文字颜色')
    return result


def configure(package, personal):
    global _active, _package, _personal
    if package == _package and personal == _personal:
        return
    _package, _personal = deepcopy(package), deepcopy(personal)
    _active = bool(package or personal)
    _values.cache_clear()
    from . import theme
    theme.apply(theme.mode())


def part_for(widget):
    explicit = widget.property('skinPart')
    if explicit:
        return explicit
    name = widget.objectName()
    part = {'Sidebar': 'sidebar', 'TileBottom': 'controls', 'SettingsNav': 'settings.navigation',
            'SettingsStack': 'settings.content', 'UpdateNotice': 'notices'}.get(name)
    if part:
        return part
    if type(widget).__name__ == 'FollowFolderButton':
        return 'folders'
    if type(widget).__name__ == 'SettingsDialog':
        return 'settings'
    if name == 'LayoutPicker':
        return 'layout_menu'
    if isinstance(widget, QMenu):
        return 'menus'
    if name == 'PresetManageButton':
        return 'buttons'
    if isinstance(widget, QDialog):
        return 'dialogs'
    if isinstance(widget, QPushButton):
        parent = widget.parentWidget()
        while parent:
            if isinstance(parent, QDialog) or parent.objectName() == 'LayoutPicker':
                return 'buttons'
            parent = parent.parentWidget()
    return ''


def values_for(part):
    from . import theme
    return deepcopy(_values(part, theme.is_light()))


@lru_cache(maxsize=64)
def _values(part, light):
    return resolve_values(part, light, _personal)


def resolve_values(part, light, personal):
    """Resolve a preview without changing the application's active appearance."""
    result = {}
    for layer in (_package, personal):
        keys = ('buttons', part) if part.startswith('buttons.') else (('menus', part) if part == 'layout_menu' else (part,))
        for key in keys:
            values = layer.get(key, {})
            if values.get('builtin'):
                result.clear()
            for entry in (values, values.get('light' if light else 'dark', {})):
                for name, value in entry.items():
                    if name in ('dark', 'light', 'builtin'):
                        continue
                    if isinstance(value, dict):
                        result.setdefault(name, {}).update(value)
                    else:
                        result[name] = value
    if part in ('settings.navigation', 'settings.content') and 'image' in resolve_values('settings', light, personal):
        root = personal.get('settings', {})
        mode = 'light' if light else 'dark'
        personal_wallpaper = 'image' in root or 'image' in root.get(mode, {})
        layers = (personal,) if personal_wallpaper else (_package, personal)
        separate_background = any(
            values.get('builtin') or any(field in entry for field in ('image', 'background'))
            for layer in layers for values in (layer.get(part, {}),)
            for entry in (values, values.get(mode, {})))
        if not separate_background:
            result.pop('image', None)
            result['background'] = '#00000000'
    return result


def _declarations(values):
    rules = []
    for key, css in (('background', 'background-color'), ('foreground', 'color'), ('border_color', 'border-color')):
        if key in values:
            rules.append(f'{css}: {QColor(values[key]).name(QColor.HexArgb)};')
    for key, css in (('radius', 'border-radius'), ('border_width', 'border-width')):
        if key in values:
            rules.append(f'{css}: {values[key]}px;')
    if 'border_color' in values or 'border_width' in values:
        rules.append('border-style: solid;')
    if 'image' in values:
        path = values['image'].replace('\\', '/').replace('"', '%22')
        rules.append(f'border-image: url("{path}") 0 0 0 0 stretch stretch;')
    return ''.join(rules)


def style_for(widget, *, personal=None, light=None):
    if not _active and personal is None:
        return ''
    part = part_for(widget)
    if not part:
        return ''
    # Mark only this widget; never apply a descendant-wide card/video rule.
    if widget.property('skinPart') != part:
        widget.setProperty('skinPart', part)
    values = values_for(part) if personal is None else resolve_values(part, light, personal)
    name = widget.objectName()
    selector = (f'#{name}' if name else '*') + f'[skinPart="{part}"]'
    rules = _declarations(values)
    result = f'{selector} {{{rules}}}' if rules else ''
    if 'foreground' in values and part in ('controls', 'settings', 'settings.content', 'dialogs', 'notices'):
        result += f'{selector} QLabel {{color: {QColor(values["foreground"]).name(QColor.HexArgb)};}}'
    if part == 'layout_menu':
        return result
    for state in ('hover', 'pressed', 'checked', 'disabled'):
        rules = _declarations(values.get(state, {}))
        if rules:
            if part == 'menus' and state in ('checked', 'hover'):
                suffix = '::item:selected'
            elif part == 'settings.navigation' and state in ('checked', 'hover'):
                suffix = '::item:selected' if state == 'checked' else '::item:hover'
            else:
                suffix = ':' + state
            result += f'{selector}{suffix} {{{rules}}}'
    return result


def icon_path(widget):
    values = values_for(part_for(widget))
    for state, active in (('muted', getattr(widget, 'muted', False)),
                          ('paused', getattr(widget, 'paused', False)),
                          ('checked', getattr(widget, 'isChecked', lambda: False)()),
                          ('hover', widget.underMouse()),
                          ('pressed', getattr(widget, 'isDown', lambda: False)()),
                          ('disabled', not widget.isEnabled())):
        if active:
            values.update(values.get(state, {}))
    return values.get('icon', '')


def paint_button(widget):
    if not _active or not isinstance(widget, (QPushButton, QToolButton)):
        return False
    path = icon_path(widget)
    if not path:
        return False
    icon = QIcon(path)
    if icon.isNull():
        return False
    tool = isinstance(widget, QToolButton)
    option = QStyleOptionToolButton() if tool else QStyleOptionButton()
    widget.initStyleOption(option)
    option.icon = icon
    option.iconSize = QSize(18, 18)
    if tool and option.toolButtonStyle == Qt.ToolButtonTextOnly:
        option.toolButtonStyle = Qt.ToolButtonTextBesideIcon
    if widget.property('skinIconOnly'):
        option.text = ''
    if widget.property('skinPart') == 'buttons.volume':
        option.text = {3: 'L', 4: 'R'}.get(getattr(widget, 'audio_channel', 0), '')
    painter = QPainter(widget)
    if tool:
        widget.style().drawComplexControl(QStyle.CC_ToolButton, option, painter, widget)
    else:
        widget.style().drawControl(QStyle.CE_PushButton, option, painter, widget)
    return True
