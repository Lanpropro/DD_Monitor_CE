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
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QInputMethodEvent, QKeySequence, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QKeySequenceEdit, QMessageBox, QPushButton
from PySide6.QtTest import QTest
from ddm import config, layouts, room_presets, theme
from ddm.app import MainWindow
from ddm.layout_picker import LayoutPicker
from ddm.player import TilePlayer
from ddm.room_presets_ui import thumbnail
from selfcheck_corner_resize import border_for, drag
from selfcheck_layout_16 import resize_picker


def expect_invalid(snapshot):
    try:
        room_presets.validate(snapshot)
    except ValueError:
        return
    raise AssertionError(snapshot)


def contrast(first, second):
    def luminance(color):
        values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                  for v in (color.redF(), color.greenF(), color.blueF())]
        return sum(a * b for a, b in zip(values, (.2126, .7152, .0722)))
    a, b = sorted((luminance(first), luminance(second)))
    return (b + .05) / (a + .05)


def check_portrait_preset_cards():
    picker = LayoutPicker('portrait_main2', preferred_size=QSize(568, 532))
    picker.setAttribute(Qt.WA_ShowWithoutActivating)
    picker.show()
    QTest.qWait(20)
    try:
        assert picker.group() == '竖屏布局'
        cards = picker._cards[picker.group()]
        assert len(cards) == 6
        for width, columns in ((568, 3), (320, 2), (568, 3)):
            picker.resize(width, 532)
            QTest.qWait(20)
            assert len({card.x() for card in cards}) == columns, width
            assert len({card.y() for card in cards}) == 6 // columns
            assert cards[columns].y() == cards[0].height() + picker._grid.spacing()
            for card in cards:
                assert card.isVisible() and card.height() > card.width()
                assert card.iconSize().height() >= 100
                assert card.icon().actualSize(card.iconSize()) == card.iconSize()
                assert card.fontMetrics().horizontalAdvance(card.text()) <= card.width() - 16
                assert card.geometry().right() < picker.scroll.viewport().width()
        picker.resize(320, 245)
        QTest.qWait(20)
        scrollbar = picker.scroll.verticalScrollBar()
        assert scrollbar.maximum() > 0
        scrollbar.setValue(scrollbar.maximum())
        assert picker.scroll.viewport().rect().contains(cards[-1].mapTo(
            picker.scroll.viewport(), cards[-1].rect().center()))

        picker.set_group('普通布局')
        QTest.qWait(20)
        assert all(not card.isVisible() for card in cards)
        assert all(card.width() > card.height() for card in picker._cards['普通布局'])
        picker.set_group('竖屏布局')
        QTest.qWait(20)
        assert scrollbar.value() == 0 and cards[0].isChecked()
        chosen = []
        picker.chosen.connect(chosen.append)
        QTest.mouseClick(cards[0], Qt.LeftButton)
        assert chosen == ['portrait_main2'] and not picker.isVisible()
    finally:
        picker.close()


def check_layout_only_presets(app, directory):
    from ddm.layout_preset_editor import LayoutPresetEditor
    from ddm.layout_presets_ui import edit_shortcut

    rooms = [dict(room_id=str(n), uname=str(n), live=False) for n in range(20, 26)]
    state = {'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}}
    window = MainWindow(rooms, deepcopy(rooms), layout_id='corner', state=state)
    window.resize(1180, 760)
    window.show()
    app.processEvents()
    try:
        presets = window.layout_presets
        wall = window.wall
        original = wall.corner_ratios()
        before = [(tile, tile.room['room_id'], tile.volume, tile.muted, tile.audio_channel,
                   int(tile.video.winId())) for tile in wall.tiles]
        before_geometry = [tile.geometry() for tile in wall.tiles]

        def button(editor, label):
            return next(item for item in editor.actions.findChildren(QPushButton) if item.text() == label)

        def start_editor():
            window.sidebar.open_layout_picker()
            picker = window.sidebar._picker
            assert picker.custom_layouts_page is None
            assert picker.edit_button.objectName() == 'IconButton'
            assert picker.edit_button.text() == '修改布局'
            footer = picker.layout().itemAt(picker.layout().count() - 1).layout()
            assert [item.widget() for index in range(footer.count())
                    if (item := footer.itemAt(index)).widget()] == [picker.edit_button]
            QTest.mouseClick(picker.edit_button, Qt.LeftButton)
            assert picker.isVisible() and picker.edit_button.text() == '选择要修改的布局'
            card = next(card for card in picker._cards[picker.group()] if card.property('layoutId') == 'corner')
            QTest.mouseClick(card, Qt.LeftButton)
            app.processEvents()
            editor = next(dialog for dialog in window.findChildren(LayoutPresetEditor) if dialog.isVisible())
            assert not picker.isVisible()
            assert editor.geometry().topLeft() == wall.mapToGlobal(QPoint())
            assert editor.size() == wall.size() and editor.testAttribute(Qt.WA_TranslucentBackground)
            view = editor.preview
            leaves, dividers, scale, origin, _ = view._geometry()
            assert view.geometry() == editor.rect()
            assert scale == 1 and origin == QPoint()
            assert [leaves[cell] for cell in range(6)] == before_geometry
            assert {(node.key, index): rect for node, index, rect, _ in dividers} == wall._divider_rects
            return editor

        def adjust(editor):
            view = editor.preview
            _, dividers, scale, origin, _ = view._geometry()
            rect = next(rect for node, index, rect, _ in dividers if (node.key, index) == ('root/0', 0))
            point = view._mapped(rect, scale, origin).center().toPoint()
            assert view._hit(point)[0].key == 'root/0', 'The T-junction must hit the main divider grip'
            QTest.mousePress(view, Qt.LeftButton, pos=point)
            QTest.mouseMove(view, point - QPoint(75, 0))
            QTest.mouseRelease(view, Qt.LeftButton, pos=point - QPoint(75, 0))
            _, dragged, _, _, _ = view._geometry()
            moved = next(rect for node, index, rect, _ in dragged if (node.key, index) == ('root/0', 0))
            assert moved.left() == rect.left() - 75, 'The divider must follow the pointer at wall scale'
            assert editor.ratios()['width'] < original['width']
            assert wall.corner_ratios() == original
            assert [tile.geometry() for tile in wall.tiles] == before_geometry

        editor = start_editor()
        reset = button(editor, '恢复默认')
        undo = button(editor, '撤回')
        assert not undo.isEnabled()
        QTest.mouseClick(reset, Qt.LeftButton)
        assert not undo.isEnabled()
        adjust(editor)
        first = editor.ratios()
        adjust(editor)
        second = editor.ratios()
        assert second['width'] < first['width']
        QTest.mouseClick(reset, Qt.LeftButton)
        assert editor.ratios() == original
        for expected in (second, first, original):
            assert undo.isEnabled()
            QTest.mouseClick(undo, Qt.LeftButton)
            assert editor.ratios() == expected
        assert not undo.isEnabled() and not presets.override_state()
        adjust(editor)
        QTest.keyClick(editor, Qt.Key_Escape)
        app.processEvents()
        assert not presets.override_state() and wall.corner_ratios() == original

        editor = start_editor()
        adjust(editor)
        saved = editor.ratios()
        saved_geometry = editor.preview._geometry()[0]
        QTest.mouseClick(button(editor, '保存布局'), Qt.LeftButton)
        app.processEvents()
        assert wall.corner_ratios() == saved
        assert [saved_geometry[cell] for cell in range(6)] == [tile.geometry() for tile in wall.tiles]
        assert [(tile, tile.room['room_id'], tile.volume, tile.muted, tile.audio_channel,
                 int(tile.video.winId())) for tile in wall.tiles] == before

        window.sidebar.open_layout_picker()
        picker = window.sidebar._picker
        corner = next(card for card in picker._cards['普通布局'] if card.property('layoutId') == 'corner')
        assert '恢复默认比例' not in corner.toolTip()
        corner.click()  # Reselecting the current preset uses the saved override.
        assert wall.corner_ratios() == saved and presets.override_state()['corner']['ratios'] == saved
        picker.show()

        def choose_shortcut(dialog):
            dialog.findChild(QKeySequenceEdit).setKeySequence(QKeySequence('Ctrl+1'))
            return QDialog.Accepted

        with patch.object(QDialog, 'exec', choose_shortcut):
            edit_shortcut(picker, presets, 'corner')
        picker.close()
        assert presets.shortcuts() == {'Ctrl+1': 'corner'}
        for binding in ('Ctrl+1', 'F'):
            try:
                presets.bind('1x1', binding)
            except ValueError:
                pass
            else:
                raise AssertionError(f'Occupied shortcut {binding} must be rejected')
        presets.bind('1x1', 'Ctrl+2')
        window.activateWindow()
        window.setFocus()
        app.processEvents()
        QTest.keySequence(window, QKeySequence('Ctrl+2'))
        assert wall.layout_id == '1x1' and len(wall.visible_tiles()) == 1
        QTest.keySequence(window, QKeySequence('Ctrl+1'))
        assert wall.layout_id == 'corner' and wall.corner_ratios() == saved
        assert [(tile, tile.room['room_id'], tile.volume, tile.muted, tile.audio_channel,
                 int(tile.video.winId())) for tile in wall.tiles] == before
        window.sidebar.search.setFocus()
        app.processEvents()
        assert not window._handle_shortcut('Ctrl+2')

        # Editing a different built-in preset stages only that record until it is selected.
        editor = presets.edit('1x2')
        view = editor.preview
        app.processEvents()
        _, dividers, scale, origin, _ = view._geometry()
        point = view._mapped(dividers[0][2], scale, origin).center().toPoint()
        QTest.mousePress(view, Qt.LeftButton, pos=point)
        QTest.mouseRelease(view, Qt.LeftButton, pos=point + QPoint(50, 0))
        editor.accept()
        app.processEvents()
        assert wall.layout_id == 'corner' and wall.corner_ratios() == saved
        assert presets.override_state()['1x2']['ratios']['root'][0] > .5

        presets.select_builtin('1x2')
        editor = presets.edit('1x2')
        app.processEvents()
        leaves, dividers, scale, origin, _ = editor.preview._geometry()
        assert scale == 1 and origin == QPoint()
        assert leaves == {cell: tile.geometry() for cell, tile in wall._preset_widgets().items()}
        assert {(node.key, index): rect for node, index, rect, _ in dividers} == wall._divider_rects
        custom = editor.ratios()
        QTest.mouseClick(button(editor, '恢复默认'), Qt.LeftButton)
        assert editor.ratios() == {} and presets.override_state()['1x2']['ratios'] == custom
        QTest.mouseClick(button(editor, '撤回'), Qt.LeftButton)
        assert editor.ratios() == custom
        editor.reject()
        presets.select_builtin('corner')

        stored = window.current_state()
        assert stored['ui']['layout_preset_overrides']['corner'] == {'ratios': saved, 'shortcut': 'Ctrl+1'}
        assert not stored['ui']['custom_layout_presets'] and not stored['room_presets']['items']
        with patch.object(config, 'CONFIG_PATH', str(directory / 'layouts.json')), patch.dict(os.environ):
            os.environ.pop('DDM_NO_SAVE', None)
            config.save(stored, raise_errors=True)
            reopened_state = config.load()
        reopened = MainWindow([], layout_id='1x1', state=reopened_state)
        try:
            assert reopened.layout_presets.shortcuts()['Ctrl+1'] == 'corner'
            reopened.layout_presets.select_builtin('corner')
            assert reopened.wall.corner_ratios() == saved
            assert not any(tile.room.get('room_id') for tile in reopened.wall.tiles)
            editor = reopened.layout_presets.edit('corner')
            app.processEvents()
            QTest.mouseClick(button(editor, '恢复默认'), Qt.LeftButton)
            assert editor.ratios() == original and reopened.wall.corner_ratios() == saved
            QTest.mouseClick(button(editor, '保存布局'), Qt.LeftButton)
            assert reopened.wall.corner_ratios() == original
            assert reopened.layout_presets.override_state()['corner']['ratios'] == original
            assert reopened.layout_presets.shortcuts()['Ctrl+1'] == 'corner'
        finally:
            reopened.close()
    finally:
        window.close()
        app.processEvents()


def check_snap_grid_and_other_presets(app):
    from PySide6.QtCore import QEvent, QMimeData, QPointF
    from PySide6.QtGui import QColor, QContextMenuEvent, QDragEnterEvent, QDropEvent, QImage, QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QMenu
    from ddm.layout_preset_editor import LayoutPresetEditor
    from ddm import snap_grid
    from ddm.sidebar_drag import ROOM_MIME, TILE_MIME

    rooms = [dict(room_id=str(n), uname=str(n), live=False) for n in (701, 702)]
    window = MainWindow(rooms, deepcopy(rooms), layout_id='corner',
                        state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
    window.resize(1800, 1000)
    window.show()
    app.processEvents()
    wall = window.wall
    presets = window.layout_presets
    tiles = wall.tiles[:2]
    handles = [int(tile.video.winId()) for tile in tiles]

    def open_from(group, base):
        window.sidebar.open_layout_picker()
        picker = window.sidebar._picker
        picker.set_group(group)
        if group == '自定义布局':
            assert picker.card_ids() == ['custom_grid9', 'custom_grid16']
            assert not any(layouts.snap_grid_size(card.property('layoutId')) for card in picker._cards['普通布局'])
            heading, = picker._sections[group]
            assert heading.text() == group and heading.isVisible()
            tab = picker._tabs[group]
            assert tab.text() == group and tab.width() >= tab.sizeHint().width()
            assert heading.width() == heading.sizeHint().width() < picker.scroll.viewport().width()
            assert picker._tabs[group].isChecked()
        assert picker.edit_button.isVisible() and picker.edit_button.text() == '修改布局'
        picker.edit_button.click()
        assert picker.isVisible() and picker.edit_button.text() == '选择要修改的布局'
        card = next(card for card in picker._cards[group] if card.property('layoutId') == base)
        card.click()
        app.processEvents()
        editor = next(dialog for dialog in window.findChildren(LayoutPresetEditor) if dialog.isVisible())
        assert editor.preview.base == base
        return editor

    def gesture(view, start, end):
        QTest.mousePress(view, Qt.LeftButton, pos=start)
        QTest.mouseMove(view, end)
        QTest.mouseRelease(view, Qt.LeftButton, pos=end)

    def wheel(widget, point, delta, modifiers=Qt.ControlModifier):
        event = QWheelEvent(QPointF(point), QPointF(widget.mapToGlobal(point)), QPoint(),
                            QPoint(0, delta), Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)
        return event.isAccepted()

    def drop_room(kind, room_id, point):
        mime = QMimeData()
        mime.setData(kind, room_id.encode())
        action = Qt.MoveAction if kind == TILE_MIME else Qt.CopyAction
        enter = QDragEnterEvent(point, action, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(wall, enter)
        drop = QDropEvent(QPointF(point), action, mime, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(wall, drop)
        return enter.isAccepted(), drop.isAccepted()

    def begin_wall_drag(grab_point):
        local = first.mapFrom(wall, grab_point)
        QTest.mousePress(first, Qt.LeftButton, pos=local)
        moved = local + QPoint(18, 0)
        event = QMouseEvent(QEvent.MouseMove, QPointF(moved), QPointF(first.mapToGlobal(moved)),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(first, event)
        assert session.active and session.ghost is None
        assert wall.snap_grid.guide.isVisible()
        assert len(wall.snap_grid.guide.units) == 16

    try:
        for group, base in (('弹幕布局', 'dm_pair'), ('竖屏布局', 'portrait_dm2')):
            editor = open_from(group, base)
            assert wall.layout_id == 'corner'
            view = editor.preview
            _, dividers, scale, origin, _ = view._geometry()
            node, _, handle, _ = next(entry for entry in dividers if entry[0].key == 'root' and entry[1] == 0)
            start = view._mapped(handle, scale, origin).center().toPoint()
            assert view._hit(start)[0].key == node.key
            delta = QPoint(-30, 0) if node.axis == Qt.Horizontal else QPoint(0, -30)
            gesture(view, start, start + delta)
            assert editor.ratios(), base
            editor.reject()
        presets.select_builtin('dm_pair')
        app.processEvents()
        video, chat = wall._preset_widgets().values()
        assert abs(video.width() / (video.width() + chat.width()) - .8) < .005
        editor = presets.edit('dm_pair')
        assert editor.preview.base == 'dm_pair'
        editor.reject()

        for base, count in (('custom_grid9', 3), ('custom_grid16', 4)):
            presets.select_builtin(base)
            app.processEvents()
            assert wall.acceptDrops() and wall.visible_tiles() == tiles
            units = snap_grid.geometry(count, layouts.even_cells(count, count),
                                       wall._corner_area(), wall.grid.spacing())
            first, second = tiles
            first_cell = first.video.rect().center()
            assert wheel(first.video, first_cell, 120)
            assert wall.snap_grid.cells()[0] == (0, 0, 1, 1), 'An occupied cell blocks growth'

            with patch.object(window, '_stop_tile') as stop, patch.object(window, 'start_tile') as start:
                assert drop_room(TILE_MIME, '702', units[count * count - 1].center()) == (True, True)
                assert second.geometry() == units[count * count - 1]
                assert wheel(first.video, first_cell, 120)
                assert wall.snap_grid.cells()[0] == (0, 0, 2, 2)
                wheel(first.video, first.video.rect().center(), -120, Qt.NoModifier)
                assert wall.snap_grid.cells()[0] == (0, 0, 2, 2)
                assert wheel(first.video, first.video.rect().center(), -120)
                assert first.geometry() == units[0]
                stop.assert_not_called()
                start.assert_not_called()

            editor = open_from('自定义布局', base)
            view = editor.preview
            before = view.draft
            with patch.dict(window.shortcuts, {'layout_grow': 'Ctrl+Alt+WheelDown'}):
                wheel(view, units[0].center(), 120)
                assert view.draft == before
                assert wheel(view, units[0].center(), -120, Qt.ControlModifier | Qt.AltModifier)
            assert view.draft[0] == (0, 0, 2, 2)
            assert wheel(view, units[0].center(), 120, Qt.AltModifier)
            assert view.draft[0] == (0, 0, 3, 2)
            view.undo()
            assert view.draft[0] == (0, 0, 2, 2)
            assert first.geometry() == units[0]
            view.undo()
            assert view.draft == before
            assert wheel(view, units[0].center(), 120)
            editor.accept()
            assert wall.tiles[:2] == tiles and [int(tile.video.winId()) for tile in tiles] == handles
            snapshot = window.room_preset_snapshot()
            assert snapshot['layout']['ratios']['grid'][0] == (0, 0, 2, 2)
            assert set(room_presets.thumbnail_geometry(snapshot, wall.rect())) == {0, 1}

        assert drop_room(TILE_MIME, '701', units[3].center()) == (False, False)
        assert wall.snap_grid.cells()[0] == (0, 0, 2, 2), 'Moving a large tile cannot cross the grid edge'

        assert wheel(first.video, first.video.rect().center(), -120)
        assert wheel(first.video, first.video.rect().center(), 120)
        session = window.sidebar.drag_session
        with patch('ddm.sidebar_drag.widget_at', side_effect=lambda point:
                   first if first.geometry().contains(wall.mapFromGlobal(point)) else wall):
            begin_wall_drag(units[5].center())
            guide = wall.snap_grid.guide
            assert guide.target == first.geometry()
            session.position = wall.mapToGlobal(units[6].center())
            session._update_target()
            assert guide.target == units[1].united(units[6])
            assert session.finish() and not guide.isVisible()
            assert first.geometry() == units[1].united(units[6])

            begin_wall_drag(units[6].center())
            session.position = wall.mapToGlobal(units[12].center())
            session._update_target()
            assert guide.target is None and guide.isVisible()
            session.cancel()
            assert not guide.isVisible()
            assert first.geometry() == units[1].united(units[6])

            begin_wall_drag(units[6].center())
            session.position = wall.mapToGlobal(units[5].center())
            assert session.finish() and not guide.isVisible()
            assert first.geometry() == units[0].united(units[5])
            assert [int(tile.video.winId()) for tile in wall.tiles[:2]] == handles

            # A 2x2 source can swap with an edge 1x1 even where placing its footprint would overflow.
            first_rect, second_rect = first.geometry(), second.geometry()
            before = wall.snap_grid.cells()
            players = {first: Mock(), second: Mock()}
            with patch.dict(window.players, players), patch.dict(first.room, live=True), \
                    patch.dict(second.room, live=True), patch.object(window, '_stop_tile') as stop, \
                    patch.object(window, 'start_tile') as start, patch.object(window.recorder, 'stop') as stop_recording:
                first.state_control.pending_grid_aspect = wall.layout_id
                second.state_control.pending_grid_aspect = wall.layout_id
                window._save_timer.stop()
                begin_wall_drag(units[0].center())
                session.position = wall.mapToGlobal(second_rect.center())
                session._update_target()
                assert guide.isVisible() and (guide.swap_source, guide.target) == (first_rect, second_rect)
                assert first.geometry() == first_rect and second.geometry() == second_rect
                assert session.finish() and not guide.isVisible()
                assert first.geometry() == second_rect and second.geometry() == first_rect
                assert wall.snap_grid.cells() == before and window._save_timer.isActive()
                assert all(window.players[tile] is players[tile] for tile in tiles)
                assert [int(tile.video.winId()) for tile in tiles] == handles
                assert all(tile.state_control.pending_grid_aspect is None for tile in tiles)
                assert not any(getattr(tile, '_card_drop_overlay', None) for tile in tiles)
                begin_wall_drag(units[15].center())
                session.position = wall.mapToGlobal(first_rect.center())
                assert session.finish() and not guide.isVisible()
                assert first.geometry() == first_rect and second.geometry() == second_rect
                stop.assert_not_called()
                start.assert_not_called()
                stop_recording.assert_not_called()

        item = window.sidebar.items()[0]
        mime = QMimeData()
        mime.setData(ROOM_MIME, b'701')
        with patch('ddm.sidebar_drag.widget_at', return_value=wall) as hit:
            assert session.start(item, mime, item._drag_pixmap(), QPoint(), wall.mapToGlobal(units[8].center()))
            assert guide.isVisible() and session.ghost is not None
            hit.return_value = window.sidebar
            session._update_target()
            assert not guide.isVisible()
            session.cancel()

        controller = window.skin_controller
        with tempfile.TemporaryDirectory(prefix='ddm-grid-wallpaper-') as temporary:
            asset = Path(temporary) / 'utils' / 'skins' / 'background.png'
            asset.parent.mkdir(parents=True)
            wallpaper = QColor('#efb531')
            image = QImage(QSize(12, 12), QImage.Format_RGB32)
            image.fill(wallpaper)
            assert image.save(str(asset))
            sample = wall.mapTo(window, units[12].center())
            with patch.object(config, 'data_root', return_value=temporary), patch.dict(window.settings, {
                    'skin_background': 'utils/skins/background.png', 'skin_mask': 35, 'skin_mask_enabled': True}):
                controller.refresh()
                app.processEvents()
                base = controller.layer.grab().toImage().pixelColor(controller.layer.rect().center())
                masked = window.grab().toImage().pixelColor(sample)
                tint = theme.qcolor(theme.BG)
                opacity = .84
                assert all(abs(result - (original * (1 - opacity) + color * opacity)) <= 2
                           for result, original, color in zip(masked.getRgb()[:3], base.getRgb()[:3], tint.getRgb()[:3]))
                window.settings['skin_mask'] = 70
                controller.refresh()
                app.processEvents()
                assert window.grab().toImage().pixelColor(sample) != masked
                window.settings['skin_mask_enabled'] = False
                controller.refresh()
                app.processEvents()
                assert window.grab().toImage().pixelColor(sample) == wallpaper
            controller.refresh()
            app.processEvents()

        chat_points = [units[index].center() for index in (2, 6)]
        for point in chat_points:
            event = QContextMenuEvent(QContextMenuEvent.Mouse, point, wall.mapToGlobal(point))
            QApplication.sendEvent(wall, event)
            menu = QApplication.activePopupWidget()
            assert isinstance(menu, QMenu)
            action = next(item for item in menu.actions() if item.text() == '添加弹幕格')
            action.trigger()
            menu.close()
        panes = wall.pane_danmaku
        assert len(panes.panels) == 2 and wall.visible_tiles() == tiles
        assert all(any(panel.geometry().contains(point) for panel in panes.rendered()) for point in chat_points)
        assert wheel(tiles[0].video, tiles[0].video.rect().center(), 120)
        assert wall.snap_grid.cells()[0] == (0, 0, 2, 2), 'An independent chat pane also blocks growth'

        panel = next(panel for panel in panes.rendered() if panel.geometry().contains(chat_points[0]))
        start = panel.rect().center()
        moved = start + QPoint(18, 0)
        event = QMouseEvent(QEvent.MouseMove, QPointF(moved), QPointF(panel.mapToGlobal(moved)),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        with patch('ddm.sidebar_drag.widget_at', return_value=panel) as hit, \
                patch('ddm.danmaku_widgets.QDrag', side_effect=AssertionError('Native drag bypasses the grid')):
            QTest.mousePress(panel, Qt.LeftButton, pos=start)
            QApplication.sendEvent(panel, event)
            assert session.active and guide.isVisible()
            hit.return_value = first.video
            session.position = first.video.mapToGlobal(first.video.rect().center())
            session._update_target()
            assert session.active and guide.isVisible() and guide.target is None
            assert session.target in (None, wall), 'The video tile cannot take over the drag'
            hit.return_value = wall
            destination = units[8].center()
            QTest.mouseRelease(wall, Qt.LeftButton, pos=destination)
            assert not session.active and not guide.isVisible()
            assert panel.geometry() == units[8] and panel in panes.rendered()
            assert all(tile.room['room_id'] == room['room_id'] for tile, room in zip(tiles, rooms))

        wall.grab().save(str(Path(__file__).resolve().parents[1] / 'work' / 'custom-grid16.png'))

        point = units[7].center()
        room = dict(room_id='703', uname='拖入测试', live=False)
        previous = wall.layout_ratios()
        with patch.object(window, '_room_dict', return_value=None):
            assert drop_room(ROOM_MIME, '999', units[9].center()) == (True, False)
        assert wall.layout_ratios() == previous
        with patch.object(window, '_room_dict', return_value=room):
            assert drop_room(ROOM_MIME, '703', point) == (True, True)
        added = window._tile_of('703')
        assert added.geometry() == units[7] and added.isVisible()
        added.closeRequested.emit(added.room)
        assert added.isHidden()

        restored_state = window.current_state()
        resumed = MainWindow(rooms, deepcopy(rooms), layout_id='custom_grid16', state=restored_state)
        try:
            resumed.show()
            app.processEvents()
            assert resumed.wall.layout_ratios()['custom_grid16']['grid'][0] == (0, 0, 2, 2)
            assert len(resumed.wall.pane_danmaku.rendered()) == 2
            panes = resumed.wall.pane_danmaku
            menu = panes.create_menu(next(iter(panes.panels)))
            assert menu.actions()[0].text() == '移除弹幕格'
            menu.actions()[0].trigger()
            menu.deleteLater()
            assert len(panes.rendered()) == 1
            resumed.add_to_wall(room)
            assert resumed._tile_of('703').isVisible()
            resumed.layout_presets.select_builtin('custom_grid9')
            assert len(resumed.wall.visible_tiles()) == 3 and not panes.panels
            assert resumed.wall.layout_ratios()['custom_grid9']['grid'][0] == (0, 0, 2, 2)
            editor = resumed.layout_presets.edit('custom_grid9')
            editor.preview.reset_to_default()
            editor.accept()
            app.processEvents()
            assert len(resumed.wall.visible_tiles()) == 3
            assert resumed.wall.snap_grid.cells()[0] == (0, 0, 1, 1)
            resumed.layout_presets.select_builtin('3x3')
            assert len(resumed.wall.visible_tiles()) == 9 and not resumed.wall.acceptDrops()
        finally:
            resumed.close()
        for invalid in ([None] * 9, [(0, 0, 3, 4)] + [None] * 8):
            try:
                snap_grid.validate(3, invalid)
            except ValueError:
                pass
            else:
                raise AssertionError('Damaged grid must be rejected')
    finally:
        window.close()
        app.processEvents()


def check_full_snap_grid_swaps(app):
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from ddm.sidebar_drag import TILE_MIME

    for size in (3, 4):
        rooms = [dict(room_id=str(800 + i), uname=str(i), live=False) for i in range(size * size)]
        window = MainWindow(rooms, deepcopy(rooms), layout_id=f'custom_grid{size * size}',
                            state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
        window.resize(1400, 900)
        window.show()
        app.processEvents()
        try:
            wall = window.wall
            grid = wall.snap_grid
            assert len(wall.visible_tiles()) == size * size and len(grid.occupied()) == size * size
            first, source = wall.tiles[:2]
            destination = wall.tiles[-1]
            before = grid.cells()
            source_rect, destination_rect = source.geometry(), destination.geometry()
            # Duplicate room IDs can survive in old configurations. Swap the tile actually picked up.
            with patch.dict(first.room, room_id=source.room['room_id']), patch.dict(source.room, live=True), \
                    patch.dict(destination.room, live=True), patch.dict(window.players, {source: Mock(), destination: Mock()}):
                assert window._tile_of(source.room['room_id']) is first
                mime = QMimeData()
                mime.setData(TILE_MIME, source.room['room_id'].encode())
                assert grid.mark_drag(mime, source, source.rect().center())
                point = destination_rect.center()
                enter = QDragEnterEvent(point, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(wall, enter)
                assert enter.isAccepted()
                drop = QDropEvent(QPointF(point), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(wall, drop)
                assert drop.isAccepted()
                assert wall.tiles[0] is first and wall.tiles[1] is destination and wall.tiles[-1] is source
                assert source.geometry() == destination_rect and destination.geometry() == source_rect
                assert grid.cells() == before
        finally:
            window.close()
            app.processEvents()


def check_portrait_live_defaults(app):
    from threading import Event
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QWheelEvent
    from ddm import snap_grid
    from ddm.sidebar_drag import ROOM_MIME, TILE_MIME
    from selfcheck_stream_playback import Player

    landscape = {'w': 1920, 'h': 1080, 'dw': 1920, 'dh': 1080}
    rotated = {**landscape, 'rotate': 90}
    portrait = {'w': 1080, 'h': 1920}

    def resize_with_wheel(tile, delta, modifiers=Qt.ControlModifier):
        point = tile.video.rect().center()
        event = QWheelEvent(QPointF(point), QPointF(tile.video.mapToGlobal(point)), QPoint(),
                            QPoint(0, delta), Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
        assert QApplication.sendEvent(tile.video, event) and event.isAccepted()

    for layout_id, size in (('custom_grid9', 3), ('custom_grid16', 4)):
        preferred = 3 if size == 4 else 2
        window = MainWindow([], [], layout_id=layout_id, state={
            'plugins_enabled': [], 'settings': {'close_behavior': 'exit', 'auto_quality': False}})
        window.resize(1500, 850)
        window.show()
        app.processEvents()
        wall = window.wall
        grid = wall.snap_grid
        units = snap_grid.geometry(size, layouts.even_cells(size, size),
                                   wall._corner_area(), wall.grid.spacing())

        def drop_room(rid, point):
            mime = QMimeData()
            mime.setData(ROOM_MIME, rid.encode())
            room = dict(room_id=rid, uname=rid, live=False)
            enter = QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(wall, enter)
            event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            with patch.object(window, '_room_dict', return_value=room):
                QApplication.sendEvent(wall, event)
            assert enter.isAccepted() and event.isAccepted()
            return window._tile_of(rid)

        def first_frame(tile, params, *, pending=True):
            with patch.object(window.recorder, 'on_resolved'), patch.object(window, '_sync_replay_scope'):
                window.stream_playback.play_on(tile, 'http://127.0.0.1/fixture', player_type=Player)
            player = window.players[tile]
            try:
                assert player.report_video_resolution == pending
                player._prop = Mock(return_value=params)
                if pending:
                    player.videoResolutionChanged.emit(f"{params['w']}×{params['h']}")
                    assert player._prop.called and not player.report_video_resolution
                assert not grid.wants_video_aspect(tile)
                player._prop.reset_mock()
                player.videoResolutionChanged.emit('720×1280')
                player._prop.assert_not_called()
            finally:
                window.players.pop(tile, None)
                player.deleteLater()

        try:
            # This test uses the actual host resolution callback, with decoded metadata
            # supplied by the offline player fixture.
            window.add_to_wall(dict(room_id='801', uname='竖屏直播', live=False))
            first = window._tile_of('801')
            assert wall.layout_control.cell_of(first) == (0, 0, 1, 1)
            first_frame(first, rotated)
            assert wall.layout_control.cell_of(first) == (0, 0, preferred, 1)
            assert wall.layout_ratios()[layout_id]['grid'][0] == (0, 0, preferred, 1)

            grid.add_danmaku(units[size + 1].center())
            blocked = drop_room('802', units[1].center())
            first_frame(blocked, portrait)
            assert wall.layout_control.cell_of(blocked) == (0, 1, 1, 1)
            assert len(wall.pane_danmaku.panels) == 1

            edge = drop_room('803', units[size * (size - 1)].center())
            first_frame(edge, portrait)
            assert wall.layout_control.cell_of(edge) == (size - 1, 0, 1, 1)

            wide = drop_room('804', units[2].center())
            first_frame(wide, landscape)
            assert wall.layout_control.cell_of(wide) == (0, 2, 1, 1)
            with patch.dict(window.shortcuts, {'volume_up': 'Alt+WheelUp'}), \
                    patch.object(window, '_tile_under_cursor', return_value=wide):
                volume = wide.volume
                resize_with_wheel(wide, 120, Qt.AltModifier)
                assert wide.volume == volume and wall.layout_control.cell_of(wide) == (0, 2, 2, 1)
                resize_with_wheel(wide, -120, Qt.AltModifier)
                assert wall.layout_control.cell_of(wide) == (0, 2, 1, 1)

            manual = drop_room('805', units[size + 2].center())
            assert grid.resize_tile(manual, -1)
            first_frame(manual, portrait, pending=False)
            assert wall.layout_control.cell_of(manual) == (1, 2, 1, 1)

            if size == 4:
                index = next(i for i in range(size * size) if i not in grid.occupied())
                enlarged = snap_grid.place(size, grid.cells(), index, (2, 2, 2, 2), grid.occupied())
                grid._commit(enlarged)
                window.add_to_wall(dict(room_id='807', uname='竖屏直播', live=False))
                tile = window._tile_of('807')
                assert wall.layout_control.cell_of(tile) == (2, 2, 2, 2)
                first_frame(tile, portrait)
                assert wall.layout_control.cell_of(tile) == (2, 2, 2, 1)

            window.layout_presets.select_builtin('4x4')
            window.add_to_wall(dict(room_id='806', uname='普通布局直播', live=False))
            fixed = window._tile_of('806')
            first_frame(fixed, portrait, pending=False)
            with patch.dict(window.shortcuts, {'volume_up': 'Alt+WheelUp'}), \
                    patch.object(window, '_tile_under_cursor', return_value=fixed):
                volume = fixed.volume
                resize_with_wheel(fixed, 120, Qt.AltModifier)
                assert fixed.volume > volume
            menu = fixed.build_menu()
            assert all(action.data() != 'portrait_footprint' for action in menu.actions())
            menu.deleteLater()
        finally:
            window.close()
            app.processEvents()

        room = dict(room_id='811', uname='竖屏直播', live=True, live_start_ts=123)
        window = MainWindow([room], [], layout_id=layout_id, state={
            'plugins_enabled': [], 'settings': {'close_behavior': 'exit', 'auto_quality': False}})
        window.resize(1500, 850)
        window.show()
        app.processEvents()
        wall = window.wall
        grid = wall.snap_grid
        session = window.sidebar.drag_session
        units = snap_grid.geometry(size, layouts.even_cells(size, size),
                                   wall._corner_area(), wall.grid.spacing())
        point = units[len(units) - 1].center()
        expected = units[len(units) - 1].united(units[len(units) - size * (preferred - 1) - 1])
        mime = QMimeData()
        mime.setData(ROOM_MIME, b'811')
        release = Event()

        def room_init(room_id, *, timeout):
            assert room_id == '811' and timeout == 2 and release.wait(3)
            return {'is_portrait': True, 'live_status': 1}

        try:
            with patch('ddm.sidebar_drag.widget_at', return_value=wall), patch('ddm.bili._room_init', side_effect=room_init):
                def begin_drag():
                    assert session.start(window.sidebar.items()[0], mime, QPixmap(), QPoint(), wall.mapToGlobal(point))

                begin_drag()
                assert grid.guide.isVisible() and grid.guide.target is None
                if size == 4:
                    # Releasing before the lookup returns must not briefly create a 1×1 tile.
                    assert session.finish() and window._tile_of('811') is None
                release.set()
                worker = grid._orientation_checks['811']
                assert worker.wait(3000)
                app.processEvents()
                if size == 3:
                    session._tick()
                    assert grid.guide.target == expected
                    assert session.finish()
                tile = window._tile_of('811')
                assert tile is not None and tile.geometry() == expected
                assert wall.layout_control.cell_of(tile) == (size - preferred, size - 1, preferred, 1)
                assert not grid.wants_video_aspect(tile)

                resize_with_wheel(tile, 120)
                assert tile.geometry() == expected, 'A portrait tile at the grid edge must not widen into a square'
                if size == 4:
                    tile.set_room(None)
                    grid.sync_visibility()
                    begin_drag()
                    assert grid.guide.target == expected
                    assert session.finish() and window._tile_of('811').geometry() == expected
                    tile = window._tile_of('811')

                other = 5 - preferred
                resize_with_wheel(tile, 120 if other == 3 else -120, Qt.AltModifier)
                index = wall.pane_danmaku.cell_for_tile(tile)
                assert wall.layout_ratios()[layout_id]['grid'][index][2:] == (other, 1)
                if other == 3:
                    resize_with_wheel(tile, -120, Qt.AltModifier)
                assert wall.layout_control.cell_of(tile)[2:] == (2, 1)

                move = QMimeData()
                move.setData(TILE_MIME, b'811')
                grid.show_drag_guide(move, units[0].center())
                assert grid.guide.target == units[0].united(units[size])
                assert grid.drop(move, units[0].center())
                grid.hide_drag_guide()
                if size == 4:
                    resize_with_wheel(tile, 120)
                    assert wall.layout_control.cell_of(tile) == (0, 0, 4, 2)
                    resize_with_wheel(tile, -120, Qt.AltModifier)
                    assert wall.layout_control.cell_of(tile) == (0, 0, 3, 2)
                    resize_with_wheel(tile, -120)
                    assert wall.layout_control.cell_of(tile) == (0, 0, 3, 2)
                    resize_with_wheel(tile, 120, Qt.AltModifier)
                    resize_with_wheel(tile, -120)
                    assert wall.layout_control.cell_of(tile) == (0, 0, 2, 1)
                    custom = Qt.AltModifier | Qt.ControlModifier
                    with patch.dict(window.shortcuts, {
                        'layout_grow': 'Ctrl+Alt+WheelDown', 'layout_shrink': 'Ctrl+Alt+WheelUp',
                        'layout_portrait_tall': 'Ctrl+Shift+WheelDown', 'layout_portrait_short': 'Ctrl+Shift+WheelUp',
                    }):
                        resize_with_wheel(tile, -120, custom)
                        assert wall.layout_control.cell_of(tile) == (0, 0, 4, 2)
                        resize_with_wheel(tile, 120, custom)
                        assert wall.layout_control.cell_of(tile) == (0, 0, 2, 1)
                        resize_with_wheel(tile, -120, Qt.ControlModifier | Qt.ShiftModifier)
                        assert wall.layout_control.cell_of(tile) == (0, 0, 3, 1)
                        resize_with_wheel(tile, 120, Qt.ControlModifier | Qt.ShiftModifier)
                        assert wall.layout_control.cell_of(tile) == (0, 0, 2, 1)

                resize_with_wheel(tile, 120, Qt.AltModifier)
                resize_with_wheel(tile, 120)
                resize_with_wheel(tile, -120)
                assert wall.layout_control.cell_of(tile) == (0, 0, 3, 1)
                resize_with_wheel(tile, 120, Qt.AltModifier)
                assert wall.layout_control.cell_of(tile) == (0, 0, size, 1)
                if size == 4:
                    resize_with_wheel(tile, -120, Qt.AltModifier)
                resize_with_wheel(tile, -120, Qt.AltModifier)

                grid.add_danmaku(units[2 * size].center())
                with patch.dict(window.shortcuts, {'volume_up': 'Alt+WheelUp'}), \
                        patch.object(window, '_tile_under_cursor', return_value=tile):
                    volume = tile.volume
                    resize_with_wheel(tile, 120, Qt.AltModifier)
                    assert tile.volume == volume
                assert wall.layout_control.cell_of(tile) == (0, 0, 2, 1)
                menu = tile.build_menu()
                assert all(action.data() != 'portrait_footprint' for action in menu.actions())
                menu.deleteLater()
        finally:
            release.set()
            session.cancel()
            window.close()
            app.processEvents()


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
    check_portrait_preset_cards()
    fixture = [dict(room_id=str(1000 + i) if i != 2 else '', uname=f'主播 {i + 1}',
                    live=True, live_known=True, volume=0 if i == 2 else (100 if i == 5 else 20 + i * 7),
                    muted=i % 2 == 0, audio_channel=(0, 3, 4)[i % 3]) for i in range(6)]
    with tempfile.TemporaryDirectory(prefix='ddm-combinations-') as temporary, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'state.json')))
        stack.enter_context(patch('ddm.plugins.DEFAULT_PLUGINS_DIR', str(Path(temporary) / 'plugins')))
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account', 'sync_danmaku',
                       'load_avatars_for', 'load_room_avatars', 'load_cached_covers', 'load_cached_avatars',
                       '_check_startup_update', '_check_startup_plugins'):
            stack.enter_context(patch.object(MainWindow, method))
        check_layout_only_presets(app, Path(temporary))
        check_snap_grid_and_other_presets(app)
        check_full_snap_grid_swaps(app)
        check_portrait_live_defaults(app)
        window = MainWindow(deepcopy(fixture), deepcopy(fixture), layout_id='corner',
                            state={'plugins_enabled': [], 'settings': {'auto_update': False,
                                   'preview_on_hover': False, 'recording_replay_enabled': False}})
        assert window.room_preset_control.host is window
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
            default_size = picker.size()
            window._save_timer.stop()
            resize_picker(picker, picker.rect().bottomRight() - QPoint(3, 3), QPoint(70, 36))
            remembered = picker.size()
            assert remembered != default_size and window._save_timer.isActive()
            ui = window.current_state()['ui']
            assert ui['layout_picker_size'] == remembered.toTuple()
            with patch.dict(os.environ):
                os.environ.pop('DDM_NO_SAVE', None)
                config.save({'version': config.STATE_VERSION, 'ui': ui}, raise_errors=True)
            stored = config.load()
            assert stored['ui']['layout_picker_size'] == list(remembered.toTuple())
            picker.close()
            window.sidebar.open_layout_picker()
            picker = window.sidebar._picker
            assert picker.size() == remembered
            # Use the same serialized state a fresh MainWindow receives from config.load.
            restored = MainWindow([], [], layout_id='corner', state={'ui': stored['ui'], 'plugins_enabled': [],
                'settings': {'auto_update': False, 'close_behavior': 'exit'}})
            try:
                controller = restored.sidebar.presentation_control.layout_picker
                assert controller.preferred_size == QSize(*ui['layout_picker_size'])
                restored.setGeometry(window.geometry())
                restored.show()
                restored.sidebar.open_layout_picker()
                assert restored.sidebar._picker.size() == remembered
                restored.sidebar._picker.close()
            finally:
                restored.close()
            picker.show()
            picker.set_group('直播间组合')
            page = picker.presets_page
            assert page.isVisible() and not picker.edit_button.isVisible()
            with patch('ddm.room_presets_ui.QInputDialog.getText', side_effect=AssertionError('Save must stay inline')):
                QTest.mouseClick(page.save_button, Qt.LeftButton)
                app.processEvents()
                assert page.name_form.isVisible() and picker.isVisible()
                assert page.name_edit.window() is picker
                assert page.summary.contentsRect().height() >= page.summary.fontMetrics().height(), 'Section text is clipped'
                assert app.focusWindow() is picker.windowHandle() and app.focusObject() is page.name_edit
                QTest.mouseClick(page.confirm_save, Qt.LeftButton)
                assert page.name_hint.text() and not window.room_presets['items']
                app.sendEvent(app.focusObject(), QInputMethodEvent('bisai', []))
                assert not page.name_edit.text() and picker.isVisible()
                commit = QInputMethodEvent()
                commit.setCommitString('  比赛  ')
                app.sendEvent(app.focusObject(), commit)
                assert page.name_edit.text() == '  比赛  '
                QTest.keyClick(page.name_edit, Qt.Key_Return)
            assert not page.name_form.isVisible() and picker.isVisible()
            key = window.room_presets['items'][0]['id']
            assert window.room_presets['items'][0]['name'] == '比赛'
            assert page.cards[key].isChecked()
            assert page.cards[key].parentWidget().property('current') is True
            assert room_presets.same(room_presets.validate(window.room_presets['items'][0]), a)
            assert thumbnail(a).size().width() == 224
            picker.close()
            # Keep the original players while swapping room locations and applying sounds.
            players = {}
            for tile in window.wall.tiles:
                if tile.room.get('room_id'):
                    player = Mock(spec=TilePlayer)
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
            with patch('ddm.room_presets_ui.QInputDialog.getText', side_effect=AssertionError('Save must stay inline')), \
                    patch('ddm.room_presets_ui.QMessageBox.question', side_effect=AssertionError('Save confirmation must stay inline')):
                QTest.mouseClick(page.save_button, Qt.LeftButton)
                page.name_edit.setText('取消保存')
                QTest.mouseClick(page.cancel_save, Qt.LeftButton)
                assert len(window.room_presets['items']) == 2
                QTest.mouseClick(page.save_button, Qt.LeftButton)
                page.name_edit.setText('比赛')
                QTest.mouseClick(page.confirm_save, Qt.LeftButton)
                assert page.confirm_save.text() == '确认覆盖' and page.name_hint.text()
                assert room_presets.same(room_presets.validate(window.room_presets['items'][0]), a)
                page.name_edit.setText('比赛改名')
                assert page.confirm_save.text() == '保存' and not page.name_hint.text()
                QTest.mouseClick(page.cancel_save, Qt.LeftButton)
                QTest.mouseClick(page.save_button, Qt.LeftButton)
                assert not page.name_edit.text()
                page.name_edit.setText('日常观看')
                QTest.mouseClick(page.confirm_save, Qt.LeftButton)
                QTest.mouseClick(page.confirm_save, Qt.LeftButton)
                assert len(window.room_presets['items']) == 2
                assert room_presets.same(room_presets.validate(window.room_presets['items'][1]), b)
                assert room_presets.same(room_presets.validate(window.room_presets['items'][0]), a)
                assert not page.name_form.isVisible() and picker.isVisible()
            first_record = window.room_presets['items'][0]
            rename = page.cards[key].parentWidget().findChild(QPushButton, 'PresetManageButton')
            with patch('ddm.room_presets_ui.QInputDialog.getText', return_value=('比赛观察', True)):
                QTest.mouseClick(rename, Qt.LeftButton)
            assert first_record['name'] == '比赛观察'
            window.rename_room_preset(key, '比赛')
            window.wall.tiles[0].set_volume(86)
            b = window.room_preset_snapshot()
            page.save_new()
            page.name_edit.setText('日常观看')
            QTest.mouseClick(page.confirm_save, Qt.LeftButton)
            QTest.mouseClick(page.confirm_save, Qt.LeftButton)
            assert room_presets.same(room_presets.validate(window.room_presets['items'][1]), b)
            discarded = window.save_room_preset('待删除')
            page.refresh()
            app.processEvents()
            with patch('ddm.room_presets_ui.QMessageBox.question', side_effect=AssertionError('Delete must stay inline')):
                panel, card, confirm, cancel = page.delete_panels[discarded]
                assert confirm.objectName() == 'PrimaryButton' and confirm.property('deleteConfirm')
                assert cancel.objectName() == 'IconButton'
                delete = next(button for button in card.parentWidget().findChildren(QPushButton)
                              if button.accessibleName() == '删除组合 待删除')
                page.scroll.ensureWidgetVisible(delete)
                QTest.mouseClick(delete, Qt.LeftButton)
                assert panel.isVisible() and card.isHidden() and panel.window() is picker
                assert any(item['id'] == discarded for item in window.room_presets['items'])
                danger_fills = [theme.qcolor(color) for color in ('#b52b32', '#c3333c')]
                for button in (cancel, confirm):
                    button.setFocus()
                    image = confirm.grab().toImage()
                    assert image.pixelColor(image.width() // 2, round(5 * image.devicePixelRatio())) in danger_fills
                    assert image.pixelColor(0, 0) not in danger_fills
                QTest.mouseClick(cancel, Qt.LeftButton)
                assert panel.isHidden() and card.isVisible()
                assert any(item['id'] == discarded for item in window.room_presets['items'])
                QTest.mouseClick(delete, Qt.LeftButton)
                page._ask_delete(key)
                assert panel.isHidden() and page.delete_panels[key][0].isVisible()
                page.scroll.ensureWidgetVisible(delete)
                QTest.mouseClick(delete, Qt.LeftButton)
                QTest.mouseClick(confirm, Qt.LeftButton)
                assert picker.isVisible()
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
                # Reopen just as users do after changing the app theme, so raster icons regenerate.
                window.sidebar._picker.close()
                window.sidebar.open_layout_picker()
                picker = window.sidebar._picker
                picker.set_group('普通布局')
                QTest.qWait(30)
                picker.grab().save(str(directory / f'layout-picker-{mode}.png'))
                for group in picker._cards.values():
                    for card in group:
                        icon = card.icon().pixmap(card.iconSize()).toImage()
                        visible = sum(icon.pixelColor(x, y).alpha() > 200 and
                                      contrast(icon.pixelColor(x, y), theme.qcolor(theme.CONTENT)) >= 3
                                      for x in range(icon.width()) for y in range(icon.height()))
                        assert visible > icon.width() * icon.height() * .04, card.text()
                for button in (*picker._tabs.values(), picker.edit_button):
                    assert contrast(button.palette().color(QPalette.ButtonText),
                                    theme.qcolor(theme.CONTENT)) >= 4.5, button.text()
                picker.set_group('直播间组合')
                QTest.qWait(30)
                picker.grab().save(str(directory / f'room-presets-{mode}.png'))
                page = picker.presets_page
                candidate = next(iter(page.cards))
                page._ask_delete(candidate)
                picker.grab().save(str(directory / f'room-presets-delete-{mode}.png'))
                page._cancel_delete()
                management = page.findChildren(QPushButton, 'PresetManageButton')
                assert management and all(button.kind == 'rename' and not button.text()
                                          and button.toolTip() == '重命名' for button in management)
                for button in management:
                    assert contrast(button.palette().color(QPalette.ButtonText),
                                    theme.qcolor(theme.CONTENT)) >= 4.5
                for card in page.cards.values():
                    if card.isEnabled():
                        assert contrast(card.palette().color(QPalette.ButtonText),
                                        theme.qcolor(theme.CONTENT)) >= 4.5
                page.save_new()
                page.name_edit.setText('我的直播间组合')
                window.sidebar._picker.grab().save(str(directory / f'room-presets-inline-{mode}.png'))
                page._cancel_name()
            window.sidebar._picker.grab().save(str(directory / 'room-presets-preview.png'))
        finally:
            window.close()
            app.processEvents()
    print('PASS: combination Qt save/cards, validation, audio/cell/ratio/player identity, recording cancel, '
          'wall-only status, fullscreen mute, isolated disk/restart, direction and moved danmaku')


if __name__ == '__main__':
    main()
