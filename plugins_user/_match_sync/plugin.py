"""Package entry point loaded by DD Monitor CE's single-file plugin loader."""
import os

from PySide6.QtWidgets import QToolBar

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
        self.toolbar = None
        self.button = None

    def on_load(self, context):
        self.context = context
        host = context.window
        if hasattr(host, "_content") and hasattr(host, "addToolBar"):
            self.toolbar = QToolBar("比赛二路", host)
            self.toolbar.setMovable(False)
            self.button = self.toolbar.addAction("比赛二路")
            self.button.setCheckable(True)
            self.button.toggled.connect(self.set_enabled)
            host.addToolBar(self.toolbar)
        context.log("比赛二路同步已就绪；点击主窗口「比赛二路」按钮开启")

    def on_event(self, event, payload):
        if event == api.EVENT_STREAM_RESOLVED:
            source = payload["source"]
            if source.platform == "bilibili" and str(source.room_id).isdigit():
                self.sources[str(source.room_id)] = {
                    "url": source.url, "headers": dict(source.headers), "uname": source.uname}
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
        if self.toolbar is not None:
            self.context.window.removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None
            self.button = None


plugin = MatchSyncPlugin()
