"""Shared page order for the settings dialog and its worker session."""

SETTINGS_PAGES = (
    ('general', '常规'), ('appearance', '外观'), ('danmaku', '弹幕'),
    ('recording', '录制'), ('notifications', '通知'), ('shortcuts', '快捷键'),
    ('streamer_defaults', '主播独立设置'),
    ('tray', '托盘行为'), ('plugins', '插件'), ('updates', '软件更新'), ('diagnostics', '诊断与反馈'),
)
PAGE_INDEX = {key: index for index, (key, _label) in enumerate(SETTINGS_PAGES)}
