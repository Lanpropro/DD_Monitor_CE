"""海外登录引导：官方链接、配置收起、浏览器重试、授权码复制和取消隔离。"""
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import theme
from ddm.account_store import AccountStore
from ddm.oauth_login import OAuthAccountDialog


def main():
    app = QApplication([])
    # offscreen 平台不会自动发现 Windows 字体，显式加载以验证中文截图。
    if Path('C:/Windows/Fonts/msyh.ttc').exists():
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(theme.FONT_DEFAULT, 10))
    app.setStyleSheet(theme.qss())
    app.setQuitOnLastWindowClosed(False)
    preview = ROOT / 'work' / 'oauth-guide'
    preview.mkdir(parents=True, exist_ok=True)
    expected = {
        'twitch': ['https://dev.twitch.tv/console/apps',
                   'https://dev.twitch.tv/docs/authentication/register-app/',
                   'https://dev.twitch.tv/console/apps'],
        'youtube': ['https://console.cloud.google.com/',
                    'https://console.cloud.google.com/apis/library/youtube.googleapis.com',
                    'https://console.cloud.google.com/auth/audience',
                    'https://console.cloud.google.com/auth/clients'],
    }
    with TemporaryDirectory() as root, patch('ddm.oauth_login.AccountStore',
            side_effect=lambda kind: AccountStore(kind, root=root)):
        for kind in ('twitch', 'youtube'):
            page = OAuthAccountDialog(SimpleNamespace(kind=kind), login_only=True)
            page.show()
            app.processEvents()
            assert page.setup_button.isChecked() and page.setup.isVisible()
            assert page.read_button.isVisible() and page.isVisible()
            assert not hasattr(page, 'browser')
            with patch('ddm.oauth_login.QDesktopServices.openUrl', return_value=True) as opened:
                for label, url in zip(page.setup_links, expected[kind], strict=True):
                    assert re.search('href="([^"]+)"', label.text()).group(1) == url
                    label.linkActivated.emit(url)
                    assert opened.call_args.args[0].toString() == url
                QTest.mouseClick(page.setup_page_button, Qt.LeftButton)
                assert opened.call_args.args[0].toString() == expected[kind][0]
                assert page._worker is None
            page._read()
            assert page._worker is None and page.setup_button.isChecked()
            # 小窗口中只滚动配置说明，底部授权与取消按钮始终可见。
            page.resize(620, 330)
            app.processEvents()
            assert page.rect().contains(page.read_button.mapTo(page, page.read_button.rect().bottomRight()))
            assert page.setup.verticalScrollBar().maximum() > 0
            page.setup.verticalScrollBar().setValue(page.setup.verticalScrollBar().maximum())
            app.processEvents()
            assert page.setup.viewport().rect().contains(
                page.client_id.mapTo(page.setup.viewport(), page.client_id.rect().center()))
            page.setup.verticalScrollBar().setValue(0)
            page.resize(700, 510)
            app.processEvents()
            page.grab().save(str(preview / (kind + '.png')))

            # 外部浏览器初次打开失败不丢失当前授权，可重开同一页面并复制设备码。
            page.setup_button.setChecked(False)
            page._worker = Mock()
            with patch('ddm.oauth_login.QDesktopServices.openUrl', side_effect=[False, True]) as opened:
                page._open_browser('https://www.twitch.tv/activate?device-code=FIXTURE', 'FIXTURE')
                app.processEvents()
                assert page.browser_actions.isVisible() and page.copy_code_button.isVisible()
                assert '无法打开' in page.status.text()
                page._worker.cancel.assert_not_called()
                QTest.mouseClick(page.browser_button, Qt.LeftButton)
                assert opened.call_count == 2
                assert '等待结果' in page.status.text()
                assert opened.call_args.args[0] == opened.call_args_list[0].args[0]
                QTest.mouseClick(page.copy_code_button, Qt.LeftButton)
                assert QApplication.clipboard().text() == 'FIXTURE'
                page.cancel_read()
                page._worker.cancel.assert_called_once()
                assert not page.browser_actions.isVisible() and not page.code.text()
                page._open_browser('https://www.twitch.tv/activate', 'LATE')
                assert opened.call_count == 2 and page._user_code == ''
            page._worker = None
            page._read_cancelled = False
            with patch('ddm.oauth_login.QDesktopServices.openUrl', return_value=True):
                page._open_browser('https://accounts.google.com/o/oauth2/v2/auth', '')
                assert page.copy_code_button.isHidden() and not page.code.text()

            # 正确桌面客户端 JSON 可导入并收起说明，Web 客户端不能冒充桌面客户端。
            if kind == 'youtube':
                assert page.import_button.isVisible()
                path = Path(root) / 'desktop.json'
                client = {'client_id': 'fixture.apps.googleusercontent.com', 'client_secret': 'fixture-secret'}
                path.write_text(json.dumps({'installed': client}), encoding='utf-8')
                with patch('ddm.oauth_login.QFileDialog.getOpenFileName', return_value=(str(path), '')):
                    QTest.mouseClick(page.import_button, Qt.LeftButton)
                    assert page.client_id.text() == client['client_id']
                    assert not page.setup_button.isChecked()
                    path.write_text(json.dumps({'web': client}), encoding='utf-8')
                    QTest.mouseClick(page.import_button, Qt.LeftButton)
                    assert '桌面应用' in page.status.text()
            page.close()
            page.deleteLater()
            app.processEvents()

            # 重启后的已有配置默认收起，但仍能展开查看和修改。
            AccountStore(kind + '_oauth_client', root=root).save([], {
                'client_id': 'fixture-client' if kind == 'twitch' else 'fixture.apps.googleusercontent.com'})
            other = OAuthAccountDialog(SimpleNamespace(kind=kind), login_only=True)
            other.show()
            app.processEvents()
            assert not other.setup_button.isChecked() and not other.setup.isVisible()
            QTest.mouseClick(other.setup_button, Qt.LeftButton)
            assert other.setup.isVisible()
            other.close()
            other.deleteLater()
            app.processEvents()
    QApplication.clipboard().clear()
    print('PASS: numbered official links; browser buttons; compact/scrollable setup; JSON import; reopen/copy; cancel isolation')


if __name__ == '__main__':
    main()
