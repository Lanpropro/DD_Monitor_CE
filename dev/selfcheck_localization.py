"""实际输入控件的中文默认菜单、右键弹出、编辑功能与翻译生命周期。"""
import gc
import os
from pathlib import Path
import sys

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMenu, QTextBrowser
from ddm.dialogs import AddRoomDialog, DanmakuSettingsPage, FollowImportDialog, RecordingSettingsPage
from ddm.localization import install_chinese_translations
from ddm.user_notice import UserNoticeDialog


def labels(menu):
    return [action.text().split("\t")[0] for action in menu.actions() if not action.isSeparator()]


def assert_chinese(menu, expected):
    text = labels(menu)
    for word in expected:
        assert any(word in label for label in text), (word, text)
    assert not any(word in label for label in text
                   for word in ("Undo", "Redo", "Cut", "Copy", "Paste", "Delete", "Select All")), text


def main():
    app = QApplication([])
    install_chinese_translations(app)
    translators = list(app._chinese_translators)
    assert len(translators) == 2, "source and frozen environments must contain both Qt Chinese catalogs"
    install_chinese_translations(app)
    assert app._chinese_translators == translators, "installation must not duplicate translators"
    gc.collect()

    adding = AddRoomDialog()
    importing = FollowImportDialog([], set())
    recording = RecordingSettingsPage({})
    danmaku = DanmakuSettingsPage({})
    notice = UserNoticeDialog()
    notes = QTextBrowser()
    notes.setHtml('<a href="https://example.com">更新说明</a>')
    combo = QComboBox()
    combo.setEditable(True)
    edits = [adding.edit, importing.search_edit, recording.directory,
             danmaku.block_edit, combo.lineEdit(), danmaku.size_spin.findChild(QLineEdit)]
    for edit in edits:
        menu = edit.createStandardContextMenu()
        assert_chinese(menu, ("撤消", "重做", "剪切", "复制", "粘贴", "删除", "全选"))
        menu.deleteLater()
    for browser in (notes, notice.content):
        menu = browser.createStandardContextMenu()
        assert_chinese(menu, ("复制", "全选"))
        menu.deleteLater()

    adding.show()
    app.processEvents()
    failures = []
    def inspect_popup():
        menu = QApplication.activePopupWidget()
        try:
            assert isinstance(menu, QMenu), "right-click must open the actual standard menu"
            assert_chinese(menu, ("撤消", "重做", "剪切", "复制", "粘贴", "删除", "全选"))
        except Exception as error:
            failures.append(error)
        finally:
            if menu is not None:
                menu.close()
    QTimer.singleShot(20, inspect_popup)
    point = adding.edit.rect().center()
    event = QContextMenuEvent(QContextMenuEvent.Mouse, point, adding.edit.mapToGlobal(point))
    QApplication.sendEvent(adding.edit, event)
    assert not failures, failures

    edit = adding.edit
    edit.setText("https://live.bilibili.com/123")
    edit.selectAll()
    def trigger(word):
        menu = edit.createStandardContextMenu()
        action = next(a for a in menu.actions() if word in a.text())
        assert action.isEnabled()
        action.trigger()
        menu.deleteLater()
    trigger("复制")
    assert app.clipboard().text() == edit.text()
    edit.setCursorPosition(len(edit.text()))
    app.clipboard().setText("456")
    trigger("粘贴")
    assert edit.text().endswith("123456")
    trigger("撤消")
    assert edit.text().endswith("123")
    trigger("重做")
    assert edit.text().endswith("123456")
    QTest.keyClick(edit, Qt.Key_Z, Qt.ControlModifier)
    assert edit.text().endswith("123"), "standard shortcuts must keep working"
    edit.setReadOnly(True)
    menu = edit.createStandardContextMenu()
    assert_chinese(menu, ("复制", "全选"))
    assert not any(a.isEnabled() and "粘贴" in a.text() for a in menu.actions())
    menu.deleteLater()

    for widget in (adding, importing, recording, danmaku, notice, notes, combo):
        widget.close()
    print("PASS: Chinese standard menus across add/import/settings/text/combo/spin controls, actual right-click, copy/paste/undo/redo, shortcuts and read-only behavior")


if __name__ == "__main__":
    main()
