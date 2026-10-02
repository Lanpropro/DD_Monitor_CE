"""Package entry point loaded by DD Monitor CE's single-file plugin loader."""
import os

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolButton

from ddm import plugins as api

# Keep sibling imports local to this plugin, including in the frozen EXE.
__path__ = [os.path.dirname(__file__)]
__package__ = __name__

from .viewer import Viewer


class MatchSyncPlugin(api.Plugin):
    def __init__(self):
        super().__init__()
        self.sources = {}
        self.viewer = None
        self.entry = None
        self.button = None

    def on_load(self, context):
        self.context = context
        host = context.window
        sidebar = getattr(host, "sidebar", None)
        if hasattr(host, "_content") and hasattr(sidebar, "tool_row"):
            self.button = QAction("比赛二路", host)
            self.button.setCheckable(True)
            self.button.toggled.connect(self.set_enabled)
            self.entry = QToolButton(sidebar.tool_row)
            self.entry.setDefaultAction(self.button)
            self.entry.setObjectName("IconButton")
            self.entry.setToolTip("开启或关闭比赛二路模式")
            sidebar.tool_row.layout().insertWidget(0, self.entry)
        context.log("比赛二路同步已就绪；点击关注栏底部「比赛二路」按钮开启")

    def on_event(self, event, payload):
        if event == api.EVENT_STREAM_RESOLVED:
            source = payload["source"]
            if source.platform == "bilibili" and str(source.room_id).isdigit():
                self.sources[str(source.room_id)] = {
                    "url": source.url, "headers": dict(source.headers), "uname": source.uname,
                    "quality": source.quality or 250}
        elif event == api.EVENT_CLOSING:
            self.on_unload()

    def tile_actions(self, tile):
        if self.button is not None:
            return []
        room = tile.room or {}
        if str(room.get("room_id") or "").isdigit():
            return [("比赛二路同步…", lambda: self.open_viewer(dict(room)))]
        return []

    def set_enabled(self, enabled):
        if enabled:
            self.open_viewer({})
        elif self.viewer is not None:
            self.viewer.close()

    def _closed(self):
        if self.button is not None:
            self.button.blockSignals(True)
            self.button.setChecked(False)
            self.button.blockSignals(False)

    def open_viewer(self, room):
        if self.viewer is None:
            self.viewer = Viewer(self.context, self.sources, room)
            if self.button is not None:
                self.viewer.embed(self.context.window._content)
                self.viewer.finished.connect(lambda _result: self._closed())
        elif room.get("room_id") and str(room["room_id"]) not in self.viewer.rows:
            self.viewer.add_room(str(room["room_id"]), {"alias": room.get("uname") or ""})
        self.viewer.show()
        self.viewer.raise_()
        if self.button is not None and self.viewer.rows and not self.viewer.running:
            self.viewer.toggle_running()
        if self.button is None:
            self.viewer.activateWindow()

    def on_unload(self):
        if self.viewer is not None:
            self.viewer.close()
        if self.entry is not None:
            self.entry.deleteLater()
            self.entry = None
            self.button.deleteLater()
            self.button = None


plugin = MatchSyncPlugin()
