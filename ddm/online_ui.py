"""插件商店和软件更新页面；联网、下载和解压都在工作线程执行。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRectF, QThread, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea, QStyledItemDelegate, QTextBrowser, QVBoxLayout, QWidget

from .corner_geometry import continuous_path
from . import config, motion, online, plugin_updates, theme, update_install, version
from .ui import SettingsSurface, ActionButton, AnimatedDialog, ElidedLabel, page_header
from .update_version import installed_revision, release_label


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


def plugin_update_offers(manager, offers):
    installed = {entry['id']: entry for entry in manager.catalog()} if manager else {}
    pending = plugin_updates.pending_versions(manager) if manager else {}
    result = []
    for offer in offers:
        existing = installed.get(offer['id'])
        if not existing or offer['id'] in pending or not offer.get('available'):
            continue
        try:
            newer = online.version_key(offer['version']) > online.version_key(existing['version'])
        except (ValueError, KeyError):
            newer = False
        if newer:
            result.append(offer)
    return result


def plugin_update_notes(manager, offers):
    return {offer['id']: '更新日志 · v' + offer['version'] + '\n' +
            (offer.get('notes') or '暂无更新日志')
            for offer in plugin_update_offers(manager, offers)}


_retired_online_tasks = set()


def _release_online_task(task):
    if task not in _retired_online_tasks:
        return
    _retired_online_tasks.remove(task)
    if task.result_cleanup is not None:
        task.result_cleanup(task.result)
    task.deleteLater()


def _wait_online_tasks_on_exit():
    # Only final application exit waits; closing a settings page never does.
    for task in tuple(_retired_online_tasks):
        task.wait()
        _release_online_task(task)


class OnlineTask(QThread):
    succeeded = Signal(object)
    failed = Signal(object)
    progress = Signal(int)

    def __init__(self, operation, callback, parent):
        super().__init__(parent)
        self.operation = operation
        self.callback = callback
        self.result = None
        self.result_cleanup = None

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

    def start(self, operation, callback, *, key=None):
        if self.stopping or (self.jobs and (key is None or any(
                task.key in (None, key) for task in self.jobs))):
            return
        task = OnlineTask(operation, callback, self)
        task.key = key
        task.percent = 0
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
        if self.stopping:
            return
        task = self.sender()
        if task in self.jobs:
            self.jobs.remove(task)
        task.deleteLater()
        self.busyChanged.emit(bool(self.jobs))

    def stop(self, result_cleanup=None):
        self.stopping = True
        app = QApplication.instance()
        if not getattr(app, '_online_task_cleanup_connected', False):
            app.aboutToQuit.connect(_wait_online_tasks_on_exit)
            app._online_task_cleanup_connected = True
        tasks, self.jobs = self.jobs, []
        for task in tasks:
            task.requestInterruption()
            task.succeeded.disconnect(self._succeeded)
            task.failed.disconnect(self._failed)
            task.progress.disconnect(self._progress)
            task.finished.disconnect(self._finished)
            task.callback = None
            task.result_cleanup = result_cleanup
            task.setParent(None)
            _retired_online_tasks.add(task)
            task.finished.connect(lambda t=task: _release_online_task(t))
            if not task.isRunning():
                _release_online_task(task)


class PluginBrowserToolbar(QWidget):
    def __init__(self, parent, states):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.search_row = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('搜索插件名称、功能或作者')
        self.search.setAccessibleName('搜索插件')
        self.search.setClearButtonEnabled(True)
        self.search_row.addWidget(self.search, 1)
        layout.addLayout(self.search_row)
        filters = QHBoxLayout()
        self.filter = QComboBox(self)
        self.filter.addItems(states)
        self.filter.setAccessibleName('按状态筛选插件')
        filters.addWidget(self.filter)
        self.sort = QComboBox(self)
        self.sort.addItems(('默认排序', '名称排序', '更新优先'))
        self.sort.setAccessibleName('插件排序')
        filters.addWidget(self.sort)
        filters.addStretch()
        self.count = QLabel(self)
        self.count.setObjectName('SettingsHint')
        filters.addWidget(self.count)
        layout.addLayout(filters)


class PluginDetailsDialog(AnimatedDialog):
    def __init__(self, page, offer, *, installed_entry=None):
        super().__init__(page.window())
        self.page, self.plugin_id = page, offer['id']
        self.offer = dict(offer)
        self.installed_entry = installed_entry
        self.setWindowTitle('插件详情')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(560, 440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        author = str(offer.get('author') or '').strip().lstrip('@')
        entry = installed_entry if installed_entry is not None else offer
        subtitle = 'v' + str(entry.get('version') or '—') + (' · @' + author if author else '')
        layout.addLayout(page_header(entry['name'], subtitle))
        self.document = QTextBrowser(self)
        self.document.setObjectName('UpdateNotes')
        self.document.setOpenExternalLinks(False)
        parts = [entry.get('description') or '暂无说明']
        if installed_entry is not None:
            parts.extend(('插件 ID：' + entry['id'], '状态：' + entry.get('status', ''),
                          '本次选择：' + ('启用' if entry['enabled'] else '禁用') + '（保存后生效）'))
            if entry.get('reason'):
                parts.append(entry['reason'])
        if offer.get('min_app_version'):
            parts.append('需要主程序版本：' + offer['min_app_version'] + ' 或更高')
        if offer.get('reason'):
            parts.append(offer['reason'])
        parts.extend(('更新日志 · v' + str(offer.get('version') or '—'),
                      offer.get('notes') or '暂无更新日志'))
        self.document.setPlainText('\n\n'.join(parts))
        layout.addWidget(self.document, 1)
        footer = QHBoxLayout()
        close = ActionButton('关闭', self)
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        footer.addStretch()
        self.action = ActionButton(parent=self)
        self.action.setAutoDefault(False)
        self.action.clicked.connect(self.install)
        footer.addWidget(self.action)
        layout.addLayout(footer)
        store = page.store_page if installed_entry is not None else page
        store.controlsChanged.connect(self.refresh_action)
        if installed_entry is not None:
            page.changed.connect(self.refresh_action)
        self.refresh_action()

    def refresh_action(self):
        store = self.page.store_page if self.installed_entry is not None else self.page
        buttons = self.page.update_buttons if self.installed_entry is not None else store.buttons
        button = buttons.get(self.plugin_id)
        if self.installed_entry is not None and (button is None or button.isHidden()):
            self.action.setText('暂无更新' if self.plugin_id in self.page.checks else '插件已删除')
            self.action.setEnabled(False)
            return
        current = next((offer for offer in store._display_offers if offer['id'] == self.plugin_id), {})
        if any(current.get(key) != self.offer.get(key) for key in ('version', 'sha256', 'url')):
            self.action.setText('目录已更新')
            self.action.setEnabled(False)
            self.action.setToolTip('请关闭并重新打开详情，查看最新版本')
            return
        self.action.setText(button.text() if button else '暂不可安装')
        self.action.setEnabled(bool(button and button.isEnabled() and not store.stopping))

    def install(self):
        buttons = self.page.update_buttons if self.installed_entry is not None else self.page.buttons
        button = buttons.get(self.plugin_id)
        if button is not None:
            button.click()


class PluginStorePage(OnlinePage):
    installed = Signal(str)
    offersChanged = Signal(object)
    controlsChanged = Signal()

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.offers = []
        self.buttons = {}
        self._offer_cards = {}
        self._display_offers = []
        self._installed_ids = set()
        self._update_ids = set()
        self.seen_versions = {}
        self.cache_path = Path(config.data_root()) / 'cache' / 'plugin-catalog.json'
        self._checked_at = 0
        self._opened = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 4, 8)
        self.refresh = QPushButton('刷新插件商店')
        self.refresh.setObjectName('IconButton')
        self.refresh.clicked.connect(lambda: self.refresh_catalog(force=True))
        self.browser = PluginBrowserToolbar(self, ('全部插件', '未安装', '已安装', '可更新'))
        self.search, self.filter, self.sort, self.count = (
            self.browser.search, self.browser.filter, self.browser.sort, self.browser.count)
        self.browser.search_row.addWidget(self.refresh)
        layout.addWidget(self.browser)
        layout.addWidget(self.status)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName('PluginScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 4, 12)
        self.cards = QVBoxLayout()
        self.cards.setSpacing(6)
        content_layout.addLayout(self.cards)
        self.empty = QLabel('没有符合条件的插件，请尝试其他关键词或筛选条件。', content)
        self.empty.setObjectName('SettingsHint')
        self.empty.setWordWrap(True)
        content_layout.addWidget(self.empty)
        content_layout.addStretch(1)
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)
        self.search.textChanged.connect(self._filter_offers)
        self.filter.currentIndexChanged.connect(self._filter_offers)
        self.sort.currentIndexChanged.connect(self._filter_offers)
        self._filter_offers()
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
        force = not self._opened
        self._opened = True
        if not force and self.offers and 0 <= time.time() - self._checked_at < online.CATALOG_CHECK_SECONDS:
            return
        self.refresh_catalog(force=force)

    def _busy(self, busy):
        self.refresh.setEnabled(not busy)
        reading = any(task.key is None for task in self.jobs)
        running = {task.key: task for task in self.jobs}
        for plugin_id, button in self.buttons.items():
            task = running.get(plugin_id)
            button.setEnabled(bool(button.property('storeEnabled')) and not reading and task is None)
            button.setText(('校验/解压中' if task.percent >= 100 else f'下载 {task.percent}%')
                           if task else button.property('storeText'))
        self.controlsChanged.emit()

    def _progress(self, percent):
        if self.stopping:
            return
        task = self.sender()
        task.percent = percent
        self._busy(bool(self.jobs))
        self.status.setText(f'正在并行安装 {len(self.jobs)} 个插件…' if len(self.jobs) > 1
                            else '正在下载、校验和解压插件…')

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
        self.status.setText('暂时无法查询最新版本，显示已缓存的官方插件目录。' if any(
            offer.get('cached') for offer in offers) else '选择插件即可下载安装，重启后启用。')
        self.offersChanged.emit(self.offers)

    def show_offers(self, offers):
        while self.cards.count():
            self.cards.takeAt(0)
        for card in self._offer_cards.values():
            card.deleteLater()
        self.buttons = {}
        self._offer_cards = {}
        self._display_offers = [dict(offer) for offer in offers]
        installed = {entry['id']: entry for entry in self.manager.catalog()} if self.manager else {}
        self._installed_ids = set(installed)
        pending = plugin_updates.pending_versions(self.manager) if self.manager else {}
        self._update_ids = {offer['id'] for offer in plugin_update_offers(self.manager, offers)}
        for offer in offers:
            card = SettingsSurface()
            card.setObjectName('PluginCard')
            body = QHBoxLayout(card)
            body.setContentsMargins(14, 10, 14, 10)
            body.setSpacing(12)
            summary = QVBoxLayout()
            summary.setSpacing(4)
            body.addLayout(summary, 1)
            title = ElidedLabel(offer['name'] + ('  v' + offer['version'] if offer['version'] else ''))
            title.setObjectName('PluginName')
            title.setTextFormat(Qt.PlainText)
            title.setToolTip(offer['name'])
            summary.addWidget(title)
            button = QPushButton('安装')
            button.setObjectName('IconButton')
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance('校验/解压中') + 28)
            description = ElidedLabel(' '.join(str(offer.get('description') or '暂无说明').split()), card)
            description.setObjectName('SettingsHint')
            description.setTextFormat(Qt.PlainText)
            description.setToolTip(offer.get('description') or '暂无说明')
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
            button.setProperty('storeText', button.text())
            button.setProperty('storeEnabled', allowed)
            button.setEnabled(allowed and not self.jobs)
            button.clicked.connect(lambda _checked=False, entry=offer: self.install_offer(entry))
            self.buttons[offer['id']] = button
            summary.addWidget(description)
            hint = ElidedLabel(note or ' ', card)
            hint.setObjectName('SettingsHint')
            hint.setTextFormat(Qt.PlainText)
            hint.setToolTip(note)
            footer = QHBoxLayout()
            details = ActionButton('详情', card)
            details.setObjectName('PluginDetailsButton')
            details.setAccessibleName('查看 ' + offer['name'] + ' 的详情')
            details.clicked.connect(lambda _checked=False, entry=offer: self.show_details(entry))
            footer.addWidget(hint, 1)
            author = str(offer.get('author') or '').strip().lstrip('@')
            if author:
                credit = ElidedLabel('@' + author, card)
                credit.setObjectName('PluginAuthor')
                credit.setTextFormat(Qt.PlainText)
                credit.setToolTip('@' + author)
                credit.setAccessibleName('GitHub 作者：' + author)
                credit.setStyleSheet(f'color: {theme.TEXT3}; font-size: {theme.FONT_CAPTION}px;')
                footer.addWidget(credit, 0, Qt.AlignRight | Qt.AlignBottom)
            summary.addLayout(footer)
            actions = QVBoxLayout()
            actions.setSpacing(2)
            actions.addWidget(button)
            actions.addWidget(details)
            body.addLayout(actions)
            self._offer_cards[offer['id']] = card
            self.cards.addWidget(card)
        self._filter_offers()
        self.update_dots()

    def _filter_offers(self, *_args, reset_scroll=True):
        terms = self.search.text().casefold().split()
        scope = self.filter.currentIndex()
        visible = []
        for offer in self._display_offers:
            plugin_id = offer['id']
            text = ' '.join(str(offer.get(key) or '') for key in ('name', 'id', 'description', 'author')).casefold()
            matches = all(term in text for term in terms)
            matches = matches and (scope == 0 or (scope == 1 and plugin_id not in self._installed_ids)
                or (scope == 2 and plugin_id in self._installed_ids)
                or (scope == 3 and plugin_id in self._update_ids))
            self._offer_cards[plugin_id].setVisible(matches)
            if matches:
                visible.append(offer)
        if self.sort.currentIndex() == 1:
            visible.sort(key=lambda offer: (offer['name'].casefold(), offer['id']))
        elif self.sort.currentIndex() == 2:
            visible.sort(key=lambda offer: (offer['id'] not in self._update_ids, offer['name'].casefold(), offer['id']))
        position = self.scroll.verticalScrollBar().value()
        while self.cards.count():
            self.cards.takeAt(0)
        for offer in visible:
            self.cards.addWidget(self._offer_cards[offer['id']])
        self.count.setText(f'{len(visible)} / {len(self._display_offers)} 个插件')
        self.empty.setVisible(not visible)
        self.scroll.verticalScrollBar().setValue(0 if reset_scroll else position)

    def show_details(self, offer):
        dialog = PluginDetailsDialog(self, offer)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.open()
        return dialog

    def update_dots(self):
        unread = {offer['id'] for offer in plugin_update_offers(self.manager, self.offers)
                  if self.seen_versions.get(offer['id']) != offer['version']}
        for plugin_id, button in self.buttons.items():
            set_update_dot(button, plugin_id in unread)
        self._busy(bool(self.jobs))

    def install_offer(self, offer):
        if (not self.manager or not offer.get('available') or self.stopping
                or any(task.key in (None, offer['id']) for task in self.jobs)):
            return
        button = self.buttons.get(offer['id'])
        if button is not None and button.hasFocus():
            button.clearFocus()  # Disabling a focused button otherwise scrolls to the next card.
        self.status.setText('正在下载安装包…')
        def install(cancelled, progress):
            with tempfile.TemporaryDirectory(prefix='ddm-plugin-download-') as temporary, online.session() as client:
                archive = online.download(offer, Path(temporary) / 'plugin.zip', client, cancelled, progress)
                if cancelled():
                    raise InterruptedError('安装已取消')
                new = offer['id'] not in {entry['id'] for entry in self.manager.catalog()}
                return plugin_updates.install(self.manager, archive, offer), new
        self.start(install, self._installed, key=offer['id'])

    def _installed(self, result):
        plugin_id, new = result
        self._installed_ids.add(plugin_id)
        self._update_ids.discard(plugin_id)
        if new and self.manager.enabled is not None:
            self.manager.enabled.add(plugin_id)
            self.manager.save_plugin_settings()
        self.installed.emit(plugin_id)
        button = self.buttons.get(plugin_id)
        if button is not None:
            button.setProperty('storeText', '已安装' if new else '待重启')
            button.setProperty('storeEnabled', False)
        self.update_dots()  # Keep the cards and their scroll position while changing the completed action.
        self._filter_offers(reset_scroll=False)
        self.offersChanged.emit(self.offers)
        self.status.setText('安装包已校验，保存并重启后生效。')
        show_result(self.window(), '插件已安装，保存并重启后生效')


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


class ResultNotice(UpdateNotice):
    """顶部通知卡片：不抢焦点，按提示类型自动收起。"""
    def __init__(self, parent):
        super().__init__(parent)
        from .room_artwork import RoomArtwork
        self.artwork = RoomArtwork(())
        theme.signals().changed.connect(self._refresh_artwork_theme)
        self.platform_layout = QHBoxLayout()
        self.platform_layout.setContentsMargins(0, 0, 0, 0)
        self.platform_layout.setSpacing(4)
        self.text_column.layout().removeWidget(self.category)
        self.text_column.layout().insertLayout(0, self.platform_layout)
        self.description.hide()
        self.action.hide()
        self.timer.setInterval(3000)
        self.avatar_strip = QWidget(self)
        self.avatar_layout = QHBoxLayout(self.avatar_strip)
        self.avatar_layout.setContentsMargins(0, 0, 0, 0)
        self.avatar_layout.setSpacing(4)
        self.heading.insertWidget(0, self.avatar_strip, 0, Qt.AlignTop)
        self._avatars = {}
        self.avatar_strip.hide()
        self._on_click = None
        self._file_path = ''
        self._file_message = ''

    def _open_file_location(self):
        path = Path(self._file_path)
        if sys.platform == 'win32' and path.is_file():
            try:
                subprocess.Popen(['explorer.exe', '/select,', str(path)])
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def contextMenuEvent(self, event):
        if not self._file_path:
            return super().contextMenuEvent(event)
        menu = QMenu(self)
        menu.addAction('打开文件位置', self._open_file_location)
        menu.addAction('复制完整路径', lambda _checked=False, path=self._file_path:
                       QApplication.clipboard().setText(path))
        active = self.timer.isActive()
        self.timer.stop()
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()
            if active and self.isVisible():
                self.timer.start()
        event.accept()

    def _open(self):
        callback = self._on_click
        self.dismiss(animate=False, handled=True)
        if callback is not None:
            callback()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._open()
            event.accept()
            return
        QFrame.mouseReleaseEvent(self, event)

    def hideEvent(self, event):
        super().hideEvent(event)
        if getattr(self.parentWidget(), '_result_notice', None) is self:
            self.parentWidget()._result_notice = None
        self.deleteLater()

    def _set_rooms(self, rooms):
        from .images import load_cached_avatar, load_room_avatar
        from .avatar_widgets import Avatar
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
        count = self.avatar_layout.count()
        self.avatar_strip.setFixedWidth(count * 28 + max(0, count - 1) * self.avatar_layout.spacing())
        self.avatar_strip.setVisible(bool(self._avatars))
        from .room_artwork import RoomArtwork, add_platform_logos, style_room_notice
        self.artwork = RoomArtwork(rooms)
        while self.platform_layout.count():
            widget = self.platform_layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                if widget is not self.category:
                    widget.deleteLater()
        add_platform_logos(self.platform_layout, rooms, self.text_column)
        self.platform_layout.addWidget(self.category)
        self.category.show()
        self.platform_layout.addStretch()
        style_room_notice(self, self.artwork)

    def set_room_artwork(self, room_id, pixmap, kind):
        from .room_artwork import style_room_notice
        if self.artwork.set_image(room_id, pixmap, kind):
            style_room_notice(self, self.artwork)

    def _refresh_artwork_theme(self, _mode):
        from .room_artwork import style_room_notice
        style_room_notice(self, self.artwork)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.artwork.source is not None:
            from .room_artwork import paint_room_background, notice_frost
            painter = QPainter(self)
            paint_room_background(painter, self.rect(), self.artwork.source, theme.RADIUS_LG,
                                  focus=self.artwork.banner is None, frost=notice_frost(self, self.artwork))

    def set_room_avatar(self, room_id, pixmap):
        avatar = self._avatars.get(str(room_id))
        if avatar is not None:
            avatar.set_pixmap_image(pixmap)

    def show_message(self, message, rooms=(), *, kind='info', on_click=None, persistent=False,
                     file_path=None, pending=False):
        from .notification_center import live_notice_action
        self._file_path = str(file_path or '')
        self._file_message = message + Path(self._file_path).name if self._file_path else message
        self._on_click = None if pending else self._open_file_location if self._file_path else on_click
        self.setCursor(Qt.PointingHandCursor if self._on_click else Qt.ArrowCursor)
        self.setToolTip(self._file_path if pending else
                        self._file_path + '\n点击打开文件位置；右键复制完整路径' if self._file_path
                        else ('点击跳转' if on_click else ''))
        self._close_timer.stop()
        self._motion.stop()
        self._leaving = False
        self.title.setWordWrap(not bool(self._file_path))
        self.title.setText(self._file_message)
        self.category.setText(('正在导出' if pending else '导出失败' if kind == 'warning' else '已完成') if self._file_path else
                              {'live': '开播提醒', 'warning': '需要留意'}.get(kind, '操作提示'))
        self.action.setVisible(pending or self._on_click is not None)
        self.action.setEnabled(not pending)
        self.action.setText('正在导出…' if pending else '打开文件位置' if self._file_path else
                            (live_notice_action(self.parentWidget()) if kind == 'live' else
                             ('前往登录' if '登录' in message else '查看详情')))
        self._set_rooms(rooms)
        symbol, colour = {'live': ('●', theme.PINK),
                          'warning': ('!', '#e8b86d')}.get(kind, ('i', theme.ACCENT))
        self.indicator.setText(symbol)
        self.indicator.setStyleSheet('color: ' + colour + '; font-weight: 600;')
        self.indicator.setVisible(not bool(self._avatars))
        self.timer.setInterval({'live': 5000, 'warning': 6000}.get(kind, 3000))
        self._resize_to_content()
        self._progress = self._progress if self.isVisible() else 0.0
        if not motion.enabled():
            self._progress = 1.0
        self.reposition()
        self.show()
        self.raise_()
        self.timer.stop()
        if not persistent:
            self.timer.start()
        if self._progress < 1.0:
            self._animate_to(1.0, 160)

    def _resize_to_content(self):
        super()._resize_to_content()
        if self._file_path:
            self.title.setText(self.title.fontMetrics().elidedText(
                self._file_message, Qt.ElideMiddle, self.title.width()))
            super()._resize_to_content()

    def _motion_frame(self, value):
        self._progress = value
        self.reposition()

    def reposition(self):
        parent = self.parentWidget()
        offset = round(-12 * (1 - self._progress)) if motion.enabled() else 0
        self.move(parent.mapToGlobal(QPoint(self._left_x() + offset, self._stack_y())))


def _notifications_hidden(parent):
    settings = getattr(parent, 'settings', {})
    return bool(not settings.get('notifications_enabled', True)
                or (settings.get('notice_hide_fullscreen', False)
                    and (getattr(parent, '_fullscreen_tile', None) is not None or parent.isFullScreen())))


def show_result(parent, message, rooms=(), *, kind='info', on_click=None, persistent=False,
                file_path=None, notice_key=None, pending=False):
    from .notification_center import remember_result
    if getattr(parent, '_closing', False):
        return
    record = remember_result(parent, message, kind=kind, on_click=on_click, file_path=file_path,
                             rooms=rooms, notice_key=notice_key, pending=pending)
    if not parent.isVisible() or _notifications_hidden(parent):
        return
    notice = next((item for item in getattr(parent, '_notices', [])
                   if notice_key is not None and getattr(item, '_notice_key', None) == notice_key), None)
    if notice is None:
        notice = ResultNotice(parent)
    notice._notice_key = notice_key
    parent._result_notice = notice
    notice.track_history(record)
    notice.show_message(message, rooms, kind=kind, on_click=on_click,
                        persistent=persistent or pending, file_path=file_path, pending=pending)
