"""Present the existing tile as an owned window without resizing the playback wall."""
from PySide6.QtCore import QEvent, QObject, QRect, Qt

from .widgets import _repolish


class FullscreenPresentation(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.tile = None
        self._owner_hidden = False
        window.installEventFilter(self)

    def enter(self, tile, geometry=None):
        wall = self.window.wall
        self.tile = tile
        self._flags, self._geometry = tile.windowFlags(), QRect(tile.geometry())
        self._show_without_activating = tile.testAttribute(Qt.WA_ShowWithoutActivating)
        self._grid_enabled = wall.grid.isEnabled()
        self._visible = [(pane, pane.isVisible()) for pane in (*wall.tiles, wall.danmaku)]
        self._borders = [border for border in wall._pane_borders.values() if border.isVisible()]
        self._owner_hidden = False
        wall._fullscreen_layout_pending = True
        wall.grid.setEnabled(False)
        wall._relayout_timer.stop()
        wall._resize_timer.stop()
        wall.fullscreen_tile = tile
        tile.hide()
        wall._sync_danmaku_controls()
        for pane, visible in self._visible:
            if pane is not tile and visible:
                pane.hide()
        for border in self._borders:
            border.hide()
        tile.installEventFilter(self)
        tile._presentation_changing = True
        try:
            flags = Qt.Window | Qt.FramelessWindowHint
            background = (self._show_without_activating
                          or self.window.testAttribute(Qt.WA_ShowWithoutActivating)
                          or self.window.windowFlags() & Qt.WindowDoesNotAcceptFocus)
            tile.setAttribute(Qt.WA_ShowWithoutActivating, bool(background))
            if background:
                flags |= Qt.WindowDoesNotAcceptFocus
            tile.setWindowFlags(flags)
            tile.setProperty('fullscreen', True)
            _repolish(tile)
            tile.setGeometry(geometry if geometry is not None else self.window.screen().geometry())
        finally:
            tile._presentation_changing = False
        tile._layout_areas()
        layer = wall._quick_danmaku_layer
        if layer is not None:
            layer.set_presentation_window(tile)
        tile.show()
        tile.raise_()
        if not tile.testAttribute(Qt.WA_ShowWithoutActivating):
            tile.activateWindow()

    def leave(self):
        tile = self.tile
        if tile is None:
            return
        wall = self.window.wall
        tile.removeEventFilter(self)
        self.tile = None
        tile._presentation_changing = True
        try:
            tile.hide()
            layer = wall._quick_danmaku_layer
            if layer is not None:
                layer.set_presentation_window(None)
            tile.setProperty('fullscreen', False)
            _repolish(tile)
            tile.setWindowFlags(self._flags)
            tile.setAttribute(Qt.WA_ShowWithoutActivating, self._show_without_activating)
            tile.setGeometry(self._geometry)
        finally:
            tile._presentation_changing = False
        wall.fullscreen_tile = None
        wall._sync_danmaku_controls()
        tile._layout_areas()
        for pane, visible in self._visible:
            pane.setVisible(visible)
        for border in self._borders:
            border.show()
        wall._fullscreen_layout_pending = False
        wall.grid.setEnabled(self._grid_enabled)
        tile.bottom.setUpdatesEnabled(True)
        self._visible = self._borders = []
        if self.window.isVisible() and not self.window.testAttribute(Qt.WA_ShowWithoutActivating):
            self.window.activateWindow()

    def eventFilter(self, watched, event):
        tile = self.tile
        if tile is not None:
            if watched is tile and event.type() == QEvent.Close:
                event.ignore()
                self.window.close()
                return True
            if watched is self.window:
                if event.type() == QEvent.Hide:
                    self._owner_hidden = tile.isVisible()
                    tile.hide()
                elif event.type() == QEvent.Show and self._owner_hidden:
                    tile.show()
                    self._owner_hidden = False
        return super().eventFilter(watched, event)
