"""全屏时只播放当前格子的声音，可直接安装到 v0.2 便携版。"""
from functools import wraps

from ddm import plugins as api


class FullscreenAudioPlugin(api.Plugin):
    name = "全屏独享声音"
    description = "进入单路全屏时，静音其他所有格子并打开当前格子的声音"
    version = "1.0"

    def on_load(self, context: api.PluginContext) -> None:
        self.context = context
        self._wall = context.window.wall
        self._original = self._wall.set_fullscreen_tile

        # 按钮、右键菜单和 F 快捷键最终都经过这个入口。仅包装当前实例，
        # 不依赖鼠标位置，也不改变窗口/播放器类或轮询 UI 状态。
        @wraps(self._original)
        def set_fullscreen_tile(tile, *args, **kwargs):
            previous = self._wall.fullscreen_tile
            result = self._original(tile, *args, **kwargs)
            if (tile is not None and tile is not previous
                    and self._wall.fullscreen_tile is tile
                    and tile in self._wall.tiles and tile.room.get("room_id")):
                try:
                    self._focus_audio(tile)
                except Exception as error:
                    # 插件故障不能中断本体的全屏切换。
                    context.log(f"全屏声音切换失败：{error}")
            return result

        self._hook = set_fullscreen_tile
        self._wall.set_fullscreen_tile = self._hook
        context.log("已启用：进入全屏时只播放当前格子的声音")

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
        if wall is not None and wall.set_fullscreen_tile is self._hook:
            wall.set_fullscreen_tile = self._original


plugin = FullscreenAudioPlugin()
