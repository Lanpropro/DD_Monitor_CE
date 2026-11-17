"""Hidden contribution anchor for general controls owned by the settings worker."""
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from .settings_contributions import GeneralContributions
from .settings_layout import SettingsColumns


class HostedGeneralPage(QWidget):
    def __init__(self, settings):
        super().__init__()
        self.setObjectName('SettingsPage')
        layout = QVBoxLayout(self)
        # Released plugins find their insertion grid at layout item 1.
        layout.addLayout(QHBoxLayout())
        grid = QGridLayout()
        layout.addLayout(grid)
        self.sections = SettingsColumns(self)
        grid.addWidget(self.sections, 0, 0, 1, 2)
        anchor = QCheckBox('显示关注栏平台 Logo', self)
        anchor.setChecked(bool(settings.get('sidebar_platform_logos', True)))
        anchor.hide()
        grid.addWidget(anchor, 1, 0, 1, 2)
        self._checks = {'sidebar_platform_logos': anchor}
        self.contributions = GeneralContributions(self, grid)

    def plugin_controls(self):
        return self.contributions.checks()

    def values(self):
        # All other general values come from SettingsDialog's initial snapshot
        # and the worker's acknowledged changes, never a second set of editors.
        return {'sidebar_platform_logos': self._checks['sidebar_platform_logos'].isChecked()}
