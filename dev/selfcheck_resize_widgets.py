"""No-network checks for resize throttling, final decoration and native identity."""
from contextlib import ExitStack
from itertools import pairwise
from time import monotonic
from unittest.mock import patch

from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QWidget
from selfcheck_corner_resize import QApplication, QEvent, QTest, WallGrid, theme

from ddm import widgets


def check_throttle(app, wall, layout_id):
    wall.set_layout(layout_id)
    wall.resize(2500, 1000)
    app.processEvents()
    QTest.qWait(50)
    method = '_relayout_corner' if layout_id == 'corner' else '_relayout_preset'
    original = getattr(wall, method)
    passes = []

    def record(*args, **kwargs):
        passes.append((monotonic(), wall.size()))
        return original(*args, **kwargs)

    topology = list(wall.tiles)
    identities = [(int(tile.video.winId()), int(tile.controls.winId())) for tile in topology]
    with patch.object(wall, method, side_effect=record), \
            patch.object(wall, '_clear', wraps=wall._clear) as clear, \
            patch.object(wall, 'ensure_slots', wraps=wall.ensure_slots) as ensure:
        wall.set_interactive_resize(True)
        # Requests arrive faster than the timer for several timer intervals.
        for step in range(40):
            wall.resize(2501 + step, 1001 + step)
            QTest.qWait(5)
        assert 2 <= len(passes) < 40, len(passes)
        assert all((b[0] - a[0]) >= .020 for a, b in pairwise(passes)), passes
        wall.resize(2601, 1101)
        assert wall._resize_pending and wall._resize_timer.isActive()
        before = len(passes)
        wall.finish_resize()
        assert len(passes) == before + 1 and passes[-1][1] == wall.size()
        assert not wall._interactive_resize and not wall._resize_timer.isActive()
        final = [tile.geometry() for tile in wall.tiles]
        original()
        assert [tile.geometry() for tile in wall.tiles] == final
        wall.finish_resize()
        QTest.qWait(60)
        # Windows can deliver a corrected native size after resize() returns.
        assert all(a[1] != b[1] for a, b in pairwise(passes[before:])), passes
        assert not wall._resize_pending and not wall._resize_timer.isActive()
        assert not clear.called and not ensure.called
        # Immediate programmatic resizing is retained.
        before = len(passes)
        wall.resize(2650, 1150)
        assert len(passes) == before + 1
        original()
        assert [tile.geometry() for tile in wall.tiles] != final
    assert list(wall.tiles) == topology
    assert [(int(tile.video.winId()), int(tile.controls.winId())) for tile in wall.tiles] == identities


def check_masks(app, wall):
    tile = wall.tiles[0]
    with patch.object(tile.video_danmaku, 'set_quick_rounded') as rounded:
        for fullscreen in (True, False):
            tile.setProperty('fullscreen', fullscreen)
            tile._round_video()
            rounded.assert_called_with(not fullscreen)
    tile._layout_areas()
    app.processEvents()
    with patch.object(tile.video, 'setMask', wraps=tile.video.setMask) as video_mask, \
            patch.object(tile.controls, 'setMask', wraps=tile.controls.setMask) as controls_mask, \
            patch.object(tile, '_apply_native_controls_mask',
                         wraps=tile._apply_native_controls_mask) as native_mask:
        tile._layout_areas()
        tile._layout_areas()
        assert not video_mask.called and not controls_mask.called and not native_mask.called
        tile.video.clearMask()
        tile._round_video()
        assert video_mask.call_count == 1 and not tile.video.mask().isEmpty()
        video_mask.reset_mock()
        tile.resize(tile.width() + 10, tile.height() + 10)
        assert video_mask.call_count == 1
        assert not controls_mask.called and not native_mask.called
        # Local hit rectangles, rather than the controls' wall position, are cached.
        tile.controls.move(30, 20)
        tile._update_controls_mask()
        assert not controls_mask.called and not native_mask.called
        tile.quality_button.setText('A much longer quality label')
        tile._layout_controls()
        assert controls_mask.called
        assert tile.controls.mask().contains(tile.close_button.geometry().center())
        assert tile.controls.x() == max(10, tile.video.width() + 1 - tile.controls.width() - 10)
        video_mask.reset_mock()
        controls_mask.reset_mock()
        QApplication.sendEvent(tile.video, QEvent(QEvent.Type.WinIdChange))
        QApplication.sendEvent(tile.controls, QEvent(QEvent.Type.WinIdChange))
        QTest.qWait(10)
        assert video_mask.called and controls_mask.called
        video_mask.reset_mock()
        controls_mask.reset_mock()
        QApplication.sendEvent(tile, QEvent(QEvent.Type.DevicePixelRatioChange))
        QTest.qWait(10)
        assert video_mask.called and controls_mask.called
        video_mask.reset_mock()
        QApplication.sendEvent(tile.video, QEvent(QEvent.Type.WinIdChange))
        assert tile._mask_refresh_timer.isActive()
        tile.hide()
        assert not tile._mask_refresh_timer.isActive()
        QTest.qWait(10)
        assert not video_mask.called
        tile.show()
        app.processEvents()
    wall._relayout_corner()


def check_decoration_pass(wall):
    tile = wall.tiles[0]
    overlays = (tile.video_danmaku, *tile.video_corners, tile.controls,
                tile.stream_badge, tile.title_badge, tile.time_badge,
                tile.spinner, tile.pause_overlay, tile.bottom)
    for available in (True, False):
        tile.set_recording_available(available)
        with ExitStack() as stack:
            bottom = stack.enter_context(patch.object(
                tile, '_layout_bottom_controls', wraps=tile._layout_bottom_controls))
            raises = [stack.enter_context(patch.object(widget, 'raise_', wraps=widget.raise_))
                      for widget in overlays]
            tile._layout_areas()
            assert bottom.call_count == 1
            assert all(raise_.call_count == 1 for raise_ in raises)
    tile.set_recording_available(True)


def check_covers(app, wall):
    tile, playing = wall.tiles[:2]
    source = QPixmap(320, 180)
    source.fill(theme.qcolor(theme.BG))
    tile.set_cover(source)
    playing.set_cover(source)
    playing.set_video_active(True)
    app.processEvents()
    QTest.qWait(20)
    with patch.object(widgets, 'rounded_pixmap', wraps=widgets.rounded_pixmap) as render:
        wall.set_interactive_resize(True)
        for step in range(12):
            wall.resize(2700 + step, 1200 + step)
            QTest.qWait(6)
        assert not render.called
        assert tile.cover.hasScaledContents()
        replacement = QPixmap(321, 181)
        replacement.fill(theme.qcolor(theme.ACCENT))
        tile.set_cover(replacement)
        tile.set_status('resize status')
        assert not render.called
        wall.finish_resize()
        assert render.call_count == 1
        assert render.call_args.args[1] == tile.video.size()
        assert not tile.cover.hasScaledContents()
        wall.finish_resize()
        tile._layout_areas()
        assert render.call_count == 1
        playing.set_video_active(False)
        assert render.call_count == 2
        playing.set_video_active(True)
        playing.set_cover(replacement)
        playing.set_status('hidden status')
        assert render.call_count == 2
        playing.set_video_active(False)
        assert render.call_count == 3
        assert render.call_args.args[0].cacheKey() == replacement.cacheKey()
        playing.set_video_active(True)
        playing.set_cover(None)
        playing.set_status('hidden fallback')
        playing.set_video_active(False)
        assert playing.cover.text() == 'hidden fallback'
        playing.hide()
        playing.set_room({'room_id': '2000', 'uname': 'Replacement'}, replacement)
        playing.show()
        assert playing.cover.pixmap().size() == playing.video.size()
        tile.set_cover(None)
        tile.set_status('updated fallback')
        assert tile.cover.text() == 'updated fallback'
        # Returning to the original size clears scaled display without a render.
        tile.set_cover(source)
        render.reset_mock()
        size = tile.size()
        tile.set_interactive_resize(True)
        tile.resize(size.width() + 10, size.height() + 10)
        tile.resize(size)
        tile.set_interactive_resize(False)
        assert not tile.cover.hasScaledContents() and not render.called


def check_cancellation(app, wall):
    wall.set_layout('corner')
    app.processEvents()
    with ExitStack() as stack:
        preset = stack.enter_context(patch.object(wall, '_relayout_preset', wraps=wall._relayout_preset))
        corner = stack.enter_context(patch.object(wall, '_relayout_corner', wraps=wall._relayout_corner))
        for action in ('cancel', 'layout', 'fullscreen', 'sidebar', 'hide', 'close'):
            wall.set_interactive_resize(True)
            wall.resize(wall.width() + 11, wall.height() + 11)
            assert wall._resize_timer.isActive()
            if action == 'cancel':
                wall.set_interactive_resize(False)
            elif action == 'layout':
                wall.set_layout('3x3')
            elif action == 'fullscreen':
                wall.set_fullscreen_tile(wall.tiles[0])
            elif action == 'sidebar':
                wall.set_sidebar_animating(True)
            elif action == 'hide':
                wall.hide()
            else:
                wall.close()
            before = preset.call_count, corner.call_count
            assert not wall._resize_timer.isActive() and not wall._resize_pending
            QTest.qWait(60)
            assert (preset.call_count, corner.call_count) == before, action
            if action == 'fullscreen':
                wall.set_fullscreen_tile(None, stagger=True, first=wall.tiles[0])
                assert all(tile.isHidden() for tile in wall._pending_reveal)
                wall.reveal_tiles_staggered()
                QTest.qWait(30)
            elif action == 'sidebar':
                wall.set_sidebar_animating(False)
            elif action == 'hide':
                wall.show()
            app.processEvents()


def check_reshow(app, wall):
    # Resize settling and the existing Quick layer must both survive reshow.
    with patch.object(wall, '_quick_danmaku_layer') as layer:
        wall.hide()
        wall.show()
        app.processEvents()
        layer.show.assert_called_once_with()
    for identifier in ('3x3', 'corner'):
        wall.set_layout(identifier)
        app.processEvents()
        method = '_relayout_corner' if identifier == 'corner' else '_relayout_preset'
        original = getattr(wall, method)
        for cancel_before_hide in (False, True):
            before = [tile.geometry() for tile in wall.tiles]
            with patch.object(wall, method, wraps=original) as geometry:
                wall.set_interactive_resize(True)
                wall.resize(wall.width() + 50, wall.height() + 30)
                assert wall._resize_pending
                if cancel_before_hide:
                    wall.set_interactive_resize(False)
                wall.hide()
                QTest.qWait(60)
                assert wall._resize_on_show and not geometry.called
                assert [tile.geometry() for tile in wall.tiles] == before
                wall.show()
                app.processEvents()
                assert geometry.call_count == 1 and not wall._resize_on_show
                restored = [tile.geometry() for tile in wall.tiles]
                original()
                assert [tile.geometry() for tile in wall.tiles] == restored != before
        wall.set_interactive_resize(True)
        wall.resize(wall.width() + 40, wall.height() + 20)
        wall.set_interactive_resize(False)
        wall.hide()
        assert wall._resize_on_show
        wall.set_fullscreen_tile(wall.tiles[0])
        assert not wall._resize_on_show
        wall.show()
        wall.set_fullscreen_tile(None)
        wall.set_interactive_resize(True)
        wall.resize(wall.width() + 40, wall.height() + 20)
        wall.set_interactive_resize(False)
        wall.hide()
        assert wall._resize_on_show
        wall.set_layout('corner' if identifier == '3x3' else '3x3')
        assert not wall._resize_on_show
        wall.show()
        app.processEvents()


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    host = QWidget()
    host.setGeometry(-9000, -9000, 3000, 1800)
    wall = WallGrid([{'room_id': str(index + 1000), 'uname': f'Fixture {index}'}
                     for index in range(9)], layout_id='3x3', parent=host)
    wall.setGeometry(0, 0, 2500, 1000)
    host.show()
    wall.show()
    app.processEvents()
    try:
        for identifier in ('3x3', 'corner'):
            check_throttle(app, wall, identifier)
        tile = wall.tiles[0]
        border = wall._pane_borders[tile]
        border.set_highlights([border._edge_rect(edge) for edge in border.targets])
        tile.raise_overlays()
        app.processEvents()
        point = QPoint(tile.width() - 2, tile.bottom.geometry().center().y())
        assert tile.childAt(point) is border, '底栏不能盖住拖动边缘'
        for scale in (1, 1.5, 2):
            image = QImage(round(border.width() * scale), round(border.height() * scale),
                           QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(scale)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            border._render_badge(painter)
            painter.end()
            corner = [image.pixelColor(x, y).alpha()
                      for x in range(image.width() - round(14 * scale), image.width())
                      for y in range(round(14 * scale))]
            assert any(1 < alpha < 255 for alpha in corner), '圆角应包含抗锯齿透明像素'
        if QApplication.platformName() == 'windows':
            border.repaint()
            assert border._alpha_uploaded, '原生指示条应上传逐像素透明图像'
        check_masks(app, wall)
        check_decoration_pass(wall)
        check_covers(app, wall)
        check_reshow(app, wall)
        check_cancellation(app, wall)
        print('PASS: sustained latest-size throttle, final flush, masks, covers, IDs and cancellation')
    finally:
        wall.close()
        host.close()


if __name__ == '__main__':
    main()
