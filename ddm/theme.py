"""设计令牌与全局样式。

配色与尺度参考 BewlyCat（暗色体系）：基色 #2a2d32 派生背景/卡片/浮层，
主题色取 B 站蓝，强调色取 B 站粉。

Qt 没有真正的背景模糊，这里用半透明叠加 + 细描边模拟玻璃质感，
避免玻璃效果带来的 GPU 开销（本项目以低占用为优先）。
"""


import os


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


def qss() -> str:
    """全局样式表。"""
    return f"""
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
    background: {mix(ACCENT, "#ffffff", 0.35)};
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

/* 房间条目 */
#NavItem {{
    border-radius: {RADIUS_MD}px;
    background: transparent;
}}
#NavItem:hover {{
    background: {CONTENT_HOVER};
}}
#NavItem[selected="true"] {{
    background: {ACCENT_SOFT};
}}
#NavItem[selected="true"]:hover {{
    background: rgba(0, 161, 214, 0.24);
}}
#NavName {{
    font-size: {FONT_CONTROL}px;
    font-weight: 600;
}}
#NavSub {{
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
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
    background: rgba(131, 131, 145, 0.28);
    color: {TEXT2};
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
#IconButton:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#IconButton:checked {{
    background: {ACCENT_SOFT};
    border: 1px solid rgba(0, 161, 214, 0.45);
    color: {ACCENT};
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
    background: {mix(ACCENT, "#ffffff", 0.12)};
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
    background: {ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS_LG}px;
}}
#LayoutCard {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_MD}px;
    padding: 6px 4px 4px 4px;
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
}}
#LayoutCard:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#LayoutCard:checked {{
    background: {ACCENT_SOFT};
    border: 1px solid rgba(0, 161, 214, 0.45);
    color: {ACCENT};
}}
#PickerTab {{
    background: {CONTENT};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 3px 14px;
    color: {TEXT3};
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#PickerTab:hover {{
    background: {CONTENT_HOVER};
    color: {TEXT1};
}}
#PickerTab:checked {{
    background: {ACCENT_SOFT};
    border: 1px solid rgba(0, 161, 214, 0.45);
    color: {ACCENT};
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
    background: rgba(10, 11, 13, 0.72);
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
#TileCtrl {{
    background: rgba(12, 13, 16, 0.78);   /* 每个按钮各自一个底，靠间距分开 */
    color: {TEXT2};
    border: none;
    border-radius: {TILE_CONTROL_HEIGHT // 2}px;
    min-width: {TILE_CONTROL_HEIGHT}px;
    min-height: {TILE_CONTROL_HEIGHT}px;
    padding: 0 8px;
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#TileCtrl:hover {{
    background: {ACCENT};
    color: #04161f;
}}
#TileCtrl:checked {{
    background: rgba(0, 161, 214, 0.85);
    color: #04161f;
}}
#TileCtrlStrip {{
    background: transparent;
}}

/* 弹幕格：占画面墙里的一整格，和别的格子同一套规格 */
#DanmakuPanel {{
    background: {TILE_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
#DanmakuHeader {{
    background: transparent;
    border-bottom: 1px solid {BORDER};
}}
#DanmakuTitle {{
    color: {TEXT1};
    font-size: {FONT_CAPTION}px;
    font-weight: 600;
}}
#DanmakuCount {{
    color: {TEXT4};
    font-size: {FONT_CAPTION}px;
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
    background: rgba(10, 11, 13, 0.72);
    border-radius: {RADIUS_MD}px;
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

/* ---------- 关注列表的封面缩略图 ---------- */
#NavThumb {{
    background: rgba(12, 13, 16, 0.6);
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
#NavThumbCover {{
    background: transparent;
    color: {TEXT4};
    font-size: {FONT_CAPTION}px;
    border-radius: 6px;
}}
#NavThumbVideo {{
    background: #000000;
}}
#NavThumbHint {{
    background: rgba(10, 11, 13, 0.66);
    color: {TEXT2};
    font-size: {FONT_CAPTION}px;
    border-radius: 6px;
}}
#NavThumbFace {{
    border: 1px solid rgba(0, 0, 0, 0.55);
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
    width: 8px;
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
"""
