"""Interactive image-cache usage chart; disk operations stay off the GUI thread."""
import math

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import config, image_cache, theme

LABELS = {'avatars': '主播头像', 'covers': '直播间封面'}


def cache_colors():
    return {'avatars': theme.ACCENT, 'covers': theme.qcolor(theme.TEXT3).name()}


def size_text(value):
    for suffix in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or suffix == 'GB':
            return f'{value:.1f} {suffix}' if suffix != 'B' else f'{value} B'
        value /= 1024


class CachePie(QWidget):
    toggled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(214, 214)
        self.setMouseTracking(True)
        self.setAccessibleName('头像与封面缓存占用饼图，可通过旁边的复选框选择类别')
        self.values = {kind: {'bytes': 0, 'files': 0} for kind in image_cache.KINDS}
        self.selected = set()

    def segment_at(self, point):
        delta = point - QPointF(self.rect().center())
        radius = math.hypot(delta.x(), delta.y())
        if not 55 < radius < 95:
            return None
        total = sum(value['bytes'] for value in self.values.values())
        angle = (90 - math.degrees(math.atan2(-delta.y(), delta.x()))) % 360
        end = 0
        for kind in image_cache.KINDS:
            end += 360 * self.values[kind]['bytes'] / max(1, total)
            if angle < end:
                return kind
        return None

    def mouseMoveEvent(self, event):
        kind = self.segment_at(event.position())
        self.setCursor(Qt.PointingHandCursor if kind and self.isEnabled() else Qt.ArrowCursor)
        total = sum(value['bytes'] for value in self.values.values())
        self.setToolTip(f"{LABELS[kind]} · {size_text(self.values[kind]['bytes'])} · "
                        f"{self.values[kind]['bytes'] / max(1, total):.1%}\n点击选择或取消" if kind else '')

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            kind = self.segment_at(event.position())
            if kind:
                self.toggled.emit(kind)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(12, 12, 190, 190)
        total = sum(value['bytes'] for value in self.values.values())
        ring = QPainterPath()
        ring.setFillRule(Qt.OddEvenFill)
        ring.addEllipse(rect)
        ring.addEllipse(QRectF(52, 52, 110, 110))
        painter.save()
        painter.setClipPath(ring)
        painter.setPen(Qt.NoPen)
        if not total:
            painter.setBrush(theme.qcolor(theme.BORDER))
            painter.drawEllipse(rect)
        start = 90 * 16
        for kind in image_cache.KINDS:
            span = round(360 * 16 * self.values[kind]['bytes'] / max(1, total))
            color = QColor(cache_colors()[kind])
            if self.selected and kind not in self.selected:
                color.setAlpha(65)
            painter.setBrush(color)
            painter.drawPie(rect, start, -span)
            start -= span
        painter.restore()
        painter.setPen(theme.qcolor(theme.TEXT1))
        font = painter.font()
        font.setPointSize(15)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(35, 78, 144, 32), Qt.AlignCenter, size_text(total))
        font.setPointSize(9)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(theme.qcolor(theme.TEXT3))
        painter.drawText(QRectF(35, 112, 144, 24), Qt.AlignCenter, '图片缓存' if total else '暂无图片缓存')


class _Signals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.completed.emit(self.operation())
        except Exception as error:
            self.signals.failed.emit(str(error))


class ImageCachePanel(QWidget):
    def __init__(self, parent=None, *, root=None):
        super().__init__(parent)
        self.root = root or config.data_root()
        self.values = {kind: {'bytes': 0, 'files': 0} for kind in image_cache.KINDS}
        self._task = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        title = QLabel('图片缓存')
        title.setObjectName('SettingsTitle')
        layout.addWidget(title)
        hint = QLabel('点击饼图或勾选类别，选择要清理的图片。占比仅包含头像和封面。')
        hint.setObjectName('SettingsHint')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        content = QHBoxLayout()
        self.pie = CachePie()
        self.pie.toggled.connect(self._toggle)
        content.addWidget(self.pie)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.checks, self.details, self.dots = {}, {}, {}
        for row, kind in enumerate(image_cache.KINDS):
            dot = QLabel('●')
            dot.setStyleSheet(f'color: {cache_colors()[kind]}; font-size: 16px;')
            check = QCheckBox(LABELS[kind])
            check.setAccessibleName('选择清理' + LABELS[kind])
            check.toggled.connect(self._selection_changed)
            detail = QLabel('尚未统计')
            detail.setObjectName('SettingsHint')
            grid.addWidget(dot, row * 2, 0)
            grid.addWidget(check, row * 2, 1)
            grid.addWidget(detail, row * 2 + 1, 1)
            self.checks[kind], self.details[kind] = check, detail
            self.dots[kind] = dot
        content.addLayout(grid, 1)
        layout.addLayout(content)
        actions = QHBoxLayout()
        self.selected_button = QPushButton('清理所选')
        self.selected_button.setObjectName('IconButton')
        self.selected_button.clicked.connect(self.clear_selected)
        self.all_button = QPushButton('全部清理')
        self.all_button.setObjectName('IconButton')
        self.all_button.setToolTip('只清理头像和封面缓存')
        self.all_button.clicked.connect(self.clear_all)
        self.refresh_button = QPushButton('刷新统计')
        self.refresh_button.setObjectName('IconButton')
        self.refresh_button.clicked.connect(self.refresh)
        for button in (self.selected_button, self.all_button, self.refresh_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status = QLabel('主播有新图时自动清理旧图。手动清理后按需重新加载，不影响账号、关注和录像。')
        self.status.setObjectName('SettingsHint')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        theme.signals().changed.connect(self._theme_changed)
        self._selection_changed()

    def _theme_changed(self, *_args):
        for kind, dot in self.dots.items():
            dot.setStyleSheet(f'color: {cache_colors()[kind]}; font-size: 16px;')
        self.pie.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def _toggle(self, kind):
        self.checks[kind].toggle()

    def selected(self):
        return {kind for kind, check in self.checks.items() if check.isChecked()}

    def _selection_changed(self):
        self.pie.selected = self.selected()
        self.pie.update()
        busy = self._task is not None
        size = sum(self.values[kind]['bytes'] for kind in self.selected())
        files = sum(self.values[kind]['files'] for kind in self.selected())
        self.selected_button.setText('清理所选' + (f' · {size_text(size)}' if files else ''))
        self.selected_button.setEnabled(not busy and bool(files))
        self.all_button.setEnabled(not busy and any(value['files'] for value in self.values.values()))
        self.refresh_button.setEnabled(not busy)
        self.pie.setEnabled(not busy)
        for check in self.checks.values():
            check.setEnabled(not busy)

    def _start(self, operation, text):
        if self._task is not None:
            return
        self.status.setText(text)
        self._task = _Task(operation)
        self._task.signals.completed.connect(self._completed)
        self._task.signals.failed.connect(self._failed)
        self._selection_changed()
        QThreadPool.globalInstance().start(self._task)

    def refresh(self):
        self._start(lambda: (None, image_cache.usage(self.root)), '正在统计图片缓存…')

    def clear_selected(self):
        kinds = self.selected()
        if kinds:
            self._clear(kinds)

    def clear_all(self):
        self._clear(image_cache.KINDS)

    def _clear(self, kinds):
        def operation():
            result = image_cache.clear(self.root, kinds)
            return result, image_cache.usage(self.root)
        self._start(operation, '正在清理图片缓存…')

    def _completed(self, payload):
        result, self.values = payload
        self._task = None
        self.pie.values = self.values
        total = sum(value['bytes'] for value in self.values.values())
        for kind, value in self.values.items():
            self.details[kind].setText(f"{size_text(value['bytes'])} · {value['files']} 个文件 · "
                                      f"{value['bytes'] / max(1, total):.1%}")
        self.status.setText(f"已释放 {size_text(result['bytes'])}，清理 {result['files']} 个文件，"
                            f"跳过 {result['skipped']} 个在用文件。" if result is not None
                            else '点击饼图选择类别；没有新图时保留最近一次头像和封面。')
        self._selection_changed()

    def _failed(self, message):
        self._task = None
        self.status.setText('图片缓存操作未完成：' + message)
        self._selection_changed()
