"""真实 DPAPI、两个应用实例的关注恢复、账号隔离与忘记登录。"""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from ddm.app import MainWindow
from ddm.account_store import AccountStore
from ddm.account_dialog import AccountPlatformDialog
from ddm.dialogs import FollowImportDialog


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    room = {'room_id': 'douyin:1001', 'platform': 'douyin', 'anchor_uid': '101',
            'uname': 'Fixture anchor', 'title': 'Fixture title', 'live': True,
            'live_known': True, 'stream_url': {'secret': 'must-not-save'}}
    with TemporaryDirectory() as root, patch('ddm.account_store.AccountStore',
            side_effect=lambda kind: AccountStore(kind, root=root)), patch('ddm.app.QTimer.singleShot'):
        def window():
            return MainWindow([], [], state={'plugins_enabled': ['domestic_live']})
        first = window()
        first._accounts['douyin'] = {'uid': '42', 'uname': 'Fixture account'}
        first._platform_login_sessions['douyin'] = {'remember': True}
        with patch.dict(os.environ, DDM_NO_SAVE='0'):
            AccountStore('douyin', root=root).save([], first._accounts['douyin'])
            first._cache_douyin_follows([room])
        encrypted = AccountStore('douyin_follows', root=root).path.read_bytes()
        assert b'Fixture anchor' not in encrypted
        saved = AccountStore('douyin_follows', root=root).load_account()
        assert 'stream_url' not in saved['rooms'][0]
        first.close()
        app.processEvents()

        # 新实例读取磁盘，不依赖上一个窗口或浏览器。
        with patch.dict(os.environ, DDM_NO_SAVE='0'):
            second = window()
        provider = second.plugins.platforms['douyin']
        assert provider._anchor_uids == {'douyin:1001': '101'}
        with patch('ddm.platform_login.PlatformFollowDialog', side_effect=AssertionError('Browser reopened')):
            dialog = AccountPlatformDialog(second, {'douyin': provider}, import_follows=True, platform_kind='douyin')
            assert isinstance(dialog.page, FollowImportDialog) and dialog.page.rooms == saved['rooms']
            dialog.reject()
            dialog.deleteLater()
        with patch.dict(os.environ, DDM_NO_SAVE='0'):
            second._platform_login_sessions['douyin'] = {'remember': False}
            second._cache_douyin_follows([room])
            assert not AccountStore('douyin_follows', root=root).path.exists()
            second._platform_login_sessions['douyin']['remember'] = True
            with patch.object(AccountStore, 'save', side_effect=OSError('Fixture disk error')):
                second._cache_douyin_follows([room])
                assert second._douyin_follow_cache['rooms'] == [room]
            second._cache_douyin_follows([])
            assert AccountStore('douyin_follows', root=root).load_account()['rooms'] == []
            second._douyin_follow_cache = None
            second._restore_platform_accounts()
            assert second._douyin_follow_cache['rooms'] == []
            AccountStore('douyin', root=root).save([], {'uid': '99'})
            second._douyin_follow_cache = None
            second._restore_platform_accounts()
            assert second._douyin_follow_cache is None
            second._clear_platform_account('douyin')
            assert not AccountStore('douyin_follows', root=root).path.exists()
            AccountStore('douyin_follows', root=root).path.write_bytes(b'corrupt')
            second._restore_platform_accounts()
            assert second._douyin_follow_cache is None
        second.close()
        app.processEvents()
    print('PASS: encrypted restart cache; no browser; anchor identity restored; no signed URLs; empty/account/logout/forget/corruption')


if __name__ == '__main__':
    main()
