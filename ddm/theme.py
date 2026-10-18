"""设计令牌与全局样式。

配色与尺度参考 BewlyCat（暗色体系）：基色 #2a2d32 派生背景/卡片/浮层，
主题色取 B 站蓝，强调色取 B 站粉。

Qt 没有真正的背景模糊，这里用半透明叠加 + 细描边模拟玻璃质感，
避免玻璃效果带来的 GPU 开销（本项目以低占用为优先）。
"""


import os
import re
import sys
from functools import lru_cache
from weakref import WeakKeyDictionary

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget


def qcolor(value, fallback: str = "#000000") -> QColor:
    """把主题里的颜色变成 QColor。

    主题常量有两种写法：`#rrggbb` 和 CSS 的 `rgba(r, g, b, a)`。注意
    **`QColor("rgba(...)")` 解析不了**，它不抛错、直接给出无效色（画出来是黑的）——
    以前 `QColor(theme.TEXT3)` 这类调用就踩了这个坑（布局缩略图里的占位格子、
    描边全是黑的）。要画主题色一律走这里。
    """
    text = str(value or "").strip()
    if text.lower().startswith("rgba(") and text.endswith(")"):
        parts = [item.strip() for item in text[5:-1].split(",")]
        if len(parts) == 4:
            try:
                red, green, blue = (int(round(float(item))) for item in parts[:3])
                alpha = int(round(float(parts[3]) * 255))
            except ValueError:
                return QColor(fallback)
            clamp = lambda item: max(0, min(255, item))       # noqa: E731
            return QColor(clamp(red), clamp(green), clamp(blue), clamp(alpha))
    colour = QColor(text)
    return colour if colour.isValid() else QColor(fallback)


ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """按比例把 color_a 向 color_b 混合，ratio=0 返回 color_a。"""
    a = _rgb(color_a)
    b = _rgb(color_b)
    return "#%02x%02x%02x" % tuple(_clamp(x + (y - x) * ratio) for x, y in zip(a, b))


def asset(name: str) -> str:
    """QSS 里引用图片用的路径（必须用正斜杠，Windows 的反斜杠 Qt 认不出来）。"""
    return os.path.join(ASSETS_DIR, name).replace("\\", "/")


BASE = "#2a2d32"
TILE_FULLSCREEN_STYLE = '''
#Tile[fullscreen="true"],
#Tile[fullscreen="true"]:hover,
#Tile[fullscreen="true"][focused="true"] {
    border: none;
    border-radius: 0px;
}
'''

BG = mix(BASE, "#000000", 0.20)
SIDEBAR = mix(BASE, "#000000", 0.30)
CONTENT = mix(BASE, "#ffffff", 0.03)
CONTENT_HOVER = mix(BASE, "#ffffff", 0.08)
ELEVATED = mix(BASE, "#ffffff", 0.06)
TILE_BG = "#101114"

ACCENT = "#00a1d6"
ACCENT_SOFT = "rgba(0, 161, 214, 0.16)"
PINK = "#fb7299"
SUCCESS = "#29a383"
WARNING = "#f59e0b"
ERROR = "#e5484d"

TEXT1 = "#f1f2f5"
TEXT2 = "rgba(214, 218, 224, 0.90)"
TEXT3 = "rgba(184, 189, 197, 0.75)"
TEXT4 = "rgba(170, 175, 184, 0.55)"

BORDER = "rgba(131, 131, 145, 0.16)"
BORDER_STRONG = "rgba(255, 255, 255, 0.12)"

FONT_DEFAULT = "Microsoft YaHei UI"
FONT_FAMILY = f'"{FONT_DEFAULT}", "Microsoft YaHei", "Segoe UI", sans-serif'

FONT_CAPTION = 12
FONT_CONTROL = 13
FONT_BODY = 15
FONT_HEADING = 20

RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_LG = 12
RADIUS_XL = 16

SIDEBAR_WIDTH = 248
SIDEBAR_RAIL_WIDTH = 60
CONTROL_HEIGHT = 34
TILE_CONTROL_HEIGHT = 26
AVATAR_SIZE = 32              # 关注列表里的头像尺寸（收起侧栏后账号头像也用这个）
SCROLLBAR_SIZE = 8            # 滚动条粗细（两轴同一个值；横排列表要按它留高度）


_DARK = {name: globals()[name] for name in (
    "BG", "SIDEBAR", "CONTENT", "CONTENT_HOVER", "ELEVATED", "TEXT1", "TEXT2",
    "TEXT3", "TEXT4", "BORDER", "BORDER_STRONG", "ACCENT", "ACCENT_SOFT")}
_LIGHT = dict(BG="#F4F6F9", SIDEBAR="#EBEEF3", CONTENT="#FFFFFF",
    CONTENT_HOVER="#E7EFF7", ELEVATED="#FFFFFF", TEXT1="#202630", TEXT2="#4A5565",
    TEXT3="#5E6A7D", TEXT4="#7A8596", BORDER="#D7DDE7", BORDER_STRONG="#BCC6D5",
    ACCENT="#007BA8", ACCENT_SOFT="rgba(0, 123, 168, 0.12)")
_mode = "dark"
_light = False
_styles = WeakKeyDictionary()
_signals = None
_skin_active = False
_skin_sidebar = False


def set_skin_active(active, sidebar=False):
    global _skin_active, _skin_sidebar
    active, sidebar = bool(active), bool(sidebar)
    if (_skin_active, _skin_sidebar) != (active, sidebar):
        _skin_active, _skin_sidebar = active, sidebar
        apply(_mode)


def _skin_style(widget):
    if not _skin_active:
        return ''
    name = widget.objectName()
    if name == 'Sidebar' and not _skin_sidebar:
        return ''
    if name == 'Root':
        return '#Root {background: transparent;}'
    if name in ('WallGrid', 'TileVideo'):
        return (f'#{name}[appearanceLight="false"], #{name}[appearanceLight="true"] '
                '{background: transparent;}')
    colors = {'Sidebar': 'SIDEBAR', 'Tile': 'BG',
              'TileBottom': 'BG', 'DanmakuPanel': 'CONTENT'}
    if name not in colors:
        return ''
    opacity = .84 if name in ('Sidebar', 'Tile') else .88
    rules = []
    for mode, palette in (('false', _DARK), ('true', _LIGHT)):
        color = qcolor(palette[colors[name]])
        selector = '#' + name + f'[appearanceLight="{mode}"]'
        if name == 'Tile':
            selector += ', ' + selector + '[empty="true"]'
        rules.append(f'{selector} {{background: rgba({color.red()}, {color.green()}, {color.blue()}, {opacity});}}')
    return ''.join(rules)


# Stable QSS reads colours from the palette; switching no longer re-polishes
# every widget's fonts, metrics and layout through QApplication.setStyleSheet.
_PALETTE_ROLES = dict(zip(_DARK, (
    'window', 'alternate-base', 'base', 'button', 'tooltip-base',
    'window-text', 'text', 'button-text', 'tooltip-text', 'mid', 'dark',
    'highlight', 'light')))
_MIX_ROLES = {('ACCENT', '#ffffff', .35): 'midlight',
    ('CONTENT', '#000000', .12): 'shadow',
    ('ACCENT', '#ffffff', .12): 'link',
    ('ACCENT', '#000000', .16): 'link-visited'}


def _apply_palette(app, colors):
    palette = QPalette()
    roles = {name.lower().replace('_', '').replace('-', ''): role
        for name, role in QPalette.ColorRole.__members__.items()}
    values = {role: colors[name] for name, role in _PALETTE_ROLES.items()}
    values.update({role: mix(colors[name], other, ratio)
        for (name, other, ratio), role in _MIX_ROLES.items()})
    for name, color in values.items():
        parsed = qcolor(color)
        if color.startswith('rgba('):
            parsed.setAlpha(int(float(color[5:-1].split(',')[-1]) * 255))
        palette.setColor(roles[name.replace('-', '')], parsed)
    app.setPalette(palette.resolve(app.palette()))
    for widget in app.allWidgets():
        widget.setPalette(palette.resolve(widget.palette()))
        refresh_theme_properties(widget)
    # Clear cached palette-dependent paint rules once, without re-polishing
    # every widget or resetting its geometry and fonts.
    app.style().unpolish(app)
    app.style().polish(app)


def refresh_theme_properties(widget):
    # The light exceptions are installed once. Change the selector property,
    # not hundreds of local stylesheets, and invalidate only affected widgets.
    name = widget.objectName()
    if name not in ('BadgeOff', 'NavThumbCover', 'NavThumbHint', 'Search', 'PrimaryButton', 'Sidebar',
                    'Tile', 'TileVideo', 'DanmakuPanel', 'TileBottom', 'TilePlaceholder',
                    'PauseOverlay', 'DanmakuHeader', 'DanmakuCount', 'DanmakuBody', 'TileCtrl', 'TileToggle', 'WallGrid'):
        return
    if widget.property('appearanceLight') != _light:
        widget.setProperty('appearanceLight', _light)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


@lru_cache(maxsize=32)
def _conditional_light_style(style):
    # Restrict matching to selectors so hexadecimal colour values stay intact.
    rules = []
    for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', style):
        selector = re.sub(r'#[A-Za-z]\w*', lambda match:
            match.group() + '[appearanceLight="true"]', selector)
        rules.append(selector + '{' + body + '}')
    return ''.join(rules)


def _light_style(widget):
    name = widget.objectName()
    if name == 'TileToggle':
        return _conditional_light_style('#TileToggle {background: transparent; color: #4A5565; border: none;} #TileToggle:hover, #TileToggle[hovered="true"] {background: #E7EFF7; color: #007BA8;}')
    if name == 'TileCtrl':
        parent = widget.parentWidget()
        while parent is not None and parent.objectName() != 'TileBottom':
            parent = parent.parentWidget()
        if parent is not None:
            return _conditional_light_style('#TileCtrl {background: transparent; color: #4A5565; border: none;} #TileCtrl:hover, #TileCtrl[hovered="true"] {background: #E7EFF7; color: #007BA8;} #TileCtrl:checked {background: #DDF3FB; color: #007BA8;} #TileCtrl[recording="true"] {color: #E5484D;}')
        return _conditional_light_style('#TileCtrl {background: #F7F9FC; color: #202630; border: 1px solid #D7DDE7;} #TileCtrl:hover, #TileCtrl[hovered="true"] {background: #E7EFF7; color: #007BA8;} #TileCtrl[recording="true"] {color: #E5484D;}')
    return _conditional_light_style({
        'Search': '#Search {color: #202630; placeholder-text-color: #5E6A7D;}',
        'PrimaryButton': '#PrimaryButton {color: #FFFFFF;} #PrimaryButton[addRoom="true"] {background: #FB7299; color: #202630;} #PrimaryButton[addRoom="true"]:hover {background: #FC87A8;} #PrimaryButton[addRoom="true"]:pressed {background: #EC6089;}',
        'WallGrid': '#WallGrid {background: #E6EBF2;}',
        'Tile': '#Tile, #Tile[empty="true"] {background: #FFFFFF; border: 1px solid #BCC8D8; border-radius: 10px;} #Tile:hover {border-color: #95A7BE;} #Tile[focused="true"] {border-color: #00A1D6;}' + TILE_FULLSCREEN_STYLE,
        'TileVideo': '#TileVideo {background: #FFFFFF;}',
        'DanmakuPanel': '#DanmakuPanel {background: #FFFFFF;}',
        'TileBottom': '#TileBottom {background: #F0F3F8; border: none; border-top: 1px solid #D7DDE7; border-top-left-radius: 0; border-top-right-radius: 0; border-bottom-left-radius: 9px; border-bottom-right-radius: 9px;} #TileBottom QLabel {color: #4A5565;}',
        'TilePlaceholder': '#TilePlaceholder {color: #4A5565;}',
        'PauseOverlay': '#PauseOverlay QLabel {color: #F1F2F5;}',
        'DanmakuHeader': '#DanmakuHeader {background: #EBEEF3; border-bottom: 1px solid #D7DDE7;}',
        'DanmakuBar': '#DanmakuBar {background: #EBEEF3; border-top: 1px solid #D7DDE7;}',
        'DanmakuCount': '#DanmakuCount[state="connected"] {color: #007BA8;} #DanmakuCount[state="error"] {color: #B93665;}',
        'DanmakuBody': '#DanmakuBody QScrollBar::handle:vertical {background: #BCC6D5;}',
    }.get(name, ''))


class ThemeSignals(QObject):
    changed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self._repairing_palette = False

    def palette_changed(self, _palette):
        if self._repairing_palette:
            return
        app = QApplication.instance()
        colors = _LIGHT if _light else _DARK
        expected = {QPalette.Window: colors['BG'], QPalette.Base: colors['CONTENT'],
                    QPalette.Button: colors['CONTENT_HOVER'], QPalette.WindowText: colors['TEXT1']}
        if all(app.palette().color(group, role) == qcolor(color)
               for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled)
               for role, color in expected.items()):
            return
        self._repairing_palette = True
        try:
            # Restore synchronously: deferring until the next event-loop turn
            # allows palette-based QSS to paint one frame in the platform colour.
            _apply_palette(app, colors)
            print('[主题] 已拦截外部调色板重置，保持当前模式：' + _mode,
                  file=sys.stderr, flush=True)
        finally:
            self._repairing_palette = False

    def eventFilter(self, widget, event):
        if event.type() == QEvent.Paint and isinstance(widget, QWidget):
            from .skin_parts import paint_button
            if paint_button(widget):
                return True
        # Newly opened settings/popups need the same exceptions as existing UI.
        if event.type() == QEvent.Polish and isinstance(widget, QWidget):
            refresh_theme_properties(widget)
        if event.type() == QEvent.Polish and isinstance(widget, QWidget):
            from .skin_parts import style_for
            extra = _light_style(widget) + _skin_style(widget) + style_for(widget)
            if extra and widget not in _styles:
                source = widget.styleSheet()
                styled = source + '\n' + extra
                _styles[widget] = (source, {name: globals()[name] for name in _DARK}, styled)
                widget.setStyleSheet(styled)
        return False


def signals():
    global _signals
    if _signals is None:
        app = QApplication.instance()
        _signals = ThemeSignals(app)
        app.installEventFilter(_signals)
        app.paletteChanged.connect(_signals.palette_changed)
        app.styleHints().colorSchemeChanged.connect(_system_changed)
    return _signals


def normalize_mode(value):
    return value if value in ("dark", "light", "system") else "dark"


def mode():
    return _mode


def is_light():
    return _light


def overlay_color(dark, light):
    return QColor(light if _light else dark)


def _system_changed(_scheme):
    if _mode == "system":
        apply("system")


def apply(value):
    """重绘主题，不重建控件、播放器或视频窗口。"""
    global _mode, _light
    app = QApplication.instance()
    signals()
    value = normalize_mode(value)
    light = value == "light" or (value == "system" and
        app.styleHints().colorScheme() == Qt.ColorScheme.Light)
    previous = {name: globals()[name] for name in _DARK}
    _mode = value
    _light = light
    palette = _LIGHT if light else _DARK
    widgets = list(app.allWidgets())
    # Keep the source palette of local QSS, so identical light backgrounds can
    # return to their distinct original dark colours without lossy replacement.
    for widget in widgets:
        style = widget.styleSheet()
        saved = _styles.get(widget)
        if not saved or style != saved[2]:
            _styles[widget] = (style, previous, style)
    globals().update(palette)
    _apply_palette(app, palette)
    stable_style = qss(palette_roles=True)
    if app.styleSheet() != stable_style:
        app.setStyleSheet(stable_style)
    patterns = {}
    for widget in widgets:
        source, colors, _last = _styles[widget]
        key = tuple(colors.items())
        if key not in patterns:
            replacements = {old: palette[name] for name, old in colors.items()}
            pattern = re.compile("|".join(re.escape(color) for color in sorted(replacements, key=len, reverse=True)))
            patterns[key] = pattern, replacements
        pattern, replacements = patterns[key]
        styled = pattern.sub(lambda match: replacements[match.group()], source) if source else ''
        from .skin_parts import style_for
        extra = _light_style(widget) + _skin_style(widget) + style_for(widget)
        if extra:
            styled += '\n' + extra
        if styled != widget.styleSheet():
            widget.setStyleSheet(styled)
        _styles[widget] = (source, colors, styled)
        refresh = getattr(widget, "refresh_theme", None)
        if callable(refresh):
            refresh()
        refresh_theme_properties(widget)
        QWidget.update(widget)
    signals().changed.emit(value)


def qss(palette_roles=False) -> str:
    """全局样式表。"""
    colors = {name: globals()[name] for name in _DARK}
    if palette_roles:
        colors = {name: f'palette({role})' for name, role in _PALETTE_ROLES.items()}
    BG, SIDEBAR, CONTENT, CONTENT_HOVER, ELEVATED, TEXT1, TEXT2, TEXT3, TEXT4, BORDER, BORDER_STRONG, ACCENT, ACCENT_SOFT = colors.values()
    def style_mix(name, other, ratio):
        return (f'palette({_MIX_ROLES[name, other, ratio]})' if palette_roles
            else mix(colors[name], other, ratio))
    badge_bg = 'rgba(16, 20, 28, 0.78)' if _light and not palette_roles else 'rgba(131, 131, 145, 0.28)'
    badge_text = '#F1F2F5' if _light and not palette_roles else TEXT2
    cover_text = '#F1F2F5' if _light and not palette_roles else TEXT4
    hint_text = '#F1F2F5' if _light and not palette_roles else TEXT2
    style = f"""
QPushButton#AppearanceChoice {{
    background: {CONTENT}; color: {TEXT2}; border: 1px solid {BORDER}; border-radius: 16px;
}}
QPushButton#AppearanceChoice:checked {{
    background: {ACCENT_SOFT}; color: {ACCENT}; border: 1px solid {ACCENT};
}}
* {{
    font-family: {FONT_FAMILY};
    font-size: {FONT_CONTROL}px;
}}
QWidget {{
    color: {TEXT1};
}}
QMainWindow, #Root {{
    background: {BG};
}}
QDialog {{
    background: {BG};
}}
QDialog QLabel {{
    color: {TEXT1};
}}
QLineEdit {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 6px 10px;
    color: {TEXT1};
    selection-background-color: {ACCENT};
}}
#Search {{
    placeholder-text-color: {TEXT3};
    color: {TEXT1};
}}
QLineEdit:focus {{
    border: 1px solid {ACCENT};
    background: {CONTENT_HOVER};
}}
QCheckBox {{
    color: {TEXT2};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER_STRONG};
    background: {CONTENT};
}}
QCheckBox::indicator:hover {{
    border: 1px solid {ACCENT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}
QSpinBox {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 5px 8px;
    color: {TEXT1};
}}
QSpinBox:focus {{
    border: 1px solid {ACCENT};
    background: {CONTENT_HOVER};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 18px;
    border: none;
    background: transparent;
}}
QComboBox, QFontComboBox {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 5px 8px;
    color: {TEXT1};
}}
QComboBox:hover, QFontComboBox:hover {{
    background: {CONTENT_HOVER};
}}
QComboBox:focus, QFontComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down, QFontComboBox::drop-down {{
    width: 20px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow, QFontComboBox::down-arrow {{
    image: url({asset("arrow_down.png")});
    width: 11px;
    height: 7px;
}}
QComboBox QAbstractItemView, QFontComboBox QAbstractItemView {{
    background: {ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    color: {TEXT1};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT};
    outline: none;
}}
QPlainTextEdit {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 6px 8px;
    color: {TEXT1};
    selection-background-color: {ACCENT};
}}
QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
    background: {CONTENT_HOVER};
}}
#StepButton {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: 14px;
    color: {TEXT2};
    font-size: {FONT_BODY}px;
    font-weight: 600;
}}
#StepButton:hover {{
    background: {ACCENT_SOFT};
    border: 1px solid rgba(0, 161, 214, 0.45);
    color: {ACCENT};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: rgba(131, 131, 145, 0.30);
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
    background: #ffffff;
}}
QSlider::handle:horizontal:hover {{
    background: {style_mix("ACCENT", "#ffffff", 0.35)};
}}

/* ---------- 设置窗口（左侧选类别，右侧改内容） ---------- */
#SettingsNav {{
    background: {SIDEBAR};
    border: none;
    border-right: 1px solid {BORDER};
    padding: 12px 8px;
    outline: none;
}}
#SettingsNav::item {{
    height: 34px;
    padding: 0 10px;
    border-radius: {CONTROL_HEIGHT // 2}px;
    color: {TEXT2};
}}
#SettingsNav::item:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#SettingsNav::item:selected {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
    font-weight: 600;
}}
#SettingsStack, #SettingsPage {{
    background: transparent;
}}
#SettingsTitle {{
    font-size: {FONT_HEADING}px;
    font-weight: 700;
}}
#SettingsHint {{
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
}}
#PluginCard {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
}}
#PluginScroll, #PluginScroll > QWidget > QWidget {{
    background: transparent;
}}
#PluginTabs::pane {{
    border: none;
    background: transparent;
}}
#PluginTabs QTabBar::tab {{
    background: transparent;
    color: {TEXT2};
    padding: 7px 14px;
    margin-right: 6px;
    border-radius: {RADIUS_MD}px;
    border: 1px solid {BORDER};
}}
#PluginTabs QTabBar::tab:selected {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}
#PluginName {{
    font-weight: 600;
    color: {TEXT1};
}}
#UpdateNotes, #UpdateNotes:focus {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 6px 8px;
    color: {TEXT1};
}}
#UpdateNotice {{
    background: transparent;
    border: none;
}}
#NoticeText {{
    color: {TEXT1};
    font-weight: 500;
}}
#NoticeClose {{
    background: transparent;
    border: none;
    color: {TEXT3};
}}
#NoticeClose:hover {{
    color: {TEXT1};
    background: {CONTENT_HOVER};
    border-radius: {RADIUS_SM}px;
}}

/* ---------- 侧栏 ---------- */
#Sidebar {{
    background: {SIDEBAR};
    border-right: 1px solid {BORDER};
}}
#AppTitle {{
    font-size: {FONT_BODY + 1}px;
    font-weight: 600;
}}
#AppSubtitle {{
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
}}
#SectionLabel {{
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#Search {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 6px 10px;
    color: {TEXT1};
}}
#Search:focus {{
    border: 1px solid {ACCENT};
    background: {CONTENT_HOVER};
}}
/* 搜索没有匹配（或关注列表本来就空）时顶在列表位置上的提示 */
#FilterHint {{
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
    padding: 20px 10px;
}}

/* 房间条目 */
#NavItem {{
    border-radius: {RADIUS_MD}px;
    background: transparent;
}}
#NavItem[portraitStrip="true"] {{
    background: {CONTENT};
}}
#NavItem:hover, #NavItem[hovered="true"] {{
    background: {CONTENT_HOVER};
}}
#NavItem[selected="true"] {{
    background: {ACCENT_SOFT};
}}
#NavItem[selected="true"]:hover, #NavItem[selected="true"][hovered="true"] {{
    background: rgba(0, 161, 214, 0.24);
}}
#NavItem[onWall="true"] {{
    border: 1px solid rgba(0, 161, 214, 0.62);
}}
#NavItem[sortSelected="true"] {{
    background: rgba(0, 161, 214, 0.24);
    border: 2px solid {ACCENT};
}}
#NavName {{
    color: #ffffff;
    font-size: {FONT_CONTROL}px;
    font-weight: 700;
    background: transparent;
}}
#NavSub {{
    color: rgba(238, 241, 246, 0.88);
    font-size: {FONT_CAPTION}px;
    background: transparent;
}}
#NavName[cardMode="false"] {{
    color: {TEXT1};
}}
#NavSub[cardMode="false"] {{
    color: {TEXT2};
}}
#NavAvatar {{
    color: {TEXT1};
    font-size: {FONT_CONTROL}px;
    font-weight: 600;
    border-radius: 16px;
}}

/* 徽标 */
#BadgeLive {{
    background: {PINK};
    color: #3a0d1c;
    border-radius: {RADIUS_MD}px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 700;
}}
#BadgeOff {{
    background: {badge_bg};
    color: {badge_text};
    border-radius: {RADIUS_MD}px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 600;
}}
#BadgeGhost {{
    background: rgba(12, 13, 16, 0.66);
    color: {TEXT2};
    border-radius: {RADIUS_MD}px;
    padding: 1px 6px;
    font-size: 11px;
}}
#BadgePin {{
    background: rgba(0, 161, 214, 0.18);
    color: {ACCENT};
    border-radius: {RADIUS_MD}px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 600;
}}
#IconButton {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: {CONTROL_HEIGHT // 2}px;
    padding: 0 12px;
    min-height: {CONTROL_HEIGHT}px;
    color: {TEXT2};
}}
#IconButton, #PrimaryButton, #PickerTab {{
    outline: none;
}}
#IconButton:focus, #PickerTab:focus {{
    border: 1px solid {ACCENT};
}}
#PrimaryButton:focus {{
    border: 1px solid #04161f;
}}
#IconButton:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#LoginWindow #IconButton:pressed {{
    background: {ACCENT_SOFT};
    border: 1px solid {ACCENT};
    color: {ACCENT};
}}
#IconButton:checked {{
    background: {ACCENT_SOFT};
    border: 1px solid rgba(0, 161, 214, 0.45);
    color: {ACCENT};
}}
QPushButton#IconButton:pressed {{
    background: {style_mix("CONTENT", "#000000", 0.12)};
    border: 1px solid {ACCENT};
    color: {TEXT1};
}}
#PrimaryButton {{
    background: {ACCENT};
    border: none;
    border-radius: {CONTROL_HEIGHT // 2}px;
    min-height: {CONTROL_HEIGHT}px;
    padding: 0 14px;
    color: #04161f;
    font-weight: 700;
}}
#PrimaryButton:hover {{
    background: {style_mix("ACCENT", "#ffffff", 0.12)};
}}
#PrimaryButton[updateAction="true"]:disabled {{
    background: {CONTENT}; color: {TEXT3}; border: 1px solid {BORDER_STRONG};
}}
QPushButton#PrimaryButton:pressed {{
    background: {style_mix("ACCENT", "#000000", 0.16)};
}}
#GhostButton {{
    background: transparent;
    border: 1px dashed {BORDER_STRONG};
    border-radius: {RADIUS_MD}px;
    min-height: {CONTROL_HEIGHT}px;
    color: {TEXT3};
}}
#GhostButton:hover {{
    background: {CONTENT};
    color: {TEXT1};
}}

/* ---------- 侧栏折叠按钮 ---------- */
#SidebarToggle {{
    background: transparent;
    border: none;
    color: {TEXT3};
    font-size: 14px;
    min-width: 24px;
    min-height: 24px;
    border-radius: 12px;
}}
#SidebarToggle:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#SidebarToggle:checked {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}
/* 竖屏顶部横栏右上角的收起/展开：比侧栏那个更紧凑，别把横栏撑高 */
#BarToggle {{
    background: transparent;
    border: none;
    color: {TEXT3};
    font-size: 12px;
    min-width: 18px;
    max-width: 26px;
    min-height: 18px;
    max-height: 22px;
    border-radius: 11px;
}}
#BarToggle:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#DangerButton {{
    background: rgba(229, 72, 77, 0.18);
    border: 1px solid rgba(229, 72, 77, 0.45);
    border-radius: {CONTROL_HEIGHT // 2}px;
    min-height: {CONTROL_HEIGHT}px;
    padding: 0 14px;
    color: {ERROR};
    font-weight: 600;
}}
#DangerButton:hover {{
    background: rgba(229, 72, 77, 0.32);
}}
#ChipButton {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 2px 10px;
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#ChipButton:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#ChipButton:checked {{
    background: {ACCENT_SOFT};
    border: 1px solid rgba(0, 161, 214, 0.45);
    color: {ACCENT};
}}
/* 竖屏顶部横栏里的小图标按钮（多选 / 排序 / 刷新）：方形、无内边距，
   不然 ChipButton 那 10px 左右内边距会把图标字形挤掉一半 */
#BarIcon {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: 15px;
    padding: 0;
    min-width: 28px;
    min-height: 28px;
    color: {TEXT2};
    font-size: 14px;
}}
#BarIcon:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#BarIcon:checked {{
    background: {ACCENT_SOFT};
    border: 1px solid rgba(0, 161, 214, 0.45);
    color: {ACCENT};
}}
/* 「排序」带着菜单，Qt 会在按钮里再画一个下拉小三角；横栏里那个图标是自绘的，
   多出来的小三角就叠在箭头上（用户报的「图案下面还藏了一个图案」），去掉它，
   顺便别让它占掉内容宽度把图标挤偏。横屏的「排序」是 ChipButton，不受影响。 */
#BarIcon::menu-indicator {{
    image: none;
    width: 0;
}}
/* 竖屏关心栏右侧那一块里，三个按钮之间的分割线 */
#BarDivider {{
    background: {BORDER};
    border: none;
}}
#TileControls {{
    background: transparent;
    border: none;
}}
#LoadingIndicator {{
    background: #1b1e24;              /* 会通过窗口整体透明度变成半透明 */
}}
#LoadingText {{
    color: {TEXT2};
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#FloatChrome {{
    background: #15171c;
}}
#FloatTitle {{
    color: {TEXT1};
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#FloatClose {{
    background: transparent;
    border: none;
    color: {TEXT3};
    min-width: 22px;
    min-height: 22px;
    border-radius: 11px;
    font-size: 14px;
}}
#FloatClose:hover {{
    background: rgba(229, 72, 77, 0.4);
    color: #ffffff;
}}
#FloatVideo {{
    background: #000000;
}}
#ShortcutEdit {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM + 2}px;
    padding: 4px 8px;
    color: {TEXT1};
}}
#ShortcutEdit:focus {{
    border: 1px solid {ACCENT};
}}
#AccountId {{
    color: {TEXT3}; background: transparent;
}}
#AccountName {{
    color: {TEXT1}; font-size: {FONT_CONTROL}px; font-weight: 700; background: transparent;
}}
#AccountRow {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: {CONTROL_HEIGHT // 2}px;
}}
#AccountRow:hover {{
    background: {CONTENT_HOVER};
    border: 1px solid {BORDER_STRONG};
}}
#Tile[empty="true"] {{
    background: rgba(16, 17, 20, 0.55);
    border: 1px dashed {BORDER_STRONG};
}}
#Tile[dropActive="true"] {{
    border: 1px dashed {ACCENT};
    background: rgba(0, 161, 214, 0.10);
}}

/* 布局选择弹层 */
#LayoutPicker {{
    background: {BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_LG}px;
}}
#LayoutCard {{
    background: {CONTENT};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_MD}px;
    padding: 6px 4px 4px 4px;
    color: {TEXT1};
    font-size: {FONT_CAPTION}px;
}}
#LayoutCard:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#LayoutCard:checked {{
    background: {CONTENT_HOVER};
    border: 1px solid {ACCENT};
    color: {TEXT1};
}}
#LayoutCard:focus {{
    border: 1px solid {ACCENT};
    outline: none;
}}
#PickerTab {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 3px 14px;
    color: {TEXT2};
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#PickerTab:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#PickerTab:checked {{
    background: {CONTENT_HOVER};
    border: 1px solid {ACCENT};
    color: {TEXT1};
}}
#LayoutPicker #SectionLabel {{
    color: {TEXT1}; background: {CONTENT}; border-radius: 6px; padding: 4px 8px;
}}
#LayoutResetButton, #PresetManageButton {{
    background: {CONTENT}; color: {TEXT2}; border: 1px solid {BORDER_STRONG};
    border-radius: 8px; min-height: 28px; padding: 2px 10px;
}}
#LayoutResetButton:hover, #PresetManageButton:hover {{
    background: {CONTENT_HOVER}; color: {TEXT1}; border-color: {ACCENT};
}}
#LayoutResetButton:focus, #PresetManageButton:focus {{border-color: {ACCENT}; outline: none;}}
#RoomPresetEntry {{
    background: {CONTENT}; border: 1px solid {BORDER_STRONG}; border-radius: 10px;
}}
#RoomPresetEntry[current="true"] {{border-color: {ACCENT}; background: {CONTENT_HOVER};}}
#RoomPresetName {{color: {TEXT1}; font-weight: 600;}}
#RoomPresetEntry QPushButton[deleteConfirm="true"] {{border-color: {ERROR};}}
#RoomPresetEntry #LayoutCard {{
    background: transparent; border: none; padding: 0; color: {TEXT2};
}}
#RoomPresetEntry #LayoutCard:hover, #RoomPresetEntry #LayoutCard:checked {{color: {TEXT1};}}
#RoomPresetEntry #LayoutCard:focus {{border: 1px solid {ACCENT};}}
#PresetManageButton {{min-height: 24px; padding: 0;}}
#LayoutPicker #RoomPresetNameForm {{
    background: {CONTENT}; border: 1px solid {BORDER_STRONG}; border-radius: 10px;
}}

/* ---------- 画面墙 ---------- */
#Tile {{
    background: {TILE_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
#Tile:hover {{
    border: 1px solid {BORDER_STRONG};
}}
#Tile[focused="true"] {{
    border: 1px solid rgba(0, 161, 214, 0.65);
}}
#TileVideo {{
    background: {TILE_BG};
    border-radius: 10px;
}}
#TileName {{
    font-size: {FONT_CONTROL}px;
    font-weight: 600;
}}
#TileTitle {{
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
}}
#TileBottom {{
    background: rgba(10, 11, 13, 0.24);
    border-radius: {RADIUS_MD}px;
}}
#TilePlaceholder {{
    color: {TEXT3};
    font-size: {FONT_CONTROL}px;
}}
#TileStatus {{
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
}}

/* 格子内的独立控制（画质 / 静音 / 刷新 / 全屏 / 关闭） */
/* 这里不写 min-width / padding：宽度由 widgets._layout_controls 按文本算好并
   固定，样式表再加 offset 会把「×」这类短文本按钮撑成和画质按钮一样宽。 */
#TileCtrl {{
    background: rgba(12, 13, 16, 0.78);   /* 每个按钮各自一个底，靠间距分开 */
    color: {TEXT2};
    border: none;
    border-radius: {TILE_CONTROL_HEIGHT // 2}px;
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#TileCtrl:hover, #TileCtrl[hovered="true"] {{
    background: {ACCENT};
    color: #04161f;
}}
#TileCtrl:checked {{
    background: rgba(0, 161, 214, 0.85);
    color: #04161f;
}}
#TileCtrl[recording="true"] {{
    color: {ERROR};
}}
/* 画面弹幕开关：开启状态用右下角的勾表示，不靠整块底色区分（对齐 B 站播放器）。 */
#TileToggle {{
    background: rgba(12, 13, 16, 0.78);
    color: {TEXT2};
    border: none;
    border-radius: {TILE_CONTROL_HEIGHT // 2}px;
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#TileToggle:hover {{
    background: {ACCENT};
    color: #04161f;
}}
#TileToggle:checked {{
    background: rgba(12, 13, 16, 0.78);
    color: {TEXT2};
}}
#TileToggle:checked:hover {{
    background: {ACCENT};
    color: #04161f;
}}
#TileCtrl:disabled {{
    background: transparent;
    color: {TEXT4};
}}
#TileCtrl:focus {{
    border: 1px solid {ACCENT};
}}
#BiliVolumeButton {{
    background: transparent;
    border: none;
    border-radius: 13px;
    padding: 0;
}}
#BiliVolumeButton:hover {{
    background: rgba(0, 174, 236, 0.14);
}}
#BiliVolumeButton:pressed {{
    background: rgba(0, 174, 236, 0.24);
}}
#TileCtrlStrip {{
    background: transparent;
}}

/* 弹幕格：占画面墙里的一整格，和别的格子同一套规格 */
#DanmakuPanel {{
    background: rgba(18, 20, 25, 0.96);
    border: none;
    border-radius: 10px;
}}
#DanmakuHeader {{
    background: rgba(255, 255, 255, 0.025);
    border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}}
#DanmakuDot {{
    color: {PINK};
    font-size: 8px;
    background: transparent;
}}
#DanmakuTitle {{
    color: {TEXT1};
    font-size: {FONT_CAPTION}px;
    font-weight: 700;
}}
#DanmakuCount {{
    color: {TEXT3};
    background: rgba(131, 131, 145, 0.16);
    border-radius: 9px;
    padding: 0 8px;
    font-size: {FONT_CAPTION}px;
}}
#DanmakuCount[state="connected"] {{
    color: #6bd8ff;
    background: rgba(0, 174, 236, 0.16);
}}
#DanmakuCount[state="connecting"] {{
    color: {WARNING};
    background: rgba(251, 191, 36, 0.14);
}}
#DanmakuCount[state="error"] {{
    color: #ff9abb;
    background: rgba(251, 114, 153, 0.15);
}}
#DanmakuCount[state="idle"] {{
    color: {TEXT4};
    background: rgba(131, 131, 145, 0.13);
}}
#DanmakuBody {{
    background: transparent;
    border: none;
    color: {TEXT2};
    font-size: {FONT_CAPTION}px;
}}
#DanmakuBody QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 2px 0;
}}
#DanmakuBody QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.18);
    border-radius: 3px;
    min-height: 24px;
}}
#DanmakuBody QScrollBar::add-line:vertical, #DanmakuBody QScrollBar::sub-line:vertical,
#DanmakuBody QScrollBar::add-page:vertical, #DanmakuBody QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0;
}}
#DanmakuBar {{
    background: rgba(10, 11, 13, 0.52);
    border-top: 1px solid rgba(255, 255, 255, 0.06);
}}
#DanmakuBarLabel {{
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
}}
#DanmakuBarValue {{
    color: {TEXT2};
    font-size: {FONT_CAPTION}px;
}}
#PauseOverlay {{
    background: rgba(26, 29, 35, 0.92);
}}

/* ---------- 关注列表的封面卡片 ---------- */
#NavThumb {{
    background: transparent;
}}
#NavThumbCover {{
    background: rgba(18, 20, 25, 0.82);
    color: {cover_text};
    font-size: {FONT_CAPTION}px;
    border-radius: 6px;
}}
#NavThumbVideo {{
    background: #000000;
}}
#NavPreviewPopup {{
    background: {CONTENT};
    border: 2px solid {ACCENT};
    border-radius: 7px;
}}
#NavPreviewPopupVideo {{
    background: {TILE_BG};
}}
#NavThumbHint {{
    background: rgba(10, 11, 13, 0.66);
    color: {hint_text};
    font-size: {FONT_CAPTION}px;
    border-radius: 6px;
}}
#NavThumbFace {{
    border-radius: 14px;          /* 没头像时的字母底色也保持圆形 */
}}
#PauseOverlay QLabel {{
    color: {TEXT1};
    font-size: {FONT_CONTROL}px;
    font-weight: 600;
    letter-spacing: 1px;
}}

/* 弹出菜单 */
QListWidget#FollowList {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 4px;
    outline: none;
}}
QListWidget#FollowList::item {{
    padding: 6px 4px;
    border-radius: {RADIUS_SM + 2}px;
    color: {TEXT2};
}}
QListWidget#FollowList::item:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
QListWidget#FollowList::item:selected {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}
QListWidget#FollowList::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER_STRONG};
    background: {CONTENT_HOVER};
    margin-right: 6px;
}}
QListWidget#FollowList::indicator:hover {{
    border: 1px solid {ACCENT};
}}
QListWidget#FollowList::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}
#EmptyHint {{
    color: {TEXT3};
    font-size: {FONT_BODY}px;
    line-height: 24px;
}}
#NavCheck::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER_STRONG};
    background: {CONTENT};
}}
#NavCheck::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}

QMenu {{
    background: {ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 20px 6px 12px;
    border-radius: {RADIUS_SM + 2}px;
    color: {TEXT2};
}}
QMenu::item:selected {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}

/* ---------- 滚动条 ---------- */
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: {SCROLLBAR_SIZE}px;
    margin: 2px 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(131, 131, 145, 0.35);
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(131, 131, 145, 0.55);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
    height: 0;
}}
/* ---------- 滚动条：横向 ----------
   竖屏顶部横栏的横向卡片条靠它滚。样式和上面的竖向条一一对应（同一组颜色、
   同粗、同样去掉两端箭头），否则会掉回系统原生那条灰底带箭头的滚动条。 */
QScrollBar:horizontal {{
    background: transparent;
    height: {SCROLLBAR_SIZE}px;
    margin: 0 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(131, 131, 145, 0.35);
    border-radius: 4px;
    min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(131, 131, 145, 0.55);
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
    width: 0;
}}
"""
    if palette_roles:
        style += '''
        #BadgeOff[appearanceLight="true"] {background: rgba(16, 20, 28, 0.78); color: #F1F2F5; border: 1px solid rgba(255, 255, 255, 0.16);}
        #NavThumbCover[appearanceLight="true"], #NavThumbHint[appearanceLight="true"] {color: #F1F2F5;}
        '''
    if _light and not palette_roles:
        style += '#BadgeOff {border: 1px solid rgba(255, 255, 255, 0.16);}'
        style += """
        #PrimaryButton {color: #FFFFFF;}
        #PrimaryButton[addRoom="true"] {background: #FB7299; color: #202630;}
        #PrimaryButton[addRoom="true"]:hover {background: #FC87A8;}
        #PrimaryButton[addRoom="true"]:pressed {background: #EC6089;}
        #WallGrid {background: #E6EBF2;}
        #Tile, #Tile[empty="true"] {background: #FFFFFF; border: 1px solid #BCC8D8; border-radius: 10px;}
        #Tile:hover {border-color: #95A7BE;}
        #Tile[focused="true"] {border-color: #00A1D6;}
        #DanmakuPanel, #TileVideo {background: #FFFFFF;}
        #TileCtrl {background: #F7F9FC; color: #202630; border: 1px solid #D7DDE7;}
        #TileCtrl:hover, #TileCtrl[hovered="true"] {background: #E7EFF7; color: #007BA8;}
        #TileBottom {background: #F0F3F8; border: none; border-top: 1px solid #D7DDE7; border-top-left-radius: 0; border-top-right-radius: 0; border-bottom-left-radius: 9px; border-bottom-right-radius: 9px;}
        #TileBottom #TileCtrl {background: transparent; color: #4A5565; border: none;}
        #TileBottom #TileCtrl:hover, #TileBottom #TileCtrl[hovered="true"] {background: #E7EFF7; color: #007BA8;}
        #TileBottom #TileCtrl:checked {background: #DDF3FB; color: #007BA8;}
        #TileBottom QLabel {color: #4A5565;}
        #TileBottom #TileCtrl[recording="true"] {color: #E5484D;}
        #TileBottom #TileToggle {background: transparent; color: #4A5565;}
        #TileBottom #TileToggle:hover {background: #E7EFF7; color: #007BA8;}
        #TilePlaceholder {color: #4A5565;}
        #NavThumbCover, #NavThumbHint, #PauseOverlay QLabel {color: #F1F2F5;}
        #DanmakuHeader {background: #EBEEF3; border-bottom: 1px solid #D7DDE7;}
        #DanmakuBar {background: #EBEEF3; border-top: 1px solid #D7DDE7;}
        #DanmakuCount[state="connected"] {color: #007BA8;}
        #DanmakuCount[state="error"] {color: #B93665;}
        #DanmakuBody QScrollBar::handle:vertical {background: #BCC6D5;}
        """
    return style + TILE_FULLSCREEN_STYLE
