"""Settings diagnostic workflow; collection stays in the independent backend."""
import datetime
import os
from pathlib import Path
import zipfile

from PySide6.QtCore import QEvent, QStandardPaths, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QBoxLayout, QDialog, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit,
    QScrollArea, QVBoxLayout, QWidget)

from .diagnostic_export import DiagnosticExport
from .ui import ActionButton, SelectControl, SettingsProgressBar, ToggleSwitch, page_header
from .settings_layout import SettingsColumns, SettingsSection


ISSUE_URL = 'https://github.com/Lanpropro/DD_Monitor_CE/issues/new/choose'


class DiagnosticDescription(QPlainTextEdit):
    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()


class DiagnosticsPage(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName('SettingsPage')
        self.export = DiagnosticExport(self)
        self.evidence = None
        self.zip_path = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)
        outer.addLayout(page_header('诊断与反馈', '描述问题、导出记录，检查后手动发送给维护者。'))
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(14)
        self.sections = SettingsColumns(body)
        layout.addWidget(self.sections)
        issue = SettingsSection('描述问题')
        self.description = DiagnosticDescription()
        self.description.setProperty('settingsWheelLocal', True)
        self.description.setAccessibleName('问题描述')
        self.description.setPlaceholderText('做了什么、遇到什么、希望是什么？')
        self.description.setMaximumBlockCount(100)
        self.description.setMinimumHeight(100)
        self.description.setMaximumHeight(150)
        self.happened = QLineEdit(datetime.datetime.now().strftime('%Y-%m-%d %H:%M') + ' 左右')
        self.happened.setAccessibleName('发生时间')
        self.reproduction = SelectControl()
        self.reproduction.setAccessibleName('复现情况')
        self.reproduction.addItems(['尚未确认', '稳定复现', '概率触发'])
        issue.grid.addWidget(QLabel('发生时间'), 0, 0)
        issue.grid.addWidget(self.happened, 0, 1)
        issue.grid.addWidget(QLabel('复现情况'), 1, 0)
        issue.grid.addWidget(self.reproduction, 1, 1)
        issue.grid.addWidget(self.description, 2, 0, 1, 2)
        self.sections.add_section('issue', issue)

        attachments = SettingsSection('图片附件（可选）')
        self.images = QListWidget()
        self.images.setMaximumHeight(100)
        self.images.setAccessibleName('手动选择的图片附件')
        attachments.grid.addWidget(self.images, 0, 0, 1, 2)
        row = QHBoxLayout()
        self.add_images = ActionButton('添加图片')
        self.remove_image = ActionButton('移除所选')
        self.remove_image.setAccessibleName('移除选中图片')
        row.addWidget(self.add_images)
        row.addWidget(self.remove_image)
        row.addStretch(1)
        attachments.grid.addLayout(row, 1, 0, 1, 2)
        self.add_images.clicked.connect(self._images)
        self.remove_image.clicked.connect(lambda: self.images.takeItem(self.images.currentRow()))
        self._hint(attachments.grid, 2, '最多5张，每张20MB。导出会移除元数据，图片内容请自行检查。')
        self.sections.add_section('attachments', attachments)

        collection = SettingsSection('收集范围')
        self._hint(collection.grid, 0, '系统与版本、脱敏配置、插件版本、近期日志及已有崩溃记录。无需重新复现也可导出。')
        self._hint(collection.grid, 1, '不读取账号文件，不自动截图或上传。')
        self.dump_enabled = ToggleSwitch('记录增强崩溃转储')
        self.dump_enabled.setChecked(bool(settings.get('native_crash_dump', False)))
        self._switch_row(collection.grid, 2, '记录增强崩溃转储', self.dump_enabled)
        self.dump_enabled.setToolTip('保存设置后用于后续崩溃，无法补回过去的进程内存。')
        self.include_dumps = ToggleSwitch('本次包含已有内存转储')
        self.include_dumps.setChecked(False)
        self._switch_row(collection.grid, 3, '本次包含已有内存转储', self.include_dumps)
        self._hint(collection.grid, 4, '内存转储可能含账号、播放地址或聊天，无法自动脱敏；仅主动勾选时打包。')
        self.sections.add_section('collection', collection)

        live = SettingsSection('补充现场（可选）')
        self.folders = ActionButton('文件夹现场')
        self.drag = ActionButton('拖放记录')
        self.cancel = ActionButton('取消采集')
        self.cancel.setEnabled(False)
        self.live_actions = QBoxLayout(QBoxLayout.LeftToRight)
        for button in (self.folders, self.drag, self.cancel):
            self.live_actions.addWidget(button)
        live.grid.addLayout(self.live_actions, 0, 0, 1, 2)
        self._hint(live.grid, 1, '问题仍在时再采集。拖放最多等待60秒，返回主窗口操作后再导出。')
        self.folders.clicked.connect(lambda: self._capture('folders'))
        self.drag.clicked.connect(lambda: self._capture('drag'))
        self.cancel.clicked.connect(self.export.stop)
        self.sections.add_section('live', live)
        live.installEventFilter(self)

        destination = SettingsSection('保存位置')
        target = QHBoxLayout()
        self.destination = QLineEdit(QStandardPaths.writableLocation(QStandardPaths.DesktopLocation) or str(Path.home()))
        self.destination.setAccessibleName('诊断包保存位置')
        self.browse = ActionButton('浏览…')
        self.browse.setAccessibleName('选择诊断包保存位置')
        target.addWidget(self.destination, 1)
        target.addWidget(self.browse)
        destination.grid.addLayout(target, 0, 0, 1, 2)
        self.browse.clicked.connect(self._browse)
        self.sections.add_section('destination', destination, wide=True)
        layout.addStretch(1)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)

        progress_row = QHBoxLayout()
        self.progress = SettingsProgressBar()
        self.progress.setAccessibleName('诊断采集进度')
        self.progress.setValue(0)
        self.progress_text = QLabel('0%')
        self.progress.valueChanged.connect(lambda value: self.progress_text.setText(f'{value}%'))
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.progress_text)
        outer.addLayout(progress_row)
        self.status = QLabel('准备就绪，可直接导出已有记录。')
        self.status.setObjectName('SettingsHint')
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.actions = QBoxLayout(QBoxLayout.LeftToRight)
        self.summary = ActionButton('查看摘要')
        self.open_folder = ActionButton('打开保存位置')
        self.open_issue = ActionButton('打开 Issue')
        self.open_issue.setToolTip('在浏览器中选择 GitHub 问题模板，可手动添加诊断包')
        self.open_issue.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ISSUE_URL)))
        self.generate = ActionButton('导出诊断包')
        self.generate.setObjectName('PrimaryButton')
        self.summary.setEnabled(False)
        self.open_folder.setEnabled(False)
        for button in (self.generate, self.summary, self.open_folder, self.open_issue):
            self.actions.addWidget(button)
        outer.addLayout(self.actions)
        self.generate.clicked.connect(self._generate)
        self.summary.clicked.connect(self._summary)
        self.open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.zip_path).parent))))
        self.export.progress.connect(self._progress)
        self.export.failed.connect(self.status.setText)
        self.export.busyChanged.connect(self._busy)
        self.export.completed.connect(self._completed)
        self.export.captured.connect(self._captured)
        dialog = self.window()
        if isinstance(dialog, QDialog):
            dialog.finished.connect(self.export.stop)

    @staticmethod
    def _hint(grid, row, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName('SettingsHint')
        grid.addWidget(label, row, 0, 1, 2)

    @staticmethod
    def _switch_row(grid, row, text, switch):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setBuddy(switch)
        controls = QHBoxLayout()
        controls.addWidget(label, 1)
        controls.addWidget(switch)
        grid.addLayout(controls, row, 0, 1, 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_actions(self.actions, (self.generate, self.summary, self.open_folder, self.open_issue),
                              self.contentsRect().width())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize and watched is self.sections.section('live'):
            self._arrange_actions(self.live_actions, (self.folders, self.drag, self.cancel), watched.width() - 36)
        return super().eventFilter(watched, event)

    @staticmethod
    def _arrange_actions(layout, buttons, width):
        needed = sum(button.sizeHint().width() for button in buttons) + max(0, layout.spacing()) * (len(buttons) - 1)
        layout.setDirection(QBoxLayout.TopToBottom if width < needed else QBoxLayout.LeftToRight)

    def values(self):
        return {'native_crash_dump': self.dump_enabled.isChecked()}

    def reset(self):
        self.dump_enabled.setChecked(False)
        self.include_dumps.setChecked(False)

    def _images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '添加图片', '', '图片 (*.png *.jpg *.jpeg *.bmp *.gif)')
        existing = [self.images.item(i).text() for i in range(self.images.count())]
        for path in paths:
            if path not in existing and self.images.count() < 5:
                if Path(path).stat().st_size > 20 * 1024 * 1024:
                    self.status.setText('图片超过 20MB，请缩小后添加。')
                    continue
                self.images.addItem(path)
                existing.append(path)

    def _browse(self):
        directory = QFileDialog.getExistingDirectory(self, '保存诊断包', self.destination.text())
        if directory:
            self.destination.setText(directory)

    def _capture(self, mode):
        pid = int(os.environ.get('DDM_DIAGNOSTIC_HOST_PID', os.getpid()))
        self.status.setText('正在采集；请返回主窗口操作。' if mode == 'drag' else '正在读取文件夹现场…')
        self.export.start({'pid': pid, 'mode': mode}, capture=True)
        self.cancel.setEnabled(self.export.busy)

    def _captured(self, evidence):
        self.evidence = evidence
        self.status.setText('现场记录已保存到本次会话，可继续填写并导出。')

    def _generate(self):
        if not Path(self.destination.text()).is_dir():
            self.status.setText('请选择已存在的保存文件夹。')
            return
        self.export.start({'destination': self.destination.text(), 'description': self.description.toPlainText()[:12000],
            'happened': self.happened.text()[:200], 'reproduction': self.reproduction.currentText(),
            'attachments': [self.images.item(i).text() for i in range(self.images.count())],
            'evidence': self.evidence, 'include_native_dumps': self.include_dumps.isChecked()})

    def _busy(self, busy):
        for control in (self.generate, self.folders, self.drag, self.destination, self.browse,
                        self.add_images, self.remove_image, self.include_dumps):
            control.setEnabled(not busy)
        self.cancel.setEnabled(False)

    def _progress(self, percent, text):
        self.progress.setValue(percent)
        self.status.setText(text)

    def _completed(self, path):
        self.zip_path = path
        self.progress.setValue(100)
        self.status.setText('诊断包已生成。请检查内容后手动发送，软件不会自动上传。')
        self.summary.setEnabled(True)
        self.open_folder.setEnabled(True)

    def _summary(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('诊断摘要')
        dialog.resize(620, 440)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        try:
            with zipfile.ZipFile(self.zip_path) as archive:
                with archive.open('诊断摘要.txt') as stream:
                    text.setPlainText(stream.read(1024 * 1024).decode('utf-8'))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            self.status.setText('无法读取诊断摘要，请检查文件是否已移动。')
            return
        layout.addWidget(text)
        dialog.exec()
