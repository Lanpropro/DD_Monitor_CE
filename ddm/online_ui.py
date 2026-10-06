"""插件商店和软件更新页面；联网、下载和解压都在工作线程执行。"""
import json
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from . import config, online, plugin_updates, update_install, version


class OnlineTask(QThread):
    succeeded = Signal(object)
    failed = Signal(object)
    progress = Signal(int)

    def __init__(self, operation, callback, parent):
        super().__init__(parent)
        self.operation = operation
        self.callback = callback
        self.result = None

    def run(self):
        try:
            result = self.operation(self.isInterruptionRequested,
                                    lambda done, total: self.progress.emit(int(done * 100 / max(total, 1))))
            self.result = result
            if not self.isInterruptionRequested():
                self.succeeded.emit((self, result))
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit((self, str(error)))


class OnlinePage(QWidget):
    busyChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('SettingsPage')
        self.jobs = []
        self.stopping = False
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setObjectName('SettingsHint')

    def start(self, operation, callback):
        if self.jobs or self.stopping:
            return
        task = OnlineTask(operation, callback, self)
        self.jobs.append(task)
        task.succeeded.connect(self._succeeded)
        task.failed.connect(self._failed)
        task.progress.connect(self._progress)
        task.finished.connect(self._finished)
        self.busyChanged.emit(True)
        task.start()

    def _succeeded(self, payload):
        task, result = payload
        if not self.stopping:
            try:
                task.callback(result)
            except Exception as error:
                self.status.setText(str(error))

    def _failed(self, payload):
        if not self.stopping:
            self.status.setText('操作失败：' + payload[1] + '。可重试。')

    def _progress(self, percent):
        if not self.stopping:
            self.status.setText(f'正在下载并校验… {percent}%')

    def _finished(self):
        task = self.sender()
        if task in self.jobs:
            self.jobs.remove(task)
        task.deleteLater()
        self.busyChanged.emit(bool(self.jobs))

    def stop(self):
        self.stopping = True
        for task in self.jobs:
            task.requestInterruption()
        for task in self.jobs:
            task.wait()


class PluginStorePage(OnlinePage):
    installed = Signal(str)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.offers = []
        self.buttons = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 4, 0)
        self.refresh = QPushButton('刷新插件商店')
        self.refresh.setObjectName('IconButton')
        self.refresh.clicked.connect(self.refresh_catalog)
        layout.addWidget(self.refresh, 0, Qt.AlignLeft)
        layout.addWidget(self.status)
        self.cards = QVBoxLayout()
        layout.addLayout(self.cards)
        layout.addStretch(1)
        self.busyChanged.connect(self._busy)

    def _busy(self, busy):
        self.refresh.setEnabled(not busy)
        if busy:
            for button in self.buttons.values():
                button.setEnabled(False)
        else:
            self.show_offers(self.offers)

    def refresh_catalog(self):
        self.status.setText('正在读取官方插件仓库…')
        def read(cancelled, progress):
            with online.session() as client:
                return online.plugin_catalog(client, version.VERSION)
        self.start(read, self._catalog_ready)

    def _catalog_ready(self, offers):
        self.offers = offers
        self.show_offers(offers)
        self.status.setText('暂时无法查询最新版本，显示内置的已发布插件目录。' if any(
            offer.get('cached') for offer in offers) else '选择插件即可下载安装，重启后启用。')

    def show_offers(self, offers):
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.buttons = {}
        installed = {entry['id']: entry for entry in self.manager.catalog()} if self.manager else {}
        pending = plugin_updates.pending_versions(self.manager) if self.manager else {}
        for offer in offers:
            card = QFrame()
            card.setObjectName('PluginCard')
            body = QVBoxLayout(card)
            heading = QHBoxLayout()
            heading.addWidget(QLabel(offer['name'] + ('  v' + offer['version'] if offer['version'] else '')))
            heading.addStretch(1)
            button = QPushButton('安装')
            button.setObjectName('IconButton')
            description = QLabel(offer['description'])
            description.setWordWrap(True)
            note = offer.get('reason', '')
            allowed = offer.get('available', False) and self.manager is not None and not self.jobs
            existing = installed.get(offer['id'])
            if offer['id'] in pending:
                button.setText('待重启')
                note = '新版本已下载，保存并重启后生效'
                allowed = False
            elif existing:
                try:
                    newer = bool(offer['version']) and online.version_key(offer['version']) > online.version_key(existing['version'])
                except ValueError:
                    newer = False
                button.setText('更新' if newer else '已安装')
                note = f"当前版本：{existing['version']}" + (' · ' + note if note else '')
                allowed = allowed and newer
            elif not offer.get('available'):
                button.setText('暂不可安装')
            button.setEnabled(allowed)
            button.clicked.connect(lambda _checked=False, entry=offer: self.install_offer(entry))
            self.buttons[offer['id']] = button
            heading.addWidget(button)
            body.addLayout(heading)
            body.addWidget(description)
            if note:
                hint = QLabel(note)
                hint.setWordWrap(True)
                hint.setObjectName('SettingsHint')
                body.addWidget(hint)
            self.cards.addWidget(card)

    def install_offer(self, offer):
        if not self.manager or not offer.get('available'):
            return
        self.status.setText('正在下载安装包…')
        def install(cancelled, progress):
            with tempfile.TemporaryDirectory(prefix='ddm-plugin-download-') as temporary, online.session() as client:
                archive = online.download(offer, Path(temporary) / 'plugin.zip', client, cancelled, progress)
                if cancelled():
                    raise InterruptedError('安装已取消')
                new = offer['id'] not in {entry['id'] for entry in self.manager.catalog()}
                return plugin_updates.install(self.manager, archive, offer), new
        self.start(install, self._installed)

    def _installed(self, result):
        plugin_id, new = result
        if new and self.manager.enabled is not None:
            self.manager.enabled.add(plugin_id)
            self.manager.save_plugin_settings()
        self.installed.emit(plugin_id)
        self.status.setText('安装包已校验，保存并重启后生效。')


class AppUpdatePage(OnlinePage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.offer = None
        self.plan_path = ''
        self.install_requested = False
        self._auto_download = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel('软件更新')
        title.setObjectName('SettingsTitle')
        layout.addWidget(title)
        layout.addWidget(QLabel('当前版本：' + version.VERSION))
        self.check = QPushButton('检查更新')
        self.check.setObjectName('IconButton')
        self.check.clicked.connect(self.check_update)
        self.auto = QPushButton('自动更新')
        self.auto.setObjectName('IconButton')
        self.auto.setToolTip('一键检查并下载新版，准备完成后点击重启并更新。')
        self.auto.clicked.connect(self.auto_update)
        self.action = QPushButton('下载更新')
        self.action.setObjectName('PrimaryButton')
        self.action.setEnabled(False)
        self.action.clicked.connect(self.download_update)
        actions = QHBoxLayout()
        actions.addWidget(self.check)
        actions.addWidget(self.auto)
        actions.addWidget(self.action)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self.status)
        layout.addWidget(QLabel('更新说明'))
        self.notes = QTextBrowser()
        self.notes.setObjectName('UpdateNotes')
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown('点击“检查更新”查看新版的 Release 更新说明。')
        layout.addWidget(self.notes, 1)
        self.release_button = QPushButton('打开发布页面')
        self.release_button.setObjectName('IconButton')
        self.release_button.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl(f'https://github.com/{online.APP_REPOSITORY}/releases')))
        layout.addWidget(self.release_button, 0, Qt.AlignLeft)
        if not getattr(sys, 'frozen', False):
            self.status.setText('源码运行可检查版本；自动替换仅适用于 Windows EXE 版。')
        result = Path(config.REPO) / update_install.RESULT
        if result.is_file():
            try:
                self.status.setText(json.loads(result.read_text(encoding='utf-8'))['message'])
            except (OSError, ValueError, KeyError):
                pass
        self.busyChanged.connect(self._busy)
        self._busy(False)

    def _busy(self, busy):
        self.check.setEnabled(not busy and not self.plan_path)
        self.auto.setEnabled(not busy and not self.plan_path and bool(getattr(sys, 'frozen', False)))
        self.action.setEnabled(not busy and bool(self.plan_path or self.offer)
                               and bool(getattr(sys, 'frozen', False)))

    def _finished(self):
        super()._finished()
        if self._auto_download:
            self._auto_download = False
            if not self.stopping and self.offer:
                self.download_update()

    def _failed(self, payload):
        super()._failed(payload)
        if not self.stopping and not self.offer:
            self.notes.setMarkdown('暂时无法获取 Release 更新说明，请稍后重试。')

    def auto_update(self):
        if getattr(sys, 'frozen', False):
            self.check_update(automatic=True)

    def stop(self):
        tasks = list(self.jobs)
        super().stop()
        if not self.install_requested:
            for path in [self.plan_path] + [task.result for task in tasks if isinstance(task.result, str)]:
                if path:
                    update_install.discard_plan(path, config.REPO)
            self.plan_path = ''

    def check_update(self, automatic=False):
        if self.jobs or self.stopping or self.plan_path:
            return
        self._auto_download = automatic
        self.offer = None
        self.notes.setMarkdown('正在获取新版的 Release 更新说明…')
        self.status.setText('正在检查正式版本…')
        def check(cancelled, progress):
            with online.session() as client:
                return online.app_release(client, version.VERSION)
        self.start(check, self._release_ready)

    def _release_ready(self, offer):
        self.offer = offer
        self.notes.setMarkdown((offer.get('notes') or '此版本暂未提供更新说明。') if offer
                               else '当前没有比 ' + version.VERSION + ' 更新的正式版本。\n\n发现新版后将在这里展示 Release 更新说明。')
        self.status.setText('发现新版 ' + offer['version'] if offer else '当前已是最新正式版本。')
        if offer and not getattr(sys, 'frozen', False):
            self.status.setText('发现新版 ' + offer['version'] + '；源码版请从仓库更新，EXE 版可自动安装。')

    def download_update(self):
        if not getattr(sys, 'frozen', False):
            return
        if self.plan_path:
            self.install_requested = True
            dialog = self.window()
            dialog._save()
            return
        if not self.offer:
            return
        offer = dict(self.offer)
        self.status.setText('正在下载新版软件…')
        def prepare(cancelled, progress):
            with tempfile.TemporaryDirectory(prefix='ddm-app-download-') as temporary, online.session() as client:
                archive = online.download(offer, Path(temporary) / 'app.zip', client, cancelled, progress)
                return update_install.prepare(archive, config.REPO, sys.executable, cancelled, offer['version'])
        self.start(prepare, self._prepared)

    def _prepared(self, plan_path):
        self.plan_path = plan_path
        self.action.setText('重启并更新')
        self.status.setText('下载和校验完成。点击重启并更新，将先保存设置并收尾录制。')
