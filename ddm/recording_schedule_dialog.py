"""Recording conditions for a streamer or a merged monitoring card."""
import sys

from PySide6.QtCore import QDate, QRectF, Qt, QTime
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QDateEdit, QDialog, QFrame, QHBoxLayout, QLabel, QLayout, QScrollArea,
    QTimeEdit, QVBoxLayout, QWidget,
)

from . import theme
from .corner_geometry import continuous_path
from .recording_calendar_image import dropped_calendar_image
from .recording_calendar_import import RecordingCalendarImport
from .recording_keyword_tags import KeywordTags
from .recording_schedule import WEEKDAYS, normalize_schedule
from .settings_window import SettingsTitleBar
from .ui import ActionButton, HintLabel, NavigationButton, SelectControl, page_header


class RecordingScheduleDialog(QDialog):
    def __init__(self, parent, schedule, keywords=()):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle('编辑录制计划')
        self.setObjectName('RecordingScheduleDialog')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setProperty('customControlSurface', True)
        theme.signals().changed.connect(self.update)
        bounds = self.screen().availableGeometry()
        self.compact_height = min(390, bounds.height() - 32)
        self.resize(min(520, bounds.width() - 32), self.compact_height)
        self.rows = []
        self.calendar = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        self.titlebar = SettingsTitleBar(self)
        header = self.titlebar.row
        header.setContentsMargins(0, 0, 0, 0)
        self.titlebar.breadcrumb.hide()
        header.takeAt(1)
        header.insertLayout(0, page_header(
            self.windowTitle(), '时段和关键词可只填一项。都填写时，须在时段内且标题包含任一关键词才开录。'), 1)
        close = self.titlebar.close_button
        close.setAccessibleName('关闭录制计划')
        close.setToolTip('取消编辑')
        header.setAlignment(close, Qt.AlignTop)
        outer.addWidget(self.titlebar)

        scroll = QScrollArea(self)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setAutoFillBackground(False)
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 4, 0)
        content.setSpacing(12)
        content.setSizeConstraint(QLayout.SetMinimumSize)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.keyword_tags = KeywordTags(keywords, body)
        self.keyword_input = self.keyword_tags.input
        content.addWidget(self.keyword_tags)

        card = QFrame(body, objectName='PluginCard')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        column_header = QHBoxLayout()
        column_header.addWidget(QLabel('录制时段', objectName='SettingsSectionTitle'), 1)
        if sys.platform == 'win32':
            self.import_calendar = ActionButton('周表识别', card)
            self.import_calendar.setAutoDefault(False)
            self.import_calendar.setCheckable(True)
            self.import_calendar.toggled.connect(self._show_calendar)
            column_header.addWidget(self.import_calendar)
        add = ActionButton('添加时段', card)
        add.setAutoDefault(False)
        add.clicked.connect(lambda: self.add_row())
        column_header.addWidget(add)
        card_layout.addLayout(column_header)
        card_layout.addWidget(HintLabel('按电脑本地时间执行，结束早于开始时跨至次日。'))
        self.row_layout = QVBoxLayout()
        self.row_layout.setSpacing(8)
        card_layout.addLayout(self.row_layout)
        if sys.platform == 'win32':
            self.calendar = RecordingCalendarImport(card)
            self.calendar.hide()
            self.calendar.applyRequested.connect(self._apply_calendar_selection)
            self.finished.connect(self.calendar.stop)
            self.setAcceptDrops(True)
            card_layout.addWidget(self.calendar)
        content.addWidget(card)
        content.addStretch()
        self.error = HintLabel('开始与结束时间相同，请修改或删除该时段。')
        outer.addWidget(self.error)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = ActionButton('取消', self)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        self.save = ActionButton('保存', self)
        self.save.setObjectName('PrimaryButton')
        self.save.setDefault(True)
        self.save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save)
        outer.addLayout(buttons)
        for row in schedule:
            self.add_row(*row)
        self._validate()
        self.keyword_input.setFocus(Qt.OtherFocusReason)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 22)
        painter.fillPath(path, theme.qcolor(theme.BG))
        painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
        painter.drawPath(path)

    def _show_calendar(self, expanded):
        self.calendar.setVisible(expanded)
        self.import_calendar.setText('收起周表识别' if expanded else '周表识别')
        bounds = self.screen().availableGeometry()
        height = min(660, bounds.height() - 32) if expanded else self.compact_height
        self.resize(self.width(), height)
        if self.frameGeometry().bottom() > bounds.bottom():
            self.move(self.x(), bounds.bottom() - self.height() + 1)

    def dragEnterEvent(self, event):
        if self.calendar is not None and dropped_calendar_image(event.mimeData()) is not None:
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dropEvent(self, event):
        if self.calendar is not None and (source := dropped_calendar_image(event.mimeData())) is not None:
            self.import_calendar.setChecked(True)
            self.calendar.load_image(source)
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def _apply_calendar_selection(self):
        existing = set(self.schedule())
        for entry in self.calendar.schedule():
            if entry not in existing:
                self.add_row(*entry)
                existing.add(entry)
        self.calendar.clear_selection()

    def accept(self):
        if self.calendar is not None and self.calendar.schedule():
            if not self.calendar.confirm.isEnabled():
                self.import_calendar.setChecked(True)
                return
            self._apply_calendar_selection()
        self.keyword_tags.commit_pending()
        super().accept()

    def add_row(self, day=0, start=20 * 60, end=22 * 60):
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        if isinstance(day, str):
            weekday = QDateEdit(QDate.fromString(day, Qt.ISODate))
            weekday.setDisplayFormat('yyyy/MM/dd')
            weekday.setCalendarPopup(True)
            weekday.setAccessibleName('单次录制日期')
            weekday.setFixedHeight(theme.CONTROL_HEIGHT)
        else:
            weekday = SelectControl()
            weekday.setAccessibleName('星期')
            weekday.addItems(WEEKDAYS)
            weekday.setCurrentIndex(day)
        opening = QTimeEdit(QTime(*divmod(start, 60)))
        closing = QTimeEdit(QTime(*divmod(end, 60))) if end is not None else HintLabel('至下播')
        fields = ((opening, '开始时间'),) if end is None else ((opening, '开始时间'), (closing, '结束时间'))
        for field, label in fields:
            field.setDisplayFormat('HH:mm')
            field.setAccessibleName(label)
            field.setFixedHeight(theme.CONTROL_HEIGHT)
            field.timeChanged.connect(self._validate)
        next_day = HintLabel('次日')
        next_day.setFixedWidth(next_day.sizeHint().width())
        remove = NavigationButton('删除时段', 'clear', row)
        remove.setAutoDefault(False)
        item = (row, weekday, opening, closing, next_day)
        remove.clicked.connect(lambda: self._remove(item))
        for widget in (weekday, opening, closing, next_day, remove):
            layout.addWidget(widget)
        self.rows.append(item)
        self.row_layout.addWidget(row)
        self._validate()

    def _remove(self, item):
        self.rows.remove(item)
        self.row_layout.removeWidget(item[0])
        item[0].hide()
        item[0].deleteLater()
        self._validate()

    def _validate(self):
        valid = True
        for _, _, opening, closing, next_day in self.rows:
            if not isinstance(closing, QTimeEdit):
                next_day.clear()
                continue
            next_day.setText('次日' if closing.time() < opening.time() else '')
            valid = valid and opening.time() != closing.time()
        self.error.setVisible(not valid)
        self.save.setEnabled(valid)

    def schedule(self):
        def minutes(field):
            return field.time().hour() * 60 + field.time().minute()

        return normalize_schedule([
            (weekday.date().toPython().isoformat() if isinstance(weekday, QDateEdit) else weekday.currentIndex(),
             minutes(opening), minutes(closing) if isinstance(closing, QTimeEdit) else None)
            for _, weekday, opening, closing, _ in self.rows
        ])

    def title_keywords(self):
        return self.keyword_tags.keywords()
