"""Present the existing video in an owned window or in the main capture window."""
import os

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication

from . import window_fullscreen
from .widget_support import _repolish


class FullscreenPresentation(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.tile = None
        self._owner_hidden = False
        self._windowed_state = None
        self._windowed_geometry = None
        self._maximized_frame = None
        window.installEventFilter(self)

    def save_window_geometry(self):
        if self._windowed_geometry is not None:
            return self._windowed_geometry
        return self.window.saveGeometry()

    def _activate_main_layout(self):
        self.window.centralWidget().layout().activate()
        self.window._content.layout().activate()

    def _set_comments_changing(self, active):
        wall = self.window.wall
        if wall._quick_danmaku_layer is not None:
            wall._quick_danmaku_layer.set_presentation_changing(active)
        for pane in wall.tiles:
            pane.video_danmaku.super_chat_overlay.set_presentation_changing(active)

    def enter(self, tile, geometry=None):
        wall = self.window.wall
        in_main_window = (geometry is None and QApplication.platformName() == 'windows'
                          and os.environ.get('DDM_FULLSCREEN_WINDOW_CAPTURE') != '0')
        geometry = QRect(geometry if geometry is not None else self.window.screen().geometry())
        self.tile = tile
        self._flags, self._geometry = tile.windowFlags(), QRect(tile.geometry())
        self._show_without_activating = tile.testAttribute(Qt.WA_ShowWithoutActivating)
        self._grid_enabled = wall.grid.isEnabled()
        panes = wall.pane_danmaku
        # A covered docked chat can stay in the wall's backing store throughout
        # fullscreen, so its text has no deferred first paint on return.
        panels = set(panes.all_panels())
        wall_widgets = [widget for widget in panes.wall_widgets() if in_main_window
                        or widget not in panels
                        or not geometry.contains(QRect(widget.mapToGlobal(QPoint()), widget.size()))]
        if in_main_window:
            self._windowed_state = self.window.windowState()
            self._windowed_geometry = self.window.saveGeometry()
            wall_widgets.extend((self.window.sidebar, self.window.empty_hint))
        native_maximized = in_main_window and bool(self._windowed_state & Qt.WindowMaximized)
        self._visible = [(pane, pane.isVisible()) for pane in (*wall.tiles, *wall_widgets)]
        self._borders = [border for border in wall._pane_borders.values() if border.isVisible()]
        self._owner_hidden = False
        wall._fullscreen_layout_pending = True
        wall.grid.setEnabled(False)
        wall._relayout_timer.stop()
        wall._resize_timer.stop()
        wall.fullscreen_tile = tile
        self._set_comments_changing(True)
        wall._sync_danmaku_controls()
        tile.installEventFilter(self)
        bar = tile.bottom
        bar_visible = bar.windowed_overlay or not bar.isHidden()
        tile._presentation_changing = True
        try:
            bar.hide()
            if in_main_window:
                self.window.sidebar.hide()
                self.window.empty_hint.hide()
                # Keep the video in its original HWND hierarchy for window capture.
                if not native_maximized:
                    self.window.setWindowState(Qt.WindowFullScreen)
                self._activate_main_layout()
                geometry = QRect(QPoint(), geometry.size()) if native_maximized else wall.rect()
            else:
                flags = Qt.Window | Qt.FramelessWindowHint
                background = (self._show_without_activating
                              or self.window.testAttribute(Qt.WA_ShowWithoutActivating)
                              or self.window.windowFlags() & Qt.WindowDoesNotAcceptFocus)
                tile.setAttribute(Qt.WA_ShowWithoutActivating, bool(background))
                if background:
                    flags |= Qt.WindowDoesNotAcceptFocus
                tile.hide()
                tile.setWindowFlags(flags)
            tile.setProperty('fullscreen', True)
            _repolish(tile)
            if not in_main_window:
                tile.winId()
            tile.setGeometry(geometry)
            # Expose the existing video HWND before rebuilding the native bar.
            tile.presentation_control.layout_video_area()
            tile.show()
            tile.raise_()
            if native_maximized:
                # Applying the native frame can dispatch intermediate paints.
                # Give them the fullscreen video instead of the old video rectangle.
                self._maximized_frame = window_fullscreen.enter(self.window)
                self._activate_main_layout()
        finally:
            tile._presentation_changing = False
        tile._layout_areas()
        if bar.qt_composited:
            bar.setWindowOpacity(0.0)
        bar.setVisible(bar_visible)
        # Exposing a new Tool bar can dispatch the owner's old native resize.
        if bar.qt_composited and bar_visible:
            bar.prepare_fullscreen_frame()
            if tile.geometry() != geometry:
                size_changed = tile.size() != geometry.size()
                tile.setGeometry(geometry)
                if size_changed:
                    tile._layout_areas()
                else:
                    bar.sync_owner_position()
                bar.prepare_fullscreen_frame()
            bar.setWindowOpacity(1.0)
        if not tile.window().testAttribute(Qt.WA_ShowWithoutActivating):
            tile.activateWindow()
        for notice in tuple(getattr(self.window, '_notices', ())):
            notice.set_presentation_owner(tile.window())
        dialog = getattr(self.window, '_stream_info_dialogs', {}).get(tile)
        if dialog is not None:
            dialog.set_presentation_owner(tile.window())
            if dialog.isVisible():
                dialog.raise_()
        # Keep the other panes visible until the selected video is ready.
        for pane, visible in self._visible:
            if pane is not tile and visible:
                pane.hide()
        for border in self._borders:
            border.hide()
        layer = wall._quick_danmaku_layer
        if layer is not None:
            if in_main_window:
                layer.resize()
            else:
                layer.set_presentation_window(tile)
        self._set_comments_changing(False)

    def leave(self):
        tile = self.tile
        if tile is None:
            return
        native_bar = tile.bottom.qt_composited
        in_main_window = self._windowed_state is not None
        wall = self.window.wall
        layer = wall._quick_danmaku_layer
        self._set_comments_changing(True)
        if in_main_window:
            tile.bottom.hide()
            if self._maximized_frame is not None:
                window_fullscreen.exit(self.window, self._maximized_frame)
                self._maximized_frame = None
            else:
                self.window.setWindowState(self._windowed_state)
            self._windowed_state = self._windowed_geometry = None
        # The independent presentation still covers the wall during restoration.
        for pane, visible in self._visible:
            if pane is not tile:
                pane.setVisible(visible)
                if not in_main_window and native_bar and visible and pane in wall.tiles:
                    # show() queues painting; flush bars while fullscreen still
                    # covers the wall, rather than exposing empty backing stores.
                    pane.bottom.repaint()
        for border in self._borders:
            border.show()
        dialog = getattr(self.window, '_stream_info_dialogs', {}).get(tile)
        if dialog is not None:
            # Detach before changing the tile's native window flags on exit.
            dialog.set_presentation_owner(self.window)
        if in_main_window:
            self._activate_main_layout()
            if layer is not None:
                layer.resize()
        elif layer is not None:
            layer.set_presentation_window(None)
        tile.removeEventFilter(self)
        self.tile = None
        for notice in tuple(getattr(self.window, '_notices', ())):
            notice.set_presentation_owner(self.window)
        tile._presentation_changing = True
        try:
            tile.bottom.hide()
            if not in_main_window:
                tile.hide()
            tile.setProperty('fullscreen', False)
            _repolish(tile)
            if not in_main_window:
                tile.setWindowFlags(self._flags)
                tile.setAttribute(Qt.WA_ShowWithoutActivating, self._show_without_activating)
            tile.setGeometry(self._geometry)
            tile.presentation_control.layout_video_area()
            for pane, visible in self._visible:
                if pane is tile:
                    pane.setVisible(visible)
                    break
        finally:
            tile._presentation_changing = False
        wall.fullscreen_tile = None
        wall._sync_danmaku_controls()
        tile._layout_areas()
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
            if watched is self.window and tile.isWindow():
                if event.type() == QEvent.Hide:
                    self._owner_hidden = tile.isVisible()
                    tile.hide()
                elif event.type() == QEvent.Show and self._owner_hidden:
                    tile.show()
                    self._owner_hidden = False
        return super().eventFilter(watched, event)
