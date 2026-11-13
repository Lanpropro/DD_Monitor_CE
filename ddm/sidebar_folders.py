"""Follow-folder editor, shared-card presentation and header controls; the sidebar owns data."""
from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, QSize, QTimer, Qt
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QLabel,
    QLineEdit, QMenu, QPushButton, QScrollArea, QStyle, QStyleOptionToolButton, QToolButton,
    QVBoxLayout, QWidget, QWidgetAction
)
from . import follow_folders, motion
from .folder_icons import FolderIconDialog, folder_icon
from .sidebar_drag import FOLDER_MIME, NAV_MIME, ROOM_MIME
from .watch_history import SORT_TIP


class SmartFolderDialog(QDialog):
    """编辑状态、平台组合条件和文件夹内部排序。"""

    def __init__(self, sidebar, folder=None):
        super().__init__(sidebar)
        self.setWindowTitle("编辑智能文件夹" if folder else "新建智能文件夹")
        self.setMinimumWidth(360)
        folder = folder or {}
        rule = folder.get("rule") or {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(folder.get("name", ""))
        self.status_combo = QComboBox()
        for value, label in (("any", "全部状态"), ("live", "开播"), ("offline", "未开播")):
            self.status_combo.addItem(label, value)
        self.status_combo.setCurrentIndex(max(0, self.status_combo.findData(rule.get("status", "any"))))
        self.sort_combo = QComboBox()
        for mode, label in sidebar.SORT_MODES:
            self.sort_combo.addItem(label, mode)
            if mode == "frequent":
                self.sort_combo.setItemData(self.sort_combo.count() - 1, SORT_TIP, Qt.ToolTipRole)
        self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(folder.get("sort", "custom"))))
        form.addRow("文件夹名称", self.name_edit)
        sources = rule.get("sources", [sidebar.default_folder()["id"]] if folder else [])
        self.source_button = QPushButton()
        self.source_button.setObjectName("IconButton")
        self.source_menu = QMenu(self.source_button)
        source_content = QWidget()
        source_layout = QVBoxLayout(source_content)
        source_layout.setContentsMargins(12, 10, 12, 10)
        self.all_sources = QCheckBox("全部关注")
        self.all_sources.setChecked(not sources)
        source_layout.addWidget(self.all_sources)
        self.source_checks = {}
        options = [(source["id"], source["name"]) for source in sidebar.folders if source["type"] != "smart"]
        options.extend((fid, "原来源文件夹已删除（请重新选择）") for fid in sources
                       if fid not in dict(options))
        for fid, label in options:
            check = QCheckBox(label)
            check.setChecked(fid in sources)
            check.toggled.connect(self._source_changed)
            source_layout.addWidget(check)
            self.source_checks[fid] = check
        self.all_sources.toggled.connect(self._all_sources_changed)
        source_scroll = QScrollArea()
        source_scroll.setFrameShape(QFrame.NoFrame)
        source_scroll.setWidgetResizable(True)
        source_scroll.setMinimumWidth(260)
        source_scroll.setFixedHeight(min(260, source_content.sizeHint().height()))
        source_scroll.setWidget(source_content)
        source_action = QWidgetAction(self.source_menu)
        source_action.setDefaultWidget(source_scroll)
        self.source_menu.addAction(source_action)
        self.source_button.setMenu(self.source_menu)
        self._update_source_label()
        self.display_combo = QComboBox()
        self.display_combo.addItem("匹配时移入显示，不匹配时回到原处", "move")
        self.display_combo.addItem("保留原处，同时在智能文件夹显示", "copy")
        self.display_combo.setCurrentIndex(max(0, self.display_combo.findData(rule.get("display", "move"))))
        form.addRow("来源文件夹（可多选）", self.source_button)
        form.addRow("显示方式", self.display_combo)
        form.addRow("开播状态", self.status_combo)
        form.addRow("卡片排序", self.sort_combo)
        layout.addLayout(form)
        layout.addWidget(QLabel("平台筛选（不勾选表示全部平台）"))
        self.platform_checks = {}
        platforms = dict(follow_folders.PLATFORM_NAMES)
        for room in sidebar.rooms():
            platform = follow_folders.room_platform(room)
            platforms.setdefault(platform, platform)
        for platform in rule.get("platforms", []):
            platforms.setdefault(platform, platform)
        for platform, label in platforms.items():
            check = QCheckBox(label)
            check.setChecked(platform in rule.get("platforms", []))
            layout.addWidget(check)
            self.platform_checks[platform] = check
        hint = QLabel("从来源文件夹筛选同时满足状态与平台条件的主播，保留原归属。\n多条移入规则匹配时，优先显示在最靠前的智能文件夹。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.name_edit.textChanged.connect(lambda text: buttons.button(QDialogButtonBox.Ok).setEnabled(bool(text.strip())))
        buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.name_edit.text().strip()))
        layout.addWidget(buttons)

    def _source_changed(self, checked):
        if checked:
            self.all_sources.setChecked(False)
        elif not any(check.isChecked() for check in self.source_checks.values()):
            self.all_sources.setChecked(True)
        self._update_source_label()

    def _all_sources_changed(self, checked):
        if checked:
            for check in self.source_checks.values():
                check.setChecked(False)
        elif not any(check.isChecked() for check in self.source_checks.values()):
            self.all_sources.setChecked(True)
        self._update_source_label()

    def _update_source_label(self):
        labels = [check.text() for check in self.source_checks.values() if check.isChecked()]
        self.source_button.setText("全部关注" if not labels else labels[0] if len(labels) == 1
                                   else f"已选择 {len(labels)} 个文件夹")
        self.source_button.setToolTip("、".join(labels) if labels else "从全部关注中筛选")

    def values(self):
        return {"name": self.name_edit.text().strip(), "sort": self.sort_combo.currentData(),
                "rule": {"status": self.status_combo.currentData(),
                         "platforms": [key for key, check in self.platform_checks.items() if check.isChecked()],
                         "sources": [key for key, check in self.source_checks.items() if check.isChecked()],
                         "display": self.display_combo.currentData()}}


class SmartFolderCard(QWidget):
    """同一关注卡片的显示副本；操作使用原卡片，不增加关注或播放实例。"""

    def __init__(self, original, parent):
        super().__init__(parent)
        self.original = original
        self.room = original.room
        self._dragged = False
        self.setCursor(Qt.PointingHandCursor)
        original.installEventFilter(self)
        for child in original.findChildren(QWidget):
            child.installEventFilter(self)
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self.update)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Paint and not getattr(self.original, "_smart_grabbing", False):
            self.update()
        return False

    def paintEvent(self, event):
        self.original._smart_grabbing = True
        try:
            pixmap = self.original.grab()
        finally:
            self.original._smart_grabbing = False
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), pixmap)

    def enterEvent(self, event):
        self._preview_timer.start()
        self.original.hovered.emit(self.room)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._preview_timer.stop()
        self.original.unhovered.emit(self.room)
        super().leaveEvent(event)

    def hideEvent(self, event):
        if self._preview_timer.isActive():
            self._preview_timer.stop()
            self.original.unhovered.emit(self.room)
        super().hideEvent(event)

    def mousePressEvent(self, event):
        self._press_pos = event.pos()
        self._dragged = False

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.LeftButton or self._dragged:
            return
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._dragged = True
        mime = QMimeData()
        rid = str(self.room["room_id"])
        mime.setData(ROOM_MIME, rid.encode("utf-8"))
        mime.setText(rid)
        pixmap, hotspot = motion.lifted_drag(self.grab(), event.pos())
        self.original.drop_host.drag_session.start(
            self, mime, pixmap, hotspot, self.mapToGlobal(event.pos()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self._dragged:
            if self.original.select_mode:
                self.original.check.setChecked(not self.original.check.isChecked())
                self.original.checkedChanged.emit()
            else:
                self.original.clicked.emit(self.room)
            self.update()

    def contextMenuEvent(self, event):
        self.original._context_menu().exec_context(event)


class FollowFolderButton(QToolButton):
    """关注文件夹标题；点击展开，右键管理，拖入卡片归类。"""

    def __init__(self, sidebar, folder_id):
        super().__init__(sidebar.list_box)
        self.sidebar = sidebar
        self.folder_id = folder_id
        self.setObjectName("IconButton")
        self.setIconSize(QSize(18, 18))
        self._default_icon = None
        self._default_icon_type = None
        self.refresh_theme()
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.clicked.connect(lambda: sidebar.toggle_folder(folder_id, animate=self._press_pos is not None))
        self._press_pos = None
        self._drag_started = False

        self._name_edit = None
        self._editing_name = False

    def begin_rename(self):
        folder = self.sidebar.get_folder(self.folder_id)
        if self._name_edit is None:
            self._name_edit = QLineEdit(self)
            self._name_edit.setAccessibleName('文件夹名称')
            self._name_edit.installEventFilter(self)
            self._name_edit.editingFinished.connect(self._finish_rename)
        edit = self._name_edit
        if self.sidebar.side == 'top':
            edit.setParent(self.sidebar.list_box)
            point = self.mapTo(self.sidebar.list_box, QPoint())
            width = min(180, self.sidebar.list_box.width())
            edit.setGeometry(min(point.x(), self.sidebar.list_box.width()-width),
                             point.y(), width, max(28, self.fontMetrics().height()+10))
        else:
            edit.setParent(self)
            edit.setGeometry(26, 2, max(12, self.width()-30), self.height()-4)
        self._editing_name = True
        edit.setText(folder['name'])
        edit.show()
        edit.raise_()
        edit.setFocus(Qt.OtherFocusReason)
        edit.selectAll()

    def _finish_rename(self, cancel=False):
        if not self._editing_name:
            return
        self._editing_name = False
        name = self._name_edit.text()
        self._name_edit.hide()
        self._name_edit.setParent(self)
        if not cancel:
            self.sidebar.rename_folder(self.folder_id, name)

    def eventFilter(self, watched, event):
        if watched is self._name_edit and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self._finish_rename(cancel=True)
            return True
        return super().eventFilter(watched, event)

    def refresh_theme(self):
        folder = self.sidebar.get_folder(self.folder_id)
        if folder is not None:
            if not folder.get('icon'):
                from .skin_parts import icon_path
                custom = icon_path(self)
                if custom:
                    self.setIcon(QIcon(custom))
                    return
                if self._default_icon is None or self._default_icon_type != folder['type']:
                    self._default_icon = folder_icon(folder, self)
                    self._default_icon_type = folder['type']
                self.setIcon(self._default_icon)
            else:
                self.setIcon(folder_icon(folder, self))

    def mousePressEvent(self, event):
        self._press_pos = event.position().toPoint() if event.button() == Qt.LeftButton else None
        self._drag_started = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not event.buttons() & Qt.LeftButton:
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        mime = QMimeData()
        mime.setData(FOLDER_MIME, self.folder_id.encode("utf-8"))
        hotspot = QPoint(self._press_pos)
        self._press_pos = None
        self._drag_started = True
        self.setDown(False)
        pixmap, hotspot = motion.lifted_drag(self.grab(), hotspot)
        self.sidebar.drag_session.start(
            self, mime, pixmap, hotspot, self.mapToGlobal(event.position().toPoint()))

    def mouseReleaseEvent(self, event):
        if self._drag_started:
            self._press_pos = None
            self._drag_started = False
            self.setDown(False)
            return
        super().mouseReleaseEvent(event)
        self._press_pos = None

    def paintEvent(self, event):
        from .skin_parts import icon_path
        folder = self.sidebar.get_folder(self.folder_id)
        custom = icon_path(self) if folder and not folder.get('icon') else ''
        if self.sidebar.side != "top" and not custom:
            super().paintEvent(event)
            return
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        if custom:
            option.icon = QIcon(custom)
        painter = QPainter(self)
        if self.sidebar.side == "top":
            option.rect = QRect(0, 0, self.height(), self.width())
            painter.translate(self.width(), 0)
            painter.rotate(90)
        self.style().drawComplexControl(QStyle.CC_ToolButton, option, painter, self)

    def _context_menu(self):
        menu = motion.AnimatedMenu(self)
        folder = self.sidebar.get_folder(self.folder_id)
        self.sidebar.add_folder_sort_menu(menu.addMenu("排序"), folder)
        menu.addSeparator()
        if folder["type"] == "smart":
            menu.addAction("编辑智能文件夹…").triggered.connect(
                lambda: self.sidebar.prompt_smart_folder(self.folder_id))
        else:
            menu.addAction("重命名文件夹…").triggered.connect(
                self.begin_rename)
            default = menu.addAction("设为默认文件夹")
            default.setCheckable(True)
            default.setChecked(folder["type"] == "unclassified")
            default.setEnabled(folder["type"] != "unclassified")
            default.triggered.connect(lambda: self.sidebar.set_default_folder(self.folder_id))
        menu.addAction("修改图标…").triggered.connect(self._edit_icon)
        index = self.sidebar.folders.index(folder)
        up = menu.addAction("文件夹上移")
        up.setEnabled(index > 0)
        up.triggered.connect(lambda: self.sidebar.move_folder(self.folder_id, -1))
        down = menu.addAction("文件夹下移")
        down.setEnabled(index < len(self.sidebar.folders) - 1)
        down.triggered.connect(lambda: self.sidebar.move_folder(self.folder_id, 1))
        delete = menu.addAction("删除文件夹（保留关注）")
        delete.setEnabled(folder["type"] != "unclassified" or any(
            item["type"] == "normal" for item in self.sidebar.folders))
        if not delete.isEnabled():
            delete.setToolTip("至少保留一个普通文件夹，用于接收新增关注")
        delete.triggered.connect(lambda: self.sidebar.delete_folder(self.folder_id))
        return menu

    def _edit_icon(self):
        folder = self.sidebar.get_folder(self.folder_id)
        dialog = FolderIconDialog(folder, self, existing_names=(
            item['name'] for item in self.sidebar.folders if item['id'] != self.folder_id))
        if dialog.exec() == QDialog.Accepted:
            folder['name'] = dialog.result_name
            if dialog.result_icon is None:
                folder.pop('icon', None)
            else:
                folder['icon'] = dialog.result_icon
            self.refresh_theme()
            self.sidebar._refresh_folders()
        dialog.deleteLater()

    def contextMenuEvent(self, event):
        self._context_menu().exec_context(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(FOLDER_MIME) or (
                event.mimeData().hasFormat(NAV_MIME) and self.sidebar.get_folder(self.folder_id)["type"] != "smart"):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(FOLDER_MIME):
            event.acceptProposedAction()
            folder_id = bytes(event.mimeData().data(FOLDER_MIME)).decode("utf-8", "ignore")
            self.sidebar.hover_folder_drag(folder_id, self.mapToGlobal(event.position().toPoint()))
        elif event.mimeData().hasFormat(NAV_MIME) and self.sidebar.get_folder(self.folder_id)["type"] != "smart":
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasFormat(FOLDER_MIME):
            folder_id = bytes(event.mimeData().data(FOLDER_MIME)).decode("utf-8", "ignore")
            self.sidebar.finish_folder_drag(folder_id, self.mapToGlobal(event.position().toPoint()))
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(NAV_MIME) and self.sidebar.get_folder(self.folder_id)["type"] != "smart":
            room_id = bytes(event.mimeData().data(NAV_MIME)).decode("utf-8", "ignore")
            self.sidebar.move_to_folder(self.sidebar.dragged_room_ids(room_id), self.folder_id)
            event.acceptProposedAction()
