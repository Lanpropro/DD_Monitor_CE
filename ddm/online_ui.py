"""插件商店和软件更新页面；联网、下载和解压都在工作线程执行。"""
import json
from pathlib import Path
import sys
import tempfile
import time

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRectF, QThread, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from . import config, motion, online, plugin_updates, theme, update_install, version


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
        self.cache_path = Path(config.REPO) / 'cache' / 'plugin-catalog.json'
        self._checked_at = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 4, 0)
        self.refresh = QPushButton('刷新插件商店')
        self.refresh.setObjectName('IconButton')
        self.refresh.clicked.connect(lambda: self.refresh_catalog(force=True))
        layout.addWidget(self.status)
        self.cards = QVBoxLayout()
        self.cards.setSpacing(10)
        layout.addLayout(self.cards)
        layout.addStretch(1)
        self.busyChanged.connect(self._busy)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(online.CATALOG_CHECK_SECONDS * 1000)
        self._refresh_timer.timeout.connect(self.open_catalog)
        cached = online.load_plugin_cache(self.cache_path)
        if cached:
            self._checked_at = cached['checked_at']
            self._catalog_ready(online._compatible_offers(cached['offers'], version.VERSION))

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_timer.start()

    def hideEvent(self, event):
        self._refresh_timer.stop()
        super().hideEvent(event)

    def open_catalog(self):
        if self.jobs or self.stopping:
            return
        if self.offers and 0 <= time.time() - self._checked_at < online.CATALOG_CHECK_SECONDS:
            return
        self.refresh_catalog()

    def _busy(self, busy):
        self.refresh.setEnabled(not busy)
        if busy:
            for button in self.buttons.values():
                button.setEnabled(False)
        else:
            for button in self.buttons.values():
                button.setEnabled(bool(button.property('storeEnabled')))

    def refresh_catalog(self, force=False):
        if self.jobs or self.stopping:
            return
        if not self.offers:
            self.status.setText('正在读取官方插件仓库…')
        def read(cancelled, progress):
            with online.session() as client:
                return online.cached_plugin_catalog(client, version.VERSION, self.cache_path, force)
        self.start(read, self._catalog_ready)

    def _catalog_ready(self, offers):
        if offers != self.offers or not self.buttons:
            self.offers = [dict(offer) for offer in offers]
            self.show_offers(offers)
        self._checked_at = online.load_plugin_cache(self.cache_path).get('checked_at', self._checked_at)
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
            body.setContentsMargins(14, 12, 14, 12)
            body.setSpacing(6)
            heading = QHBoxLayout()
            title = QLabel(offer['name'] + ('  v' + offer['version'] if offer['version'] else ''))
            title.setObjectName('PluginName')
            heading.addWidget(title)
            heading.addStretch(1)
            button = QPushButton('安装')
            button.setObjectName('IconButton')
            description = QLabel(offer['description'])
            description.setWordWrap(True)
            note = offer.get('reason', '')
            allowed = offer.get('available', False) and self.manager is not None
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
            button.setProperty('storeEnabled', allowed)
            button.setEnabled(allowed and not self.jobs)
            button.clicked.connect(lambda _checked=False, entry=offer: self.install_offer(entry))
            self.buttons[offer['id']] = button
            heading.addWidget(button)
            body.addLayout(heading)
            body.addWidget(description)
            hint = QLabel(note or ' ')
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
        self.show_offers(self.offers)
        self.status.setText('安装包已校验，保存并重启后生效。')
        show_result(self.window(), '插件已安装，保存并重启后生效')


class AppUpdatePage(OnlinePage):
    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.offer = None
        self.plan_path = ''
        self.install_requested = False
        layout = QVBoxLayout(self)
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
        self.notes.setObjectName('UpdateNotes')
        self.notes.setOpenExternalLinks(True)
        self.show_current_notes()
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
        self.action.setEnabled(not busy and bool(self.plan_path or self.offer)
                               and bool(getattr(sys, 'frozen', False)))

    def values(self):
        return {'auto_update': self.auto.isChecked()}

    def show_current_notes(self):
        self.notes_title.setText('当前版本 ' + version.VERSION + ' 更新说明')
        try:
            notes = (Path(config.REPO) / ('RELEASE-v' + version.VERSION + '.md')).read_text(encoding='utf-8-sig')
        except OSError:
            notes = '本地未附带当前版本的更新说明，可点击“打开发布页面”查看。'
        self.notes.setMarkdown(notes)

    def stop(self):
        tasks = list(self.jobs)
        super().stop()
        if not self.install_requested:
            for path in [self.plan_path] + [task.result for task in tasks if isinstance(task.result, str)]:
                if path:
                    update_install.discard_plan(path, config.REPO)
            self.plan_path = ''

    def check_update(self):
        if self.jobs or self.stopping or self.plan_path:
            return
        self.offer = None
        self.show_current_notes()
        self.status.setText('正在检查正式版本…')
        def check(cancelled, progress):
            with online.session() as client:
                return online.app_release(client, version.VERSION)
        self.start(check, self._release_ready)

    def _release_ready(self, offer):
        self.offer = offer
        if offer:
            self.notes_title.setText('新版 ' + offer['version'] + ' 更新说明')
            self.notes.setMarkdown(offer.get('notes') or '此版本暂未提供更新说明。')
        else:
            self.show_current_notes()
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


class UpdateNotice(QFrame):
    """不抢焦点的悬浮更新提醒，十秒后自动收起。"""
    activated = Signal()

    def __init__(self, parent):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName('UpdateNotice')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        heading = QHBoxLayout()
        self.title = QLabel('')
        self.title.setObjectName('PluginName')
        heading.addWidget(self.title, 1)
        close = QPushButton('×')
        close.setObjectName('NoticeClose')
        close.setFixedSize(24, 24)
        close.setToolTip('关闭提示')
        close.clicked.connect(lambda: self.dismiss())
        heading.addWidget(close)
        layout.addLayout(heading)
        layout.addWidget(QLabel('点击查看更新说明并选择安装'))
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
        parent.installEventFilter(self)

    def show_offer(self, offer):
        was_visible = self.isVisible()
        self._motion.stop()
        self._leaving = False
        self.title.setText('发现新版本 v' + offer['version'])
        self.setFixedWidth(min(360, max(240, self.parentWidget().width() - 40)))
        self.adjustSize()
        self._progress = self._progress if was_visible else 0.0
        if not motion.enabled():
            self._progress = 1.0
        self.setWindowOpacity(self._progress)
        self.reposition()
        self.show()
        self.raise_()
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
            self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(theme.ELEVATED))
        painter.setPen(QColor(131, 131, 145, 80))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                theme.RADIUS_MD, theme.RADIUS_MD)

    def reposition(self):
        parent = self.parentWidget()
        offset = round(-24 * (1 - self._progress)) if motion.enabled() else 0
        self.move(parent.mapToGlobal(QPoint(max(0, parent.width() - self.width() - 20), 20 + offset)))

    def eventFilter(self, watched, event):
        if self.isVisible():
            if event.type() in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange):
                self.reposition()
            elif event.type() == QEvent.Hide:
                self.dismiss(animate=False)
        return False

    def dismiss(self, animate=True):
        self.timer.stop()
        if (animate and self.isVisible() and self.parentWidget().isVisible()
                and not getattr(self.parentWidget(), '_closing', False) and motion.enabled()):
            self._leaving = True
            self._animate_to(0.0, 180)
        else:
            self._motion.stop()
            self.hide()

    def _open(self):
        self.dismiss(animate=False)
        self.activated.emit()


class ResultNotice(UpdateNotice):
    """复用悬浮提醒；操作结果全程不透明，三秒后自动收起。"""
    def __init__(self, parent):
        super().__init__(parent)
        self.layout().itemAt(1).widget().hide()
        self.action.hide()
        self.title.setWordWrap(True)
        self.timer.setInterval(3000)
        self.avatar_strip = QWidget(self)
        self.avatar_layout = QHBoxLayout(self.avatar_strip)
        self.avatar_layout.setContentsMargins(0, 0, 0, 0)
        self.avatar_layout.setSpacing(4)
        self.layout().itemAt(0).layout().insertWidget(0, self.avatar_strip)
        self._avatars = {}
        self.avatar_strip.hide()

    def _set_rooms(self, rooms):
        from .images import load_cached_avatar, load_room_avatar
        from .widgets import Avatar
        while self.avatar_layout.count():
            widget = self.avatar_layout.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self._avatars.clear()
        for index, room in enumerate(rooms[:3]):
            room_id = str(room.get("room_id", ""))
            avatar = Avatar(str(room.get("uname") or "?"), index, size=28)
            pixmap = load_cached_avatar(room.get("face")) if room.get("face") else None
            if pixmap is None:
                pixmap = load_room_avatar(room_id)
            if pixmap is not None:
                avatar.set_pixmap_image(pixmap)
            self.avatar_layout.addWidget(avatar)
            self._avatars[room_id] = avatar
        self.avatar_strip.setVisible(bool(self._avatars))

    def set_room_avatar(self, room_id, pixmap):
        avatar = self._avatars.get(str(room_id))
        if avatar is not None:
            avatar.set_pixmap_image(pixmap)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(theme.TILE_BG))
        painter.setPen(QColor(131, 131, 145, 80))
        radius = self.height() / 2
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                radius, radius)

    def show_message(self, message, rooms=()):
        self._motion.stop()
        self._leaving = False
        self.title.setText(message)
        self._set_rooms(rooms)
        self.setFixedWidth(min(360, max(240, self.parentWidget().width() - 40)))
        self.adjustSize()
        self._progress = self._progress if self.isVisible() else 0.0
        if not motion.enabled():
            self._progress = 1.0
        self.reposition()
        self.show()
        self.raise_()
        self.timer.start()
        if self._progress < 1.0:
            self._animate_to(1.0, 160)

    def _motion_frame(self, value):
        self._progress = value
        self.reposition()

    def reposition(self):
        parent = self.parentWidget()
        offset = round(-12 * (1 - self._progress)) if motion.enabled() else 0
        self.move(parent.mapToGlobal(QPoint(max(0, (parent.width() - self.width()) // 2),
                                           20 + offset)))


def show_result(parent, message, rooms=()):
    if not parent.isVisible():
        return
    notice = getattr(parent, '_result_notice', None)
    if notice is None:
        notice = parent._result_notice = ResultNotice(parent)
    notice.show_message(message, rooms)
