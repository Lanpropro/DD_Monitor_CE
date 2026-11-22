"""离线回归：两处拼音搜索、原筛选语义、勾选保留与缓存。"""
import os
from pathlib import Path
import sys
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication
from ddm import config, theme
from ddm.app import MainWindow
from ddm.dialogs import FollowImportDialog
from ddm.search import _pinyin_keys, matches_query, matches_text


def check_shared_queries():
    text = '字幕工具 42 Example 小明'
    for query in ('', '   ', '字幕', 'zimu', 'ZM', 'xiaoming', 'XM', '42', 'EXAMPLE',
                  'zm 42 example xm', 'xiao ming'):
        assert matches_query(text, query), query
    for query in ('zm 43', 'zimu missing', 'xiaohong', '43', 'reverse subtitle'):
        assert not matches_query(text, query), query
    assert matches_text('小明', 'xiao ming'), 'Keep the existing single-query pinyin contract'
    assert not matches_text('Alice', 'al ice'), 'Do not change the original substring contract'
    entries = ['重庆作者', '小明', 'Alice']
    original = list(entries)
    assert [text for text in entries if matches_query(text, 'XM')] == ['小明']
    assert entries == original, 'Filtering must not rewrite caller order'
    print('PASS: shared empty/Chinese/pinyin/initials/ID/English/AND query contract and original order')


def check_plugin_search(app):
    from ddm.plugin_store_ui import PluginStorePage
    from ddm.settings_plugins import PluginSettingsPage
    entries = [dict(id='caption_tools', name='字幕工具', description='实时翻译', version='1.0',
                    enabled=True, status='已加载'),
               dict(id='recorder_2', name='录制助手', description='保存直播', version='1.0',
                    enabled=False, status='已禁用')]
    offers = [dict(entry, version='2.0', available=True, author=author)
              for entry, author in zip(entries, ('小明', '重庆作者'))]
    with TemporaryDirectory(prefix='ddm-plugin-pinyin-') as directory, \
            patch.object(config, 'data_root', return_value=directory), \
            patch.object(PluginStorePage, 'open_catalog'):
        manager = SimpleNamespace(catalog=lambda: entries, plugins_dir=str(Path(directory) / 'plugins'),
                                  enabled={'caption_tools'}, _removed=set())
        page = PluginSettingsPage(manager)
        store = page.store_page
        try:
            store.offers = offers
            store.show_offers(offers)
            page._show_update_notes(offers)
            original_button = store.buttons['caption_tools']
            cases = [('字幕', {'caption_tools'}), ('zimu', {'caption_tools'}), ('ZM', {'caption_tools'}),
                     ('ssfy', {'caption_tools'}), ('XM', {'caption_tools'}), ('cqzz', {'recorder_2'}),
                     ('CAPTION', {'caption_tools'}), ('2', {'recorder_2'}),
                     ('zimu xm caption', {'caption_tools'}), ('zm 2', set()), ('2.0', set())]
            for query, expected in cases:
                store.search.setText(query)
                page.installed_browser.search.setText(query)
                assert {key for key, card in store._offer_cards.items() if not card.isHidden()} == expected, query
                assert {key for key, card in page._installed_cards.items() if not card.isHidden()} == expected, query
            store.search.setText('zimu')
            store.filter.setCurrentIndex(1)
            assert all(card.isHidden() for card in store._offer_cards.values()), 'Retain the uninstalled filter'
            store.filter.setCurrentIndex(3)
            assert not store._offer_cards['caption_tools'].isHidden(), 'Combine pinyin with the update filter'
            page.installed_browser.search.setText('lz')
            page.installed_browser.filter.setCurrentIndex(1)
            assert all(card.isHidden() for card in page._installed_cards.values()), 'Retain the enabled filter'
            page.installed_browser.filter.setCurrentIndex(2)
            assert not page._installed_cards['recorder_2'].isHidden()
            page.checks['recorder_2'].setChecked(True)
            assert page._installed_cards['recorder_2'].isHidden(), 'Keep unsaved enable choices when filtering'
            assert page.checks['recorder_2'].isChecked()
            store.filter.setCurrentIndex(0)
            store.search.clear()
            store.sort.setCurrentIndex(1)
            expected = [entry['id'] for entry in sorted(offers, key=lambda entry: (entry['name'].casefold(), entry['id']))]
            assert [store.cards.itemAt(i).widget() for i in range(store.cards.count())] == [store._offer_cards[key] for key in expected]
            store.search.setText('xm')
            store.search.clear()
            assert [store.cards.itemAt(i).widget() for i in range(store.cards.count())] == [store._offer_cards[key] for key in expected]
            assert store.buttons['caption_tools'] is original_button, 'Searching must preserve the active action identity'
        finally:
            store.stop()
            page.close()
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print('PASS: installed/store pinyin fields, ID/English/AND, original filters, enable drafts, sorting and action identity')


def main():
    check_shared_queries()
    if sys.argv[1:] == ['--query-only']:
        return
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    check_plugin_search(app)
    for text, query in [('小明', 'xiaoming'), ('小明', 'XM'), ('小明', 'xiao ming'),
                        ('重庆主播', 'chongqing'), ('重庆主播', 'cqzb'),
                        ('莉蔻Liko', 'likouliko'), ('莉蔻Liko', 'lkliko'),
                        ('呂小明', 'lvxiaoming'), ('呂小明', 'lxm'),
                        ('大东彦', 'ddy'), ('大东彦', 'DADONGYAN'),
                        ('大橙橙橙子', 'dcccz'), ('大橙橙橙子', 'dcz'),
                        ('Alice', 'ALICE'), ('小明', '小明')]:
        assert matches_text(text, query), (text, query)
    assert not matches_text('小明', 'xiaohong')
    assert not matches_text('大东彦', 'ydd'), 'Initials must retain their order'
    assert not matches_text('主播111号', 'zb1h'), 'Do not collapse digits in abbreviations'
    assert not matches_text('Alice', 'al ice'), 'Keep the original English substring rule'
    rooms = [dict(room_id='9101', uname='小明', title='深夜音乐', live=True),
             dict(room_id='9102', uname='重庆主播', title='小明', live=False),
             dict(room_id='9103', display_room_id='70342', uname='Alice', title='Morning Coffee', live=True),
             dict(room_id='9104', uname='大橙橙橙子', title='', live=True),
             dict(room_id='9105', uname='大东彦', title='', live=True)]
    with patch('ddm.app.QTimer.singleShot'):
        window = MainWindow([], [], state={'plugins_enabled': []})
    dialog = FollowImportDialog(rooms, {'9101'})
    try:
        for room in rooms:
            window.sidebar.add_room(room)
        folder = window.sidebar.create_folder('音乐区')
        window.sidebar.move_to_folder(['9101'], folder)
        def sidebar(query):
            window.sidebar.search.setText(query)
            return {item.room['room_id'] for item in window.sidebar.visible_items()}
        def imported(query):
            dialog.search_edit.setText(query)
            return {dialog.list.item(i).data(Qt.UserRole)['room_id'] for i in range(dialog.list.count())
                    if not dialog.list.item(i).isHidden()}
        for query, ids in [('xiaoming', {'9101', '9102'}), ('xm', {'9101', '9102'}),
                           ('xiaoming 9101', {'9101'}), ('yinyuequ', {'9101'}),
                           ('yyq', {'9101'}), ('ALICE', {'9103'}),
                           ('Morning', {'9103'}), ('shenyeyinyue', {'9101'}),
                           ('深夜音乐', {'9101'}), ('xiaoming 深夜', {'9101'}),
                           ('70342 coffee', {'9103'}), ('9102', {'9102'}),
                           ('dcz', {'9104'}), ('dcccz', {'9104'}), ('ddy', {'9105'})]:
            assert sidebar(query) == ids, query
        assert sidebar('小明') == {'9101', '9102'}
        window.sidebar.navigation.set_live_only(True)
        assert sidebar('小明') == {'9101'}
        window.sidebar.navigation.set_live_only(False)

        assert sidebar('Evening') == set()
        window.room_status.apply_status({'9103': dict(live=True, title='Evening Coffee')})
        assert sidebar('Evening') == {'9103'}, 'Title changes must update the active search'
        assert sidebar('Morning') == set()
        for query, ids in [('xiaoming', {'9101'}), ('XM', {'9101'}),
                           ('xiao ming', {'9101'}), ('chongqing', {'9102'}),
                           ('cqzb', {'9102'}), ('Alice', {'9103'}),
                           ('dcz', {'9104'}), ('dcccz', {'9104'}), ('DDY', {'9105'}),
                           ('shenyeyinyue', set()), ('9101', set())]:
            assert imported(query) == ids, query
        imported('cqzb')
        dialog._check_all(True)
        assert {r['room_id'] for r in dialog.selected()} == {'9101', '9102'}
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor('red'))
        dialog.set_avatar('9102', pixmap)
        imported('XM')
        assert not dialog.list.item(1).icon().isNull()
        imported('')
        assert {r['room_id'] for r in dialog.selected()} == {'9101', '9102'}
        dialog.rooms[0]['uname'] = '小红'
        # Resolve the current row data, as asynchronous account updates do.
        room = dialog.list.item(0).data(Qt.UserRole)
        room['uname'] = '小红'
        dialog.list.item(0).setData(Qt.UserRole, room)
        assert imported('xiaohong') == {'9101'}
        assert imported('xiaoming') == set()
    finally:
        dialog.close()
        window.close()
    many = [dict(room_id=str(10000+i), uname=f'测试主播{i}', title='', live=i % 2 == 0)
            for i in range(750)]
    large = FollowImportDialog(many, set())
    try:
        large.show()
        _pinyin_keys.cache_clear()
        start = time.perf_counter()
        large.search_edit.setText('ceshizhubo')
        cold_ms = (time.perf_counter() - start) * 1000
        from PySide6.QtTest import QTest
        for _ in range(500):
            if not large._populating:
                break
            QTest.qWait(10)
        assert not large._populating, 'All fetched follows must eventually be available'
        assert all(not large.list.item(i).isHidden() for i in range(750))
        misses = _pinyin_keys.cache_info().misses
        start = time.perf_counter()
        large.search_edit.setText('cszb')
        warm_ms = (time.perf_counter() - start) * 1000
        assert _pinyin_keys.cache_info().misses == misses, 'Typing must reuse cached transliterations'
        assert all(not large.list.item(i).isHidden() for i in range(750))
        large._check_live()
        assert len(large.selected()) == 375
        assert _pinyin_keys.cache_info().maxsize == 8192
        print(f'PASS: 750 Chinese names, cold={cold_ms:.1f}ms, cached={warm_ms:.1f}ms')
    finally:
        large.close()
    root = Path(__file__).resolve().parents[1]
    assert 'pypinyin==0.55.0' in (root/'requirements.txt').read_text(encoding='utf-8')
    assert '--collect-all pypinyin' in (root/'dev/build_release.ps1').read_text(encoding='utf-8-sig')
    assert 'Permission is hereby granted' in (root/'ddm/assets/licenses/pypinyin-LICENSE.txt').read_text(encoding='utf-8')
    print('PASS: pinyin, initials, original filters, selections, avatars, changed names and packaging metadata')


if __name__ == '__main__':
    main()
