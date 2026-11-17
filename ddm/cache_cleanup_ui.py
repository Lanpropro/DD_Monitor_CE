"""Selectable additional caches; the existing avatar/cover chart stays independent."""
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from . import cache_cleanup, config
from .cache_settings import _Task, _forget_task, _live_tasks, size_text
from .settings_layout import SettingsSection
from .ui import ActionButton, HintLabel


ITEMS = (
    ('emoticons', '弹幕表情', '清理磁盘中的表情图片；再次出现时下载。已显示的表情可能仍在内存中。'),
    ('sc-avatars', 'SC 头像', '清理醒目留言头像；再次需要时下载，不影响关注列表头像。'),
    ('banners', '直播间横幅', '清理空间横幅和房间背景图片；再次加载时下载，离线时可能暂缺背景。'),
    ('plugin-catalog', '插件商店目录', '清理商店列表和更新记录缓存；刷新商店后重建，不卸载插件。离线列表将暂不可用。'),
    ('web-login', '网页登录 HTTP 缓存', '安排在下次打开网页登录时清理；不自动打开登录页，不清除 Cookie、账号或登录资料。'),
    ('logs', '历史日志与崩溃转储', '仅清理今天以前且未占用的本体记录。保留当前日志和进行中的诊断；清理后无法追溯对应的旧问题。'),
)


class ExtraCachePanel(SettingsSection):
    def __init__(self, parent=None, *, root=None):
        super().__init__('其他缓存与历史日志', parent)
        self.root = root or config.data_root()
        self._task = None
        self.values = {kind: dict(bytes=0, files=0) for kind in cache_cleanup.KINDS}
        self.checks, self.details = {}, {}
        for row, (kind, title, hint) in enumerate(ITEMS):
            item = QWidget()
            item.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            box = QVBoxLayout(item)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(5)
            heading = QHBoxLayout()
            check = QCheckBox(title)
            check.setAccessibleName('选择清理' + title)
            check.toggled.connect(self._selection_changed)
            heading.addWidget(check)
            heading.addStretch(1)
            box.addLayout(heading)
            detail = HintLabel('尚未统计')
            box.addWidget(detail)
            box.addWidget(HintLabel(hint))
            self.checks[kind], self.details[kind] = check, detail
            self.grid.addWidget(item, row, 0, 1, 2)
        buttons = QHBoxLayout()
        self.selected_button = ActionButton('清理所选')
        self.selected_button.clicked.connect(self.clear_selected)
        buttons.addWidget(self.selected_button)
        self.refresh_button = ActionButton('刷新统计')
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        self.grid.addLayout(buttons, len(ITEMS), 0, 1, 2)
        self.status = HintLabel('请选择要清理的类别。配置、账号、录制、插件升级备份不在清理范围内。')
        self.grid.addWidget(self.status, len(ITEMS) + 1, 0, 1, 2)
        self._selection_changed()

    def selected(self):
        return {kind for kind, check in self.checks.items() if check.isChecked()}

    def _selection_changed(self):
        selected = self.selected()
        size = sum(self.values[kind]['bytes'] for kind in selected)
        files = sum(self.values[kind]['files'] for kind in selected)
        self.selected_button.setText('清理所选' + (f' · {size_text(size)}' if files else ''))
        self.selected_button.setEnabled(self._task is None and bool(files or 'web-login' in selected))
        self.refresh_button.setEnabled(self._task is None)
        for check in self.checks.values():
            check.setEnabled(self._task is None)

    def _start(self, operation, message):
        if self._task is not None:
            return
        self.status.setText(message)
        self._task = _Task(operation)
        self._task.signals.completed.connect(self._completed)
        self._task.signals.failed.connect(self._failed)
        _live_tasks.add(self._task)
        self._task.signals.finished.connect(lambda task=self._task: _forget_task(task))
        self._selection_changed()
        QThreadPool.globalInstance().start(self._task)

    def refresh(self):
        root = self.root
        self._start(lambda: (None, cache_cleanup.usage(root)), '正在统计其他缓存和历史日志…')

    def clear_selected(self):
        selected, root = self.selected(), self.root
        if selected:
            def operation():
                return cache_cleanup.clear(root, selected), cache_cleanup.usage(root)
            self._start(operation, '正在清理所选缓存…')

    def _completed(self, payload):
        result, self.values = payload
        self._task = None
        for kind, value in self.values.items():
            pending = ' · 已安排下次网页登录时清理' if value.get('pending') else ''
            self.details[kind].setText(f"{size_text(value['bytes'])} · {value['files']} 个文件" + pending)
        if result is not None:
            message = (f"已释放 {size_text(result['bytes'])}，清理 {result['files']} 个文件，"
                       f"跳过 {result['skipped']} 个在用或不可清理文件。")
            if result['deferred']:
                message += ' 网页登录 HTTP 缓存已安排在下次打开网页登录时清理。'
            self.status.setText(message)
        else:
            self.status.setText('统计完成。日志仅统计今天以前的本体历史记录；清理时跳过占用文件。')
        self._selection_changed()

    def _failed(self, message):
        self._task = None
        self.status.setText('缓存操作未完成：' + message)
        self._selection_changed()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
