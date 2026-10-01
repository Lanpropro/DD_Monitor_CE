"""Package entry point loaded by DD Monitor CE's single-file plugin loader."""
import os

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

    def on_load(self, context):
        self.context = context
        context.log("比赛二路同步已就绪；从直播画面右键菜单进入")

    def on_event(self, event, payload):
        if event == api.EVENT_STREAM_RESOLVED:
            source = payload["source"]
            if source.platform == "bilibili" and str(source.room_id).isdigit():
                self.sources[str(source.room_id)] = {
                    "url": source.url, "headers": dict(source.headers), "uname": source.uname}
        elif event == api.EVENT_CLOSING:
            self.on_unload()

    def tile_actions(self, tile):
        room = tile.room or {}
        if str(room.get("room_id") or "").isdigit():
            return [("比赛二路同步…", lambda: self.open_viewer(dict(room)))]
        return []

    def open_viewer(self, room):
        if self.viewer is None:
            self.viewer = Viewer(self.context, self.sources, room)
        elif str(room.get("room_id") or "") not in self.viewer.rows:
            self.viewer.add_room(str(room["room_id"]), {"alias": room.get("uname") or ""})
        self.viewer.show()
        self.viewer.raise_()
        self.viewer.activateWindow()

    def on_unload(self):
        if self.viewer is not None:
            self.viewer.close()


plugin = MatchSyncPlugin()
