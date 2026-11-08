"""User result notifications and file actions."""
from pathlib import Path
import subprocess
import sys
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMenu, QWidget
from . import motion, theme
from .update_notice import UpdateNotice, _notifications_hidden
from .update_notice import _notifications_hidden


class ResultNotice(UpdateNotice):
    """顶部通知卡片：不抢焦点，按提示类型自动收起。"""
    def __init__(self, parent):
        super().__init__(parent)
        from .room_artwork import RoomArtwork
        self.artwork = RoomArtwork(())
        theme.signals().changed.connect(self._refresh_artwork_theme)
        self.platform_layout = QHBoxLayout()
        self.platform_layout.setContentsMargins(0, 0, 0, 0)
        self.platform_layout.setSpacing(4)
        self.text_column.layout().removeWidget(self.category)
        self.text_column.layout().insertLayout(0, self.platform_layout)
        self.description.hide()
        self.action.hide()
        self.timer.setInterval(3000)
        self.avatar_strip = QWidget(self)
        self.avatar_layout = QHBoxLayout(self.avatar_strip)
        self.avatar_layout.setContentsMargins(0, 0, 0, 0)
        self.avatar_layout.setSpacing(4)
        self.heading.insertWidget(0, self.avatar_strip, 0, Qt.AlignTop)
        self._avatars = {}
        self.avatar_strip.hide()
        self._on_click = None
        self._file_path = ''
        self._file_message = ''

    def _open_file_location(self):
        path = Path(self._file_path)
        if sys.platform == 'win32' and path.is_file():
            try:
                subprocess.Popen(['explorer.exe', '/select,', str(path)])
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def contextMenuEvent(self, event):
        from .online_ui import QMenu
        if not self._file_path:
            return super().contextMenuEvent(event)
        menu = QMenu(self)
        menu.addAction('打开文件位置', self._open_file_location)
        menu.addAction('复制完整路径', lambda _checked=False, path=self._file_path:
                       QApplication.clipboard().setText(path))
        active = self.timer.isActive()
        self.timer.stop()
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()
            if active and self.isVisible():
                self.timer.start()
        event.accept()

    def _open(self):
        callback = self._on_click
        self.dismiss(animate=False, handled=True)
        if callback is not None:
            callback()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._open()
            event.accept()
            return
        QFrame.mouseReleaseEvent(self, event)

    def hideEvent(self, event):
        super().hideEvent(event)
        if getattr(self.parentWidget(), '_result_notice', None) is self:
            self.parentWidget()._result_notice = None
        self.deleteLater()

    def _set_rooms(self, rooms):
        from .images import load_cached_avatar, load_room_avatar
        from .avatar_widgets import Avatar
        while self.avatar_layout.count():
            widget = self.avatar_layout.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self._avatars.clear()
        for index, room in enumerate(rooms[:3]):
            room_id = str(room.get("room_id", ""))
            avatar = Avatar(str(room.get("uname") or "?"), index, size=28)
            pixmap = load_cached_avatar(room.get("face")) if room.get("face") else None
            if pixmap is None:
                pixmap = load_room_avatar(room_id)
            if pixmap is not None:
                avatar.set_pixmap_image(pixmap)
            self.avatar_layout.addWidget(avatar)
            self._avatars[room_id] = avatar
        count = self.avatar_layout.count()
        self.avatar_strip.setFixedWidth(count * 28 + max(0, count - 1) * self.avatar_layout.spacing())
        self.avatar_strip.setVisible(bool(self._avatars))
        from .room_artwork import RoomArtwork, add_platform_logos, style_room_notice
        self.artwork = RoomArtwork(rooms)
        while self.platform_layout.count():
            widget = self.platform_layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                if widget is not self.category:
                    widget.deleteLater()
        add_platform_logos(self.platform_layout, rooms, self.text_column)
        self.platform_layout.addWidget(self.category)
        self.category.show()
        self.platform_layout.addStretch()
        style_room_notice(self, self.artwork)

    def set_room_artwork(self, room_id, pixmap, kind):
        from .room_artwork import style_room_notice
        if self.artwork.set_image(room_id, pixmap, kind):
            style_room_notice(self, self.artwork)

    def _refresh_artwork_theme(self, _mode):
        from .room_artwork import style_room_notice
        style_room_notice(self, self.artwork)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.artwork.source is not None:
            from .room_artwork import paint_room_background, notice_frost
            painter = QPainter(self)
            paint_room_background(painter, self.rect(), self.artwork.source, theme.RADIUS_LG,
                                  focus=self.artwork.banner is None, frost=notice_frost(self, self.artwork))

    def set_room_avatar(self, room_id, pixmap):
        avatar = self._avatars.get(str(room_id))
        if avatar is not None:
            avatar.set_pixmap_image(pixmap)

    def show_message(self, message, rooms=(), *, kind='info', on_click=None, persistent=False,
                     file_path=None, pending=False):
        from .notification_center import live_notice_action
        self._file_path = str(file_path or '')
        self._file_message = message + Path(self._file_path).name if self._file_path else message
        self._on_click = None if pending else self._open_file_location if self._file_path else on_click
        self.setCursor(Qt.PointingHandCursor if self._on_click else Qt.ArrowCursor)
        self.setToolTip(self._file_path if pending else
                        self._file_path + '\n点击打开文件位置；右键复制完整路径' if self._file_path
                        else ('点击跳转' if on_click else ''))
        self._close_timer.stop()
        self._motion.stop()
        self._leaving = False
        self.title.setWordWrap(not bool(self._file_path))
        self.title.setText(self._file_message)
        self.category.setText(('正在导出' if pending else '导出失败' if kind == 'warning' else '已完成') if self._file_path else
                              {'live': '开播提醒', 'warning': '需要留意'}.get(kind, '操作提示'))
        self.action.setVisible(pending or self._on_click is not None)
        self.action.setEnabled(not pending)
        self.action.setText('正在导出…' if pending else '打开文件位置' if self._file_path else
                            (live_notice_action(self.parentWidget()) if kind == 'live' else
                             ('前往登录' if '登录' in message else '查看详情')))
        self._set_rooms(rooms)
        symbol, colour = {'live': ('●', theme.PINK),
                          'warning': ('!', '#e8b86d')}.get(kind, ('i', theme.ACCENT))
        self.indicator.setText(symbol)
        self.indicator.setStyleSheet('color: ' + colour + '; font-weight: 600;')
        self.indicator.setVisible(not bool(self._avatars))
        self.timer.setInterval({'live': 5000, 'warning': 6000}.get(kind, 3000))
        self._resize_to_content()
        self._progress = self._progress if self.isVisible() else 0.0
        if not motion.enabled():
            self._progress = 1.0
        self.reposition()
        self.show()
        self.raise_()
        self.timer.stop()
        if not persistent:
            self.timer.start()
        if self._progress < 1.0:
            self._animate_to(1.0, 160)

    def _resize_to_content(self):
        super()._resize_to_content()
        if self._file_path:
            self.title.setText(self.title.fontMetrics().elidedText(
                self._file_message, Qt.ElideMiddle, self.title.width()))
            super()._resize_to_content()

    def _motion_frame(self, value):
        self._progress = value
        self.reposition()

    def reposition(self):
        parent = self.parentWidget()
        offset = round(-12 * (1 - self._progress)) if motion.enabled() else 0
        self.move(parent.mapToGlobal(QPoint(self._left_x() + offset, self._stack_y())))


def show_result(parent, message, rooms=(), *, kind='info', on_click=None, persistent=False,
                file_path=None, notice_key=None, pending=False):
    from .notification_center import remember_result
    if getattr(parent, '_closing', False):
        return
    record = remember_result(parent, message, kind=kind, on_click=on_click, file_path=file_path,
                             rooms=rooms, notice_key=notice_key, pending=pending)
    if not parent.isVisible() or _notifications_hidden(parent):
        return
    notice = next((item for item in getattr(parent, '_notices', [])
                   if notice_key is not None and getattr(item, '_notice_key', None) == notice_key), None)
    if notice is None:
        notice = ResultNotice(parent)
    notice._notice_key = notice_key
    parent._result_notice = notice
    notice.track_history(record)
    notice.show_message(message, rooms, kind=kind, on_click=on_click,
                        persistent=persistent or pending, file_path=file_path, pending=pending)
