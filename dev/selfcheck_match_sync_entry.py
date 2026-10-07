"""Check the plugin entry against the native portrait layout, without playback."""
import os
from pathlib import Path
import sys
from unittest.mock import Mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DDM_NO_SAVE", "1")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton, QVBoxLayout, QWidget
from ddm import theme
from ddm.widgets import Sidebar
from plugins_user._match_sync.plugin import MatchSyncPlugin


def settle():
    for _ in range(8):
        app.processEvents()


def native_geometry():
    return tuple((widget.mapTo(sidebar._bar_right, QPoint()).toTuple(),
                  widget.size().toTuple()) for widget in
                 (sidebar.account_row, sidebar.layout_button, sidebar.settings_button))


def native_tools():
    box = sidebar.tool_row.layout()
    return [box.itemAt(i).widget() for i in range(box.count())]


app = QApplication.instance() or QApplication([])
host = QWidget()
host.setStyleSheet(theme.qss())
host.sidebar = sidebar = Sidebar([], auto_compact=False)
host._content = QWidget()
box = QVBoxLayout(host)
box.addWidget(sidebar)
box.addWidget(host._content, 1)
sidebar.set_account("测试主播", uid="123")
sidebar.set_side("top")
host.resize(820, 600)
host.show()
settle()
baseline = native_geometry()
baseline_tools = native_tools()
baseline_height = sidebar.height()
context = Mock(window=host)
plugin = MatchSyncPlugin()
plugin.set_enabled = Mock()
plugin.on_load(context)
settle()
assert native_geometry() == baseline, (native_geometry(), baseline)
assert native_tools() == baseline_tools
assert sidebar.height() == baseline_height
entry = plugin.entry
assert entry.parentWidget() is sidebar._bar_row
assert entry.size().toTuple() == (30, 30)
assert entry.toolButtonStyle() == Qt.ToolButtonIconOnly
assert entry.accessibleName() == "比赛二路" and "比赛二路" in entry.toolTip()
assert sidebar._bar_row_box.indexOf(entry) == sidebar._bar_row_box.indexOf(sidebar.toggle_button) - 1
QTest.mouseClick(entry, Qt.LeftButton)
assert plugin.button.isChecked()
plugin.set_enabled.assert_called_once_with(True)
QTest.mouseClick(entry, Qt.LeftButton)
assert not plugin.button.isChecked()
plugin.set_enabled.assert_called_with(False)
assert not entry.icon().isNull(), "Action state changes must preserve the entry icon"
assert "开启或关闭" in entry.toolTip()

for _ in range(4):
    sidebar.set_collapsed(True, animate=False)
    settle()
    assert entry.isVisible() and entry not in native_tools()
    sidebar.set_collapsed(False, animate=False)
    settle()
    assert native_geometry() == baseline
    sidebar.set_side("left")
    settle()
    assert entry.parentWidget() is sidebar.tool_row
    assert native_tools() == [entry, sidebar.layout_button, sidebar.settings_button]
    assert entry.objectName() == "IconButton"
    assert entry.toolButtonStyle() == Qt.ToolButtonTextOnly
    sidebar.set_collapsed(True, animate=False)
    settle()
    assert entry.isHidden()
    sidebar.set_collapsed(False, animate=False)
    sidebar.set_side("top")
    settle()
    assert entry.parentWidget() is sidebar._bar_row and entry.isVisible()
    assert native_tools() == baseline_tools
    assert native_geometry() == baseline

if "--snapshot" in sys.argv:
    output = REPO / "work" / "match-sync-portrait-entry.png"
    output.parent.mkdir(exist_ok=True)
    assert sidebar.grab().save(str(output))
    print(output)

plugin.on_unload()
settle()
app.sendPostedEvents(None, QEvent.DeferredDelete)
settle()
assert plugin.entry is None and plugin.button is None
assert native_tools() == baseline_tools and native_geometry() == baseline
sidebar.set_side("left")
settle()
legacy = QToolButton(sidebar.tool_row)
legacy.setDefaultAction(QAction("比赛二路", host))
legacy.setObjectName("IconButton")
sidebar.tool_row.layout().insertWidget(0, legacy)
legacy.show()
settle()
legacy_geometry = tuple(widget.geometry().getRect() for widget in
                        (legacy, sidebar.layout_button, sidebar.settings_button))
sidebar.tool_row.layout().removeWidget(legacy)
legacy.hide()
legacy.deleteLater()
plugin.on_load(context)
settle()
assert plugin.entry.parentWidget() is sidebar.tool_row
assert native_tools() == [plugin.entry, sidebar.layout_button, sidebar.settings_button]
assert tuple(widget.geometry().getRect() for widget in
             (plugin.entry, sidebar.layout_button, sidebar.settings_button)) == legacy_geometry
plugin.on_unload()
settle()
assert native_tools() == [sidebar.layout_button, sidebar.settings_button]
host.close()
print("PASS: native positions, portrait entry, clicks, orientation/collapse cycles, unload")
