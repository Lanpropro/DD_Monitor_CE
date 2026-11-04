"""A selected group of existing playback panes in one independent floating window."""
import math

from PySide6.QtCore import QByteArray, QObject, QRect, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QScrollArea, QVBoxLayout, QWidget,
)

from . import theme
from .ui import ActionButton, ElidedLabel, page_header


def pane_rectangles(count, area, columns=0):
    if not count:
        return []
    if not columns:
        # Prefer cells close to a video's aspect ratio, including tall windows.
        columns = min(range(1, count + 1), key=lambda cols:
            abs(math.log(max(1, area.width()) * math.ceil(count / cols)
                         / (max(1, area.height()) * cols * 16 / 9)))
            + (math.ceil(count / cols) * cols - count) * .08)
    columns = min(count, columns)
    rows = math.ceil(count / columns)
    gap = 3
    width = max(1, area.width() - gap * (columns - 1))
    height = max(1, area.height() - gap * (rows - 1))
    return [QRect(area.x() + width * (index % columns) // columns + gap * (index % columns),
                  area.y() + height * (index // columns) // rows + gap * (index // columns),
                  width * (index % columns + 1) // columns - width * (index % columns) // columns,
                  height * (index // columns + 1) // rows - height * (index // columns) // rows)
            for index in range(count)]


class CompositionPreview(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('PluginCard')
        self.setFixedHeight(156)
        self.labels = []
        self.columns = 0
        self.aspect = 16 / 9

    def set_panes(self, names, columns, aspect=0):
        for label in self.labels:
            label.deleteLater()
        self.labels = [ElidedLabel(name, self) for name in names]
        self.columns = columns
        cols = min(len(names), columns or math.ceil(math.sqrt(len(names)))) if names else 1
        self.aspect = aspect or cols / max(1, math.ceil(len(names) / cols)) * 16 / 9
        for label in self.labels:
            label.setAlignment(Qt.AlignCenter)
            label.setObjectName('PluginCard')
            label.setTextFormat(Qt.PlainText)
            label.show()
        self._arrange()

    def _arrange(self):
        area = self.rect().adjusted(8, 8, -8, -8)
        width = min(area.width(), round(area.height() * self.aspect))
        canvas = QRect(0, 0, width, min(area.height(), round(width / self.aspect)))
        canvas.moveCenter(area.center())
        for label, rect in zip(self.labels, pane_rectangles(
                len(self.labels), canvas, self.columns)):
            label.setGeometry(rect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()


class PictureInPictureDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.floating or controller.host)
        self.controller = controller
        self.setWindowTitle('组合画中画')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(480, 580)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addLayout(page_header('画中画', '选择画面组合；关闭小窗后返回原监控室布局'))
        self.preview = CompositionPreview(self)
        layout.addWidget(self.preview)
        self.columns = QComboBox(self)
        for title, value in (('自动排列', 0), ('横向排列', 16), ('纵向排列', 1), ('两列排列', 2), ('三列排列', 3)):
            self.columns.addItem(title, value)
        self.columns.setAccessibleName('画中画排列方式')
        self.columns.setCurrentIndex(max(0, self.columns.findData(controller.columns)))
        layout.addWidget(self.columns)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        choices = QVBoxLayout(content)
        self.checks = {}
        capacity = controller.host.wall._capacity() or len(controller.host.wall.tiles)
        for index, tile in enumerate(controller.host.wall.tiles[:capacity]):
            if not tile.room.get('room_id'):
                continue
            name = f'{index + 1} · ' + str(tile.room.get('uname') or tile.room['room_id'])
            check = QCheckBox(name, content)
            check.setToolTip(name)
            check.setChecked(index in controller.selection)
            check.toggled.connect(self._refresh)
            self.checks[index] = check
            choices.addWidget(check)
        choices.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.hint = QLabel(self)
        self.hint.setObjectName('SettingsHint')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        footer = QHBoxLayout()
        cancel = ActionButton('取消', self)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        footer.addStretch()
        self.start = ActionButton('应用组合' if controller.active else '打开画中画', self)
        self.start.setObjectName('PrimaryButton')
        self.start.clicked.connect(self._apply)
        footer.addWidget(self.start)
        layout.addLayout(footer)
        self.columns.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_args):
        names = [check.text() for check in self.checks.values() if check.isChecked()]
        wall = self.controller.host.wall
        aspect = wall.width() / max(1, wall.height()) if self.controller.active else 0
        self.preview.set_panes(names, self.columns.currentData(), aspect)
        self.start.setEnabled(bool(names))
        self.hint.setText(f'已选择 {len(names)} 路。小窗支持自由缩放和置顶，其他画面按原声音设置在后台播放。'
                          if self.checks else '画面墙中还没有直播间，请先添加画面。')

    def _apply(self):
        selected = [index for index, check in self.checks.items() if check.isChecked()]
        self.controller.start(selected, self.columns.currentData())
        self.accept()


class PictureInPictureWindow(QWidget):
    def __init__(self, controller):
        flags = Qt.Window | (Qt.WindowStaysOnTopHint if controller.pinned else Qt.Widget)
        super().__init__(None, flags)
        self.controller = controller
        self.setWindowTitle('画中画 · DD监控室CE')
        self.setObjectName('PictureInPicture')
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet(f'#PictureInPicture {{ background: {theme.BG}; }}')
        self.setMinimumSize(280, 180)
        self.resize(640, 400)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(4, 4, 4, 4)
        self.box.setSpacing(4)
        toolbar = QHBoxLayout()
        self.title = QLabel(self)
        self.title.setObjectName('SettingsHint')
        toolbar.addWidget(self.title, 1)
        manage = ActionButton('组合', self)
        manage.clicked.connect(controller.manage)
        toolbar.addWidget(manage)
        self.pin = QCheckBox('置顶', self)
        self.pin.setChecked(controller.pinned)
        self.pin.toggled.connect(self._pin)
        toolbar.addWidget(self.pin)
        back = ActionButton('返回', self)
        back.setToolTip('返回监控室（Esc）')
        back.clicked.connect(self.close)
        toolbar.addWidget(back)
        self.box.addLayout(toolbar)
        shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        shortcut.activated.connect(self.close)

    def _pin(self, pinned):
        self.controller.pinned = pinned
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, pinned)
        self.setGeometry(geometry)
        self.show()

    def closeEvent(self, event):
        self.controller.restore(activate=True)
        event.accept()


class PictureInPicture(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.floating = None
        self.dialog = None
        saved = host.state.get('ui', {}).get('picture_in_picture', {})
        self.selection = list(saved.get('selection', []))
        self.columns = saved.get('columns', 0)
        self.pinned = bool(saved.get('pinned', True))
        self.geometry = saved.get('geometry', '')
        theme.signals().changed.connect(self._refresh_theme)
        self.placeholder = QFrame(host._content)
        self.placeholder.setObjectName('PluginCard')
        layout = QVBoxLayout(self.placeholder)
        layout.addStretch()
        text = QLabel('正在画中画中观看\n其他画面按原设置在后台播放\n返回后恢复原监控室布局', self.placeholder)
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)
        for title, action in (('管理画中画', self.manage), ('返回监控室', self.restore)):
            button = ActionButton(title, self.placeholder)
            button.clicked.connect(action)
            layout.addWidget(button, 0, Qt.AlignHCenter)
        layout.addStretch()
        self.placeholder.hide()

    @property
    def active(self):
        return self.floating is not None

    def _refresh_theme(self, *_args):
        if self.active:
            self.floating.setStyleSheet(f'#PictureInPicture {{ background: {theme.BG}; }}')

    def manage(self):
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if not self.selection:
            capacity = self.host.wall._capacity() or len(self.host.wall.tiles)
            self.selection = [index for index, tile in enumerate(self.host.wall.tiles[:capacity])
                              if tile.room.get('room_id')]
        self.dialog = PictureInPictureDialog(self)
        self.dialog.finished.connect(lambda _result: setattr(self, 'dialog', None))
        self.dialog.open()

    def start(self, selection, columns=0):
        wall = self.host.wall
        tiles = [wall.tiles[index] for index in selection
                 if 0 <= index < len(wall.tiles) and wall.tiles[index].room.get('room_id')]
        if not tiles:
            return
        self.host._cancel_interactive_resize()
        if self.host._fullscreen_tile is not None:
            self.host._exit_fullscreen()
        self.selection, self.columns = list(selection), columns
        if not self.active:
            wall.set_sidebar_animating(False)
            self.floating = PictureInPictureWindow(self)
            if self.geometry:
                self.floating.restoreGeometry(QByteArray.fromBase64(self.geometry.encode('ascii')))
            else:
                cols = min(len(tiles), columns or math.ceil(math.sqrt(len(tiles))))
                width = 480 if len(tiles) == 1 else 640
                self.floating.resize(width, round(width * math.ceil(len(tiles) / cols) / cols * 9 / 16) + 44)
            self._minimums = {tile: tile.minimumSize() for tile in wall.tiles}
            content = self.host._content.layout()
            content.removeWidget(wall)
            content.insertWidget(0, self.placeholder, 1)
            self.placeholder.show()
            self.floating.box.addWidget(wall, 1)
        wall.set_picture_in_picture(tiles, columns)
        self.floating.title.setText(f'{len(tiles)} 路')
        self.floating.show()
        wall.show()
        self._sync_overlays()
        self.host.sidebar.picture_in_picture_button.setToolTip(f'管理画中画（{len(tiles)} 路）')

    def _sync_overlays(self):
        wall = self.host.wall
        layer = wall._quick_danmaku_layer
        if layer is not None:
            layer.set_presentation_window(None)
            layer.show()
        for tile in wall.tiles:
            tile.video_danmaku.super_chat_overlay.set_presentation_changing(False)
            dialog = self.host._stream_info_dialogs.get(tile)
            if dialog is not None:
                dialog.set_presentation_owner(tile.window())

    def restore(self, *, activate=False):
        floating = self.floating
        if floating is None:
            return
        if self.dialog is not None:
            self.dialog.reject()
        self.geometry = str(floating.saveGeometry().toBase64(), 'ascii')
        self.floating = None
        wall = self.host.wall
        floating.box.removeWidget(wall)
        content = self.host._content.layout()
        content.removeWidget(self.placeholder)
        self.placeholder.hide()
        content.insertWidget(0, wall, 1)
        for tile, minimum in self._minimums.items():
            tile.setMinimumSize(minimum)
        wall.set_picture_in_picture(None)
        floating.hide()
        floating.deleteLater()
        wall.show()
        self._sync_overlays()
        self.host.sidebar.picture_in_picture_button.setToolTip('选择多路画面，组合为置顶小窗')
        self.host._refresh_meta()
        if activate:
            self.host._tray.restore()

    def state(self):
        geometry = (str(self.floating.saveGeometry().toBase64(), 'ascii')
                    if self.active else self.geometry)
        return dict(selection=self.selection, columns=self.columns, pinned=self.pinned, geometry=geometry)
