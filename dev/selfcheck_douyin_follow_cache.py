"""抖音关注跨导入窗口复用、手动读取、空列表和账号隔离。"""
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from ddm import app as app_module
from ddm.account_dialog import AccountPlatformDialog
from ddm.platform_login import PlatformFollowDialog
from dev.selfcheck_account_dialog import dispose, follows_ready
from dev.selfcheck_platform_follows import ROOMS, wait_for


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    rooms = [dict(room, room_id='douyin:' + room['room_id'].split(':')[1], platform='douyin') for room in ROOMS]
    account = {'uid': '123', 'uname': 'Fixture'}
    provider = SimpleNamespace(kind='douyin', label='抖音', follow_cookie_domain='douyin.com',
        follow_login_url='about:blank', account_info=Mock(return_value=account),
        follow_rooms=Mock(return_value=rooms), follow_browser_init_script='// interactive fixture')
    with patch.object(app_module.QTimer, 'singleShot'):
        owner = app_module.MainWindow([], [], state={'plugins_enabled': []})
    owner._accounts['douyin'] = dict(account)
    try:
        with patch.object(QWebEngineView, 'load') as browser_load:
            dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
            dialog.show()
            wait_for(app, lambda: follows_ready(dialog) and owner._follow_loader is None)
            assert dialog.page.rooms == rooms and provider.follow_rooms.call_count == 1
            dispose(app, dialog)

            # 每次新建窗口，直接打开上次列表，不创建浏览器或启动读取线程。
            for _ in range(2):
                with patch('ddm.platform_login.PlatformFollowDialog', side_effect=AssertionError('Browser reopened')):
                    dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
                    assert follows_ready(dialog) and dialog.page.rooms == rooms
                    assert not dialog._platform_pages and provider.follow_rooms.call_count == 1
                    assert dialog.page.reread_button.cursor().shape() == Qt.PointingHandCursor
                    assert not dialog.page.selected()
                    dialog.page._check_all(True)
                    assert dialog.page.selected() == rooms
                dispose(app, dialog)
            browser_load.assert_not_called()

            # 手动重新读取才打开官网；成功后替换缓存，空列表也可复用。
            dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
            dialog.show()
            provider.follow_rooms.return_value = []
            dialog.page.reread_button.click()
            wait_for(app, lambda: follows_ready(dialog) and owner._follow_loader is None)
            assert dialog.page.rooms == [] and provider.follow_rooms.call_count == 2
            dispose(app, dialog)
            dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
            assert follows_ready(dialog) and dialog.page.rooms == [] and not dialog._platform_pages

            # 失败不覆盖上次成功结果，关闭后仍可打开选择列表。
            provider.follow_rooms.side_effect = RuntimeError('Fixture read failed')
            dialog.page.reread_button.click()
            wait_for(app, lambda: isinstance(dialog.page, PlatformFollowDialog) and owner._follow_loader is None)
            assert 'Fixture read failed' in dialog.page.status.text()
            dispose(app, dialog)
            with patch('ddm.platform_login.PlatformFollowDialog', side_effect=AssertionError('Failed refresh erased cache')):
                dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
                assert follows_ready(dialog) and dialog.page.rooms == []
                dispose(app, dialog)

            entered, release = threading.Event(), threading.Event()
            def late_rooms(_session, _cancelled):
                entered.set()
                assert release.wait(5)
                return rooms
            with patch.object(provider, 'follow_rooms', side_effect=late_rooms):
                dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
                dialog.show()
                dialog.page.reread_button.click()
                assert entered.wait(2)
                page = dialog.page
                page.read_button.click()
                release.set()
                wait_for(app, lambda: owner._follow_loader is None)
                page._loaded(rooms)
                assert owner._douyin_follow_cache['rooms'] == [] and not dialog._follow_pages
                dispose(app, dialog)

            # 换账号不能使用旧关注；退出账号会立即清空缓存。
            provider.follow_rooms.side_effect = None
            provider.follow_rooms.return_value = rooms
            owner._accounts['douyin'] = {'uid': '456'}
            provider.account_info.return_value = {'uid': '456', 'uname': 'Other'}
            dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
            assert isinstance(dialog.page, PlatformFollowDialog)
            wait_for(app, lambda: follows_ready(dialog) and owner._follow_loader is None)
            assert dialog.page.rooms == rooms
            dispose(app, dialog)
            owner._clear_platform_account('douyin')
            assert owner._douyin_follow_cache is None
            dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
            assert isinstance(dialog.page, PlatformFollowDialog) and dialog.page._worker is None
            dispose(app, dialog)
    finally:
        owner.close()
        app.processEvents()
    print('PASS: Douyin cached reopen without browser; manual reread; empty/failure cache; account isolation and logout')


if __name__ == '__main__':
    main()
