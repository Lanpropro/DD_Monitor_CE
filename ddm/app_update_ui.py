"""Application update settings page and staged download actions."""
import json
from pathlib import Path
import sys
import tempfile
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextBrowser, QVBoxLayout, QWidget
from . import config, online, update_install, version
from .update_version import installed_revision, release_label
from .online_tasks import OnlinePage


class AppUpdatePage(OnlinePage):
    releaseChecked = Signal(object)
    saveRequested = Signal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.offer = None
        self._checked = False
        self.plan_path = ''
        self.install_requested = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        self.scroll.setWidget(content)
        root.addWidget(self.scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel('软件更新')
        title.setObjectName('SettingsTitle')
        layout.addWidget(title)
        layout.addWidget(QLabel('当前版本：' + version.VERSION))
        self.check = QPushButton('检查更新')
        self.check.setObjectName('IconButton')
        self.check.clicked.connect(self.check_update)
        self.auto = QCheckBox('自动更新（启动时检查并提醒）')
        self.auto.setChecked(bool((settings or {}).get('auto_update', False)))
        self.auto.setToolTip('开启后，启动软件时检查新版；点击悬浮提示进入此页，自行下载并安装。')
        layout.addWidget(self.auto)
        self.action = QPushButton('下载更新')
        self.action.setObjectName('PrimaryButton')
        self.action.setProperty('updateAction', True)
        self.action.setEnabled(False)
        self.action.clicked.connect(self.download_update)
        actions = QHBoxLayout()
        actions.addWidget(self.check)
        actions.addWidget(self.action)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self.status)
        self.notes_title = QLabel('当前版本 ' + version.VERSION + ' 更新说明')
        layout.addWidget(self.notes_title)
        self.notes = QTextBrowser()
        self.notes.setMinimumHeight(160)
        self.notes.setObjectName('UpdateNotes')
        self.notes.setOpenExternalLinks(True)
        self.show_current_notes()
        layout.addWidget(self.notes, 1)
        self.release_button = QPushButton('打开发布页面')
        self.release_button.setObjectName('IconButton')
        self.release_button.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl(f'https://github.com/{online.APP_REPOSITORY}/releases')))
        layout.addWidget(self.release_button, 0, Qt.AlignLeft)
        from .data_settings import DataSettingsPage
        self.data_page = DataSettingsPage()
        layout.addSpacing(16)
        layout.addWidget(self.data_page)
        self.status.setText('点击“检查更新”查询可下载的新版。' if getattr(sys, 'frozen', False) else
                            '源码运行可检查版本；自动替换仅适用于 Windows EXE 版。')
        message = update_install.result_message(config.REPO, config.data_root(), version.VERSION)
        if message:
            self.status.setText(message)
        self.busyChanged.connect(self._busy)
        self._busy(False)

    def _busy(self, busy):
        self.check.setEnabled(not busy and not self.plan_path)
        self.action.setEnabled(not busy and bool(self.plan_path or self.offer)
                               and bool(getattr(sys, 'frozen', False)))
        if busy:
            text, hint = (('正在下载…', '正在下载和校验更新包，请等待完成') if self.offer else
                          ('检查中…', '正在查询正式版本，请等待检查结果'))
        elif self.plan_path:
            text, hint = '重启并更新', '更新包已准备完成，点击保存设置并重启安装'
        elif not getattr(sys, 'frozen', False):
            text, hint = '仅 EXE 版可更新', '当前为源码运行，请通过仓库更新源码'
        elif self.offer:
            text, hint = '下载更新', '下载并校验新版软件，完成后再确认重启安装'
        elif self._checked:
            text, hint = '已是最新版本', '未发现比当前版本更新的正式版本，无需下载'
        else:
            text, hint = '请先检查更新', '点击“检查更新”；如果检查失败，可重试或打开发布页面手动下载'
        self.action.setText(text)
        self.action.setToolTip(hint)

    def values(self):
        return {'auto_update': self.auto.isChecked()}

    def show_current_notes(self):
        self.notes_title.setText('当前版本 ' + version.VERSION + ' 更新说明')
        try:
            filename = 'RELEASE-v' + version.VERSION + '.md'
            path = Path(config.REPO) / 'docs' / 'releases' / filename
            if not path.is_file():
                path = Path(config.REPO) / filename
            notes = path.read_text(encoding='utf-8-sig')
        except OSError:
            notes = '本地未附带当前版本的更新说明，可点击“打开发布页面”查看。'
        self.notes.setMarkdown(notes)

    def stop(self):
        cleanup = None
        if not self.install_requested:
            root = config.REPO
            cleanup = lambda result: update_install.discard_plan(result, root) if isinstance(result, str) and result else None
        super().stop(result_cleanup=cleanup)
        if not self.install_requested:
            if self.plan_path:
                update_install.discard_plan(self.plan_path, config.REPO)
            self.plan_path = ''

    def check_update(self):
        if self.jobs or self.stopping or self.plan_path:
            return
        self.offer = None
        self._checked = False
        self.show_current_notes()
        self.status.setText('正在检查正式版本…')
        def check(cancelled, progress):
            with online.session() as client:
                offer = online.app_release(client, version.VERSION, installed_revision(config.REPO, version.VERSION))
                notes = ''
                if offer is None:
                    try:
                        notes = online.release_notes(client, version.VERSION)
                    except (online.requests.RequestException, ValueError):
                        pass
                return offer, notes
        self.start(check, self._check_ready)

    def _check_ready(self, result):
        offer, notes = result
        self._release_ready(offer)
        if offer is None and notes:
            self.notes.setMarkdown(notes)

    def _release_ready(self, offer):
        self.offer = offer
        self._checked = True
        self._busy(bool(self.jobs))
        self.releaseChecked.emit(offer)
        if offer:
            self.notes_title.setText('新版 ' + release_label(offer) + ' 更新说明')
            self.notes.setMarkdown(offer.get('notes') or '此版本暂未提供更新说明。')
        else:
            self.show_current_notes()
        self.status.setText('发现新版 ' + release_label(offer) if offer else '当前已是最新正式版本。')
        if offer and not getattr(sys, 'frozen', False):
            self.status.setText('发现新版 ' + release_label(offer) + '；源码版请从仓库更新，EXE 版可自动安装。')

    def download_update(self):
        if not getattr(sys, 'frozen', False):
            return
        if self.plan_path:
            self.install_requested = True
            self.saveRequested.emit()
            return
        if not self.offer:
            return
        offer = dict(self.offer)
        self.status.setText('正在下载新版软件…')
        def prepare(cancelled, progress):
            with tempfile.TemporaryDirectory(prefix='ddm-app-download-') as temporary, online.session() as client:
                archive = online.download(offer, Path(temporary) / 'app.zip', client, cancelled, progress)
                return update_install.prepare(archive, config.REPO, sys.executable, cancelled, offer['version'],
                                              data_root=config.data_root(), expected_revision=offer.get('revision', 0))
        self.start(prepare, self._prepared)

    def _prepared(self, plan_path):
        self.plan_path = plan_path
        self.action.setText('重启并更新')
        plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
        permission = ' 更新程序文件时将请求管理员授权；取消授权会保留原版本。' if plan.get('elevate') else ''
        self.status.setText('下载和校验完成。点击重启并更新，将先保存设置并收尾录制。' + permission)
