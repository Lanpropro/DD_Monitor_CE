"""Check the plugin entry against the native portrait layout, without playback."""
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DDM_NO_SAVE", "1")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton, QVBoxLayout, QWidget
from ddm import motion, theme
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
with patch.object(motion, 'THEME_WAVE_EASING'):
    del motion.THEME_WAVE_EASING
    plugin.on_load(context)
settle()
assert native_geometry() == baseline, (native_geometry(), baseline)
assert native_tools() == baseline_tools
assert sidebar.height() == baseline_height
entry = plugin.entry
assert entry._stretch.easingCurve().type().name == 'OutCubic', 'Released hosts must load without the new easing constant'
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

for side in ('left', 'top', 'left'):
    sidebar.set_side(side)
    settle()
    old_width = entry.width()
    with patch.object(motion, 'enabled', return_value=True):
        entry.set_mode(True)
    settle()
    assert sidebar.layout_button.isHidden()
    assert entry.parentWidget() is sidebar.tool_row and entry.toolButtonStyle() == Qt.ToolButtonTextOnly
    assert entry.width() > old_width, 'Active match entry must occupy the freed preset space'
    width = entry.width()
    entry._stretch.setCurrentTime(80)
    assert entry.width() == width, 'The stretch is painted without repeatedly relaying out the sidebar'
    entry._stretch.setCurrentTime(160)
    assert entry._paint_width is None
    with patch.object(motion, 'enabled', return_value=True):
        entry.set_mode(False)
        assert entry._closing and sidebar.layout_button.isHidden()
        assert entry._stretch.startValue() == width and entry._stretch.endValue() == old_width
        entry._stretch.setCurrentTime(80)
        halfway = entry._paint_width
        assert old_width <= halfway < width and entry.width() == width
        # Reopening midway reverses from the visible edge, without a jump.
        entry.set_mode(True)
        assert not entry._closing and entry._stretch.startValue() == halfway
        entry._stretch.setCurrentTime(160)
        entry.set_mode(False)
        entry._stretch.setCurrentTime(160)
    settle()
    assert not entry._closing and entry._paint_width is None
    assert not sidebar.layout_button.isHidden()
    assert entry.width() == old_width
    with patch.object(motion, 'enabled', return_value=True):
        entry.set_mode(True)
        entry._stretch.setCurrentTime(160)
    with patch.object(motion, 'enabled', return_value=False):
        entry.set_mode(False)
    settle()
    assert not sidebar.layout_button.isHidden()
sidebar.set_side('top')
settle()
assert native_geometry() == baseline
with patch.object(motion, 'enabled', return_value=True):
    entry.set_mode(True)
    entry._stretch.setCurrentTime(160)
    entry.set_mode(False)
    assert entry._closing
    sidebar.set_side('left')
settle()
assert not entry._closing and not sidebar.layout_button.isHidden()
assert entry.parentWidget() is sidebar.tool_row
sidebar.set_side('top')
settle()
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
