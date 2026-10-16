"""Local skin persistence, media playback, ownership and non-interference."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from contextlib import ExitStack
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
platform._wmi_query = lambda *a: (_ for _ in ()).throw(OSError('Isolated skin test'))
from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFontDatabase, QImage, QRegion
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QToolButton, QWidget
from ddm import app as module, config, motion, theme
from ddm.dialogs import SettingsDialog
from ddm.plugins import PluginManager, read_manifest
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from ddm.skins import import_asset, validate_asset
from ddm.skin_settings import PartSettings, SkinSettings, SkinAssetDropArea
from dev.selfcheck_tile_fullscreen import SilentPoller


def check_parts(app):
    from ddm.skin_parts import validate_parts, values_for, part_for, icon_path
    from ddm.skin_settings import PartSettings
    from ddm.online_ui import ResultNotice
    from PySide6.QtWidgets import QMenu

    def check_scene_background(bar):
        backdrop = QColor('#d123a7')
        image = QImage(bar.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(backdrop)
        bar.render(image, QPoint(), QRegion(), QWidget.DrawChildren)
        for point in (QPoint(0, 0), QPoint(bar.width() - 1, bar.height() - 1)):
            assert image.pixelColor(point) == backdrop, 'Scene tab strip must expose the page background'

    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory)
        stack.enter_context(patch.object(config, 'REPO', directory))
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars'):
            stack.enter_context(patch.object(module.MainWindow, method))
        image = QImage(32, 32, QImage.Format_RGB32)
        image.fill(QColor('#ff8800'))
        source = root/'icon.png'
        image.save(str(source))
        managed = Path(import_asset(source)).relative_to('utils/skins').as_posix()
        parts = {'controls': {'background': '#114455', 'radius': 8},
                 'folders': {'background': '#223366', 'icon': 'icon.png'},
                 'buttons.pause': {'icon': 'icon.png', 'paused': {'icon': 'icon.png'}},
                 'buttons.volume': {'icon': 'icon.png'},
                 'settings': {'background': '#334455'}, 'settings.navigation': {'background': '#223344'},
                 'settings.content': {'background': '#445566'}, 'sidebar': {'background': '#123456'},
                 'menus': {'background': '#225544'}, 'notices': {'background': '#551155'},
                 'dialogs': {'background': '#445522'}}
        from ddm.skin_parts import _validate_image
        _validate_image.cache_clear()
        with patch('ddm.skins.validate_asset', wraps=validate_asset) as decode:
            validate_parts(parts, root)
            validate_parts(parts, root)
            assert decode.call_count == 1, 'unchanged icons must not be decoded again on every mask adjustment'
        for invalid in ({'tile': {'background': '#ffffff'}}, {'controls': {'image': '../icon.png'}},
                        {'controls': {'icon': str(source)}}, {'controls': {'radius': 900}},
                        {'controls': {'background': 'red; border: none'}},
                        {'sidebar': {'foreground': '#ffffff'}}):
            try:
                validate_parts(invalid, root)
            except ValueError:
                pass
            else:
                raise AssertionError(invalid)
        window = module.MainWindow([{'room_id': '1001', 'uname': 'fixture', 'live': False}],
            [], layout_id='1x1', state={'plugins_enabled': []})
        window.resize(1200, 800)
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.move(-10000, -10000)
        window.show()
        app.processEvents()
        tile = window.wall.tiles[0]
        folder_id = window.sidebar.create_folder('fixture')
        folder_button = window.sidebar._folder_buttons[folder_id]
        window.set_skin({'skin_background': 'utils/skins/' + managed})
        background = window.skin_controller.layer.path
        untouched = [tile.video.styleSheet(), tile.stream_badge.styleSheet(), tile.title_badge.styleSheet(),
                     window.sidebar._items[0].styleSheet()]
        handle = int(tile.video.winId())
        manifest = dict(id='test_parts', name='Parts fixture', description='Offline skin', version='1.0',
                        skin={'version': 2, 'parts': parts})
        archive = root/'pack.zip'
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('test_parts/plugin.json', json.dumps(manifest))
            package.writestr('test_parts/plugin.py', 'from ddm.plugins import Plugin\nplugin = Plugin()\n')
            package.write(source, 'test_parts/icon.png')
        manager = PluginManager(window, str(root/'plugins'), enabled=[])
        manager.install_zip(str(archive))
        manager.load()
        window.plugins = manager
        window.refresh_skin()
        try:
            assert window.skin_controller.override['version'] == 2
            assert window.skin_controller.layer.path == background, 'parts-only pack must preserve the personal background'
            assert '#ff114455' in tile.bottom.styleSheet()
            assert '#ff123456' in window.sidebar.styleSheet()
            assert icon_path(tile.pause_button).endswith('icon.png')
            folder_button.grab()
            folder = window.sidebar.get_folder(folder_id)
            folder['icon'] = {'type': 'builtin', 'name': 'heart', 'color': 'pink'}
            folder_button.refresh_theme()
            individual = folder_button.icon().pixmap(18, 18).toImage()
            theme.apply(theme.mode())
            assert folder_button.icon().pixmap(18, 18).toImage() == individual, 'individual folder icons win over the package'
            folder.pop('icon')
            folder_button.refresh_theme()
            assert not part_for(tile.reload_button), 'top controls are excluded'
            icon_image = tile.pause_button.grab().toImage()
            assert any(icon_image.pixelColor(x, y) == QColor('#ff8800')
                       for x in range(icon_image.width()) for y in range(icon_image.height()))
            tile.volume_button.set_state(False, 40, 4)
            tile.volume_button.grab()
            assert tile.volume_button.audio_channel == 4
            dialog = SettingsDialog(window.settings, window.shortcuts, window, plugin_manager=manager)
            dialog.setAttribute(Qt.WA_ShowWithoutActivating)
            dialog.move(-10000, -10000)
            dialog.show()
            app.processEvents()
            assert '#ff334455' in dialog.styleSheet()
            assert '#ff223344' in dialog.nav.styleSheet()
            assert '#ff445566' in dialog.stack.styleSheet()
            menu = QMenu(window)
            menu.addAction('fixture')
            menu.ensurePolished()
            assert '#ff225544' in menu.styleSheet()
            notice = ResultNotice(window)
            notice.grab()
            controls = dialog.appearance_page.skin_settings
            dialog.nav.setCurrentRow(1)
            app.processEvents()
            assert controls.choose.isEnabled() and controls.parts_button.isEnabled()
            assert controls.parts_button.isHidden()
            assert not any(button.isVisible() and '跟随美化包' in button.text()
                           for button in dialog.appearance_page.findChildren(QPushButton))
            appearance = dialog.appearance_page
            embedded = appearance.parts_editor
            assert embedded.isVisible() and embedded.embedded and not embedded.isWindow()
            assert embedded.apply_button.isHidden() and embedded.close_button.isHidden()
            assert embedded.preview.mapTo(embedded, QPoint()).y() < embedded.selection_title.mapTo(embedded, QPoint()).y()
            assert embedded.introduction.text() == '点击上方预览图中可修改部分 在下方自定义修改'
            forbidden = ('背景皮肤', '颜色模式', '当前：', '立即生效并保存', '主界面入口：', '切换不重连直播')
            assert not any(label.isVisible() and not embedded.isAncestorOf(label) and
                           any(text in label.text() for text in forbidden)
                           for label in appearance.findChildren(QLabel))
            dialog.nav.setCurrentRow(0)
            editor = PartSettings(window, dialog, professional=True)
            editor.setAttribute(Qt.WA_ShowWithoutActivating)
            editor.move(-10000, -10000)
            editor.show()
            app.processEvents()
            assert editor.part.currentData() == 'background'
            assert editor.preview.selected == 'background' and editor.scenes.currentIndex() == 0
            assert editor.background_controls.isVisible() and editor.parameter_box.isHidden()
            assert editor.introduction.text() == '点击左侧预览图中可修改部分 在下方自定义修改'
            assert editor.selection_title.text() == '软件整体背景'
            assert editor.page_title.y() < editor.introduction.y()
            output = ROOT/'work/appearance-delivery'
            output.mkdir(parents=True, exist_ok=True)
            editor.grab().save(str(output/'parts-editor-default.png'))
            original_mask = editor.background_controls.mask_slider.value()
            editor.background_controls.mask_slider.setValue(44)
            assert controls.values() == editor.background_controls.values(), 'Outer settings must retain edits made in the preview page'
            editor.background_controls.mask_slider.setValue(original_mask)
            from ddm.skin_parts import PARTS
            clicked = []
            editor.preview.partSelected.connect(clicked.append)
            for part in (*PARTS, 'background'):
                editor.part.setCurrentIndex(editor.part.findData(part))
                app.processEvents()
                editor.preview.grab()
                QTest.mouseClick(editor.preview, Qt.LeftButton, pos=editor.preview.point_for(part))
                assert clicked[-1] == part and editor.part.currentData() == part
                assert editor.page_title.text() == '界面美化'
                assert editor.introduction.text() == '点击左侧预览图中可修改部分 在下方自定义修改'
            assert editor.background_controls.isVisible() and editor.parameter_box.isHidden()
            editor.part.setCurrentIndex(editor.part.findData('sidebar'))
            editor.preview.grab()
            scale, offset = editor.preview._transform()
            for rect in editor.preview.protected:
                point = (rect.center()*scale+offset).toPoint()
                assert not editor.preview.part_at(point), 'cards and video must not be editable hotspots'
            # Live drafts change the miniature, not global styling or saved settings.
            editor.part.setCurrentIndex(editor.part.findData('controls'))
            before = editor.preview.grab().toImage()
            old_settings = window.current_state()['settings']['skin_parts']
            editor.fields['background'][0].setChecked(True)
            editor.fields['background'][1].setText('#72A9C1')
            assert editor.preview._values('controls')['background'] == '#72A9C1'
            assert editor.preview.grab().toImage() != before
            assert values_for('controls')['background'] == '#114455'
            assert window.current_state()['settings']['skin_parts'] == old_settings
            editor.fields['background'][1].setText('#')
            with patch.object(window, 'set_skin_parts') as apply:
                editor.apply_part()
                apply.assert_not_called()
            assert editor.preview._values('controls')['background'] == '#72A9C1'
            editor.fields['background'][1].setText('#72A9C1')
            editor.part.setCurrentIndex(editor.part.findData('folders'))
            editor.fields['radius'][0].setChecked(True)
            editor.fields['radius'][1].setValue(20)
            editor.part.setCurrentIndex(editor.part.findData('controls'))
            assert editor.fields['background'][1].text() == '#72A9C1'
            with patch.object(config, 'save') as save:
                QTest.mouseClick(editor.apply_button, Qt.LeftButton)
                assert save.called
            assert values_for('controls')['background'] == '#72A9C1'
            assert values_for('folders')['radius'] == 20
            window.set_skin_parts({})
            editor.load_part()
            output = ROOT/'work/appearance-delivery'
            output.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(output/'parts-main-test.png'))
            dialog.grab().save(str(output/'parts-settings-test.png'))
            editor.grab().save(str(output/'parts-editor-test.png'))
            # The custom layout popup shares menu styling, while its thumbnails keep their content.
            window.save_room_preset('美化验收组合')
            window.sidebar.open_layout_picker()
            picker = window.sidebar._picker
            picker.set_group('直播间组合')
            app.processEvents()
            assert part_for(picker) == 'layout_menu' and '#ff225544' in picker.styleSheet()
            assert part_for(picker.presets_page.save_button) == 'buttons'
            management = picker.findChildren(QToolButton, 'PresetManageButton')
            assert management and part_for(management[0]) == 'buttons'
            card = next(iter(picker.presets_page.cards.values()))
            assert not part_for(card), 'Combination thumbnails are not generic skinnable buttons'
            original_icon = card.icon().cacheKey()
            window.set_skin_parts({'buttons': {'icon': managed}})
            app.processEvents()
            assert icon_path(management[0]).endswith(managed)
            assert not icon_path(card) and card.icon().cacheKey() == original_icon
            capture = management[0].grab().toImage()
            assert any(capture.pixelColor(x, y) == QColor('#ff8800')
                       for x in range(capture.width()) for y in range(capture.height())), 'Management button must paint the custom icon'
            assert int(tile.video.winId()) == handle
            window.set_skin_parts({})
            # Busy or bright wallpaper cannot show through label/selection plates.
            picker.set_group('普通布局')
            for mode in ('dark', 'light'):
                theme.apply(mode)
                samples = []
                for color in ('#000000', '#ffffff'):
                    background_source = root / ('layout-' + color[1:] + '.png')
                    backdrop = QImage(32, 32, QImage.Format_RGB32)
                    backdrop.fill(QColor(color))
                    backdrop.save(str(background_source))
                    relative = Path(import_asset(background_source)).relative_to('utils/skins').as_posix()
                    window.set_skin_parts({'layout_menu': {'image': relative}})
                    app.processEvents()
                    capture = picker.grab().toImage()
                    dpr = capture.devicePixelRatio()
                    selected = next(card for card in picker._cards['普通布局'] if card.isChecked())
                    heading = picker._sections['普通布局'][0]
                    tab = picker._tabs['普通布局']
                    pixels = []
                    for control in (selected, heading, tab):
                        point = control.mapTo(picker, QPoint(control.width()-10, 8))
                        pixels.append(capture.pixelColor(round(point.x()*dpr), round(point.y()*dpr)))
                    samples.append(pixels)
                assert samples[0] == samples[1], 'Wallpaper must not bleed through selected cards, headings or tabs'
                assert all(pixel.alpha() == 255 for pixel in samples[0])
                picker.grab().save(str(output/f'layout-wallpaper-readable-{mode}.png'))
            theme.apply('dark')
            window.set_skin_parts({})
            # Restore the miniature editor as the default entry, preserving saved artwork.
            window.set_skin_parts({'layout_menu': {'image': managed},
                                   'settings': {'radius': 13, 'foreground': '#abcdef'}})
            before = window.current_state()['settings']['skin_parts']
            def inspect_preview(page):
                from ddm.skin_preview import BASIC_PARTS, GROUPS, group_color
                assert page.preview.accessibleName() == '可点击的界面分区预览'
                assert page.scenes.count() == 3
                assert window.settings['skin_parts'] == before
                page.setAttribute(Qt.WA_ShowWithoutActivating)
                page.move(-10000, -10000)
                page.show()
                app.processEvents()
                assert {page.part.itemData(i) for i in range(page.part.count())} == BASIC_PARTS
                assert set(page.group_labels) == set(GROUPS)
                for mode in ('dark', 'light'):
                    theme.apply(mode)
                    assert len({group_color(group, theme.is_light()).name() for group in GROUPS}) == 4
                    for part in BASIC_PARTS:
                        page._select_part(part)
                        app.processEvents()
                        page.preview.grab()
                        assert {key for key, _rect in page.preview.regions} <= BASIC_PARTS
                        point = page.preview.point_for(part)
                        QTest.mouseClick(page.preview, Qt.LeftButton, pos=point)
                        assert page.part.currentData() == part
                        check_scene_background(page.scenes)
                        if part != 'background':
                            visible = {key for key, (check, _edit) in page.fields.items() if check.isVisible()}
                            assert not visible, 'Simple artwork imports have no enable checkbox'
                            key = 'icon' if part.startswith('buttons.') else 'image'
                            assert page.asset_buttons[key].isVisible()
                            assert page.fields[key][1].isHidden()
                            assert page.reset_button.isHidden()
                            assert page.builtin_button.width() == page.asset_buttons[key].width()
                            assert page.asset_buttons[key].mapTo(page, QPoint()).x() == page.selection_title.mapTo(page, QPoint()).x()
                            assert page.builtin_button.mapTo(page, QPoint()).y() < page.status.mapTo(page, QPoint()).y()
                            if part in ('settings', 'layout_menu'):
                                assert page.asset_status.text().startswith('当前：')
                    for index, part in enumerate(('background', 'settings', 'layout_menu')):
                        page.scenes.setCurrentIndex((index + 1) % 3)
                        page.scenes.setCurrentIndex(index)
                        app.processEvents()
                        assert page.part.currentData() == part
                        page.grab().save(str(output/f'parts-basic-{part}-{mode}.png'))
                theme.apply('dark')
                page._select_part('settings')
                original_render = SettingsDialog.render
                def change_scene_while_rendering(widget, *args):
                    original_render(widget, *args)
                    page._select_part('layout_menu')
                with patch.object(SettingsDialog, 'render', change_scene_while_rendering):
                    page.preview.capture_interface(window)
                assert page.preview.scene == 'popups'
                settings_image = page.preview.interface_images['settings']
                layout_image = page.preview.interface_images['popups']
                assert settings_image.toImage() != layout_image.toImage()
                assert page.preview.interface_image.cacheKey() == layout_image.cacheKey()
                page._select_part('settings')
                assert page.preview.interface_image.cacheKey() != layout_image.cacheKey()
                row = dialog.nav.currentRow()
                with patch('ddm.dialogs.PluginSettingsPage', side_effect=AssertionError('Preview must not create plugin workers')), \
                        patch('ddm.online_ui.AppUpdatePage', side_effect=AssertionError('Preview must not create the updater')), \
                        patch.object(config, 'save') as save:
                    page._update_preview()
                    save.assert_not_called()
                assert dialog.nav.currentRow() == row, 'Preview must not navigate the live settings dialog'
                assert page.preview.interface_image and not page.preview.interface_image.isNull()
                rendered = page.preview.interface_image.toImage()
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(source))])
                area = page.asset_buttons['image']
                enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                area.dragEnterEvent(enter)
                assert enter.isAccepted() and area.property('dragging')
                drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                area.dropEvent(drop)
                assert drop.isAccepted() and not area.property('dragging')
                assert page.fields['image'][0].isChecked()
                assert page.preview.interface_image.toImage() != rendered, 'Real settings controls must preview the imported draft'
                assert window.settings['skin_parts'] == before, 'Import remains a draft until Apply'
                assert isinstance(page.background_controls.choose, SkinAssetDropArea)
                assert all(isinstance(button, SkinAssetDropArea) for button in page.asset_buttons.values())
                for urls in ([QUrl('https://example.invalid/image.png')],
                             [QUrl.fromLocalFile(str(source)), QUrl.fromLocalFile(str(source))]):
                    mime.setUrls(urls)
                    event = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                    area.dragEnterEvent(event)
                    assert not event.isAccepted()
                video = source.with_suffix('.mp4')
                video.write_bytes(b'fixture')
                mime.setUrls([QUrl.fromLocalFile(str(video))])
                event = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                area.dragEnterEvent(event)
                assert not event.isAccepted(), 'Part backgrounds accept only static images'
                page.background_controls.choose.dragEnterEvent(event)
                assert event.isAccepted(), 'Whole-window backgrounds also accept video'
                page.background_controls.choose.dragLeaveEvent(event)
                for width, height in ((1100, 700), (950, 520)):
                    page.resize(width, height)
                    app.processEvents()
                    assert page.apply_button.isVisible() and page.close_button.isVisible()
                    assert page.apply_button.mapTo(page, QPoint()).y() > page.height() - page.apply_button.height() - 30
                    assert abs(page.apply_button.mapTo(page, QPoint()).y() - page.close_button.mapTo(page, QPoint()).y()) <= 2
                    assert not any(isinstance(parent, QScrollArea) for parent in
                                   (page.apply_button.parentWidget(), page.close_button.parentWidget()))
                page.resize(1100, 700)
                with patch('ddm.skin_settings.QFileDialog.getOpenFileName', return_value=(str(source), '')):
                    page._choose('image')
                page.apply_part()
                assert page.result() == PartSettings.Accepted and page.isHidden(), 'Apply must save and close'
                page.show()
                page._import_part_asset('image', str(source))
                with patch.object(window, 'set_skin_parts', side_effect=ValueError('Fixture save failure')):
                    page.apply_part()
                assert page.isVisible() and 'Fixture save failure' in page.status.text(), 'Save failures must keep the editor open'
                assert window.settings['skin_parts']['settings']['radius'] == 13
                assert window.settings['skin_parts']['settings']['foreground'] == '#abcdef'
                assert values_for('settings.navigation')['background'] == '#00000000'
                assert values_for('settings.content')['background'] == '#00000000'
                capture = dialog.grab().toImage()
                point = dialog.nav.mapTo(dialog, QPoint(5, 5))
                dpr = capture.devicePixelRatio()
                assert capture.pixelColor(round(point.x()*dpr), round(point.y()*dpr)) == QColor('#ff8800')
                page.reset_part()
                assert 'image' not in values_for('settings') and window.settings['skin_parts']['settings']['radius'] == 13
                assert page.builtin_button.isVisible() and page.builtin_button.text() == '恢复默认背景'
                QTest.mouseClick(page.builtin_button, Qt.LeftButton)
                assert values_for('settings').get('background') is None, 'Restore default must skip the package wallpaper/background'
                assert window.settings['skin_parts']['settings']['radius'] == 13
                page.reset_part()
                assert values_for('settings')['background'] == '#334455', 'Follow pack must clear the builtin marker'
                assert not any('专业美化' in button.text() for button in page.findChildren(QPushButton))
                assert not hasattr(page, 'open_professional'), 'Professional editor has no user entry point'
                for part, field in (('layout_menu', 'image'), ('buttons.pause', 'icon')):
                    saved_parts = window.current_state()['settings']['skin_parts']
                    page._select_part(part)
                    mime.setUrls([QUrl.fromLocalFile(str(source))])
                    drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                    page.asset_buttons[field].dropEvent(drop)
                    assert drop.isAccepted() and page.fields[field][0].isChecked()
                    assert page.fields[field][1].text()
                    assert page.builtin_button.isVisible()
                    QTest.mouseClick(page.builtin_button, Qt.LeftButton)
                    assert not values_for(part).get(field)
                    page.reset_part()
                    window.set_skin_parts(saved_parts)
                    page.load_part()
                page._drafts.clear()
                page._select_part('background')
                page.preview.grab()
                scale, offset = page.preview._transform()
                # Sidebar and playback bars are context only; their old entry points are gone.
                for rect in page.preview.protected:
                    assert not page.preview.part_at((rect.center()*scale+offset).toPoint())
                page._select_part('controls')
                assert page.part.currentData() == 'background'
                page.close()
                return PartSettings.Rejected
            with patch.object(PartSettings, 'exec', inspect_preview):
                controls._edit_parts()
            assert window.settings['skin_parts'] == before
            # Inline drafts are committed by the existing settings footer only.
            for action in ('save', 'cancel', 'fail'):
                inline_dialog = SettingsDialog(window.settings, window.shortcuts, window)
                inline_dialog.setAttribute(Qt.WA_ShowWithoutActivating)
                inline_dialog.move(-10000, -10000)
                inline_dialog.resize(720, 645)
                inline_dialog.show()
                with patch.object(PartSettings, 'exec', side_effect=AssertionError('Appearance must not open another dialog')):
                    inline_dialog.nav.setCurrentRow(1)
                    app.processEvents()
                    inline = inline_dialog.appearance_page.parts_editor
                    assert inline.parentWidget().isAncestorOf(inline) and not inline.isWindow()
                    assert inline.preview.mapTo(inline, QPoint()).y() < inline.selection_title.mapTo(inline, QPoint()).y()
                    sizes = ((720, 645), (660, 520), (720, 645)) if action == 'save' else ((720, 645),)
                    for width, height in sizes:
                        inline_dialog.resize(width, height)
                        for part in ('background', 'settings', 'layout_menu', 'background'):
                            inline._select_part(part)
                            app.processEvents()
                            scroll = inline_dialog.appearance_page.scroll.verticalScrollBar()
                            scroll.setValue(min(100, scroll.maximum()))
                            capture = inline_dialog.grab()
                            app.processEvents()
                            bottom = inline.preview.mapTo(inline, QPoint(0, inline.preview.height())).y()
                            if action == 'save':
                                check_scene_background(inline.scenes)
                            labels = list(inline.group_labels.values())
                            assert all(label.mapTo(inline, QPoint()).y() >= bottom for label in labels), (
                                f'Legend overlaps {part} preview at {width}x{height}')
                            legend_bottom = max(label.mapTo(inline, QPoint(0, label.height())).y()
                                                for label in labels)
                            assert inline.selection_title.mapTo(inline, QPoint()).y() >= legend_bottom
                            if action == 'save' and (width, height) == (720, 645):
                                name = {'background': 'preview', 'settings': 'settings',
                                        'layout_menu': 'layout'}[part]
                                capture.save(str(output/f'appearance-inline-{name}.png'))
                    scroll.setValue(0)
                    if action == 'save':
                        inline_dialog.appearance_page.scroll.ensureWidgetVisible(inline.background_controls.choose)
                        app.processEvents()
                        assert inline_dialog.confirm_button.isVisible()
                        inline_dialog.grab().save(str(output/'appearance-inline-controls.png'))
                    inline._select_part('settings')
                    inline._import_part_asset('image', str(source))
                    draft = inline.fields['image'][1].text()
                    assert window.settings['skin_parts'] == before and inline._drafts
                    if action == 'save':
                        inline_dialog.nav.setCurrentRow(0)
                        QTest.mouseClick(inline_dialog.confirm_button, Qt.LeftButton)
                        assert inline_dialog.result() == SettingsDialog.Accepted and inline_dialog.isHidden()
                        assert window.settings['skin_parts']['settings']['image'] == draft
                        window.set_skin_parts(before)
                    elif action == 'cancel':
                        QTest.keyClick(inline, Qt.Key_Escape)
                        assert inline_dialog.isHidden(), 'Escape must close settings, not hide just the embedded editor'
                        assert window.settings['skin_parts'] == before
                    else:
                        with patch.object(window, 'set_skin_parts', side_effect=ValueError('Inline save failure')):
                            inline_dialog.nav.setCurrentRow(0)
                            QTest.mouseClick(inline_dialog.confirm_button, Qt.LeftButton)
                        assert inline_dialog.isVisible() and inline_dialog.nav.currentRow() == 1
                        assert 'Inline save failure' in inline.status.text()
                        inline_dialog.reject()
                inline_dialog.deleteLater()
                app.processEvents()
            for part in ('background', 'settings', 'layout_menu'):
                clean = PartSettings(window, dialog)
                clean.setAttribute(Qt.WA_ShowWithoutActivating)
                clean.move(-10000, -10000)
                clean._select_part(part)
                clean.show()
                app.processEvents()
                assert not clean._drafts
                with patch.object(window, 'set_skin_parts') as save:
                    QTest.mouseClick(clean.apply_button, Qt.LeftButton)
                    save.assert_not_called()
                assert clean.result() == PartSettings.Accepted and clean.isHidden(), part
                clean.deleteLater()
            # A missing saved asset previously blocked both rendering and no-op Apply.
            window.settings['skin_parts'] = {'buttons.pause': {'icon': 'missing-old-file.png'}}
            broken = PartSettings(window, dialog)
            broken.setAttribute(Qt.WA_ShowWithoutActivating)
            broken.move(-10000, -10000)
            for part in ('settings', 'layout_menu'):
                broken._select_part(part)
                assert broken.preview.interface_image and not broken.preview.interface_image.isNull()
                broken.show()
                app.processEvents()
                with patch.object(window, 'set_skin_parts') as save:
                    QTest.mouseClick(broken.apply_button, Qt.LeftButton)
                    save.assert_not_called()
                assert broken.isHidden() and broken.result() == PartSettings.Accepted
            broken._import_part_asset('image', str(source))
            broken.show()
            QTest.mouseClick(broken.apply_button, Qt.LeftButton)
            assert broken.isVisible(), 'Changed artwork must not be discarded just because another saved asset is invalid'
            broken.close()
            broken.deleteLater()
            window.settings['skin_parts'] = before
            assert 'image' not in values_for('menus') and Path(values_for('layout_menu')['image']).is_file()
            window.set_skin_parts({})
            picker.close()
            editor.part.setCurrentIndex(editor.part.findData('controls'))
            check, edit = editor.fields['background']
            check.setChecked(True)
            edit.setText('#abcdef')
            with patch.object(config, 'save') as save:
                editor.apply_part()
                assert save.called
            assert values_for('controls')['background'] == '#abcdef'
            assert window.current_state()['settings']['skin_parts']['controls']['background'] == '#abcdef'
            with patch('ddm.skin_settings.QFileDialog.getOpenFileName', return_value=(str(source), '')):
                editor._choose('image')
            assert editor.fields['image'][0].isChecked()
            relative = editor.fields['image'][1].text()
            assert (root/'utils/skins'/relative).is_file()
            editor.apply_part()
            source.unlink()
            assert Path(values_for('controls')['image']).is_file(), 'imported art must survive source removal'
            painted = tile.bottom.grab().toImage()
            assert painted.pixelColor(painted.width()//2, painted.height()//2) == QColor('#ff8800')
            window.set_skin_parts({'buttons.pause': {'icon': managed}, 'controls': {'light': {'background': '#fedcba'}}})
            for mode in ('light', 'dark'):
                theme.apply(mode)
                assert values_for('controls')['background'] == ('#fedcba' if mode == 'light' else '#114455')
            window.set_skin_parts({'buttons.pause': {'icon': managed}, 'controls': {'background': '#abcdef'}})
            theme.apply('light')
            assert values_for('controls')['background'] == '#abcdef'
            theme.apply('dark')
            editor.reset_part()
            assert values_for('controls')['background'] == '#114455'
            editor.use_builtin()
            assert not values_for('controls')
            assert 'skinPart="controls"' not in tile.bottom.styleSheet()
            editor.reset_part()
            assert values_for('controls')['background'] == '#114455'
            assert [tile.video.styleSheet(), tile.stream_badge.styleSheet(), tile.title_badge.styleSheet(),
                    window.sidebar._items[0].styleSheet()] == untouched
            manager.enabled.clear()
            window.refresh_skin()
            assert 'skinPart="controls"' not in tile.bottom.styleSheet()
            assert icon_path(tile.pause_button), 'personal icon survives package disable'
            window.set_skin_parts({})
            assert not icon_path(tile.pause_button)
            assert int(tile.video.winId()) == handle
            # Activation takes over backgrounds once; subsequent personal edits survive refresh/restart.
            custom_parts = {'settings': {'image': managed, 'builtin': True, 'radius': 13,
                                         'dark': {'image': managed}},
                            'layout_menu': {'image': managed, 'builtin': True},
                            'controls': {'background': '#abcdef'}}
            window.set_skin_parts(custom_parts)
            window.set_skin({'skin_background_override': True, 'skin_mask_override': True})
            plugin = manager.plugins[0]
            plugin.skin['background'] = 'icon.png'
            plugin.skin['parts']['settings']['image'] = 'icon.png'
            plugin.skin['parts']['layout_menu'] = {'image': 'icon.png'}
            manager.enabled.add('test_parts')
            window.refresh_skin()
            assert window.skin_controller.layer.path == str(root/'plugins/test_parts/icon.png')
            assert not window.settings['skin_background_override']
            assert not window.settings['skin_mask_override']
            for part in ('settings', 'layout_menu'):
                assert values_for(part)['image'] == str(root/'plugins/test_parts/icon.png')
                assert 'builtin' not in window.settings['skin_parts'][part]
            assert window.settings['skin_parts']['settings']['radius'] == 13
            assert values_for('controls')['background'] == '#abcdef'
            window.set_skin_parts(custom_parts)
            window.set_skin({'skin_background_override': True})
            # Recreate the controller's initial ownership state without changing persisted settings.
            window.skin_controller.override = None
            window.refresh_skin()
            assert window.settings['skin_background_override']
            assert values_for('settings')['image'] == str(root/'utils/skins'/managed)
            assert values_for('layout_menu')['image'] == str(root/'utils/skins'/managed)
            controls.sync()
            assert controls.choose.isEnabled() and window.skin_controller.layer.path
            controls.mask_slider.setValue(60)
            assert window.skin_controller.layer.path and window.skin_controller.layer.mask == 60
            controls.reset()
            assert not window.skin_controller.layer.path
            manager.enabled.clear()
            window.refresh_skin()
            manager.enabled.add('test_parts')
            window.refresh_skin()
            assert window.skin_controller.layer.path and window.skin_controller.layer.mask == 35
            manager.enabled.clear()
            window.refresh_skin()
            editor.close()
            dialog.close()
        finally:
            window.close()
            from ddm.skin_parts import configure
            configure({}, {})
    print('PASS: parts ZIP, clickable scenes/all hotspots, protected areas, draft previews/persistence, styling, icons, inheritance, reset and stable HWND')


def write_demo():
    """Build a harmless ordinary plugin ZIP with generated, non-user artwork."""
    from PySide6.QtGui import QLinearGradient, QPainter, QPainterPath, QPen
    from PySide6.QtCore import QRectF
    output = ROOT/'work/appearance-delivery/skin_parts_demo.zip'
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        image = QImage(1280, 720, QImage.Format_RGB32)
        painter = QPainter(image)
        gradient = QLinearGradient(0, 0, 1280, 720)
        gradient.setColorAt(0, QColor('#172B45'))
        gradient.setColorAt(1, QColor('#4A657A'))
        painter.fillRect(image.rect(), gradient)
        painter.end()
        image.save(str(folder/'background.png'))
        for name in ('pause', 'play', 'volume', 'muted', 'folder'):
            icon = QImage(48, 48, QImage.Format_ARGB32)
            icon.fill(Qt.transparent)
            painter = QPainter(icon)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor('#7DE0DD'), 3))
            painter.setBrush(QColor('#7DE0DD'))
            if name == 'pause':
                for x in (14, 28):
                    painter.drawRoundedRect(QRectF(x, 10, 6, 28), 2, 2)
            elif name == 'play':
                path = QPainterPath()
                path.moveTo(15, 9)
                path.lineTo(37, 24)
                path.lineTo(15, 39)
                path.closeSubpath()
                painter.drawPath(path)
            elif name == 'folder':
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(QRectF(6, 15, 36, 25), 4, 4)
                painter.drawLine(9, 15, 9, 9)
                painter.drawLine(9, 9, 23, 9)
                painter.drawLine(23, 9, 29, 15)
            else:
                path = QPainterPath()
                path.moveTo(8, 19)
                path.lineTo(15, 19)
                path.lineTo(24, 11)
                path.lineTo(24, 37)
                path.lineTo(15, 29)
                path.lineTo(8, 29)
                path.closeSubpath()
                painter.drawPath(path)
                if name == 'muted':
                    painter.drawLine(31, 18, 41, 30)
                    painter.drawLine(41, 18, 31, 30)
                else:
                    painter.setBrush(Qt.NoBrush)
                    painter.drawArc(20, 11, 22, 26, -70*16, 140*16)
            painter.end()
            icon.save(str(folder/(name+'.png')))
        parts = {
            'sidebar': {'background': '#DA203346'},
            'folders': {'background': '#AA2D465C', 'foreground': '#E7F1F8', 'radius': 10,
                        'border_color': '#667D9AAF', 'border_width': 1, 'icon': 'folder.png'},
            'controls': {'background': '#D0142D35', 'radius': 9},
            'settings': {'background': '#1F3045'},
            'settings.navigation': {'background': '#17283B', 'checked': {'background': '#325A76'}},
            'settings.content': {'background': '#253950'},
            'menus': {'background': '#253950', 'foreground': '#E7F1F8', 'radius': 8},
            'dialogs': {'background': '#253950'},
            'notices': {'background': '#253950', 'foreground': '#E7F1F8', 'radius': 12},
            'buttons': {'background': '#354F68', 'foreground': '#E7F1F8', 'radius': 8,
                        'hover': {'background': '#48738C'}, 'pressed': {'background': '#294357'},
                        'checked': {'background': '#26767E'}, 'disabled': {'background': '#303D4A'}},
            'buttons.pause': {'icon': 'pause.png', 'paused': {'icon': 'play.png'}},
            'buttons.volume': {'icon': 'volume.png', 'muted': {'icon': 'muted.png'}},
        }
        for part, color in {'sidebar': '#DAE6F1F7', 'folders': '#DAE2EEF4', 'controls': '#D0DDEFF2',
                'settings': '#ECF3F8', 'settings.navigation': '#DEE9F1', 'settings.content': '#F5F8FB',
                'menus': '#ECF3F8', 'dialogs': '#ECF3F8', 'notices': '#ECF3F8', 'buttons': '#D8E7EF'}.items():
            parts[part]['light'] = {'background': color}
            if part in ('folders', 'menus', 'notices', 'buttons'):
                parts[part]['light']['foreground'] = '#233C4F'
        for state in ('hover', 'pressed', 'checked'):
            parts['buttons'][state]['foreground'] = '#FFFFFF'
        manifest = dict(id='skin_parts_demo', name='分区美化测试包', description='逐项测试分区、图标和个人覆盖',
                        version='1.0.0', skin={'version': 2, 'background': 'background.png', 'mask': 25, 'parts': parts})
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as package:
            package.writestr('skin_parts_demo/plugin.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            package.writestr('skin_parts_demo/plugin.py', 'from ddm.plugins import Plugin\nplugin = Plugin()\n')
            for path in folder.iterdir():
                package.write(path, 'skin_parts_demo/'+path.name)
    print('Demo:', output)


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate(), 'Skin operation did not finish'


def main():
    app = QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    check_parts(app)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    if '--make-demo' in sys.argv:
        write_demo()
        return
    if '--parts-only' in sys.argv:
        return
    module.StatusPoller = module.StatsPoller = SilentPoller
    with tempfile.TemporaryDirectory() as directory, patch.object(config, 'REPO', directory):
        folder = Path(directory)
        image = QImage(160, 90, QImage.Format_RGB32)
        image.fill(QColor('#E95C93'))
        source = folder / 'background.png'
        assert image.save(str(source))
        original = source.read_bytes()
        path = import_asset(source)
        assert (folder/path).read_bytes() == original and source.read_bytes() == original
        assert not list((folder/'utils/skins').glob('*.part'))
        try:
            import_asset(source, cancelled=lambda: True)
        except ValueError:
            pass
        else:
            raise AssertionError('Cancelled imports must not commit an asset')
        assert not list((folder/'utils/skins').glob('*.part'))
        bad = folder / 'bad.png'
        bad.write_text('invalid')
        try:
            validate_asset(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('Corrupt images must be rejected')
        with patch('PySide6.QtCore.QTimer.singleShot'):
            window = module.MainWindow([], [], layout_id='1x1',
                state={'plugins_enabled': [], 'settings': {'auto_update': False}})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.move(-10000, -10000)
        window.resize(1280, 800)
        window.show()
        QTest.qWait(20)
        layer = window.skin_controller.layer
        assert layer.player is None, 'Default/image skins must not create a video decoder'
        default_controls = SkinSettings(window.settings, window.skin_controller, window)
        assert not hasattr(default_controls, 'sidebar_toggle'), 'Sidebar coverage is always enabled'
        assert default_controls.video_toggle.isHidden() and default_controls.values()['skin_video_enabled']
        default_controls.deleteLater()
        hwnd = int(window.wall.tiles[0].video.winId())
        with patch.object(motion, 'enabled', return_value=False), patch.object(config, 'save') as save:
            window.set_skin({'skin_background': path, 'skin_mask': 35})
            assert save.call_args.args[0]['settings']['skin_background'] == path
            source.unlink()
            assert layer.image is not None and not layer.image.isNull()
            original_background = layer.image.copy()
            for mode in ('dark', 'light', 'dark', 'light'):
                window.set_appearance(mode)
                window.set_skin({'skin_mask': 0})
                samples = []
                for background in ('#FF0000', '#0000FF'):
                    layer.image.fill(QColor(background))
                    layer.update()
                    QTest.qWait(20)
                    video = window.wall.tiles[0].video
                    root = window.centralWidget()
                    point = video.mapTo(root, QPoint(20, video.height()//2))
                    frame = root.grab().toImage()
                    scale = frame.devicePixelRatio()
                    samples.append(frame.pixelColor(round(point.x()*scale),
                        round(point.y()*scale)).getRgb()[:3])
                difference = max(abs(a-b) for a, b in zip(*samples))
                assert difference >= 20, (mode, samples, 'The actual background must show through empty tiles')
            layer.image = original_background
            window.set_skin({'skin_mask': 35})
            window.set_appearance('light')
            QTest.qWait(30)
            assert 'rgba(' in window.sidebar.styleSheet(), 'Background must cover the sidebar by default'
            live_video = folder/'live.mp4'
            subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'color=c=blue:size=320x180:rate=15', '-t', '20', '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', str(live_video)], check=True)
            tile = window.wall.tiles[0]
            live = TilePlayer(tile.video, window, silent=True)
            window.players[tile] = live
            live.play(str(live_video))
            tile.set_video_active(True)
            wait_for(lambda: live.player.get_time() > 0)
            live_time = live.player.get_time()
            with patch('PySide6.QtCore.QTimer.singleShot'), patch('ddm.online.load_plugin_cache', return_value=None):
                dialog = SettingsDialog(window.settings, window.shortcuts, window)
            dialog.nav.setCurrentRow(1)
            dialog.setAttribute(Qt.WA_ShowWithoutActivating)
            dialog.move(-10000, -10000)
            dialog.show()
            controls = dialog.appearance_page.skin_settings
            assert controls.choose.isEnabled()
            assert not hasattr(controls, 'sidebar_toggle')
            QTest.qWait(30)
            assert 'rgba(' in window.sidebar.styleSheet()
            assert controls.values()['skin_sidebar']
            assert window.settings['skin_background'] == path and layer.mask == 35
            window.set_appearance('dark')
            assert 'rgba(' in window.sidebar.styleSheet()
            window.set_appearance('light')
            assert 'rgba(' in window.sidebar.styleSheet()
            next_source = folder / 'next.png'
            image.fill(QColor('#426CDB'))
            image.save(str(next_source))
            controls.import_file(str(next_source))
            wait_for(lambda: controls.job is None)
            custom = controls.path
            assert window.settings['skin_background'] == custom
            assert layer.image.pixelColor(0, 0) == QColor('#426CDB')
            controls.mask_slider.setValue(50)
            assert layer.mask == 50 and window.settings['skin_mask'] == 50
            assert controls.mask_slider.maximum() == 100
            controls.mask_slider.setValue(100)
            assert layer.mask == 100 and window.settings['skin_mask'] == 100
            assert layer.grab().toImage().pixelColor(10, 10) == theme.qcolor(theme.BG)
            controls.mask_slider.setValue(50)
            # Install through the existing ZIP API; it only executes after load.
            archive = folder / 'skin.zip'
            manifest = dict(id='test_skin', name='Test skin', description='Offline fixture', version='1.0',
                skin={'background': 'assets/background.png', 'mask': 100})
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('test_skin/plugin.json', json.dumps(manifest))
                package.writestr('test_skin/plugin.py', 'from ddm.plugins import Plugin\nplugin = Plugin()\n')
                package.writestr('test_skin/assets/background.png', original)
            manager = PluginManager(window, str(folder/'plugins'), enabled=[])
            manager.install_zip(str(archive))
            manifest['skin']['mask'] = 20
            installed_manifest = folder/'plugins/test_skin/plugin.json'
            installed_manifest.write_text(json.dumps(manifest), encoding='utf-8')
            assert manager.active_skin() is None
            manager.load()
            window.plugins = manager
            window.refresh_skin()
            assert window.skin_controller.override['owner'] == 'test_skin'
            assert not controls.choose.isEnabled() and not controls.mask_slider.isEnabled()
            assert not controls.video_toggle.isEnabled()
            assert controls.values()['skin_sidebar'], 'Plugin ownership must preserve the user preference'
            assert controls.mask_slider.value() == 20 and controls.values()['skin_mask'] == 50
            assert layer.mask == 20 and layer.image.pixelColor(0, 0) == QColor('#E95C93')
            window.set_skin({'skin_background': '', 'skin_mask': 0})
            assert window.settings['skin_background'] == custom
            manager.enabled.clear()
            window.refresh_skin()
            assert controls.choose.isEnabled() and layer.mask == 50
            assert controls.mask_slider.value() == 50
            assert controls.values()['skin_sidebar']
            assert 'rgba(' in window.sidebar.styleSheet()
            assert layer.image.pixelColor(0, 0) == QColor('#426CDB')
            manager.enabled.add('test_skin')
            window.refresh_skin()
            # Removing the active package must restore the saved custom background.
            manager.remove_plugin('test_skin')
            assert window.skin_controller.override is None and controls.choose.isEnabled()
            assert layer.image.pixelColor(0, 0) == QColor('#426CDB')
            # Reject a package asset that escapes its installed directory.
            escaping = folder / 'escape'
            escaping.mkdir()
            manifest.update(id='escape', skin={'background': '../background.png'})
            (escaping/'plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
            try:
                read_manifest(str(escaping), 'escape')
            except ValueError:
                pass
            else:
                raise AssertionError('Escaping skin asset paths must be rejected')
            assert int(window.wall.tiles[0].video.winId()) == hwnd
            output = ROOT/'work/appearance-delivery'
            output.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(output/'skin-light.png'))
            dialog.grab().save(str(output/'skin-settings.png'))
            controls.reset()
            assert window.settings['skin_sidebar'] and 'rgba(' not in window.sidebar.styleSheet()
            window.set_skin({'skin_background': custom, 'skin_mask': 50, 'skin_sidebar': True})
            dialog.reject()
            # Exercise the new slots while the real VLC player is running.
            audio = (tile.muted, tile.volume, tile.audio_channel)
            with patch.object(window, 'start_tile') as restart, patch.object(window.recorder, 'stop') as stop:
                for color in ('#345678', '#456789'):
                    window.set_skin_parts({'controls': {'background': color},
                                           'buttons.pause': {'icon': Path(custom).name}})
                    tile.pause_button.grab()
                    QTest.qWait(40)
                window.set_skin_parts({})
                restart.assert_not_called()
                stop.assert_not_called()
            assert (tile.muted, tile.volume, tile.audio_channel) == audio
            assert window.players[tile] is live and int(tile.video.winId()) == hwnd
            video = folder/'background.mp4'
            subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'testsrc2=size=320x180:rate=15', '-f', 'lavfi',
                '-i', 'sine=frequency=440:sample_rate=44100', '-t', '1', '-c:v', 'libx264', '-c:a', 'aac',
                '-pix_fmt', 'yuv420p', str(video)], check=True)
            video_path = import_asset(video)
            video_editor = PartSettings(window)
            video_editor.setAttribute(Qt.WA_ShowWithoutActivating)
            video_editor.move(-10000, -10000)
            video_editor.show()
            app.processEvents()
            window.set_skin({'skin_background': video_path, 'skin_mask': 35})
            wait_for(lambda: layer.image is not None)
            assert video_editor.preview.background is layer.image
            before_frame = video_editor.preview.background.copy()
            before_preview = video_editor.preview.grab().toImage()
            player = layer.player
            wait_for(lambda: video_editor.preview.background != before_frame)
            assert video_editor.preview.grab().toImage() != before_preview, 'Video frames must animate in the miniature'
            assert layer.player is player and not video_editor.findChildren(QMediaPlayer), 'Preview must reuse the existing decoder'
            assert layer.player.audioOutput() is None and layer.player.loops() == QMediaPlayer.Infinite
            assert layer.player.playbackState() == QMediaPlayer.PlayingState
            video_controls = video_editor.background_controls
            assert video_controls.video_toggle.isVisible() and video_controls.video_toggle.isChecked()
            wait_for(lambda: layer.player.position() >= 350)
            late_frame = layer.image.copy()
            video_controls.video_toggle.setChecked(False)
            wait_for(lambda: layer.image is not None and layer.player.playbackState() == QMediaPlayer.PausedState)
            first_frame = layer.image.copy()
            assert first_frame != late_frame and layer.player.position() < 200, 'Static mode must decode the beginning, not freeze the current frame'
            assert not window.settings['skin_video_enabled'] and not video_controls.values()['skin_video_enabled']
            assert not save.call_args.args[0]['settings']['skin_video_enabled']
            QTest.qWait(250)
            assert layer.image == first_frame and video_editor.preview.background == first_frame
            window.set_skin({'skin_mask': 45})
            assert layer.image == first_frame and layer.player.playbackState() == QMediaPlayer.PausedState
            window.hide()
            window.show()
            QTest.qWait(60)
            assert layer.player.playbackState() == QMediaPlayer.PausedState and layer.image == first_frame
            # Loading saved video settings starts at the same first frame.
            old_sink = layer.sink
            old_frame = old_sink.videoFrame()
            layer.load('')
            window.refresh_skin()
            pending = layer.image
            old_sink.videoFrameChanged.emit(old_frame)
            assert layer.image is pending, 'Queued frames from an old sink must not overwrite a new source'
            wait_for(lambda: layer.image is not None and layer.player.playbackState() == QMediaPlayer.PausedState)
            assert layer.image == first_frame and not video_controls.video_toggle.isChecked(), (
                layer.image.format(), first_frame.format(), layer.player.position(),
                video_controls.video_toggle.isChecked(), layer.image.size(), first_frame.size())
            video_controls.video_toggle.setChecked(True)
            wait_for(lambda: layer.image is not None and layer.player.playbackState() == QMediaPlayer.PlayingState)
            video_controls.video_toggle.setChecked(False)
            wait_for(lambda: layer.image is not None and layer.player.playbackState() == QMediaPlayer.PausedState)
            assert layer.image == first_frame, 'Toggling off repeatedly must select the same starting frame'
            video_controls.import_file(str(video))
            wait_for(lambda: video_controls.job is None)
            wait_for(lambda: layer.image is not None and layer.player.playbackState() == QMediaPlayer.PlayingState)
            assert video_controls.video_toggle.isChecked() and window.settings['skin_video_enabled'], 'New videos start enabled'
            window.set_skin({'skin_mask': 100})
            wait_for(lambda: layer.player.playbackState() == QMediaPlayer.PausedState)
            frame = layer.image
            QTest.qWait(150)
            assert layer.image is frame, 'Fully masked video must skip frame conversion'
            assert video_editor.preview.background is frame
            assert layer.grab().toImage().pixelColor(10, 10) == theme.qcolor(theme.BG)
            window.set_skin({'skin_mask': 35})
            wait_for(lambda: layer.player.playbackState() == QMediaPlayer.PlayingState)
            QTest.qWait(1400)
            assert layer.player.playbackState() == QMediaPlayer.PlayingState, 'Background must loop'
            assert live.player.get_time() > live_time and live.player.is_playing(), 'Skin changes must leave live playback running'
            assert window.players[tile] is live and int(tile.video.winId()) == hwnd
            window.hide()
            QTest.qWait(30)
            assert layer.player.playbackState() == QMediaPlayer.PausedState
            window.show()
            wait_for(lambda: layer.player.playbackState() == QMediaPlayer.PlayingState)
            invalid_video = folder/'invalid.mp4'
            invalid_video.write_bytes(b'not a video')
            window.set_skin({'skin_background': import_asset(invalid_video), 'skin_mask': 35})
            wait_for(lambda: bool(window.skin_controller.error))
            assert layer.image is None and not layer.player.isPlaying()
            window.set_skin({'skin_background': window.settings['skin_background'], 'skin_mask': 40})
            assert window.skin_controller.error, 'Changing the mask must not hide a decoder error'
            window.set_skin({'skin_background': '', 'skin_mask': 35})
            assert video_editor.preview.background is None
            video_editor.close()
            assert layer.player.playbackState() == QMediaPlayer.StoppedState
            assert not theme._skin_active and 'rgba(' not in window.sidebar.styleSheet()
            missing = 'utils/skins/missing.png'
            window.set_skin({'skin_background': missing, 'skin_mask': 35})
            assert window.skin_controller.error and layer.image is None
            window.set_skin({'skin_background': '', 'skin_mask': 35})
            window.close()
        # Saved relative asset paths survive window reconstruction.
        with patch.object(config, 'CONFIG_PATH', str(folder/'saved-state.json')), patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
            config.save({'version': config.STATE_VERSION, 'plugins_enabled': [], 'settings': {'skin_background': custom, 'skin_mask': 50, 'skin_sidebar': True, 'auto_update': False}})
            persisted = config.load()
        with patch('PySide6.QtCore.QTimer.singleShot'):
            restored = module.MainWindow([], [], state=persisted)
        assert restored.skin_controller.layer.image.pixelColor(0, 0) == QColor('#426CDB')
        assert restored.settings['skin_sidebar'] and 'rgba(' in restored.sidebar.styleSheet()
        restored.close()
        theme.set_skin_active(False)
    print('PASS: copied/persisted image, default sidebar coverage, asynchronous import, translucent panels, plugin ownership, path validation, muted video/first-frame mode, pause/resume and stable video HWND')


if __name__ == '__main__':
    main()
