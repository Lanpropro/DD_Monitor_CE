"""Inline image import and OCR review in the recording plan editor."""
from datetime import date, timedelta
import json

from PySide6.QtCore import QDate, QProcess, QSignalBlocker, QSize, QTemporaryFile, Qt, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QTimeEdit, QVBoxLayout, QWidget,
)

from . import theme
from .recording_calendar import CalendarEntry, extract_calendar, next_monday
from .recording_calendar_image import CALENDAR_IMAGE_FILTER, CalendarImageLoader, dropped_calendar_image
from .ui import ActionButton, HintLabel, NavigationButton, SelectControl
from .windows_calendar_ocr import calendar_ocr_command


class _CalendarDropButton(ActionButton):
    dropped = Signal(object)

    def __init__(self, text, parent):
        super().__init__(text, parent)
        self.setAutoDefault(False)
        self.setAcceptDrops(True)

    def _highlight(self, enabled):
        self.setProperty('dropActive', enabled)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def dragEnterEvent(self, event):
        if dropped_calendar_image(event.mimeData()) is not None:
            self._highlight(True)
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dragLeaveEvent(self, event):
        self._highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._highlight(False)
        source = dropped_calendar_image(event.mimeData())
        if source is not None:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.dropped.emit(source)


class RecordingCalendarImport(QWidget):
    applyRequested = Signal()

    def __init__(self, parent, *, today=None):
        super().__init__(parent)
        self.today = today or date.today()
        self.rows = []
        self.image_file = None
        self.preview_image = QPixmap()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        self.drop_area = _CalendarDropButton('拖入本地或网页图片，也可点击选择', self)
        self.drop_area.setObjectName('CalendarImageDrop')
        self.drop_area.setMinimumHeight(46)
        self.drop_area.clicked.connect(self._choose_image)
        self.drop_area.dropped.connect(self.load_image)
        outer.addWidget(self.drop_area)
        self.preview_box = QWidget(self)
        preview_layout = QGridLayout(self.preview_box)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = _CalendarDropButton('', self.preview_box)
        self.preview.setObjectName('CalendarImagePreview')
        self.preview.setCheckable(True)
        self.preview.toggled.connect(self._update_preview)
        self.preview.dropped.connect(self.load_image)
        preview_layout.addWidget(self.preview, 0, 0)
        self.remove_image = NavigationButton('删除周表图片', 'close', self.preview_box)
        self.remove_image.setAutoDefault(False)
        self.remove_image.setObjectName('CalendarImageRemove')
        self.remove_image.setFixedSize(26, 26)
        self.remove_image.clicked.connect(self._remove_image)
        preview_layout.addWidget(self.remove_image, 0, 0, Qt.AlignTop | Qt.AlignRight)
        self.preview_box.hide()
        outer.addWidget(self.preview_box, 0, Qt.AlignHCenter)
        self.hint = HintLabel()
        self.hint.hide()
        outer.addWidget(self.hint)
        self.review = QWidget(self)
        self.review.hide()
        content = QVBoxLayout(self.review)
        content.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.review)

        options = QHBoxLayout()
        options.addWidget(QLabel('录制频率'))
        self.frequency = SelectControl()
        self.frequency.setAccessibleName('录制频率')
        self.frequency.addItems(('仅此一周', '每周重复'))
        self.frequency.currentIndexChanged.connect(self._validate)
        options.addWidget(self.frequency)
        options.addSpacing(12)
        options.addWidget(QLabel('参考周一'))
        self.week = QDateEdit(QDate(next_monday(self.today)))
        self.week.setDisplayFormat('yyyy/MM/dd')
        self.week.setCalendarPopup(True)
        self.week.setFixedHeight(theme.CONTROL_HEIGHT)
        self.week.setMinimumWidth(self.week.fontMetrics().horizontalAdvance('2026/11/30') + 62)
        self.week.setAccessibleName('日期未识别时使用的参考周一')
        self.week.setToolTip('只有星期、未识别到完整日期的场次，按这周换算。')
        self.week.dateChanged.connect(self._move_week)
        options.addWidget(self.week)
        options.addStretch()
        content.addLayout(options)

        self.list = QVBoxLayout()
        content.addLayout(self.list)
        self.warning = HintLabel('选中的单周场次日期已过，或开始与结束时间相同。')
        self.warning.hide()
        content.addWidget(self.warning)
        actions = QHBoxLayout()
        add = ActionButton('补录一场', self)
        add.setAutoDefault(False)
        add.clicked.connect(lambda: self._add_row(CalendarEntry(None, 20 * 60, None, '', True)))
        actions.addWidget(add)
        actions.addStretch()
        self.confirm = ActionButton('加入已选场次', self)
        self.confirm.setAutoDefault(False)
        self.confirm.clicked.connect(self.applyRequested)
        actions.addWidget(self.confirm)
        content.addLayout(actions)
        self._validate()

        self.loader = CalendarImageLoader(self)
        self.loader.loaded.connect(self._start_ocr)
        self.loader.failed.connect(self._status)
        self.process = QProcess(self)
        self.timeout = QTimer(self, singleShot=True, interval=20000)
        self.timeout.timeout.connect(self.process.kill)
        self.process.finished.connect(self._recognized)
        self.process.errorOccurred.connect(self._ocr_error)

    def _choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择直播周表图片', '', CALENDAR_IMAGE_FILTER)
        if path:
            self.load_image(QUrl.fromLocalFile(path))

    def _status(self, text):
        self.hint.setText(text)
        self.hint.show()

    def load_image(self, source):
        self.stop()
        self._status('正在读取图片…')
        self.loader.load(source)

    def _start_ocr(self, image):
        self.image_file = QTemporaryFile()
        if not self.image_file.open() or not image.save(self.image_file, 'PNG'):
            self.image_file = None
            self._status('无法准备图片识别，请重新导入。')
            return
        path = self.image_file.fileName()
        self.image_file.close()
        self._clear_review()
        self.preview_image = QPixmap.fromImage(image).scaled(QSize(410, 440), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setChecked(False)
        self._update_preview(False)
        self.drop_area.hide()
        self.preview_box.show()
        self._status('正在使用本机 Windows OCR 识别周表…')
        program, arguments, environment = calendar_ocr_command(path)
        self.process.setProcessEnvironment(environment)
        self.timeout.start()
        self.process.start(program, arguments)

    def _update_preview(self, full):
        size = self.preview_image.size() if full else self.preview_image.size().boundedTo(QSize(240, 135))
        pixmap = self.preview_image.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setIcon(QIcon(pixmap))
        self.preview.setIconSize(pixmap.size())
        self.preview.setFixedSize(pixmap.size() + QSize(6, 6))
        text = '缩小周表原图' if full else '放大周表原图'
        self.preview.setAccessibleName(text)
        self.preview.setToolTip(text)

    def _clear_review(self):
        while self.list.count():
            widget = self.list.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self.rows.clear()
        self._validate()
        self.review.hide()

    def _remove_image(self):
        self.stop()
        self._clear_review()
        self.preview_image = QPixmap()
        self.preview.setIcon(QIcon())
        self.preview_box.hide()
        self.hint.hide()
        self.drop_area.show()

    def _add_row(self, entry):
        card = QFrame(objectName='PluginCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        line = QHBoxLayout()
        selected = QCheckBox()
        selected.setAccessibleName('选中场次')
        selected.setToolTip('加入这场直播到录制计划')
        line.addWidget(selected)
        when = QDateEdit(QDate(entry.day) if isinstance(entry.day, date) else self.week.date().addDays(entry.day or 0))
        when.setCalendarPopup(True)
        when.setDisplayFormat('MM/dd ddd')
        when.setAccessibleName('直播日期')
        when.setFixedHeight(theme.CONTROL_HEIGHT)
        when.setMinimumWidth(when.fontMetrics().horizontalAdvance('12/31 周三') + 46)
        line.addWidget(when)
        start = QTimeEdit(QTime(*divmod(entry.start, 60)))
        end = QTimeEdit(QTime(*divmod(entry.start if entry.end is None else entry.end, 60)))
        for field, name in ((start, '开播时间'), (end, '结束时间')):
            field.setDisplayFormat('HH:mm')
            field.setAccessibleName(name)
            field.setFixedHeight(theme.CONTROL_HEIGHT)
            field.setButtonSymbols(QAbstractSpinBox.NoButtons)
            field.setFixedWidth(field.fontMetrics().horizontalAdvance('00:00') + 46)
            line.addWidget(field)
        until_offline = QCheckBox('至下播')
        until_offline.setChecked(entry.end is None)
        end.setVisible(entry.end is not None)
        until_offline.toggled.connect(end.setHidden)
        line.addWidget(until_offline)
        line.addStretch()
        layout.addLayout(line)
        note = HintLabel('')
        note.setMinimumHeight(note.fontMetrics().height())
        layout.addWidget(note)
        row = (selected, when, start, end, until_offline, note, entry)
        when.dateChanged.connect(lambda: when.setProperty('manualDate', True))
        for signal in (selected.toggled, when.dateChanged, start.timeChanged, end.timeChanged, until_offline.toggled):
            signal.connect(self._validate)
        self.rows.append(row)
        self.list.addWidget(card)
        self._validate()

    def _move_week(self, value):
        monday = value.addDays(1 - value.dayOfWeek())
        if monday != value:
            self.week.setDate(monday)
            return
        for _, when, _, _, _, _, entry in self.rows:
            if not isinstance(entry.day, date) and not when.property('manualDate'):
                when.setDate(monday.addDays(entry.day or 0))
                when.setProperty('manualDate', False)
        self._validate()

    def _validate(self):
        repeat = bool(self.frequency.currentIndex())
        count, valid = 0, True
        for selected, when, start, end, until_offline, note, entry in self.rows:
            past = not repeat and when.date().toPython() < self.today
            next_day = not until_offline.isChecked() and end.time() < start.time()
            needs_date = entry.day is None and not when.property('manualDate')
            message = ('请核对日期' if needs_date else '请核对这一场' if entry.review else '')
            labels = (message, '日期已过' if past else '', '结束时间为次日' if next_day else '', entry.text)
            note.setText(' · '.join(filter(None, labels)))
            note.setVisible(bool(note.text()))
            count += selected.isChecked()
            if selected.isChecked() and (past or (not until_offline.isChecked() and start.time() == end.time())):
                valid = False
        self.warning.setVisible(not valid)
        self.confirm.setEnabled(bool(count) and valid)

    def schedule(self):
        repeat = bool(self.frequency.currentIndex())
        return tuple((when.date().dayOfWeek() - 1 if repeat else when.date().toPython().isoformat(),
                      start.time().hour() * 60 + start.time().minute(),
                      None if until_offline.isChecked() else end.time().hour() * 60 + end.time().minute())
                     for selected, when, start, end, until_offline, _, _ in self.rows if selected.isChecked())

    def clear_selection(self):
        for selected, *_ in self.rows:
            selected.setChecked(False)

    def _ocr_error(self, error):
        if error == QProcess.FailedToStart:
            self.timeout.stop()
            self.image_file = None
            self._status('无法启动 Windows OCR，可以手动补录。')
            self.review.show()

    def _recognized(self, code, _status):
        self.timeout.stop()
        self.image_file = None
        try:
            result = json.loads(bytes(self.process.readAllStandardOutput())) if code == 0 else {}
        except (UnicodeError, ValueError):
            result = {}
        if result.get('error') == 'language':
            result_hint = '当前 Windows 没有可用的 OCR 语言包，可以手动补录。'
        elif 'passes' not in result:
            result_hint = '无法识别此图片，可以更换图片或手动补录。'
        else:
            entries = extract_calendar(result['passes'], self.week.date().toPython())
            for entry in entries:
                self._add_row(entry)
            result_hint = (f'识别到 {len(entries)} 场候选。仅有开始时间的场次会录至下播。' if entries
                           else '未读出明确的直播时间，可以对照原图补录。')
            if any(type(entry.day) is int for entry in entries):
                result_hint += ' 日期未识别的场次请核对参考周。'
        self._status(result_hint)
        self.review.show()

    def stop(self):
        self.loader.cancel()
        self.timeout.stop()
        if self.process.state() != QProcess.NotRunning:
            with QSignalBlocker(self.process):
                self.process.kill()
                self.process.waitForFinished(1000)
        self.image_file = None
