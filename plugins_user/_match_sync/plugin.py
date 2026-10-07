"""Package entry point loaded by DD Monitor CE's single-file plugin loader."""
import os

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout

from ddm import plugins as api

# Keep sibling imports local to this plugin, including in the frozen EXE.
__path__ = [os.path.dirname(__file__)]
__package__ = __name__

from .viewer import Viewer


class EntryButton(QToolButton):
    """Keep the plugin entry outside the host's two-button tool row."""
    def __init__(self, sidebar, action):
        super().__init__(sidebar)
        self.sidebar = sidebar
        self._top = None
        self.setDefaultAction(action)
        action.setToolTip("比赛二路：开启或关闭比赛二路模式")
        self.setAccessibleName("比赛二路")
        pixmap = QPixmap(36, 36)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#dde3eb"), 1.5))
        painter.drawRoundedRect(2, 3, 8, 12, 2, 2)
        painter.drawRoundedRect(12, 6, 4, 9, 1, 1)
        painter.end()
        action.setIcon(QIcon(pixmap))
        self.setIconSize(QSize(18, 18))
        self._placement = QTimer(self)
        self._placement.setSingleShot(True)
        self._placement.timeout.connect(self._place)
        sidebar.installEventFilter(self)
        self._place()

    def eventFilter(self, watched, event):
        if watched is self.sidebar and event.type() in (
                QEvent.LayoutRequest, QEvent.Resize, QEvent.Show):
            self._placement.start(0)
        return super().eventFilter(watched, event)

    def _place(self):
        sidebar = self.sidebar
        top = getattr(sidebar, "side", "left") == "top"
        if top:
            parent = sidebar._bar_row
            box = sidebar._bar_row_box
            anchor = sidebar.toggle_button
        else:
            parent = sidebar
            box = sidebar.layout() or QVBoxLayout(sidebar)
            anchor = sidebar.tool_row
        if self._top != top:
            self._top = top
            self.setObjectName("BarIcon" if top else "IconButton")
            self.setToolButtonStyle(Qt.ToolButtonIconOnly if top else Qt.ToolButtonTextOnly)
            self.setMinimumSize(QSize(30, 30) if top else QSize(0, 0))
            self.setMaximumSize(QSize(30, 30) if top else QSize(16777215, 16777215))
            self.setSizePolicy(QSizePolicy.Fixed if top else QSizePolicy.Expanding,
                               QSizePolicy.Fixed)
            self.style().unpolish(self)
            self.style().polish(self)
        if (self.parentWidget() is not parent or box.indexOf(self) < 0
                or box.indexOf(self) + 1 != box.indexOf(anchor)):
            old = self.parentWidget().layout()
            if old is not None:
                old.removeWidget(self)
            self.setParent(parent)
            box.insertWidget(box.indexOf(anchor), self)
        self.setVisible(top or not getattr(sidebar, "collapsed", False))

    def detach(self):
        self.sidebar.removeEventFilter(self)
        self._placement.stop()
        if self.parentWidget().layout() is not None:
            self.parentWidget().layout().removeWidget(self)
        self.hide()
        self.deleteLater()


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
            self.entry = EntryButton(sidebar, self.button)
        context.log("比赛二路同步已就绪；点击关注栏「比赛二路」入口开启")

    def on_event(self, event, payload):
        if event == api.EVENT_STREAM_RESOLVED:
            source = payload["source"]
            platform = self.context.manager.platform_for(str(source.room_id))
            if str(source.room_id).isdigit() or platform is not None:
                room_id = platform.normalize(str(source.room_id)) if platform else str(source.room_id)
                self.sources[room_id] = {
                    "url": source.url, "headers": dict(source.headers), "uname": source.uname,
                    "quality": source.quality or 250, "title": source.title}
        elif event == api.EVENT_CLOSING:
            self.on_unload()

    def tile_actions(self, tile):
        if self.button is not None:
            return []
        room = tile.room or {}
        room_id = str(room.get("room_id") or "")
        if room_id.isdigit() or self.context.manager.platform_for(room_id) is not None:
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
            self.entry.detach()
            self.entry = None
            self.button.deleteLater()
            self.button = None


plugin = MatchSyncPlugin()
