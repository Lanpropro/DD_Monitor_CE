"""Interactive image-cache usage chart; disk operations stay off the GUI thread."""
import math

from PySide6.QtCore import QElapsedTimer, QObject, QPointF, QRectF, QRunnable, QSignalBlocker, Qt, QThreadPool, Signal, QVariantAnimation
from PySide6.QtGui import QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QBoxLayout, QCheckBox, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget

from . import config, image_cache, motion, theme
from .settings_layout import SettingsSection
from .ui import ActionButton, HintLabel

LABELS = {'avatars': '主播头像', 'covers': '直播间封面'}
_live_tasks = set()


def cache_colors():
    return {'avatars': theme.ACCENT, 'covers': theme.SUCCESS}


def size_text(value):
    for suffix in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or suffix == 'GB':
            return f'{value:.1f} {suffix}' if suffix != 'B' else f'{value} B'
        value /= 1024


class CachePie(QWidget):
    toggled = Signal(str)

    def __init__(self, parent=None, *, labels=LABELS, colors=cache_colors, title='图片缓存'):
        super().__init__(parent)
        self.labels = labels
        self.colors = colors
        self.setFixedSize(214, 214)
        self.setMouseTracking(True)
        self.setAccessibleName(title + '占用饼图，可通过复选框选择类别')
        self.values = {kind: {'bytes': 0, 'files': 0} for kind in labels}
        self.selected = set()

    def segment_at(self, point):
        delta = point - QPointF(self.width() / 2, self.height() / 2)
        radius = math.hypot(delta.x(), delta.y())
        if not 55 < radius < 95:
            return None
        total = sum(value['bytes'] for value in self.values.values())
        angle = (90 - math.degrees(math.atan2(-delta.y(), delta.x()))) % 360
        end = 0
        for kind in self.labels:
            end += 360 * self.values[kind]['bytes'] / max(1, total)
            if angle < end:
                return kind
        return None

    def mouseMoveEvent(self, event):
        kind = self.segment_at(event.position())
        self.setCursor(Qt.PointingHandCursor if kind and self.isEnabled() else Qt.ArrowCursor)
        total = sum(value['bytes'] for value in self.values.values())
        self.setToolTip(f"{self.labels[kind]} · {size_text(self.values[kind]['bytes'])} · "
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
        consumed = 0
        colors = self.colors()
        for kind in self.labels:
            consumed += self.values[kind]['bytes']
            end = 90 * 16 - round(360 * 16 * consumed / max(1, total))
            color = theme.qcolor(colors[kind])
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            for offset, shade in ((0., color.lighter(128)), (.5, color), (1., color.darker(123))):
                if self.selected and kind not in self.selected:
                    shade.setAlpha(65)
                gradient.setColorAt(offset, shade)
            painter.setBrush(gradient)
            painter.drawPie(rect, start, end - start)
            start = end
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
        painter.drawText(QRectF(35, 112, 144, 24), Qt.AlignCenter, '合计' if total else '暂无占用')


class _Signals(QObject):
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()


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
        finally:
            self.signals.finished.emit()


def _forget_task(task):
    _live_tasks.discard(task)


class CacheRefreshButton(ActionButton):
    def __init__(self):
        super().__init__('刷新统计')
        self._refreshing = False
        self._spin = QVariantAnimation(self, startValue=0., endValue=360., duration=850, loopCount=-1)
        self._spin.valueChanged.connect(lambda _angle: self.update())

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(size.width() + 22)
        return size

    def set_refreshing(self, refreshing):
        self._refreshing = refreshing
        self.setProperty('cacheRefreshing', refreshing)
        self.style().unpolish(self)
        self.style().polish(self)
        self._spin.stop()
        self._spin.setCurrentTime(0)
        if refreshing and self.isVisible() and motion.enabled():
            self._spin.start()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._refreshing:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(theme.qcolor(theme.TEXT2), 1.5, Qt.SolidLine, Qt.RoundCap))
            rect = QRectF(self.width() - 23, (self.height() - 12) / 2, 12, 12)
            painter.drawArc(rect, round(-16 * self._spin.currentValue()), 260 * 16)

    def hideEvent(self, event):
        self._spin.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._refreshing and motion.enabled():
            self._spin.start()


class CacheUsagePanel(SettingsSection):
    def __init__(self, title, parent=None, *, root=None, backend, labels, colors, hint, details=None, deferred=()):
        super().__init__(title, parent)
        self.root = root or config.data_root()
        self.backend = backend
        self.colors = colors
        self.deferred = frozenset(deferred)
        self.values = {kind: {'bytes': 0, 'files': 0} for kind in labels}
        self._task = None
        self._refresh_elapsed = QElapsedTimer()
        self.grid.addWidget(HintLabel(hint), 0, 0, 1, 2)
        self.content = QBoxLayout(QBoxLayout.LeftToRight)
        self.content.setSpacing(12)
        self.pie = CachePie(self, labels=labels, colors=colors, title=title)
        self.pie.toggled.connect(lambda kind: self.checks[kind].toggle())
        self.content.addWidget(self.pie, 0, Qt.AlignTop | Qt.AlignHCenter)
        self.legend = QWidget(self)
        self.legend.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        legend = QGridLayout(self.legend)
        legend.setContentsMargins(0, 0, 0, 0)
        legend.setAlignment(Qt.AlignTop)
        legend.setColumnStretch(1, 1)
        self.content.addWidget(self.legend, 1)
        self.checks, self.details, self.dots = {}, {}, {}
        for row, (kind, title) in enumerate(labels.items()):
            dot = QLabel('●')
            check = QCheckBox(title)
            check.setAccessibleName('选择清理' + title)
            check.toggled.connect(self._selection_changed)
            detail = HintLabel('尚未统计')
            if details:
                check.setToolTip(details[kind])
                detail.setToolTip(details[kind])
            legend.addWidget(dot, row * 2, 0)
            legend.addWidget(check, row * 2, 1)
            legend.addWidget(detail, row * 2 + 1, 1)
            self.checks[kind], self.details[kind], self.dots[kind] = check, detail, dot
        self.grid.addLayout(self.content, 1, 0, 1, 2)

        actions = QHBoxLayout()
        self.selected_button = ActionButton('清理所选')
        self.selected_button.clicked.connect(self.clear_selected)
        self.select_all_button = ActionButton('全选')
        self.select_all_button.clicked.connect(self._toggle_all)
        self.refresh_button = CacheRefreshButton()
        self.refresh_button.clicked.connect(self.refresh)
        for button in (self.selected_button, self.select_all_button, self.refresh_button):
            actions.addWidget(button)
        actions.addStretch(1)
        self.grid.addLayout(actions, 2, 0, 1, 2)
        self.status = HintLabel('尚未统计')
        self.grid.addWidget(self.status, 3, 0, 1, 2)
        theme.signals().changed.connect(self._theme_changed)
        self._theme_changed()
        self._selection_changed()

    def _theme_changed(self, *_args):
        for kind, color in self.colors().items():
            self.dots[kind].setStyleSheet(f'color: {color}; font-size: 16px;')
        self.pie.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        margins = self.layout().contentsMargins()
        needed = self.pie.width() + self.legend.sizeHint().width() + self.content.spacing()
        self.content.setDirection(QBoxLayout.LeftToRight
                                  if self.width() - margins.left() - margins.right() >= needed else QBoxLayout.TopToBottom)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def selected(self):
        return {kind for kind, check in self.checks.items() if check.isChecked()}

    def _toggle_all(self):
        select = len(self.selected()) < len(self.checks)
        for check in self.checks.values():
            with QSignalBlocker(check):
                check.setChecked(select)
        self._selection_changed()

    def _selection_changed(self):
        selected = self.selected()
        self.pie.selected = selected
        self.pie.update()
        busy = self._task is not None
        size = sum(self.values[kind]['bytes'] for kind in selected)
        files = sum(self.values[kind]['files'] for kind in selected)
        self.selected_button.setText('清理所选' + (f' · {size_text(size)}' if files else ''))
        self.selected_button.setEnabled(not busy and bool(files or self.deferred & selected))
        self.select_all_button.setText('取消全选' if len(selected) == len(self.checks) else '全选')
        self.select_all_button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.pie.setEnabled(not busy)
        for check in self.checks.values():
            check.setEnabled(not busy)

    def _start(self, operation, text, *, refreshing=False):
        if self._task is not None:
            return
        self.status.setText(text)
        self._task = _Task(operation)
        self._task.signals.completed.connect(self._completed)
        self._task.signals.failed.connect(self._failed)
        _live_tasks.add(self._task)
        self._task.signals.finished.connect(lambda task=self._task: _forget_task(task))
        if refreshing:
            self._refresh_elapsed.start()
            self.refresh_button.set_refreshing(True)
        self._selection_changed()
        QThreadPool.globalInstance().start(self._task)

    def refresh(self):
        backend, root = self.backend, self.root
        self._start(lambda: (None, backend.usage(root)), '正在统计…', refreshing=True)

    def clear_selected(self):
        selected, backend, root = self.selected(), self.backend, self.root
        if selected:
            def operation():
                return backend.clear(root, selected), backend.usage(root)
            self._start(operation, '正在清理所选类别…')

    def _completed(self, payload):
        result, self.values = payload
        self._task = None
        self.pie.values = self.values
        total = sum(value['bytes'] for value in self.values.values())
        for kind, value in self.values.items():
            pending = ' · 已安排下次网页登录时清理' if value.get('pending') else ''
            self.details[kind].setText(f"{size_text(value['bytes'])} · {value['files']} 个文件 · "
                                       f"{value['bytes'] / max(1, total):.1%}" + pending)
        self.refresh_button.set_refreshing(False)
        if result is None:
            message = f'统计完成 · {size_text(total)} · 耗时 {self._refresh_elapsed.elapsed() / 1000:.2f} 秒'
        else:
            message = (f"已释放 {size_text(result['bytes'])}，清理 {result['files']} 个文件，"
                       f"跳过 {result['skipped']} 个在用或不可清理文件。")
            if result.get('deferred'):
                message += ' 网页登录 HTTP 缓存已安排在下次打开网页登录时清理。'
        self.status.setText(message)
        self._selection_changed()

    def _failed(self, message):
        self._task = None
        self.refresh_button.set_refreshing(False)
        self.status.setText('缓存操作未完成：' + message)
        self._selection_changed()


class ImageCachePanel(CacheUsagePanel):
    def __init__(self, parent=None, *, root=None):
        super().__init__('图片缓存', parent, root=root, backend=image_cache, labels=LABELS, colors=cache_colors,
                         hint='点击扇区或勾选类别。主播有新图时自动清理旧图，手动清理后按需重新加载。')
