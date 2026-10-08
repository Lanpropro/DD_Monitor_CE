"""Verify update notes replace plugin details until a successful staged update."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import zipfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from ddm import config, online, plugin_updates
from ddm.dialogs import PluginSettingsPage
from ddm.plugins import PluginManager


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as temporary, patch.object(config, 'REPO', temporary):
        root = Path(temporary)
        manager = PluginManager(plugins_dir=str(root / 'plugins'), enabled=[])
        folder = root / 'plugins/match_sync'
        folder.mkdir(parents=True)
        manifest = dict(id='match_sync', name='比赛二路同步', version='1.0',
                        description='原插件说明', min_app_version='0.3')
        (folder / 'plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
        (folder / 'plugin.py').write_text('', encoding='utf-8')
        page = PluginSettingsPage(manager)
        offer = dict(manifest, version='1.1', available=True, notes='批量混音\n减少整帧复制')
        page.store_page._catalog_ready([offer])
        description, status, normal = page.card_details['match_sync']
        assert description.text() == '更新日志 · v1.1\n批量混音\n减少整帧复制'
        assert status.isHidden()
        assert page.update_buttons['match_sync'].isEnabled()
        assert not page.update_buttons['match_sync'].isHidden()
        card = page.update_buttons['match_sync'].parent()
        heading = card.layout().itemAt(0).layout()
        remove = next(button for button in card.findChildren(QPushButton) if button.text() == '删除')
        assert heading.indexOf(page.update_buttons['match_sync']) + 1 == heading.indexOf(remove)
        labels = page.store_page.findChildren(QLabel)
        assert any(label.text() == description.text() for label in labels)
        # Failure leaves notes visible and the update remains retryable.
        page.store_page._failed((None, 'download failed'))
        assert description.text().startswith('更新日志')
        assert page.store_page.buttons['match_sync'].isEnabled()
        archive = root / 'match_sync-1.1.zip'
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('match_sync/plugin.json', json.dumps(dict(manifest, version='1.1')))
            package.writestr('match_sync/plugin.py', '')
        gate = threading.Event()
        def download(_offer, _path, _client, _cancelled, progress):
            progress(50, 100)
            assert gate.wait(5)
            return str(archive)
        with patch.object(online, 'download', side_effect=download), patch('ddm.online_ui.show_result'):
            try:
                page.update_buttons['match_sync'].click()
                deadline = time.monotonic() + 5
                while page.update_buttons['match_sync'].text() != '下载 50%' and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.01)
                assert page.update_buttons['match_sync'].text() == '下载 50%'
                assert page.store_page.buttons['match_sync'].text() == '下载 50%'
                assert not page.update_buttons['match_sync'].isEnabled()
                assert description.text().startswith('更新日志')
            finally:
                gate.set()
                deadline = time.monotonic() + 5
                while page.store_page.jobs and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.01)
            assert not page.store_page.jobs
        description, status, normal = page.card_details['match_sync']
        assert description.text() == normal == '原插件说明'
        assert not status.isHidden() and '待重启' in status.text()
        assert page.store_page.buttons['match_sync'].text() == '待重启'
        assert page.update_buttons['match_sync'].text() == '待重启'
        assert not page.update_buttons['match_sync'].isEnabled()
        assert not any(label.text().startswith('更新日志') for label in
                       page.store_page.buttons['match_sync'].parent().findChildren(QLabel))
        plugin_updates.apply_pending(manager)
        page.store_page.show_offers([offer])
        page._store_installed('match_sync')
        page._show_update_notes([offer])
        assert page.store_page.buttons['match_sync'].text() == '已安装'
        assert page.card_details['match_sync'][0].text() == normal
        assert page.update_buttons['match_sync'].isHidden()
        page.close()
        app.processEvents()
    print('PASS: update notes in both tabs, failure preservation, staging and restart restoration')


if __name__ == '__main__':
    main()
