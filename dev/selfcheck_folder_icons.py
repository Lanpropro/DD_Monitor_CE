"""Folder icon edits, image ownership, persistence and list interactions."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage
from PySide6.QtWidgets import QApplication, QDialog
from ddm import config, theme
from ddm.folder_icons import FolderIconDialog, folder_icon, read_image
from ddm.follow_folders import normalize_folders, normalize_icon
from ddm.widgets import NAV_MIME, Sidebar


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.object(config, 'REPO', directory):
        sidebar = Sidebar([{'room_id': '1', 'uname': 'Test'}], auto_compact=False)
        sidebar.resize(248, 750)
        sidebar.setAttribute(Qt.WA_ShowWithoutActivating)
        sidebar.move(-10000, -10000)
        sidebar.show()
        normal = sidebar.create_folder('Normal')
        smart = sidebar.create_folder('Smart', rule={'status': 'live', 'platforms': []})
        app.processEvents()
        changes = []
        sidebar.foldersChanged.connect(lambda: changes.append(True))
        for fid in (normal, smart):
            folder = sidebar.get_folder(fid)
            button = sidebar._folder_buttons[fid]
            action = next(a for a in button._context_menu().actions() if a.text() == '修改图标…')
            dialog = FolderIconDialog(folder, button)
            for name in ('folder', 'star', 'heart', 'game', 'music', 'video'):
                dialog.select_builtin(name)
                assert not dialog.preview.pixmap().isNull()
            dialog.set_color('pink')
            assert dialog.selection['color'] == 'pink' and 'icon' not in folder
            dialog.reject()
            assert 'icon' not in folder, 'Cancel must preserve the folder'
            def save(editor):
                editor.select_builtin('heart')
                editor.set_color('pink')
                editor.accept()
                return QDialog.Accepted
            with patch.object(FolderIconDialog, 'exec', save):
                action.trigger()
            assert folder['icon'] == {'type': 'builtin', 'name': 'heart', 'color': 'pink'}
            assert changes and button.iconSize().width() == 18
            assert normalize_folders(sidebar.folder_state()) == sidebar.folder_state()
            assert button.acceptDrops()
        button = sidebar._folder_buttons[normal]
        folder = sidebar.get_folder(normal)
        old = dict(folder['icon'])
        with patch.object(FolderIconDialog, 'exec', return_value=QDialog.Rejected):
            button._edit_icon()
        assert folder['icon'] == old
        image = QImage(80, 40, QImage.Format_ARGB32)
        image.fill(QColor('#E95C93'))
        source = Path(directory)/'source.png'
        image.save(str(source))
        original = source.read_bytes()
        dialog = FolderIconDialog(folder, button)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source))])
        enter = QDragEnterEvent(dialog.drop_area.rect().center(), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(dialog.drop_area, enter)
        assert enter.isAccepted() and dialog.drop_area.property('dragging')
        drop = QDropEvent(QPointF(dialog.drop_area.rect().center()), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(dialog.drop_area, drop)
        assert drop.isAccepted() and not dialog.drop_area.property('dragging')
        assert 'icon' in folder and folder['icon'] == old, 'Dropping must not apply before Save'
        remote = QMimeData()
        remote.setUrls([QUrl('https://example.com/icon.png')])
        rejected = QDragEnterEvent(dialog.drop_area.rect().center(), Qt.CopyAction, remote, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(dialog.drop_area, rejected)
        assert not rejected.isAccepted()
        remote.setUrls([QUrl.fromLocalFile(str(source)), QUrl.fromLocalFile(str(source))])
        rejected = QDragEnterEvent(dialog.drop_area.rect().center(), Qt.CopyAction, remote, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(dialog.drop_area, rejected)
        assert not rejected.isAccepted()
        assert not dialog.color.isEnabled()
        assert dialog.image.pixelColor(128, 0).alpha() == 0
        assert dialog.image.pixelColor(128, 128) == QColor('#E95C93')
        dialog.reject()
        assert not (Path(directory)/'utils/folder-icons').exists(), 'Cancel must not copy assets'
        dialog.accept()
        assert source.read_bytes() == original
        folder['icon'] = dialog.result_icon
        copied = Path(directory)/folder['icon']['path']
        assert QImage(str(copied)).size().width() == 256
        source.unlink()
        assert not folder_icon(folder, button).isNull()
        jpeg = Path(directory)/'source.jpg'
        assert image.save(str(jpeg), 'JPEG') and not read_image(jpeg).isNull()
        snapshot = sidebar.folder_state()
        with patch.object(config, 'CONFIG_PATH', str(Path(directory)/'state.json')), patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
            config.save({'version': config.STATE_VERSION, 'folders': snapshot})
            assert config.load()['folders'] == snapshot
        restored = Sidebar([])
        restored.set_folders(snapshot)
        assert restored.folder_state() == snapshot
        restored.close()
        # Failures keep the current selection, including a failed copy on Save.
        dialog = FolderIconDialog(folder, button)
        dialog.import_image(Path(directory)/'missing.png')
        assert dialog.selection == folder['icon'] and dialog.error.text()
        dialog.image = image
        with patch.object(QImage, 'save', return_value=False):
            dialog.accept()
        assert dialog.result() != QDialog.Accepted and dialog.error.text()
        assert folder['icon'] == snapshot[0]['icon']
        oversized = Path(directory)/'huge.png'
        oversized.write_bytes(b'0'*(5*1024*1024+1))
        wide = QImage(4097, 1, QImage.Format_RGB32)
        wide.fill(Qt.red)
        wide_path = Path(directory)/'wide.png'
        wide.save(str(wide_path))
        for path in (oversized, wide_path):
            try:
                read_image(path)
            except ValueError:
                pass
            else:
                raise AssertionError('Oversized icons must be rejected')
        copied.unlink()
        assert not folder_icon(folder, button).isNull(), 'Missing assets must fall back'
        copied.write_bytes(b'broken image')
        assert not folder_icon(folder, button).isNull(), 'Corrupt assets must fall back'
        for spec in ({'type': 'builtin', 'name': 'bad', 'color': 'pink'},
                     {'type': 'image', 'path': '../private.png'},
                     {'type': 'image', 'path': 'C:/private.png'}, 'invalid'):
            assert normalize_icon(spec) is None
        button.refresh_theme()
        theme.apply('light')
        preview = FolderIconDialog(sidebar.get_folder(smart), button)
        preview.setAttribute(Qt.WA_ShowWithoutActivating)
        preview.move(-10000, -10000)
        preview.show()
        app.processEvents()
        output = Path(__file__).resolve().parents[1]/'work/appearance-delivery'
        output.mkdir(parents=True, exist_ok=True)
        assert preview.grab().save(str(output/'folder-icons.png'))
        preview.close()
        theme.apply('dark')
        sidebar.move_to_folder(['1'], normal)
        button.click()
        assert folder['collapsed']
        button.click()
        sidebar.move_to_folder(['1'], '')
        mime = QMimeData()
        mime.setData(NAV_MIME, b'1')
        QApplication.sendEvent(button, QDragEnterEvent(button.rect().center(), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier))
        drop = QDropEvent(QPointF(button.rect().center()), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(button, drop)
        assert drop.isAccepted() and sidebar.folder_for('1') == normal
        sidebar.side = 'top'
        assert not button.grab().isNull()
        def reset(editor):
            editor.reset()
            editor.accept()
            return QDialog.Accepted
        with patch.object(FolderIconDialog, 'exec', reset):
            button._edit_icon()
        assert 'icon' not in folder
        sidebar.close()
    print('PASS: normal/smart icons, colors, cancel/save/reset, transparent imports, persistence, validation/fallback, theme/DPI rendering, rotated headers and drag/drop')


if __name__ == '__main__':
    main()
