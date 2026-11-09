"""Settings diagnostic workflow; collection stays in the independent backend."""
import datetime
import os
from pathlib import Path
import zipfile

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .diagnostic_export import DiagnosticExport
from .ui import page_header


class DiagnosticsPage(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.export = DiagnosticExport(self)
        self.evidence = None
        self.zip_path = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        layout.addLayout(page_header('诊断与反馈', '收集问题线索，检查后手动发送给维护者。'))
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText('刚才做了什么？实际发生了什么？预期是什么？')
        self.description.setMaximumBlockCount(100)
        self.description.setMinimumHeight(100)
        self.description.setMaximumHeight(150)
        self.happened = QLineEdit(datetime.datetime.now().strftime('%Y-%m-%d %H:%M') + ' 左右')
        self.reproduction = QComboBox()
        self.reproduction.addItems(['尚未确认', '稳定复现', '概率触发'])
        form = QFormLayout()
        form.addRow('发生时间', self.happened)
        form.addRow('复现情况', self.reproduction)
        form.addRow('问题描述', self.description)
        layout.addLayout(form)
        self.images = QListWidget()
        self.images.setMaximumHeight(80)
        self.images.setAccessibleName('手动选择的图片附件')
        layout.addWidget(self.images)
        row = QHBoxLayout()
        self.add_images = QPushButton('添加图片')
        self.remove_image = QPushButton('移除选中图片')
        row.addWidget(self.add_images)
        row.addWidget(self.remove_image)
        row.addStretch()
        layout.addLayout(row)
        self.add_images.clicked.connect(self._images)
        self.remove_image.clicked.connect(lambda: self.images.takeItem(self.images.currentRow()))
        self._hint(layout, '最多 5 张图片，每张 20MB。图片会移除元数据，画面内容请自行检查。')
        self._label(layout, '收集范围')
        self._hint(layout, '版本与系统信息、脱敏配置、插件版本、近期日志、原生崩溃栈及对象生命周期。'
                   '不读取账号文件，不自动截图或上传。已有记录即使无法复现也可导出；缺少记录不代表正常。')
        self.dump_enabled = QCheckBox('记录增强崩溃转储（保存设置后生效）')
        self.dump_enabled.setChecked(bool(settings.get('native_crash_dump', False)))
        layout.addWidget(self.dump_enabled)
        self._hint(layout, '用于后续崩溃，不能补回过去的内存。转储可能含账号、播放地址或聊天等进程内存，无法自动脱敏。')
        self.include_dumps = QCheckBox('本次诊断包包含已有内存转储')
        self.include_dumps.setChecked(False)
        layout.addWidget(self.include_dumps)
        self._label(layout, '问题仍在时，可补充现场')
        live = QHBoxLayout()
        self.folders = QPushButton('抓取文件夹现场')
        self.drag = QPushButton('记录一次拖放')
        self.cancel = QPushButton('取消现场采集')
        self.cancel.setEnabled(False)
        live.addWidget(self.folders)
        live.addWidget(self.drag)
        live.addWidget(self.cancel)
        layout.addLayout(live)
        self._hint(layout, '现场采集后可返回主窗口操作。拖放最多等待 60 秒；完成后再导出诊断包。')
        self.folders.clicked.connect(lambda: self._capture('folders'))
        self.drag.clicked.connect(lambda: self._capture('drag'))
        self.cancel.clicked.connect(self.export.stop)
        target = QHBoxLayout()
        self.destination = QLineEdit(QStandardPaths.writableLocation(QStandardPaths.DesktopLocation) or str(Path.home()))
        self.browse = QPushButton('选择保存位置')
        target.addWidget(self.destination, 1)
        target.addWidget(self.browse)
        layout.addLayout(target)
        self.browse.clicked.connect(self._browse)
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.status = QLabel('准备就绪。无需重新复现，也可以收集已有日志。')
        self.status.setWordWrap(True)
        outer.addWidget(self.progress)
        outer.addWidget(self.status)
        actions = QHBoxLayout()
        self.summary = QPushButton('查看摘要')
        self.open_folder = QPushButton('打开保存位置')
        self.generate = QPushButton('导出诊断包')
        self.generate.setObjectName('PrimaryButton')
        self.summary.setEnabled(False)
        self.open_folder.setEnabled(False)
        actions.addWidget(self.summary)
        actions.addWidget(self.open_folder)
        actions.addStretch()
        actions.addWidget(self.generate)
        outer.addLayout(actions)
        self.generate.clicked.connect(self._generate)
        self.summary.clicked.connect(self._summary)
        self.open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.zip_path).parent))))
        self.export.progress.connect(self._progress)
        self.export.failed.connect(self.status.setText)
        self.export.busyChanged.connect(self._busy)
        self.export.completed.connect(self._completed)
        self.export.captured.connect(self._captured)
        for button in self.findChildren(QPushButton):
            if button is not self.generate:
                button.setObjectName('IconButton')
        dialog = self.window()
        if isinstance(dialog, QDialog):
            dialog.finished.connect(self.export.stop)

    @staticmethod
    def _label(layout, text):
        label = QLabel(text)
        label.setObjectName('SectionTitle')
        layout.addWidget(label)

    @staticmethod
    def _hint(layout, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName('SettingsHint')
        layout.addWidget(label)

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
