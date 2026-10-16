"""Login rejection uses the existing island and account warning, never normal network errors."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import Signal
from ddm import app as module, bili, theme
from ddm.account_dialog import AccountPlatformDialog
from ddm.plugins import LoginRequiredError
from dev.selfcheck_offline_badges import IdlePoller


class LoginPage(QDialog):
    accountCleared = Signal(str)
    busyChanged = Signal(bool)
    readFailed = Signal(str)
    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self._worker = None


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    with patch.object(module, 'StatusPoller', IdlePoller), patch.object(module, 'StatsPoller', IdlePoller):
        window = module.MainWindow([], [], layout_id='single')
        window.show()
        app.processEvents()
        tile = window.wall.tiles[0]
        tile.set_room(dict(room_id='douyu:123', live=True, uname='fixture', quality=10000))
        window._accounts['douyu'] = dict(uid='1', uname='fixture')
        try:
            platform = window.plugins.platforms['douyu']
            with patch.object(platform, 'play_url', side_effect=LoginRequiredError('斗鱼登录已失效，请重新登录')):
                resolver = bili.StreamResolver('douyu:123', 10000, platform=platform)
                resolver.run()
                assert resolver.login_required
            with patch.object(window, '_schedule_retry') as retry:
                window._on_resolve_failed(tile, '斗鱼登录已失效，请重新登录', login_required=True)
                retry.assert_not_called()
            app.processEvents()
            assert window._result_notice.isVisible(), 'Existing top island must show the login warning'
            assert window._accounts['douyu']['_login_expired']
            assert not window.sidebar.account_row._update_dot.isHidden()
            assert '重新登录' in window.sidebar.account_row.toolTip()
            assert '斗鱼' in window._login_choices()
            menu = window.sidebar.account_menu()
            # Warning row is present when Bilibili occupies the bottom account slot.
            with patch.object(bili, 'SESSION_DATA', 'fixture'):
                window._render_account(load_avatar=False)
                menu = window.sidebar.account_menu()
                from ddm.widgets import AccountRow
                assert any('登录已失效' in row.account_id.text() for row in menu.findChildren(AccountRow))
            with patch.object(window, '_show_notice') as notice:
                window._on_resolve_failed(tile, '斗鱼登录已失效，请重新登录', login_required=True)
                notice.assert_not_called()
            with patch('ddm.platform_login.PlatformFollowDialog', LoginPage):
                # Expired accounts must lead to a real login page, not "already logged in".
                dialog = AccountPlatformDialog(window, window._account_dialog_platforms(), platform_kind='douyu')
                assert not dialog.platform_buttons['douyu'].property('loggedIn')
                assert isinstance(dialog.page, LoginPage)
                dialog.close()
            window._accounts['douyu'] = dict(uid='1', uname='fixture')
            window._render_account(load_avatar=False)
            assert window.sidebar.account_row._update_dot.isHidden()
            assert '斗鱼' not in window._login_choices()
            with patch.object(platform, 'play_url', side_effect=RuntimeError('network timeout')):
                resolver = bili.StreamResolver('douyu:123', 10000, platform=platform)
                resolver.run()
                assert not resolver.login_required
            with patch.object(window, 'refresh_status'), patch.object(window, '_schedule_retry'), \
                    patch.object(window, '_show_notice') as notice:
                window._on_resolve_failed(tile, 'network timeout')
                notice.assert_not_called()
                assert not window._accounts['douyu'].get('_login_expired')
            assert tile.quality == 10000
            print('PASS: explicit login rejection -> island/account warning/relogin; duplicate suppression; successful login clears warnings; network errors preserve account and quality')
        finally:
            window.close()
            app.processEvents()


if __name__ == '__main__':
    main()
