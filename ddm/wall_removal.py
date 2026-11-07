"""Select wall slots for removal and undo the most recent removal."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                              QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget)

from . import layouts


def room_id(tile):
    return str(tile.room.get('room_id') or '')


def offline(tile):
    return bool(room_id(tile) and tile.room.get('live_known', True)
                and tile.room.get('live') is not None and not tile.room['live'])


class WallPreview(QWidget):
    def __init__(self, menu):
        super().__init__(menu)
        self.menu = menu
        self.panes = []

    def rebuild(self):
        for _tile, button, _rect in self.panes:
            button.hide()
            button.deleteLater()
        wall = self.menu.controller.host.wall
        widgets = wall._preset_widgets()
        area = QRect()
        for widget in widgets.values():
            area = area.united(widget.geometry())
        self.area = area
        self.panes = []
        for widget in widgets.values():
            tile = widget if widget in wall.tiles else None
            button = self.menu.make_pane(tile, self)
            self.panes.append((tile, button, widget.geometry()))
            button.show()
        self.setFixedHeight(max(140, min(300, round(400 * area.height() / max(1, area.width())))))
        self.place_panes()

    def place_panes(self):
        if not self.panes:
            return
        scale = min(self.width() / max(1, self.area.width()),
                    self.height() / max(1, self.area.height()))
        left = (self.width() - self.area.width() * scale) / 2
        top = (self.height() - self.area.height() * scale) / 2
        for tile, button, rect in self.panes:
            button.setGeometry(round(left + (rect.x() - self.area.x()) * scale),
                               round(top + (rect.y() - self.area.y()) * scale),
                               max(1, round(rect.width() * scale)), max(1, round(rect.height() * scale)))
            self.menu.label_pane(tile, button)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_panes()


class RemovalMenu(QFrame):
    def __init__(self, controller):
        super().__init__(controller.host, Qt.Popup)
        self.controller = controller
        self.message = ''
        self.setObjectName('LayoutPicker')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.installEventFilter(controller)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        title = QLabel('移除画面')
        title.setObjectName('AppTitle')
        outer.addWidget(title)
        self.layout_name = QLabel()
        outer.addWidget(self.layout_name)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        body = QVBoxLayout(holder)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        self.preview = WallPreview(self)
        body.addWidget(self.preview)
        self.hidden_label = QLabel('布局之外的直播')
        body.addWidget(self.hidden_label)
        self.hidden_box = QVBoxLayout()
        body.addLayout(self.hidden_box)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)
        choices = QHBoxLayout()
        self.scope_buttons = {}
        for key, text in (('offline', '选择未开播'), ('all', '选择全部直播'), ('none', '取消选择')):
            button = QPushButton(text)
            button.setObjectName('PresetManageButton')
            button.clicked.connect(lambda _checked=False, scope=key: controller.select(scope))
            choices.addWidget(button)
            self.scope_buttons[key] = button
        outer.addLayout(choices)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        actions = QHBoxLayout()
        self.undo_button = QPushButton('撤回上次移除')
        self.undo_button.setObjectName('IconButton')
        self.undo_button.clicked.connect(controller.undo)
        self.undo_button.setToolTip('恢复最近一次移除的直播和位置；不会重新开启录制')
        actions.addWidget(self.undo_button)
        self.remove_button = QPushButton()
        self.remove_button.setObjectName('PrimaryButton')
        self.remove_button.clicked.connect(controller.remove_selected)
        actions.addWidget(self.remove_button)
        outer.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(controller.sync)
        self.extra_panes = []

    def make_pane(self, tile, parent):
        button = QToolButton(parent)
        button.setObjectName('LayoutCard')
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda checked, target=tile: self.controller.toggle_selection(target, checked))
        self.label_pane(tile, button)
        return button

    def label_pane(self, tile, button):
        host = self.controller.host
        if tile is not None and tile not in host.wall.tiles:
            button.hide()
            return
        occupied = tile is not None and bool(room_id(tile))
        if tile is None:
            name, status = '弹幕', ''
        else:
            number = host.wall.tiles.index(tile) + 1
            name = f'{number} · ' + str(tile.room.get('uname') or room_id(tile) or '空位')
            status = ('直播中' if tile.room.get('live') else
                      '未开播' if offline(tile) else '状态未知') if occupied else ''
        button.setEnabled(occupied)
        selected = tile in self.controller.selected
        button.setChecked(selected)
        button.setAccessibleName(name + (' · ' + status if status else '') + (' · 已选择移除' if selected else ''))
        button.setToolTip(button.accessibleName() + ('\n点击选择或取消移除' if occupied else ''))
        label = button.fontMetrics().elidedText(('✓ ' if selected else '') + name,
                                               Qt.ElideRight, max(0, button.width() - 14))
        button.setText(label + ('\n' + status if status else ''))

    def rebuild(self):
        self.layout_name.setText(layouts.BY_ID[self.controller.host.wall.layout_id]['name'] + ' · 点击格子选择移除')
        self.preview.rebuild()
        while self.hidden_box.count():
            item = self.hidden_box.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        shown = {tile for tile, _button, _rect in self.preview.panes}
        self.extra_panes = []
        for tile in self.controller.host.wall.tiles:
            if tile not in shown and room_id(tile):
                button = self.make_pane(tile, self)
                button.setFixedHeight(48)
                self.hidden_box.addWidget(button)
                self.extra_panes.append((tile, button))
        self.hidden_label.setVisible(bool(self.extra_panes))
        self.refresh()

    def refresh(self):
        for tile, button, _rect in self.preview.panes:
            self.label_pane(tile, button)
        for tile, button in self.extra_panes:
            self.label_pane(tile, button)
        count = len(self.controller.selected)
        self.remove_button.setText(f'移除所选 {count} 路')
        self.remove_button.setEnabled(bool(count))
        self.undo_button.setEnabled(self.controller.can_undo())
        self.summary.setText(self.message or f'已选 {count} 路 · 移除后保留空位及关注列表')

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)


class WallRemoval(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.menu = None
        self.selected = set()
        self.last_removal = None
        host.sidebar.installEventFilter(self)

    def signature(self):
        return (self.host.wall.layout_id,
                tuple((tile, room_id(tile)) for tile in self.host.wall.tiles))

    def toggle_menu(self):
        if self.menu is not None and self.menu.isVisible():
            self.menu.hide()
            return
        if self.menu is None:
            self.menu = RemovalMenu(self)
        self.menu.message = ''
        self.seen = self.signature()
        self.selected = {tile for tile in self.host.wall.tiles if offline(tile)}
        self.menu.rebuild()
        self.show_menu()

    def show_menu(self):
        button = self.host.sidebar.clear_wall_button
        anchor = button.mapToGlobal(QPoint(button.width() + 6, 0))
        area = (QApplication.screenAt(anchor) or button.screen()).availableGeometry().adjusted(8, 8, -8, -8)
        self.menu.resize(min(440, area.width()), min(560, area.height()))
        self.menu.move(max(area.left(), min(anchor.x(), area.right() - self.menu.width() + 1)),
                       max(area.top(), min(anchor.y(), area.bottom() - self.menu.height() + 1)))
        self.menu.show()

    def select(self, scope):
        self.selected = {tile for tile in self.host.wall.tiles if room_id(tile)
                         and (scope == 'all' or scope == 'offline' and offline(tile))}
        if self.menu is not None:
            self.menu.message = ''
            self.menu.refresh()

    def toggle_selection(self, tile, checked):
        if checked:
            self.selected.add(tile)
        else:
            self.selected.discard(tile)
        self.menu.message = ''
        self.menu.refresh()

    def sync(self):
        if self.signature() != self.seen:
            self.seen = self.signature()
            self.menu.message = ''
            self.selected = {tile for tile in self.host.wall.tiles if offline(tile)}
            self.menu.rebuild()
        else:
            self.menu.refresh()

    def remove_selected(self):
        if self.signature() != self.seen:
            self.sync()
            self.menu.message = '画面已变化，请重新选择'
            self.menu.refresh()
            return False
        targets = [tile for tile in self.host.wall.tiles if tile in self.selected and room_id(tile)]
        if not targets:
            return False
        removed = []
        for tile in targets:
            room = dict(tile.room, quality=tile.quality)
            saved_quality = self.host._capture_quality.get(tile)
            if saved_quality is not None and saved_quality[0] == room_id(tile):
                room['quality'] = saved_quality[1]
            removed.append((tile, room, tile.paused))
            self.host._clear_tile_room(tile)
        self.last_removal = (self.signature(), removed)
        self.selected.clear()
        self.host._refresh_meta()
        self.host._save_timer.start()
        self.sync()
        self.menu.message = f'已移除 {len(removed)} 路，可撤回上次移除'
        self.menu.refresh()
        self.show_menu()
        return True

    def can_undo(self):
        return self.last_removal is not None and self.signature() == self.last_removal[0]

    def undo(self):
        if not self.can_undo():
            self.menu.message = '画面墙已变化，无法撤回上次移除'
            self.menu.refresh()
            return False
        _signature, removed = self.last_removal
        for tile, room, paused in removed:
            latest = next((item for item in self.host.sidebar.rooms()
                           if str(item.get('room_id')) == room['room_id']), {})
            for key in ('live', 'live_known', 'uname', 'title', 'face', 'cover'):
                if key in latest:
                    room[key] = latest[key]
            tile.set_room(room)
            tile.set_paused(paused)
            if tile.isVisible() and tile.room.get('live'):
                self.host.start_tile(tile)
        self.last_removal = None
        self.host._refresh_meta()
        self.host._save_timer.start()
        self.sync()
        self.menu.message = f'已恢复 {len(removed)} 路直播；录制不会自动重启'
        self.menu.refresh()
        return True

    def eventFilter(self, watched, event):
        if watched is self.menu and event.type() == QEvent.MouseButtonPress:
            button = self.host.sidebar.clear_wall_button
            if button.rect().contains(button.mapFromGlobal(event.globalPosition().toPoint())):
                self.menu.setAttribute(Qt.WA_NoMouseReplay)
        elif watched is self.host.sidebar and event.type() in (QEvent.Hide, QEvent.Resize):
            if self.menu is not None:
                self.menu.hide()
        return super().eventFilter(watched, event)
