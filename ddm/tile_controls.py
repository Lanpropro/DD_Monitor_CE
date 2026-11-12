"""Tile controls; mutable state and Qt ownership stay with Tile."""
import time
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QPushButton
from . import motion
from .fullscreen_cursor import set_native_cursor
from .widget_support import TILE_BAR_HEIGHT, _repolish


class TileControls:
    def __init__(self, host):
        self.host = host

    def plugin_interaction_active(self) -> bool:
        host = self.host
        controls = getattr(host, '_plugin_controls', None)
        return controls.interaction_active() if controls is not None else False

    def volume_clicked(self) -> None:
        host = self.host
        host._toggle_mute()

    def show_volume_popup(self) -> None:
        host = self.host
        if not host.volume_button.isVisible() or not host.volume_slider.isHidden():
            return
        host._volume_hide_timer.stop()
        host.volume_menu.ensurePolished()
        host.volume_menu.adjustSize()
        anchor = host.volume_button.mapToGlobal(QPoint(host.volume_button.width() // 2, 0))
        screen = host.screen().availableGeometry()
        x = max(screen.left(), min(anchor.x() - host.volume_menu.width() // 2,
                                  screen.right() - host.volume_menu.width() + 1))
        host.volume_menu.move(x, max(screen.top(), anchor.y() - host.volume_menu.height() - 4))
        host.volume_menu.show()
        host.volume_menu.raise_()

    def hide_volume_popup_if_outside(self) -> None:
        host = self.host
        if host.vertical_volume.isSliderDown():
            host._volume_hide_timer.start()
            return
        point = QCursor.pos()
        if any(widget.rect().contains(widget.mapFromGlobal(point))
               for widget in (host.volume_button, host.volume_menu)):
            return
        host.volume_menu.hide()

    def set_fullscreen_controls_hidden(self, hidden: bool, *, hide_bar: bool = True) -> None:
        host = self.host
        target = 1.0 if hidden and hide_bar and host.property("fullscreen") else 0.0
        if hidden == getattr(host, "_fullscreen_controls_hidden", False) and target == host._bar_target:
            return
        host._bar_clock.stop()
        host._bar_animation.stop()
        host._fullscreen_controls_hidden = hidden
        host._bar_target = target
        host.set_controls_visible(not hidden)
        if host.property("fullscreen") and motion.enabled():
            host.bottom.show()
            host._layout_areas()
            host._bar_animation.blockSignals(True)
            host._bar_animation.setCurrentTime(0)
            host._bar_animation.setStartValue(host._bar_progress)
            host._bar_animation.setEndValue(target)
            host._bar_animation.blockSignals(False)
            host._bar_animation.start()
            # Advance this QWidget slide independently of Quick's shared
            # animation clock, which stopped ticking in captured re-entries.
            host._bar_animation.pause()
            host._bar_started = time.monotonic()
            host._bar_clock.start()
        else:
            host._slide_fullscreen_bar(target)
            host._layout_areas()

    def advance_bar_animation(self) -> None:
        host = self.host
        duration = host._bar_animation.duration()
        elapsed = min(duration, round((time.monotonic() - host._bar_started) * 1000))
        host._bar_animation.setCurrentTime(elapsed)
        if elapsed >= duration:
            host._bar_clock.stop()
            host._bar_animation.stop()

    def slide_fullscreen_bar(self, progress) -> None:
        host = self.host
        host._bar_progress = float(progress)
        offset = round(TILE_BAR_HEIGHT * host._bar_progress)
        host.bottom.set_tile_geometry(0, host.height() - TILE_BAR_HEIGHT
                                      + offset,
                                      host.bottom.width(), host.bottom.height())
        if host.bottom.qt_composited:
            host.bottom.setWindowOpacity(1.0 - host._bar_progress)
        host.bottom.setVisible(host._bar_progress < 1.0 or host._bar_target == 0.0)
        host._layout_time_badge()
        host.bottom.raise_()

    def set_controls_visible(self, visible: bool) -> None:
        host = self.host
        visible = (visible and not host.property('pictureInPicture')
                   and not getattr(host, "_fullscreen_controls_hidden", False))
        visible = bool(visible)
        host.controls.setVisible(visible)
        # LIVE 浮标和标题跟着一起显隐（用户要求：别一直挂在画面上）
        host._overlay_visible = visible
        host._sync_stream_badge()
        # 右下角的直播时长和它们一样：鼠标在格子上才露出来
        host.time_badge.setVisible(host._elapsed_visible())
        if visible and getattr(host, "_overlay_ready", False):
            # 露出来之前按当前宽度重摆一遍（标题要重新让位）。
            # 构造过程中（spinner 等还没建好）不能走这里，否则会碰空控件。
            host._layout_areas()
        if visible:
            host.raise_overlays()          # 视频是原生窗口，浮层要重新抬上来
            host._round_video()            # 控制条那块从视频遮罩里挖掉
            host._controls_hide_timer.stop()
            # 显示之前先按文本把按钮宽度摆好：否则会沿用上一次的尺寸，
            # 画质文字换了之后整条控制条看起来就是错位的。
            host._layout_controls()
            host._sync_control_hover()
            host._control_hover_timer.start()
        else:
            if host.property("fullscreen") or not host._normal_hover_active:
                host._control_hover_timer.stop()
            host._set_control_hover(None)
            host.title_badge.setVisible(False)   # 收起时标题一起收
            host._round_video()                  # 收起来就把视频遮罩补回圆角

    def set_control_hover(self, hovered: QPushButton | None) -> None:
        """同步一份不依赖原生窗口 enter/leave 的悬停状态。"""
        host = self.host
        for button in (host.quality_button, host.reload_button, host.close_button):
            active = button is hovered
            if button.property("hovered") is active:
                continue
            button.setProperty("hovered", active)
            _repolish(button)
            button.update()

    def sync_control_hover(self, global_pos: QPoint | None = None) -> None:
        host = self.host
        global_pos = global_pos or QCursor.pos()
        hovered = None
        for button in (host.quality_button, host.reload_button, host.close_button):
            local = button.mapFromGlobal(global_pos)
            if button.rect().contains(local):
                hovered = button
                break
        host._set_control_hover(hovered)

    def poll_control_hover(self, *, native_cursor) -> None:
        set_native_cursor = native_cursor
        host = self.host
        if host.property('pictureInPicture'):
            host._restore_normal_cursor()
            host._normal_hover_active = False
            host.set_controls_visible(False)
            host._control_hover_timer.stop()
            return
        if not host.isVisible():
            host._restore_normal_cursor()
            host._normal_hover_active = False
            host._control_hover_timer.stop()
            return
        if host.property("fullscreen"):
            host._restore_normal_cursor()
            host._normal_hover_active = False
            host._sync_control_hover()
            return
        position, now = QCursor.pos(), time.monotonic()
        protected = (host.plugin_interaction_active() or QApplication.activePopupWidget() is not None
                     or QApplication.activeModalWidget() is not None or bool(QApplication.mouseButtons())
                     or QApplication.overrideCursor() is not None)
        if protected:
            host._restore_normal_cursor()
            host._control_last_move = now
            return
        if not host.rect().contains(host.mapFromGlobal(position)):
            host._restore_normal_cursor()
            host._normal_hover_active = False
            host.set_controls_visible(False)
            return
        moved = not host._normal_hover_active or position != host._control_pointer
        host._normal_hover_active = True
        host._control_pointer = position
        over_controls = any(widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(position))
                            for widget in (host.controls, host.stream_badge, host.title_badge, host.bottom))
        if moved or over_controls:
            host._restore_normal_cursor()
            host._control_last_move = now
            if not host._overlay_visible:
                host.set_controls_visible(True)
        elif now - host._control_last_move >= host.CONTROL_IDLE_SECONDS:
            if host._overlay_visible:
                host.set_controls_visible(False)
            if host.video.rect().contains(host.video.mapFromGlobal(position)):
                if not host._normal_cursor_hidden:
                    host._normal_cursor = host.video.cursor() if host.video.testAttribute(Qt.WA_SetCursor) else None
                    host.video.setCursor(Qt.BlankCursor)
                    host._normal_cursor_hidden = True
                set_native_cursor(Qt.BlankCursor, host.video)
        if host._overlay_visible:
            host._sync_control_hover(position)

    def restore_normal_cursor(self, *, native_cursor) -> None:
        set_native_cursor = native_cursor
        host = self.host
        if not host._normal_cursor_hidden:
            return
        if host._normal_cursor is None:
            host.video.unsetCursor()
        else:
            host.video.setCursor(host._normal_cursor)
        host._normal_cursor_hidden = False
        host._normal_cursor = None
        if (host.isVisible() and QApplication.overrideCursor() is None
                and host.video.rect().contains(host.video.mapFromGlobal(QCursor.pos()))):
            set_native_cursor(host.video.cursor().shape(), host.video)

    def hide_controls_if_outside(self) -> None:
        host = self.host
        if (host.plugin_interaction_active() or QApplication.activePopupWidget() is not None
                or QApplication.activeModalWidget() is not None or QApplication.mouseButtons()):
            return
        local = host.mapFromGlobal(QCursor.pos())
        if host.rect().contains(local):
            return
        host.set_controls_visible(False)

    def show_danmaku_actions(self, text, position):
        host = self.host
        from .danmaku_actions import show_comment_menu
        host.video_danmaku._menu_open = True
        def finished():
            host.video_danmaku._menu_open = False
            host.video_danmaku._poll_hover()
        show_comment_menu(host, text, getattr(host, '_plugin_controls', None), position, finished)

    def open_clicked_danmaku(self, event):
        host = self.host
        start = getattr(host, '_press_pos', None)
        if event.button() == Qt.LeftButton:
            host._press_pos = None
        position = event.globalPosition().toPoint()
        return (event.button() == Qt.LeftButton and start is not None
                and (host.mapFromGlobal(position) - start).manhattanLength() < QApplication.startDragDistance()
                and host.video_danmaku.open_actions_at(position))

    def focus_danmaku_input(self) -> None:
        host = self.host
        controls = getattr(host, '_plugin_controls', None)
        if controls is not None:
            # The fullscreen bar is a separate tool window. setFocus alone
            # only records a pending focus child while the video stays active.
            if host.bottom.isWindow() and controls.widget.isVisible():
                host.bottom.activateWindow()
            controls.focus_input()
