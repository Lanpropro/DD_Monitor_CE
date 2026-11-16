"""Plugin catalog browsing, details and install/update actions."""
from pathlib import Path
import time
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from .plugin_card_layout import PluginCardLayout
from . import config, online, plugin_updates, theme, version
from .ui import SettingsSurface, DisclosureButton, ElidedLabel
from .update_notice import set_update_dot
from .update_offers import plugin_update_offers
from .online_tasks import OnlinePage
from .plugin_details_ui import PluginDetailsPanel

# Compatibility export; details are now embedded widgets.
PluginDetailsDialog = PluginDetailsPanel


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


class PluginStorePage(OnlinePage):
    installed = Signal(str)
    offersChanged = Signal(object)
    controlsChanged = Signal()

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        from .plugin_downloads import PluginDownloads
        self.downloads = PluginDownloads(manager, self)
        self._owns_downloads = True
        self.downloads.changed.connect(self._download_changed)
        self.downloads.installed.connect(self._installed)
        self._progress_widgets = {}
        self.offers = []
        self.buttons = {}
        self._offer_cards = {}
        self._detail_buttons = {}
        self._details = {}
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
        self.cards = PluginCardLayout()
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
        self.scroll.viewport().installEventFilter(self)
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
            button.setText(('校验/解压中' if task.percent >= 100 else '下载中…')
                           if task else button.property('storeText'))
            state = self.downloads.states.get(plugin_id)
            progress = self._progress_widgets.get(plugin_id)
            if state and progress:
                progress.set_state(state)
        self.controlsChanged.emit()

    @property
    def jobs(self):
        downloads = getattr(self, 'downloads', None)
        return self._jobs + downloads.jobs if downloads and downloads.jobs else self._jobs

    def set_downloads(self, downloads):
        self.downloads.changed.disconnect(self._download_changed)
        self.downloads.installed.disconnect(self._installed)
        self.downloads.deleteLater()
        self.downloads = downloads
        self._owns_downloads = False
        downloads.changed.connect(self._download_changed)
        downloads.installed.connect(self._installed)
        self._busy(bool(self.jobs))

    def _download_changed(self, plugin_id):
        if self.stopping:
            return
        self._busy(bool(self.jobs))
        self.busyChanged.emit(bool(self.jobs))
        state = self.downloads.states[plugin_id]
        if state['phase'] == 'failed':
            self.status.setText('下载失败：' + state['error'])

    def stop(self):
        if self.stopping:
            return
        self.downloads.changed.disconnect(self._download_changed)
        self.downloads.installed.disconnect(self._installed)
        if self._owns_downloads:
            self.downloads.stop()
        super().stop()

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
        expanded = [key for key, button in self._detail_buttons.items() if button.isChecked()]
        while self.cards.count():
            self.cards.takeAt(0)
        for card in self._offer_cards.values():
            card.deleteLater()
        self.buttons = {}
        self._progress_widgets = {}
        self._offer_cards = {}
        self._detail_buttons = {}
        self._details = {}
        self._display_offers = [dict(offer) for offer in offers]
        installed = {entry['id']: entry for entry in self.manager.catalog()} if self.manager else {}
        self._installed_ids = set(installed)
        pending = plugin_updates.pending_versions(self.manager) if self.manager else {}
        self._update_ids = {offer['id'] for offer in plugin_update_offers(self.manager, offers)}
        for offer in offers:
            card = SettingsSurface()
            card.setObjectName('PluginCard')
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            body = QVBoxLayout(card)
            body.setSizeConstraint(QLayout.SetMinimumSize)
            body.setAlignment(Qt.AlignTop)
            body.setContentsMargins(14, 10, 14, 10)
            body.setSpacing(12)
            summary = QVBoxLayout()
            summary.setSpacing(4)
            body.addLayout(summary)
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
                note = '新版本已下载，点击“重启以应用”后生效'
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
            details = DisclosureButton(card)
            details.setText('详情')
            details.setObjectName('PluginDetailsButton')
            details.setAccessibleName('查看 ' + offer['name'] + ' 的详情')
            details.toggled.connect(lambda checked, entry=offer: self._toggle_details(entry, checked))
            self._detail_buttons[offer['id']] = details
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
            from .update_progress_ui import UpdateProgress
            progress = UpdateProgress(card, button=button)
            self._progress_widgets[offer['id']] = progress
            actions = QHBoxLayout()
            actions.setSpacing(8)
            actions.addWidget(progress, 1)
            actions.addWidget(details)
            body.addLayout(actions)
            self._offer_cards[offer['id']] = card
            self.cards.addWidget(card)
        self._filter_offers()
        self.update_dots()
        for key in expanded:
            if key in self._detail_buttons:
                self._detail_buttons[key].setChecked(True)

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
        minimum = self.fontMetrics().horizontalAdvance('128.00 MB / 128.00 MB · 12.34 MB/s') + 220
        columns = 2 if self.scroll.viewport().width() >= minimum * 2 + self.cards.spacing() else 1
        self.cards.set_columns(columns)
        for offer in visible:
            self.cards.addWidget(self._offer_cards[offer['id']])
        self.count.setText(f'{len(visible)} / {len(self._display_offers)} 个插件')
        self.empty.setVisible(not visible)
        self.scroll.verticalScrollBar().setValue(0 if reset_scroll else position)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Resize:
            if event.size().width() != event.oldSize().width():
                self._filter_offers(reset_scroll=False)
        return super().eventFilter(watched, event)

    def show_details(self, offer):
        self._detail_buttons[offer['id']].setChecked(True)
        return self._details[offer['id']]

    def _toggle_details(self, offer, expanded):
        key = offer['id']
        button = self._detail_buttons[key]
        button.setText('收起' if expanded else '详情')
        if expanded and key not in self._details:
            card = self._offer_cards[key]
            panel = PluginDetailsPanel(self, offer, parent=card)
            panel.collapsed.connect(lambda: button.setChecked(False))
            card.layout().insertWidget(1, panel)
            self._details[key] = panel
        panel = self._details.get(key)
        if panel is not None:
            if expanded:
                panel.refresh_action()
            panel.setVisible(expanded)
            panel.updateGeometry()

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
        self.downloads.start(offer)

    def _installed(self, result):
        from .online_ui import show_result
        plugin_id, new = result
        self._installed_ids.add(plugin_id)
        self._update_ids.discard(plugin_id)
        self.installed.emit(plugin_id)
        button = self.buttons.get(plugin_id)
        if button is not None:
            button.setProperty('storeText', '已安装' if new else '待重启')
            button.setProperty('storeEnabled', False)
        self.update_dots()  # Keep the cards and their scroll position while changing the completed action.
        self._filter_offers(reset_scroll=False)
        self.offersChanged.emit(self.offers)
        self.status.setText('安装包已校验，点击“重启以应用”后生效。')
        show_result(self.window(), '插件已安装，点击“重启以应用”后生效')
