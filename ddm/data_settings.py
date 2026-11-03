"""Settings entry point for opening and relocating personal data."""
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import config, data_paths
from .cache_settings import ImageCachePanel
from .ui import ActionButton, HintLabel, TitleLabel


class DataSettingsPage(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('SettingsPage')
        self.target = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        title = TitleLabel('数据与存储')
        layout.addWidget(title)
        hint = HintLabel('配置、关注与布局、登录账号、用户插件、皮肤、缓存和日志保存在下方目录。录制文件使用录制设置中的保存位置。')
        layout.addWidget(hint)
        layout.addWidget(QLabel('当前数据目录'))
        self.path = QLabel(config.data_root())
        self.path.setWordWrap(True)
        self.path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.path)
        buttons = QHBoxLayout()
        self.open_button = ActionButton('打开数据目录')
        self.open_button.clicked.connect(self.open_folder)
        self.move_button = ActionButton('迁移数据目录…')
        self.move_button.clicked.connect(self.choose_target)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.move_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._idle_status = config.DATA_MIGRATION_ERROR or '选择空文件夹后，点击“保存并重启”迁移。软件会先保存并结束录制，再复制数据；原目录的文件保留，迁移失败时继续使用原目录。账号数据仅能由原 Windows 用户解密。'
        self.status = HintLabel(self._idle_status)
        layout.addWidget(self.status)
        self.image_cache = ImageCachePanel(self)
        layout.addWidget(self.image_cache)
        layout.addStretch(1)

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(config.data_root()))

    def cancel_target(self):
        self.target = None
        self.status.setText(self._idle_status)

    def set_target(self, target):
        try:
            self.target = data_paths.validate_target(config.data_root(), target, config.REPO)
        except (OSError, ValueError) as error:
            self.target = None
            self.status.setText(str(error))
            self.changed.emit()
            return False
        self.status.setText(f'重启后迁移至：{self.target}\n原文件保留；录制文件不会移动。')
        self.changed.emit()
        return True

    def choose_target(self):
        target = QFileDialog.getExistingDirectory(self, '选择空的数据文件夹', str(Path(config.data_root()).parent))
        if target:
            self.set_target(target)

    def prepare(self):
        if self.target is None:
            return True
        try:
            data_paths.schedule_migration(config.REPO, config.data_root(), self.target)
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return False
        return True
