"""Responsive settings sections; pages keep ownership of controls and values."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from .ui import SettingsSurface


class SettingsSection(SettingsSurface):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName('SettingsSection')
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 18)
        box.setSpacing(14)
        heading = QLabel(title, self)
        heading.setObjectName('SettingsSectionTitle')
        box.addWidget(heading)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.grid.setColumnStretch(1, 1)
        box.addLayout(self.grid)
        box.addStretch(1)


class SettingsColumns(QWidget):
    """Use two columns when both cards have useful space, otherwise stack them."""
    BREAKPOINT = 760

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(16)
        self.entries = []
        self.columns = 0

    def add_section(self, key, widget, *, wide=False):
        self.entries.append((key, widget, wide))
        self._arrange()

    def section(self, key):
        return next(widget for name, widget, _wide in self.entries if name == key)

    def refresh_section(self, key):
        card = self.section(key)
        card.layout().invalidate()
        card.updateGeometry()
        index = self.grid.indexOf(card)
        position = self.grid.getItemPosition(index)
        item = self.grid.takeAt(index)
        # Qt caches this item's height hint across inline visibility changes.
        # Replace only that item, keeping every neighbouring card in place.
        self.grid.addWidget(card, *position, item.alignment())
        self.grid.activate()
        self.updateGeometry()

    def minimumSizeHint(self):
        return QSize(0, self.grid.minimumSize().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = 2 if self.width() >= self.BREAKPOINT else 1
        if columns != self.columns:
            self._arrange()

    def _arrange(self):
        self.columns = 2 if self.width() >= self.BREAKPOINT else 1
        while self.grid.count():
            self.grid.takeAt(0)
        row, column = 0, 0
        for _key, widget, wide in self.entries:
            if wide and column:
                row, column = row + 1, 0
            alignment = Qt.AlignTop if widget.sizePolicy().verticalPolicy() == QSizePolicy.Maximum else Qt.Alignment()
            self.grid.addWidget(widget, row, column, 1, self.columns if wide else 1, alignment)
            column += self.columns if wide else 1
            if column == self.columns:
                row, column = row + 1, 0
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1 if self.columns == 2 else 0)
        self.updateGeometry()


def section_grid(grid, groups, *, anchor=None, full_width_rows=()):
    """Rehouse existing grid items without replacing controls or their signals.

    General's original outer grid stays in place for released plugin logo hooks.
    The hidden anchor remains a direct child of that grid, below the cards.
    """
    entries = []
    for index in range(grid.count()):
        row, column, rows, columns = grid.getItemPosition(index)
        entries.append((row, column, rows, columns, grid.itemAt(index)))
    while grid.count():
        grid.takeAt(0)
    sections = SettingsColumns()
    targets = {}
    for key, title, row_numbers, wide in groups:
        card = SettingsSection(title)
        sections.add_section(key, card, wide=wide)
        for local_row, row in enumerate(row_numbers):
            targets[row] = (card.grid, local_row)
    for row, column, rows, columns, item in entries:
        widget, layout = item.widget(), item.layout()
        if anchor is not None and widget is anchor:
            continue
        target, local_row = targets[row]
        if row in full_width_rows:
            if column == 0:
                widget.hide()
                widget.deleteLater()
                continue
            column, columns = 0, 2
        if widget is not None:
            if isinstance(widget, QLabel):
                widget.setWordWrap(True)
            target.addWidget(widget, local_row, column, rows, columns, item.alignment())
        elif layout is not None:
            layout.setParent(None)
            target.addLayout(layout, local_row, column, rows, columns)
        else:
            target.addItem(item, local_row, column, rows, columns)
    grid.addWidget(sections, 0, 0, 1, 2)
    if anchor is not None:
        grid.addWidget(anchor, 1, 0, 1, 2)
    return sections
