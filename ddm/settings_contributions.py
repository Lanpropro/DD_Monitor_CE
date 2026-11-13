"""Frame legacy general-page contributions without replacing plugin controls."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QCheckBox, QSizePolicy

from .settings_layout import SettingsSection


class GeneralContributions(QObject):
    def __init__(self, page, grid):
        super().__init__(page)
        self.grid = grid
        self.card = None
        page.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.LayoutRequest, QEvent.Show):
            self.collect()
        return False

    def collect(self):
        page = self.parent()
        anchor = page._checks['sidebar_platform_logos']
        entries = []
        for index in range(self.grid.count() - 1, -1, -1):
            item = self.grid.itemAt(index)
            if item.widget() not in (anchor, page.sections):
                position = self.grid.getItemPosition(index)
                entries.append((*position, self.grid.takeAt(index)))
        if not entries:
            return
        if self.card is None:
            self.card = SettingsSection('平台显示与插件扩展')
            self.card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
            sections = page.sections
            sections.entries.insert(3, ('extensions', self.card, False))
            sections._arrange()
            self.card.show()
        # Preserve row/column relationships inside each legacy injection batch.
        first_row = min(entry[0] for entry in entries)
        start = self.card.grid.rowCount() if self.card.grid.count() else 0
        for row, column, rows, columns, item in sorted(entries, key=lambda entry: entry[:2]):
            widget, layout = item.widget(), item.layout()
            if widget is not None:
                hidden = widget.isHidden() and widget.testAttribute(Qt.WA_WState_ExplicitShowHide)
                self.card.grid.addWidget(widget, start + row - first_row, column, rows, columns, item.alignment())
                if not hidden:
                    widget.show()
            elif layout is not None:
                layout.setParent(None)
                self.card.grid.addLayout(layout, start + row - first_row, column, rows, columns)
            else:
                self.card.grid.addItem(item, start + row - first_row, column, rows, columns)
        page.sections.refresh_section('extensions')

    def checks(self):
        self.collect()
        if self.card is None:
            return {}
        return {check.objectName(): check for check in self.card.findChildren(QCheckBox)
                if check.objectName()}
