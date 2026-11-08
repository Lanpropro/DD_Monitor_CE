"""Update indicators and update notification presentation."""
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRectF, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QStyledItemDelegate, QVBoxLayout, QWidget
from .corner_geometry import continuous_path
from . import motion, theme
from .update_version import release_label


class UpdateDot(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self.setStyleSheet('background: #ff5263; border: none; border-radius: 4px;')
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        if parent:
            parent.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.Show):
            self.move(watched.width() - 16, (watched.height() - 8) // 2)
        return False


def set_update_dot(widget, active):
    if not hasattr(widget, '_update_dot'):
        widget._update_dot = UpdateDot(widget)
    widget._update_dot.move(widget.width() - 16, (widget.height() - 8) // 2)
    widget._update_dot.setVisible(active)
    widget._update_dot.raise_()


class UpdateNavDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.data(Qt.UserRole + 1):
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#ff5263'))
            painter.drawEllipse(option.rect.right() - 22, option.rect.center().y() - 4, 8, 8)
            painter.restore()


class UpdateNotice(QFrame):
    """不抢焦点的悬浮更新提醒，十秒后自动收起。"""
    activated = Signal()

    def __init__(self, parent):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName('UpdateNotice')
        self._history_entries = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 12, 14)
        layout.setSpacing(12)
        self.heading = QHBoxLayout()
        self.heading.setSpacing(10)
        self.indicator = QLabel('↑', self)
        self.indicator.setFixedSize(28, 28)
        self.indicator.setAlignment(Qt.AlignCenter)
        self.indicator.setObjectName('NoticeIcon')
        self.heading.addWidget(self.indicator, 0, Qt.AlignTop)
        self.text_column = QWidget(self)
        self.text_column.setMinimumWidth(0)
        content = QVBoxLayout(self.text_column)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)
        self.category = QLabel('版本更新')
        self.category.setObjectName('NoticeHeading')
        content.addWidget(self.category)
        self.title = QLabel('')
        self.title.setObjectName('NoticeText')
        self.title.setTextFormat(Qt.PlainText)
        self.title.setWordWrap(True)
        self.title.setMinimumWidth(0)
        content.addWidget(self.title)
        self.description = QLabel('查看更新说明，选择是否安装。')
        self.description.setObjectName('NoticeDescription')
        self.description.setWordWrap(True)
        content.addWidget(self.description)
        self.heading.addWidget(self.text_column, 1)
        close = QPushButton('×')
        close.setObjectName('NoticeClose')
        close.setFixedSize(24, 24)
        close.setToolTip('关闭提示')
        close.clicked.connect(lambda: self.dismiss(handled=True))
        self.heading.addWidget(close, 0, Qt.AlignTop)
        layout.addLayout(self.heading)
        self.action = QPushButton('查看更新')
        self.action.setObjectName('PrimaryButton')
        self.action.clicked.connect(self._open)
        layout.addWidget(self.action, 0, Qt.AlignRight)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(10_000)
        self.timer.timeout.connect(self.dismiss)
        self._progress = 1.0
        self._leaving = False
        self._motion = QVariantAnimation(self)
        self._motion.setEasingCurve(QEasingCurve.OutCubic)
        self._motion.valueChanged.connect(self._motion_frame)
        self._motion.finished.connect(self._motion_finished)
        # Closing must complete even if Qt's shared animation clock stops advancing.
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self._motion_finished)
        parent.installEventFilter(self)
        sidebar = getattr(parent, 'sidebar', None)
        if isinstance(sidebar, QWidget):
            sidebar.installEventFilter(self)

    def show_offer(self, offer, *, persistent=False):
        if _notifications_hidden(self.parentWidget()):
            return
        was_visible = self.isVisible()
        self._close_timer.stop()
        self._motion.stop()
        self._leaving = False
        self.title.setText('发现新版本 v' + release_label(offer))
        self._resize_to_content()
        self._progress = self._progress if was_visible else 0.0
        if not motion.enabled():
            self._progress = 1.0
        self.setWindowOpacity(self._progress)
        self.reposition()
        self.show()
        self.raise_()
        self.timer.stop()
        if not persistent:
            self.timer.start()
        if self._progress < 1.0:
            self._animate_to(1.0, 240)

    def _animate_to(self, target, duration):
        start = self._progress
        self._motion.stop()
        self._motion.setCurrentTime(0)
        self._motion.setDuration(duration)
        self._motion.setStartValue(start)
        self._motion.setEndValue(target)
        self._motion.start()

    def _motion_frame(self, value):
        self._progress = value
        self.setWindowOpacity(value)
        self.reposition()

    def _motion_finished(self):
        if self._leaving:
            self._close_timer.stop()
            self._motion.stop()
            self.hide()

    def paintEvent(self, event):
        from .skin_parts import values_for
        from PySide6.QtGui import QPainterPath, QPixmap
        custom = values_for('notices')
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(theme.qcolor(custom.get('background', theme.ELEVATED)))
        painter.setPen(Qt.NoPen if custom.get('border_width') == 0 else
            QPen(theme.qcolor(custom.get('border_color', 'rgba(131, 131, 145, 0.31)')),
                 custom.get('border_width', 1)))
        radius = custom.get('radius', theme.RADIUS_LG)
        painter.drawPath(continuous_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius))
        if custom.get('image'):
            clip = QPainterPath()
            clip.addPath(continuous_path(QRectF(self.rect()), radius))
            painter.setClipPath(clip)
            painter.drawPixmap(self.rect(), QPixmap(custom['image']))

    def _resize_to_content(self):
        self.ensurePolished()
        width = min(420, max(80, self.parentWidget().width() - 32))
        self.setFixedWidth(width)
        self.layout().invalidate()
        height = self.layout().totalHeightForWidth(width)
        if height < 0:
            height = self.layout().totalSizeHint().height()
        self.setFixedHeight(max(76, height))
        self.layout().activate()
        self.text_column.layout().activate()
        self._reflow()

    def reposition(self):
        parent = self.parentWidget()
        offset = round(-24 * (1 - self._progress)) if motion.enabled() else 0
        self.move(parent.mapToGlobal(QPoint(self._left_x() + offset, self._stack_y())))

    def _left_x(self):
        parent = self.parentWidget()
        return max(0, min(16, parent.width() - self.width() - 16))

    def _stack_y(self):
        y = 20
        for notice in getattr(self.parentWidget(), '_notices', []):
            if notice is self:
                break
            if notice.isVisible():
                y += notice.height() + 8
        return y

    def _reflow(self):
        for notice in getattr(self.parentWidget(), '_notices', []):
            notice.reposition()

    def showEvent(self, event):
        parent = self.parentWidget()
        if not hasattr(parent, '_notices'):
            parent._notices = []
        if self not in parent._notices:
            parent._notices.append(self)
        super().showEvent(event)
        self._reflow()

    def hideEvent(self, event):
        self.timer.stop()
        self._close_timer.stop()
        notices = getattr(self.parentWidget(), '_notices', [])
        if self in notices:
            notices.remove(self)
        super().hideEvent(event)
        self._reflow()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._open()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event):
        if watched is not self.parentWidget():
            if self.isVisible() and event.type() in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide):
                self.reposition()
            return False
        if self.isVisible():
            if event.type() == QEvent.Resize:
                self._resize_to_content()
            if event.type() in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange):
                self.reposition()
            elif event.type() == QEvent.Hide:
                self.dismiss(animate=False)
        return False

    def track_history(self, record):
        if record is not None and record[1] is not None:
            self._history_entries.add(record)

    def dismiss(self, animate=True, *, handled=False):
        if handled:
            for center, entry in self._history_entries:
                center._remove(entry)
            self._history_entries.clear()
        self.timer.stop()
        if (animate and self.isVisible() and self.parentWidget().isVisible()
                and not getattr(self.parentWidget(), '_closing', False) and motion.enabled()):
            self._leaving = True
            self._animate_to(0.0, 180)
            if not self._close_timer.isActive():
                self._close_timer.start(280)  # Allow the normal exit its final frame.
        else:
            self._motion.stop()
            self.hide()

    def _open(self):
        self.dismiss(animate=False, handled=True)
        self.activated.emit()


def _notifications_hidden(parent):
    settings = getattr(parent, 'settings', {})
    if callable(settings):
        settings = settings()
    return bool(settings.get('notice_hide_fullscreen', False)
                and (getattr(parent, '_fullscreen_tile', None) is not None or parent.isFullScreen()))
