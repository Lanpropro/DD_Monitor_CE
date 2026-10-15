"""Room combinations: real Qt actions, isolated disk, cell/audio identity and validation."""
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox, QMenu
from PySide6.QtTest import QTest
from ddm import config, layouts, room_presets, theme
from ddm.app import MainWindow
from ddm.room_presets_ui import thumbnail
from selfcheck_corner_resize import border_for, drag


def expect_invalid(snapshot):
    try:
        room_presets.validate(snapshot)
    except ValueError:
        return
    raise AssertionError(snapshot)


def main():
    app = QApplication([])
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    refresh_status = MainWindow.refresh_status
    app.setStyleSheet(theme.qss())
    fixture = [dict(room_id=str(1000 + i) if i != 2 else '', uname=f'主播 {i + 1}',
                    live=True, live_known=True, volume=0 if i == 2 else (100 if i == 5 else 20 + i * 7),
                    muted=i % 2 == 0, audio_channel=(0, 3, 4)[i % 3]) for i in range(6)]
    with tempfile.TemporaryDirectory(prefix='ddm-combinations-') as temporary, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'state.json')))
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account', 'sync_danmaku',
                       'load_avatars_for', 'load_room_avatars', 'load_cached_covers', 'load_cached_avatars'):
            stack.enter_context(patch.object(MainWindow, method))
        window = MainWindow(deepcopy(fixture), deepcopy(fixture), layout_id='corner',
                            state={'plugins_enabled': [], 'settings': {'auto_update': False,
                                   'preview_on_hover': False, 'recording_replay_enabled': False}})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.setGeometry(-10000, -10000, 1600, 1000)
        window.show()
        app.processEvents()
        try:
            original_follow = deepcopy(window.sidebar.rooms())
            handle, point = border_for(window.wall, ('root/0', 0))
            drag(app, handle, QPoint(-70, 0), pos=point)
            a = window.room_preset_snapshot()
            window.sidebar.open_layout_picker()
            picker = window.sidebar._picker
            picker.set_group('直播间组合')
            page = picker.presets_page
            assert page.isVisible() and not picker.reset_button.isVisible()
            with patch('ddm.room_presets_ui.QInputDialog.getText', return_value=('比赛', True)):
                QTest.mouseClick(page.save_button, Qt.LeftButton)
            key = window.room_presets['items'][0]['id']
            assert page.cards[key].isChecked()
            assert room_presets.same(room_presets.validate(window.room_presets['items'][0]), a)
            assert thumbnail(a).size().width() == 224
            picker.close()
            # Keep the original players while swapping room locations and applying sounds.
            players = {}
            for tile in window.wall.tiles:
                if tile.room.get('room_id'):
                    player = Mock()
                    player.needs_audio_restart.return_value = False
                    players[str(tile.room['room_id'])] = player
                    window.players[tile] = player
            handles = {str(tile.room['room_id']): int(tile.video.winId()) for tile in window.wall.tiles
                       if tile.room.get('room_id')}
            window.wall.tiles[0], window.wall.tiles[5] = window.wall.tiles[5], window.wall.tiles[0]
            window.wall.relayout(force=True)
            for tile in window.wall.tiles:
                tile.set_volume(82)
                tile.set_audio_channel(0)
                tile.set_muted(False)
            handle, point = border_for(window.wall, ('root', 0))
            drag(app, handle, QPoint(0, -40), pos=point)
            second = window.save_room_preset('日常')
            b = window.room_preset_snapshot()
            window.start_tile.reset_mock()
            assert window.apply_room_preset(key)
            assert room_presets.same(window.room_preset_snapshot(), a)
            window.start_tile.assert_not_called()
            for tile in window.wall.tiles:
                rid = str(tile.room.get('room_id') or '')
                if rid:
                    assert window.players[tile] is players[rid]
                    assert int(tile.video.winId()) == handles[rid]
                    players[rid].release.assert_not_called()
                    players[rid].set_volume.assert_called_with(tile.volume)
                    players[rid].set_muted.assert_called_with(tile.muted)
            window._save_timer.stop()
            assert window.apply_room_preset(key)
            assert not window._save_timer.isActive(), 'identical application must not write again'
            assert window.apply_room_preset(second)
            assert room_presets.same(window.room_preset_snapshot(), b)
            assert room_presets.same(room_presets.validate(window.room_presets['items'][0]), a)
            window.rename_room_preset(second, '日常观看')
            try:
                window.rename_room_preset(second, '比赛')
            except ValueError:
                pass
            else:
                raise AssertionError('duplicate names must be rejected')
            # Exercise the actual card management actions, including cancel and overwrite.
            window.sidebar.open_layout_picker()
            picker = window.sidebar._picker
            picker.set_group('直播间组合')
            page = picker.presets_page
            with patch('ddm.room_presets_ui.QInputDialog.getText', return_value=('取消保存', False)):
                QTest.mouseClick(page.save_button, Qt.LeftButton)
                assert len(window.room_presets['items']) == 2
            first_record = window.room_presets['items'][0]
            def choose(text):
                def create(parent):
                    menu = QMenu(parent)
                    menu.exec = lambda *_: next(action for action in menu.actions() if action.text() == text)
                    return menu
                return create
            with patch('ddm.room_presets_ui.QMenu', choose('重命名')), \
                    patch('ddm.room_presets_ui.QInputDialog.getText', return_value=('比赛观察', True)):
                page.manage(first_record, page.save_button)
            assert first_record['name'] == '比赛观察'
            window.rename_room_preset(key, '比赛')
            window.wall.tiles[0].set_volume(86)
            b = window.room_preset_snapshot()
            with patch('ddm.room_presets_ui.QMenu', choose('用当前画面更新此组合')), \
                    patch('ddm.room_presets_ui.QMessageBox.question', return_value=QMessageBox.Yes):
                page.manage(next(item for item in window.room_presets['items'] if item['id'] == second), page.save_button)
            assert room_presets.same(room_presets.validate(window.room_presets['items'][1]), b)
            discarded = window.save_room_preset('待删除')
            with patch('ddm.room_presets_ui.QMenu', choose('删除组合')), \
                    patch('ddm.room_presets_ui.QMessageBox.question', return_value=QMessageBox.Yes):
                page.manage(next(item for item in window.room_presets['items'] if item['id'] == discarded), page.save_button)
            assert not any(item['id'] == discarded for item in window.room_presets['items'])
            assert room_presets.same(window.room_preset_snapshot(), b)
            picker.close()
            # Invalid slots fail before touching the live wall.
            for field, value in [('cell', 99), ('volume', 101), ('audio_channel', 99), ('muted', 'yes')]:
                broken = deepcopy(a)
                broken['slots'][0][field] = value
                expect_invalid(broken)
            broken = deepcopy(a)
            broken['layout']['ratios']['width'] = float('nan')
            expect_invalid(broken)
            broken = deepcopy(a)
            broken['slots'][1]['room_id'] = broken['slots'][0]['room_id']
            expect_invalid(broken)
            window.room_presets['items'].append(dict(broken, id='broken', name='损坏组合'))
            before = window.room_preset_snapshot()
            try:
                window.apply_room_preset('broken')
            except ValueError:
                pass
            assert room_presets.same(before, window.room_preset_snapshot())
            window.sidebar.open_layout_picker()
            picker = window.sidebar._picker
            picker.set_group('直播间组合')
            assert not picker.presets_page.cards['broken'].isEnabled()
            window.delete_room_preset('broken')
            picker.close()
            # Removal of a recording room asks once, and refusal leaves all state intact.
            target = deepcopy(a)
            target['slots'][0].update(room_id='9999', label='待观看主播')
            window.room_presets['items'].append(dict(target, id='outside', name='未关注房间'))
            window.apply_room_preset(key)
            tile = window.wall.tiles[0]
            window.recorder.sessions[tile] = Mock(recording=True, stopping=False)
            with patch('ddm.app.QMessageBox.question', return_value=QMessageBox.No) as question:
                assert not window.apply_room_preset('outside')
                question.assert_called_once()
                assert room_presets.same(window.room_preset_snapshot(), a)
            window.recorder.sessions.clear()
            # Accepted recording replacement must retain the old Qt tile until asynchronous finalization.
            window.recorder.sessions[tile] = Mock(recording=True, stopping=False, process=Mock())
            with patch('ddm.app.QMessageBox.question', return_value=QMessageBox.Yes):
                assert window.apply_room_preset('outside')
            assert tile in window._preset_retired_tiles and tile not in window.wall.tiles
            window.recorder.sessions.pop(tile)
            window._record_state_changed(tile)
            assert tile not in window._preset_retired_tiles
            assert window.apply_room_preset('outside')
            assert window.wall.tiles[0].room['room_id'] == '9999'
            assert window.wall.tiles[0]._status_text == '等待刷新直播状态'
            assert window.sidebar.rooms() == original_follow
            # Status polling must include wall-only rooms; an old response cannot overwrite their ID.
            poller = Mock()
            window._poller = None
            with patch('ddm.app.StatusPoller', return_value=poller) as factory:
                refresh_status(window, force=True)
                assert '9999' in factory.call_args.args[0]
            window._poller = None
            assert window.apply_room_preset(key)
            window._on_status_updated({'9999': {'live': True, 'title': '', 'viewers': ''}})
            assert room_presets.same(window.room_preset_snapshot(), a)
            # Fullscreen saves original wall and original mute, never the temporary solo state.
            window._fullscreen_audio_saved = {tile: tile.muted for tile in window.wall.tiles}
            window._room_preset_fullscreen_layout = deepcopy(a['layout'])
            window._fullscreen_tile = window.wall.tiles[0]
            for tile in window.wall.tiles:
                tile.set_muted(True)
            assert room_presets.same(window.room_preset_snapshot(), a)
            window._fullscreen_tile = None
            for tile, muted in window._fullscreen_audio_saved.items():
                tile.set_muted(muted)
            window._fullscreen_audio_saved.clear()
            # Actual disk round trip and restart do not auto-apply a combination.
            state = window.current_state()
            with patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
                config.save(state)
            saved = config.load()
            assert saved['room_presets'] == window.room_presets
            resumed = MainWindow([], [], layout_id='3x3', state=saved)
            try:
                assert resumed.room_presets == window.room_presets
                assert not any(tile.room.get('room_id') for tile in resumed.wall.tiles)
            finally:
                resumed.close()
            window.delete_room_preset(second)
            assert room_presets.same(window.room_preset_snapshot(), a)
            # A separate direction and moved danmaku cell restore exact physical cell IDs.
            for identifier in ('3x3', 'dm_main3', 'portrait_dm4', 'corner'):
                window._on_layout_changed(identifier)
                app.processEvents()
                if identifier == 'dm_main3':
                    window.wall.move_danmaku_to_tile(window.wall.tiles[0])
                snapshot = window.room_preset_snapshot()
                saved_id = window.save_room_preset(identifier)
                window._on_layout_changed('2x2' if identifier != '2x2' else 'corner')
                assert window.apply_room_preset(saved_id)
                assert room_presets.same(snapshot, window.room_preset_snapshot()), identifier
            window.sidebar.open_layout_picker()
            window.sidebar._picker.set_group('直播间组合')
            app.processEvents()
            directory = Path(__file__).resolve().parents[1] / 'work'
            directory.mkdir(exist_ok=True)
            for record in window.room_presets['items']:
                record['name'] = {'3x3': '九宫观看', 'dm_main3': '比赛弹幕',
                                  'portrait_dm4': '竖屏观看', 'corner': '六路观看'}.get(record['name'], record['name'])
            for mode in ('light', 'dark'):
                theme.apply(mode)
                window.sidebar._picker.presets_page.refresh()
                QTest.qWait(30)
                window.sidebar._picker.grab().save(str(directory / f'room-presets-{mode}.png'))
            window.sidebar._picker.grab().save(str(directory / 'room-presets-preview.png'))
        finally:
            window.close()
            app.processEvents()
    print('PASS: combination Qt save/cards, validation, audio/cell/ratio/player identity, recording cancel, '
          'wall-only status, fullscreen mute, isolated disk/restart, direction and moved danmaku')


if __name__ == '__main__':
    main()
