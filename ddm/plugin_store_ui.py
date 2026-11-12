"""Plugin catalog browsing, details and install/update actions."""
from pathlib import Path
import tempfile
import time
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QTextBrowser, QVBoxLayout, QWidget
from . import config, online, plugin_updates, theme, version
from .ui import SettingsSurface, ActionButton, AnimatedDialog, ElidedLabel, page_header
from .update_notice import set_update_dot
from .update_offers import plugin_update_offers
from .online_tasks import OnlinePage


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
        self.cards = QGridLayout()
        self.cards.setHorizontalSpacing(12)
        self.cards.setVerticalSpacing(12)
        self.cards.setColumnStretch(0, 1)
        self.cards.setColumnStretch(1, 1)
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
        for index, offer in enumerate(visible):
            self.cards.addWidget(self._offer_cards[offer['id']], index // 2, index % 2)
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
        from .online_ui import show_result
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
