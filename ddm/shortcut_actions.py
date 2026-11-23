"""Shared shortcut action keys, labels and defaults for the shell and settings."""
SHORTCUT_ACTIONS = [
    ("focus", "全屏查看鼠标所在的格子", "F"),
    ("restore", "退出全屏", "Esc"),
    ("close_tile", "关闭直播或移除弹幕格，目标由鼠标位置决定", "Del"),
    ("danmaku_input", "显示播放栏／聚焦鼠标所在格子的弹幕输入框", "Return"),
    ("toggle_folders", "展开／折叠全部关注文件夹", "Ctrl+Shift+F"),
    ("mute", "静音鼠标所在那一路（再按一次取消）", "M"),
    ("audio_cycle", "声音轮询按键", "E"),
    ("record", "开始／停止鼠标所在格子的录制", "R"),
    ("video_danmaku", "切换鼠标所在格子的画面弹幕", "B"),
    ("solo", "只保留鼠标所在那一路的声音", "Alt+M"),
    ("volume_up", "按住设定的修饰键向上滚动以提高音量", "Shift+WheelUp"),
    ("volume_down", "按住设定的修饰键向下滚动以降低音量", "Shift+WheelDown"),
    ("fullscreen_volume_up", "主窗口全屏时提高当前画面音量", "Up"),
    ("fullscreen_volume_down", "主窗口全屏时降低当前画面音量", "Down"),
    ("pip_volume_up", "画中画中提高当前画面音量", "Up"),
    ("pip_volume_down", "画中画中降低当前画面音量", "Down"),
    ("pip_mute", "静音或恢复鼠标所在的画中画画面", "M"),
    ("pip_solo", "只保留鼠标所在的画中画画面的声音", "Alt+M"),
    ("pip_exit", "退出画中画并返回监控室", "Esc"),
    ("layout_grow", "等比放大鼠标所在的自定义布局直播格", "Ctrl+WheelUp"),
    ("layout_shrink", "等比缩小鼠标所在的自定义布局直播格", "Ctrl+WheelDown"),
    # Keep the saved action IDs from the original portrait-only shortcuts.
    ("layout_portrait_tall", "增加鼠标所在直播格的高度，保持宽度", "Alt+WheelUp"),
    ("layout_portrait_short", "减少鼠标所在直播格的高度，保持宽度", "Alt+WheelDown"),
]

DEFAULT_SHORTCUTS = {key: default for key, _description, default in SHORTCUT_ACTIONS}
VOLUME_WHEEL_SHORTCUTS = ('volume_up', 'volume_down')
LAYOUT_RESIZE_SHORTCUTS = ('layout_grow', 'layout_shrink')
LAYOUT_HEIGHT_SHORTCUTS = ('layout_portrait_tall', 'layout_portrait_short')
LAYOUT_WHEEL_SHORTCUTS = LAYOUT_RESIZE_SHORTCUTS + LAYOUT_HEIGHT_SHORTCUTS
WHEEL_SHORTCUTS = VOLUME_WHEEL_SHORTCUTS + LAYOUT_WHEEL_SHORTCUTS
FULLSCREEN_VOLUME_SHORTCUTS = ('fullscreen_volume_up', 'fullscreen_volume_down')
DEFAULT_WHEEL_VOLUME_STEP = 10
DEFAULT_HOVER_WHEEL_VOLUME_STEP = 3


def matches_wheel(shortcut, pressed, delta):
    if not pressed or not delta or not isinstance(shortcut, str):
        return False
    parts = [part for part in shortcut.split('+') if part]
    if not parts or parts[-1] != ('WheelUp' if delta > 0 else 'WheelDown'):
        return False
    from PySide6.QtCore import Qt

    modifiers = Qt.NoModifier
    keys = {'Shift': Qt.ShiftModifier, 'Ctrl': Qt.ControlModifier,
            'Alt': Qt.AltModifier, 'Meta': Qt.MetaModifier}
    for part in parts[:-1]:
        if part not in keys:
            return False
        modifiers |= keys[part]
    return pressed == modifiers


def wheel_action_step(shortcuts, actions, pressed, delta):
    for step, action in zip((1, -1), actions):
        if matches_wheel(shortcuts.get(action, DEFAULT_SHORTCUTS[action]), pressed, delta):
            return step
    return 0


def wheel_volume_step(value, default=DEFAULT_WHEEL_VOLUME_STEP):
    return value if type(value) is int and 1 <= value <= 100 else default


def configured_shortcuts(saved):
    """Copy old shared bindings into each newly independent setting once."""
    bindings = {**DEFAULT_SHORTCUTS, **saved}
    for key, previous in (('fullscreen_volume_up', 'pip_volume_up'),
                          ('fullscreen_volume_down', 'pip_volume_down'),
                          ('pip_mute', 'mute'), ('pip_solo', 'solo')):
        if key not in saved and previous in saved:
            bindings[key] = saved[previous]
    return bindings
