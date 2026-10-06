"""启动更新开关、非模态悬浮提示、跳转、十秒消失和关闭收尾。"""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from ddm import app as app_module, config, online, theme
from ddm.dialogs import SettingsDialog
from selfcheck_online_ui import Session


def settle(app, window):
    end = time.monotonic() + 5
    while window._startup_update_task is not None and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()
    assert window._startup_update_task is None


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    offer = {'version': '0.3.1', 'notes': '# 更新说明\n\n修复内容'}
    with ExitStack() as stack:
        temporary = stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-update-notice-'))
        stack.enter_context(patch.object(config, 'REPO', temporary))
        stack.enter_context(patch.object(online, 'session', return_value=Session()))
        for method in ('refresh_status', 'refresh_stats', 'refresh_account', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars', 'start_all'):
            stack.enter_context(patch.object(app_module.MainWindow, method))
        modal = stack.enter_context(patch.object(QMessageBox, 'information'))
        (Path(temporary) / 'RELEASE-v0.3.md').write_text('# 当前版本说明', encoding='utf-8')
        disabled = app_module.MainWindow([], [], state={'plugins_enabled': []})
        with patch.object(online, 'app_release') as check:
            assert not disabled._startup_update_timer.isActive()
            disabled._check_startup_update()
            check.assert_not_called()
        disabled.close()
        window = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'auto_update': True}})
        window.show()
        app.processEvents()
        assert window._startup_update_timer.isActive()
        with patch.object(online, 'app_release', return_value=offer) as check, \
                patch.object(online, 'download') as download:
            window._startup_update_timer.timeout.emit()
            settle(app, window)
            notice = window._update_notice
            assert notice and notice.isVisible()
            assert notice.windowModality() == Qt.NonModal and notice.isWindow()
            assert notice.testAttribute(Qt.WA_ShowWithoutActivating)
            assert notice.windowFlags() & Qt.WindowDoesNotAcceptFocus
            assert notice.timer.interval() == 10_000 and notice.timer.isActive()
            image = notice.grab().toImage()
            assert image.pixelColor(0, 0).alpha() < 50 and image.pixelColor(20, 50).alpha() > 240, \
                'floating notice must have a painted body and transparent rounded corners'
            window._check_startup_update()
            assert check.call_count == 1, 'startup check must run once'
            download.assert_not_called()
        opened = []
        class InspectDialog(SettingsDialog):
            def exec(self):
                opened.append((self.nav.currentRow(), self.update_page.offer, self.update_page.auto.isChecked()))
                self.reject()
                return self.result()
        with patch.object(app_module, 'SettingsDialog', InspectDialog):
            QTest.mouseClick(notice.action, Qt.LeftButton)
        assert opened == [(5, offer, True)] and not notice.isVisible()
        assert not notice.timer.isActive() and window.settings['auto_update']
        # 真正经过十秒，未点击的提醒自动消失，不执行下载或跳转。
        activated = QSignalSpy(notice.activated)
        notice.show_offer(offer)
        old_position = notice.pos()
        window.move(window.x() + 25, window.y() + 25)
        app.processEvents()
        assert notice.pos() != old_position
        QTest.qWait(10_200)
        assert not notice.isVisible() and activated.count() == 0
        class DisableDialog(SettingsDialog):
            def exec(self):
                self.update_page.auto.setChecked(False)
                self.confirm_button.click()
                return self.result()
        with patch.object(app_module, 'SettingsDialog', DisableDialog), patch.object(config, 'save') as save:
            assert window.open_settings('updates')
            assert not window.settings['auto_update'] and save.called
            assert window.current_state()['settings']['auto_update'] is False
        window.close()
        latest = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'auto_update': True}})
        with patch.object(online, 'app_release', return_value=None):
            latest._check_startup_update()
            settle(app, latest)
            assert latest._update_notice is None
        latest.close()
        closing = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'auto_update': True}})
        started = threading.Event()
        def pending(*args):
            started.set()
            while not closing._startup_update_task.isInterruptionRequested():
                time.sleep(0.01)
            return offer
        with patch.object(online, 'app_release', side_effect=pending):
            closing._check_startup_update()
            assert started.wait(2)
            closing.close()
            settle(app, closing)
            assert closing._update_notice is None, 'late results after closing must not show a notice'
        modal.assert_not_called()
    print('PASS: saved startup toggle, nonmodal clickable notice, ten-second dismissal, latest version and safe shutdown')


if __name__ == '__main__':
    main()
