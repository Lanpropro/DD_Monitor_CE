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

    def _set_comments_changing(self, active):
        wall = self.window.wall
        if wall._quick_danmaku_layer is not None:
            wall._quick_danmaku_layer.set_presentation_changing(active)
        for pane in wall.tiles:
            pane.video_danmaku.super_chat_overlay.set_presentation_changing(active)

    def enter(self, tile, geometry=None):
        wall = self.window.wall
        geometry = QRect(geometry if geometry is not None else self.window.screen().geometry())
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
        self._set_comments_changing(True)
        tile.hide()
        wall._sync_danmaku_controls()
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
            tile.winId()
            tile.setGeometry(geometry)
            tile.bottom.set_fullscreen(True)
        finally:
            tile._presentation_changing = False
        tile._layout_areas()
        layer = wall._quick_danmaku_layer
        if layer is not None:
            layer.set_presentation_changing(True)
            layer.set_presentation_window(tile)
        # Exposing a new Tool bar can dispatch the owner's old native resize.
        # Finish that work before restoring the final rectangle and first frame.
        if tile.bottom.qt_composited:
            tile.bottom.prepare_fullscreen_frame()
            tile.setGeometry(geometry)
            tile._layout_areas()
            tile.bottom.prepare_fullscreen_frame()
        tile.show()
        if tile.bottom.qt_composited:
            tile.bottom.setWindowOpacity(1.0)
        tile.raise_()
        if not tile.testAttribute(Qt.WA_ShowWithoutActivating):
            tile.activateWindow()
        dialog = getattr(self.window, '_stream_info_dialogs', {}).get(tile)
        if dialog is not None:
            dialog.set_presentation_owner(tile)
            if dialog.isVisible():
                dialog.raise_()
        # Keep the wall visible until its replacement is on screen.
        for pane, visible in self._visible:
            if pane is not tile and visible:
                pane.hide()
        for border in self._borders:
            border.hide()
        self._set_comments_changing(False)

    def leave(self):
        tile = self.tile
        if tile is None:
            return
        native_bar = tile.bottom.qt_composited
        wall = self.window.wall
        layer = wall._quick_danmaku_layer
        self._set_comments_changing(True)
        # Restore the wall behind the still-visible fullscreen window.
        for pane, visible in self._visible:
            if pane is not tile:
                pane.setVisible(visible)
                if native_bar and visible and pane in wall.tiles:
                    # show() queues painting; flush bars while fullscreen still
                    # covers the wall, rather than exposing empty backing stores.
                    pane.bottom.repaint()
        for border in self._borders:
            border.show()
        dialog = getattr(self.window, '_stream_info_dialogs', {}).get(tile)
        if dialog is not None:
            # Detach before changing the tile's native window flags on exit.
            dialog.set_presentation_owner(self.window)
        tile.removeEventFilter(self)
        self.tile = None
        tile._presentation_changing = True
        try:
            tile.hide()
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
            if pane is tile:
                pane.setVisible(visible)
        tile.bottom.setUpdatesEnabled(True)
        if native_bar:
            tile.bottom.repaint()
        wall._fullscreen_layout_pending = False
        wall.grid.setEnabled(self._grid_enabled)
        self._visible = self._borders = []
        if self.window.isVisible() and not self.window.testAttribute(Qt.WA_ShowWithoutActivating):
            self.window.activateWindow()
        if dialog is not None and dialog.isVisible():
            dialog.raise_()
        self._set_comments_changing(False)

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
