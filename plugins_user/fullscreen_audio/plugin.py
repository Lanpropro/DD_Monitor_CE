"""全屏时只播放当前格子的声音，可直接安装到 v0.2 便携版。"""
from functools import wraps

from ddm import plugins as api

SETTING = "fullscreen_audio_focus"
LABEL = "全屏时只播放当前格子的声音，退出后恢复"


class FullscreenAudioPlugin(api.Plugin):
    name = "全屏独享声音"
    description = "进入单路全屏时，静音其他所有格子并打开当前格子的声音"
    version = "1.1"

    def on_load(self, context: api.PluginContext) -> None:
        self.context = context
        self._saved_audio = {}
        self._register_setting()
        self._wall = context.window.wall
        self._original = self._wall.set_fullscreen_tile

        # 按钮、右键菜单和 F 快捷键最终都经过这个入口。仅包装当前实例，
        # 不依赖鼠标位置，也不改变窗口/播放器类或轮询 UI 状态。
        @wraps(self._original)
        def set_fullscreen_tile(tile, *args, **kwargs):
            previous = self._wall.fullscreen_tile
            result = self._original(tile, *args, **kwargs)
            if tile is None:
                self._restore_audio()
            elif (tile is not previous
                    and self._wall.fullscreen_tile is tile
                    and tile in self._wall.tiles and tile.room.get("room_id")
                    and context.window.settings.get(SETTING, True)):
                try:
                    if not self._saved_audio:
                        self._saved_audio = {
                            item: (bool(item.muted), int(item.volume))
                            for item in self._wall.tiles
                        }
                    self._focus_audio(tile)
                except Exception as error:
                    # 插件故障不能中断本体的全屏切换。
                    context.log(f"全屏声音切换失败：{error}")
                    self._restore_audio()
            return result

        self._hook = set_fullscreen_tile
        self._wall.set_fullscreen_tile = self._hook
        context.log("已装载：常规设置中可切换全屏独享声音，退出全屏恢复原声音")

    def _register_setting(self) -> None:
        from ddm import config, dialogs

        # 复用常规页已有的复选框、保存/取消和恢复默认逻辑，兼容现有 exe。
        self._settings_page = dialogs.GeneralSettingsPage
        self._added_setting = not any(key == SETTING for key, _ in self._settings_page.ITEMS)
        if self._added_setting:
            items = self._settings_page.ITEMS
            position = next((i + 1 for i, (key, _) in enumerate(items)
                             if key == "default_muted"), len(items))
            items.insert(position, (SETTING, LABEL))
        self._added_default = SETTING not in config.DEFAULT_SETTINGS
        config.DEFAULT_SETTINGS.setdefault(SETTING, True)

    def _restore_audio(self) -> None:
        saved, self._saved_audio = self._saved_audio, {}
        for tile, (muted, volume) in saved.items():
            if tile not in self._wall.tiles:
                continue
            try:
                # 全屏时可能调过音量（包括原先为零的格子），一并还原。
                tile.set_muted(True)
                tile.set_volume(volume)
                tile.set_muted(muted)
            except Exception as error:
                self.context.log(f"恢复格子声音失败：{error}")

    def _focus_audio(self, target) -> None:
        # 先关闭其他声音，再打开目标；包含全屏/布局隐藏的格子。
        # 使用 Tile 的接口，让 UI、保存的状态和播放器同步更新。
        for tile in self._wall.tiles:
            if tile is not target:
                tile.set_muted(True)
        if target.volume == 0:
            # 单纯取消静音无法让音量为零的格子出声。
            value = self.context.window.settings.get("default_volume", 50)
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = 50
            target.set_volume(min(100, value) if value > 0 else 50)
        target.set_muted(False)

    def on_unload(self) -> None:
        wall = getattr(self, "_wall", None)
        if wall is not None:
            self._restore_audio()
        if wall is not None and wall.set_fullscreen_tile is self._hook:
            wall.set_fullscreen_tile = self._original
        if getattr(self, "_added_setting", False):
            self._settings_page.ITEMS[:] = [
                item for item in self._settings_page.ITEMS if item[0] != SETTING]
            self._added_setting = False
        if getattr(self, "_added_default", False):
            from ddm import config
            config.DEFAULT_SETTINGS.pop(SETTING, None)
            self._added_default = False


plugin = FullscreenAudioPlugin()
