"""完整关注账号、已知房间复用、待识别导入与可取消补充读取。"""
import json
import os
from pathlib import Path
import sys
import threading
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import requests
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ddm.account_dialog import AccountPlatformDialog
from ddm.account_store import AccountStore
from ddm.app import MainWindow
from ddm.platform_login import PlatformFollowLoader
from dev.selfcheck_account_dialog import dispose
from dev.selfcheck_platform_follows import wait_for
from plugins_user.domestic_live.plugin import DouyinPlatform, LivePlatformsPlugin


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    provider = DouyinPlatform()
    provider.restore_follow_rooms([{'room_id': 'douyin:1002', 'anchor_uid': '102'}])
    users = [{'uid': str(101 + index), 'nickname': 'Account ' + str(index),
              'sec_uid': 'sec' + str(index)} for index in range(11)]
    users[0]['room_data'] = {'status': 2, 'owner': {'id_str': '101', 'web_rid': '1001'}}
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps({'status_code': 0, 'followings': users, 'has_more': 0}).encode()
    session = Mock()
    session.get.return_value = response
    with patch.object(provider, 'account_info', return_value={'uid': '42'}), patch.object(
            provider, '_follow_room', side_effect=AssertionError('Read should not resolve rooms')):
        accounts = provider.follow_accounts(session, lambda: False)
    assert len(accounts) == 11
    assert [account['room_id'] for account in accounts[:3]] == ['douyin:1001', 'douyin:1002', '']
    assert accounts[0]['live'] and not accounts[1]['live_known']
    assert len({account['anchor_uid'] for account in accounts}) == 11

    # 登录读取线程选择完整账号接口，不再只返回可播放的房间。
    fixture = SimpleNamespace(account_info=lambda *_: {'uid': '42'},
                              follow_accounts=lambda *_: accounts,
                              follow_rooms=Mock(side_effect=AssertionError('Legacy room filter')))
    loader = PlatformFollowLoader(fixture, requests.cookies.RequestsCookieJar())
    loaded = []
    loader.loaded.connect(loaded.append)
    loader.run()
    assert loaded == [accounts]

    # 映射由插件保存；重建插件后仍能恢复，不依赖登录账号或本轮接口结果。
    saved = {}
    provider._context = SimpleNamespace(set_setting=lambda key, value: saved.update({key: value}))
    provider.restore_follow_rooms(accounts)
    restored = []
    context = SimpleNamespace(setting=lambda key, default: saved.get(key, default),
                              register_platform=restored.append)
    LivePlatformsPlugin().on_load(context)
    assert restored[-1]._anchor_uids == {'douyin:1002': '102', 'douyin:1001': '101'}
    with patch.object(provider, '_follow_room', return_value={}):
        assert provider.resolve_follow_account(accounts[1], lambda: False) == accounts[1]
    with patch.object(provider, '_follow_room', return_value={'web_rid': '1003', 'status': 4}):
        resolved = provider.resolve_follow_account(accounts[2], lambda: False)
    assert resolved['room_id'] == 'douyin:1003' and not resolved['live'] and resolved['live_known']
    with patch.object(provider, '_follow_room', return_value={'web_rid': '9999', 'status': 2}):
        try:
            provider.resolve_follow_account(accounts[0], lambda: False)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Identity mismatch accepted')

    with patch('ddm.app.QTimer.singleShot'):
        owner = MainWindow([], [], state={'plugins_enabled': []})
    owner._accounts['douyin'] = {'uid': '42'}
    owner._start_avatar_loader = lambda *_: None
    owner.plugins.platforms['douyin'] = provider
    target_folder = owner.sidebar.create_folder('Pending anchors')
    provider._context = None
    with TemporaryDirectory() as root, patch('ddm.account_store.AccountStore',
            side_effect=lambda kind: AccountStore(kind, root=root)):
        owner._cache_douyin_follows(accounts)
        dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
        page = dialog.page
        assert page.list.count() == 11 and '待识别' in page.list.item(2).text()
        assert '状态待刷新' in page.list.item(1).text()
        page.list.item(2).setCheckState(Qt.Checked)
        # 补充在后台；选择、切换及取消操作仍可用。停止后迟到结果不能改勾选条目。
        entered, release = threading.Event(), threading.Event()
        def slow(account, cancelled):
            entered.set()
            release.wait(3)
            return dict(account, room_id='douyin:9999')
        with patch.object(provider, 'resolve_follow_account', side_effect=slow):
            page.resolve_button.click()
            wait_for(app, entered.is_set)
            worker = dialog._account_resolver
            assert page.import_button.isEnabled() and all(b.isEnabled() for b in dialog.platform_buttons.values())
            page.resolve_button.click()
            release.set()
            wait_for(app, lambda: dialog._account_resolver is None)
            assert page.list.item(2).data(Qt.UserRole)['room_id'] == ''
            assert worker not in owner._platform_info_running
        # 一个识别失败不能吞掉其余账号；原勾选在补充后仍保留。
        def resolve(account, cancelled):
            if account['anchor_uid'] == '102':
                raise requests.Timeout('Fixture')
            return resolved if account['anchor_uid'] == '103' else account
        with patch.object(provider, 'resolve_follow_account', side_effect=resolve):
            page.resolve_button.click()
            wait_for(app, lambda: dialog._account_resolver is None)
        assert page.list.count() == 11 and page.selected()[0]['room_id'] == 'douyin:1003'
        page.list.item(3).setCheckState(Qt.Checked)
        page._select_folder(next(action for action in page.folder_button.menu().actions()
                                if action.data() == target_folder))
        with patch.dict(os.environ, DDM_NO_SAVE='0'):
            AccountStore('douyin', root=root).save([], {'uid': '42'})
            page.accept()
        assert [room['room_id'] for room in dialog.rooms] == ['douyin:1003']
        assert dialog.pending_count == 1
        saved_cache = AccountStore('douyin_follows', root=root).load_account()
        assert len(saved_cache['rooms']) == 11 and saved_cache['pending'][0]['anchor_uid'] == '104'
        assert saved_cache['pending'][0]['pending_folder_id'] == target_folder
        assert all(room.get('room_id') for room in dialog.rooms)
        dispose(app, dialog)

        # 重启恢复完整列表及待导入选择；取消勾选后保存，不应下一次又默认勾选。
        owner._douyin_follow_cache = None
        with patch.dict(os.environ, DDM_NO_SAVE='0'):
            owner._restore_platform_accounts()
        assert len(owner._douyin_follow_cache['rooms']) == 11
        dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
        assert dialog.page.selected()[0]['anchor_uid'] == '104'
        dialog.page._check_all(False)
        dialog.page.accept()
        dispose(app, dialog)
        dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
        assert not dialog.page.selected() and dialog._account_resolver is None
        dispose(app, dialog)
        # 待识别账号后来得到房间号：只导入真房间，保留原文件夹，不自动播放，也不重复添加。
        owner._cache_douyin_follows(accounts, pending=[dict(accounts[3], pending_folder_id=target_folder)])
        dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
        dialog.page.update_account(dict(dialog.page.selected()[0], room_id='douyin:1004', live_known=True))
        dialog.page.accept()
        with patch.object(owner, 'load_avatars_for'), patch.object(owner, '_refresh_meta'), patch(
                'ddm.online_ui.show_result'):
            owner._import_selected_follows(dialog.rooms)
            owner._import_selected_follows(dialog.rooms)
        assert [room['room_id'] for room in owner.sidebar.rooms()] == ['douyin:1004']
        assert owner.sidebar.folder_for('douyin:1004') == target_folder
        assert not any(tile.room.get('room_id') for tile in owner.wall.tiles)
        dispose(app, dialog)
        owner._cache_douyin_follows(accounts, pending=[accounts[3]])
        dialog = AccountPlatformDialog(owner, {'douyin': provider}, import_follows=True, platform_kind='douyin')
        owner._accounts['douyin'] = {'uid': '99'}
        dialog._show_rooms(accounts)
        assert not dialog.page.selected() and owner._douyin_follow_cache['pending'] == []
        dispose(app, dialog)
    owner.close()
    app.processEvents()
    print('PASS: all 11 accounts; cached offline identity; plugin mapping restart; separate pending import; cancellation; failure isolation; encrypted restore; selection preservation')


if __name__ == '__main__':
    main()
