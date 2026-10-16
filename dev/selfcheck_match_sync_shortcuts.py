"""Actual key events in embedded/fullscreen match mode, without streams or audio."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QPushButton, QVBoxLayout, QWidget
from ddm import plugins
from ddm.dialogs import SHORTCUT_ACTIONS
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        host = QMainWindow()
        host.settings = {}
        host.shortcuts = {action: default for action, _label, default in SHORTCUT_ACTIONS}
        root = QWidget()
        host.setCentralWidget(root)
        context = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'keys')
        viewer = module.Viewer(context, {})
        viewer.embed(root)
        QVBoxLayout(root).addWidget(viewer)
        host.resize(1400, 1000)
        fallback = Mock()
        shortcuts = []
        for sequence in host.shortcuts.values():
            shortcut = QShortcut(QKeySequence(sequence), host)
            shortcut.activated.connect(fallback)
            shortcuts.append(shortcut)
        try:
            for key in ('1', '2', '3'):
                viewer.add_room(key, {'alias': key})
            host.show()
            host.activateWindow()
            app.processEvents()
            main_row = viewer.rows[viewer.main.currentData()]
            other = next(row for row in viewer.rows.values() if row is not main_row)
            button = viewer.picture.pause_button
            button.setFocus()
            with patch.object(module.QCursor, 'pos', side_effect=lambda: viewer.picture.mapToGlobal(viewer.picture.rect().center())):
                before = viewer.picture.danmaku_button.isChecked()
                QTest.keyClick(button, Qt.Key_B)
                assert viewer.picture.danmaku_button.isChecked() != before
                QTest.keyClick(button, Qt.Key_B)
                assert viewer.picture.danmaku_button.isChecked() == before
                audible = main_row.audible.isChecked()
                QTest.keyClick(button, Qt.Key_M)
                assert main_row.audible.isChecked() != audible
                assert viewer.picture.muted == (not main_row.audible.isChecked())
                QTest.keyClick(button, Qt.Key_M)
                assert main_row.audible.isChecked() == audible
                main_row.audible.setChecked(True)
                main_row.channel.setCurrentIndex(0)
                for channel, audible in ((1, True), (2, True), (2, False), (0, True)):
                    QTest.keyClick(button, Qt.Key_E)
                    assert main_row.channel.currentIndex() == channel
                    assert main_row.audible.isChecked() == audible
                QTest.keyClick(button, Qt.Key_M, Qt.AltModifier)
                assert all(row.audible.isChecked() == (row is main_row) for row in viewer.rows.values())
                QTest.keyClick(main_row.channel, Qt.Key_B)
                assert viewer.picture.danmaku_button.isChecked() != before, 'Combo focus must not swallow playback keys'
                viewer.picture.danmaku_button.setChecked(before)
                edit = viewer.input
                edit.show()
                edit.setFocus()
                QTest.keyClicks(edit, 'bmfe')
                assert edit.text() == 'bmfe'
                assert viewer.picture.danmaku_button.isChecked() == before
                assert main_row.audible.isChecked()
                button.setFocus()
                QTest.keyClick(button, Qt.Key_F)
                app.processEvents()
                assert viewer.fullscreen_dialog is not None, 'F must enter fullscreen without shortcut ambiguity'
                QTest.keyClick(button, Qt.Key_M)
                assert not main_row.audible.isChecked(), 'M must also work inside fullscreen'
                QTest.keyClick(button, Qt.Key_B)
                assert viewer.picture.danmaku_button.isChecked() != before
                QTest.keyClick(button, Qt.Key_F)
                app.processEvents()
                assert viewer.fullscreen_dialog is None
                QTest.keyClick(button, Qt.Key_F)
                app.processEvents()
                QTest.keyClick(button, Qt.Key_Escape)
                app.processEvents()
                assert viewer.fullscreen_dialog is None and viewer.isVisible()
                host.shortcuts['video_danmaku'] = 'Ctrl+R'
                before = viewer.picture.danmaku_button.isChecked()
                QTest.keyClick(button, Qt.Key_R, Qt.ControlModifier)
                assert viewer.picture.danmaku_button.isChecked() != before, 'Read current custom bindings'
                dialog = QDialog(host)
                modal_button = QPushButton('modal', dialog)
                QVBoxLayout(dialog).addWidget(modal_button)
                dialog.setModal(True)
                dialog.show()
                app.processEvents()
                before = viewer.picture.danmaku_button.isChecked()
                QTest.keyClick(modal_button, Qt.Key_R, Qt.ControlModifier)
                assert viewer.picture.danmaku_button.isChecked() == before
                dialog.close()
            fallback.assert_not_called()
            viewer.show_comparison(other.room_id)
            app.processEvents()
            card = viewer.comparison_panel.cards[other.room_id][0]
            with patch.object(module.QCursor, 'pos', return_value=card.mapToGlobal(card.rect().center())):
                before = other.audible.isChecked()
                QTest.keyClick(button, Qt.Key_M)
                assert other.audible.isChecked() != before, 'Comparison shortcuts must target the hovered stream'
            viewer.hide()
            host.activateWindow()
            outside = QPushButton('normal', root)
            outside.show()
            outside.setFocus()
            app.processEvents()
            QTest.keyClick(outside, Qt.Key_M)
            fallback.assert_called_once()
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: B/M/F/E/Alt+M/Esc, custom bindings, fullscreen, comparison targets, typing/modal guards and normal-mode handoff')


if __name__ == '__main__':
    main()
