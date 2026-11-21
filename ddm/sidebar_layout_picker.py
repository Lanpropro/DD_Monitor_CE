"""Sidebar layout-preset menu positioning and selection coordination."""
from PySide6.QtCore import QObject, QPoint, QRect, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import (
    QCursor, QKeySequence, QPainter, QPen, QPixmap, QRegion, QShortcut
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QVBoxLayout, QWidget
)
from . import follow_folders, layouts, motion, theme, version as version_module


class SidebarLayoutPicker(QObject):
    sizeChanged = Signal()

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.preferred_size = None

    def restore_size(self, stored):
        self.preferred_size = (QSize(*stored) if isinstance(stored, (list, tuple)) and len(stored) == 2
                               and all(type(value) is int and 0 < value <= 32767 for value in stored) else None)

    def size_state(self):
        return self.preferred_size.toTuple() if self.preferred_size else ()

    def _remember_size(self, size):
        self.preferred_size = QSize(size)
        self.sizeChanged.emit()

    def set_layout_name(self, layout_id: str) -> None:
        """按钮只写「布局预设」，当前用的是哪套放在悬停提示里。"""
        host = self.host
        host._layout_id = layout_id
        layout = layouts.BY_ID.get(layout_id) or layouts.BY_ID[layouts.DEFAULT_LAYOUT]
        host.layout_button.setText("布局预设")
        host.layout_button.setToolTip(f"当前布局：{layout['name']}　（点击切换）")

    def open_layout_picker(self) -> None:
        # 只列当前方向能用的布局：横屏不列竖屏预设（套上去画面会变形）
        host = self.host
        from .layout_picker import LayoutPicker
        # 收起时「布局预设」按钮是藏起来的，改从头像那个位置弹出来
        source = host.account_row if host.collapsed else host.layout_button
        anchor = source.mapToGlobal(source.rect().topLeft())
        screen = (QApplication.screenAt(anchor)
                  or QApplication.screenAt(QCursor.pos())
                  or QApplication.primaryScreen())
        # screenAt 偶尔全落空（窗口还在屏幕外、或显示器刚改过配置），
        # 这时千万别把窗口摆到屏幕外去：退回主屏可用区域，至少还能看见。
        available = screen.availableGeometry() if screen is not None else QRect()
        if not available.isValid():
            primary = QApplication.primaryScreen()
            if primary is not None:
                available = primary.availableGeometry()
        picker = LayoutPicker(host._layout_id, host, portrait=host.side == "top",
                              presets_host=getattr(host, "room_presets_host", None),
                              preferred_size=self.preferred_size, available=available)
        picker.chosen.connect(host._on_layout_chosen)
        picker.sizeChanged.connect(self._remember_size)
        x = anchor.x()
        if host.collapsed:
            x = anchor.x() + source.width() + 6
        y = anchor.y() - picker.height() - 6
        if available.isValid():
            x = max(available.left() + 6,
                    min(x, available.right() - picker.width() - 6))
            if y < available.top() + 6:
                y = anchor.y() + source.height() + 6
            min_y = available.top() + 6
            max_y = available.bottom() - picker.height() - 6
            if max_y < min_y:
                y = min_y
            else:
                y = max(min_y, min(y, max_y))
        else:
            # 连主屏都问不到时，至少把它压进屏幕左上角能看见的范围，
            # 别让 x 也跟着锚点跑到屏幕外去
            x = max(6, min(x, max(6, 1200 - picker.width() - 6)))
            y = max(6, y)
        picker.move(x, y)
        picker.show()
        host._picker = picker

    def on_layout_chosen(self, layout_id: str) -> None:
        host = self.host
        host.set_layout_name(layout_id)
        host.layoutChosen.emit(layout_id)
