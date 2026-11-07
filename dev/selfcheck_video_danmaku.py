"""离线画面弹幕回归：滚动、防追尾、显示参数、独立开关和共享连接。"""
import os
import math
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import threading
import time
from unittest.mock import AsyncMock, Mock, patch
from types import MethodType, SimpleNamespace

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QThread, QThreadPool, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QImage, QPaintEvent, QPixmap, QRawFont, QRegion, QWindowStateChangeEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QDialog, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config, theme
from ddm.app import MainWindow
from ddm.danmaku import DanmakuClient
from ddm.dialogs import DanmakuSettingsPage, SettingsDialog
from ddm.video_danmaku import VideoDanmaku
from ddm.widgets import DanmakuPanel, Tile, WallGrid


def check_quick_group_follows_tile_move(app):
    for layout_id, room_count in (('2x2', 2), ('3x3', 6)):
        check_quick_group_swap_layout(app, layout_id, room_count)


def check_quick_group_swap_layout(app, layout_id, room_count):
    wall = WallGrid([dict(room_id=str(i + 1), uname=str(i + 1), live=True)
                     for i in range(room_count)], layout_id=layout_id)
    wall.resize(*( (1000, 700) if layout_id == '2x2' else (1002, 702)))
    wall.show()
    app.processEvents()
    layer = Mock()
    layer.parent = wall
    geometries = {}
    layer.set_group_geometry.side_effect = lambda group, *rect: geometries.update({group: rect})
    wall._quick_danmaku_layer = layer
    first, second = wall.tiles[:2]
    occupied = wall.tiles[:room_count]
    try:
        for index, tile in enumerate(occupied):
            tile.danmaku_button.setChecked(True)
            overlay = tile.video_danmaku
            overlay._quick_layer, overlay._quick_group = layer, index
            overlay._sync_quick_geometry()
        local_rect = first.video_danmaku.geometry()
        original = dict(geometries)
        # 秒切移动整个格子，等大格子内部浮层的相对坐标不会产生 Move/Resize。
        wall.tiles[0], wall.tiles[1] = second, first
        wall.relayout(force=True)
        time.sleep(0.12)  # A stalled GUI must not submit new Quick positions ahead of native moves.
        assert geometries == original, 'GUI事件循环恢复前，不应提前提交共享弹幕的新坐标'
        app.processEvents()
        assert first.video_danmaku.geometry() == local_rect
        assert first.x() != original[0][0] - local_rect.x()
        for index, tile in enumerate(occupied):
            overlay = tile.video_danmaku
            point = overlay.mapTo(wall, QPoint())
            assert geometries[index] == (point.x(), point.y(), overlay.width(), overlay.height()), \
                '交换等大格子后，共享弹幕组必须跟随格子的墙内坐标'
        # Replacing an empty slot with an occupied tile must move all six groups too.
        wall.tiles[0], wall.tiles[-1] = wall.tiles[-1], wall.tiles[0]
        wall.relayout(force=True)
        app.processEvents()
        for index, tile in enumerate(occupied):
            overlay = tile.video_danmaku
            point = overlay.mapTo(wall, QPoint())
            assert geometries[index] == (point.x(), point.y(), overlay.width(), overlay.height())
    finally:
        for tile in occupied:
            tile.video_danmaku._quick_layer = tile.video_danmaku._quick_group = None
        wall._quick_danmaku_layer = None
        wall.close()


def check_quick_controller_mask():
    overlay = VideoDanmaku()
    overlay.resize(400, 240)
    video_mask = QRegion(0, 0, 400, 240) - QRegion(0, 0, 3, 3)
    try:
        overlay._quick_requested = True
        overlay.setMask(video_mask)
        assert overlay._quick_video_mask == video_mask
        assert overlay.mask().intersected(overlay.rect()).isEmpty()
        overlay.clearMask()
        assert overlay._quick_video_mask.isEmpty()
        assert overlay.mask().intersected(overlay.rect()).isEmpty()
        overlay._quick_requested = False
        overlay.setMask(video_mask)
        assert overlay.mask() == video_mask, 'Raster fallback must retain its native video region'
    finally:
        overlay.close()


def check_super_chat_overlay(app):
    overlay = VideoDanmaku()
    overlay.resize(800, 450)
    now = int(time.time())
    chats = [
        {"kind": "super_chat", "id": "sc-1", "super_chat_id": "sc-1",
         "uname": "老板", "message": "醒目留言", "price": 30,
         "start_time": now, "end_time": now + 120,
         "background_color": "#ffdd00", "background_price_color": "#ff8800"},
        {"kind": "super_chat", "id": "sc-2", "super_chat_id": "sc-2",
         "uname": "观众", "message": "第二条", "price": 50,
         "start_time": now + 1, "end_time": now + 120,
         "background_color": "#ff88aa", "background_price_color": "#cc3366"},
    ]
    try:
        overlay.set_enabled(True)
        overlay.set_active(True)
        overlay.set_super_chats(chats)
        overlay.show()
        app.processEvents()
        assert overlay.super_chats == chats
        assert overlay.super_chat_overlay.isVisible()
        image = overlay.super_chat_overlay.grab().toImage()
        assert not image.isNull()
        assert not image.pixelColor(image.width() - 20, 100).alpha() == 0
        overlay.set_enabled(False)
        assert not overlay.enabled
        assert overlay.super_chat_overlay.isHidden()
        assert len(overlay.super_chats) == 2, "关闭弹幕只隐藏，不能丢掉 SC 状态"
        overlay.set_enabled(True)
        assert overlay.super_chat_overlay.isVisible(), "重开弹幕要恢复当前 SC"
        overlay.set_active(False)
        assert overlay.super_chat_overlay.isHidden()
        assert len(overlay.super_chats) == 2, "停播只隐藏 SC，不能丢掉状态"
        overlay.set_active(True)
        assert overlay.super_chat_overlay.isVisible()
        overlay.resize(1600, 900)
        app.processEvents()
        sc = overlay.super_chat_overlay
        assert sc.width() <= 342 and sc.height() <= overlay.height()
        rows = sc.card_rects()
        assert len(rows) == len(chats) and rows[0].bottom() < rows[1].top()
        card = sc.card_rects()[0].toAlignedRect()
        assert overlay.rect().contains(card)
        assert sc.geometry().contains(card.translated(overlay.pos()))
        overlay.clear()
        assert not overlay.super_chats and overlay.super_chat_overlay.isHidden()
        assert overlay.add_event({"kind": "gift", "uname": "x", "text": "礼物"}) is False
    finally:
        overlay.close()


def check_move_window_mask():
    from ddm.video_danmaku_quick import _MovingDanmakuWindow

    window = _MovingDanmakuWindow()
    window.resize(800, 450)
    base = QRegion(0, 0, 800, 450) - QRegion(100, 100, 50, 50)
    try:
        window.setMask(base)
        moving = QRegion(0, 0, 200, 100) | QRegion(400, 0, 200, 100)
        window.begin_move(1, moving)
        assert not window.mask().contains(QPoint(20, 20))
        assert not window.mask().contains(QPoint(450, 20))
        assert window.mask().contains(QPoint(700, 400)), 'Unmoved tiles must remain visible'
        updated = base - QRegion(300, 200, 30, 30)
        window.setMask(updated)
        assert not window.mask().contains(QPoint(20, 20)), 'Notice mask updates must preserve move clipping'
        window.commit_move(1)
        stale = window._move_epoch
        window.begin_move(1, moving)
        window.commit_move(1)
        epoch = window._move_epoch
        window._after_move_frame(stale)
        assert window._move_frames[1] is False, 'Queued old frames cannot reveal stale coordinates'
        window._after_move_frame(epoch)
        assert not window.mask().contains(QPoint(20, 20))
        window._after_move_sync(stale)
        assert window._move_frames[1] is False
        window._after_move_sync(epoch)
        assert not window.mask().contains(QPoint(20, 20)), 'Sync alone does not present the new frame'
        window._after_move_frame(epoch)
        assert window.mask() == updated
        window.begin_move(2, moving)
        window.cancel_move(2)
        assert window.mask() == updated, 'Removing a moving group must release its clipping'
        window.setMask(QRegion())
        window.begin_move(3, QRegion(0, 0, 800, 450))
        assert not window.mask().isEmpty() and not window.mask().contains(QPoint(400, 200))
        window.commit_move(3)
        epoch = window._move_epoch
        window._after_move_sync(epoch)
        window._after_move_frame(epoch)
        assert window.mask().isEmpty(), 'An unrestricted base mask must be restored'
    finally:
        window.close()


def check_moved_overlay_refresh(app):
    wall = WallGrid([dict(room_id='1', uname='Moving text', title='Native caption', live=True)],
                    layout_id='1x1')
    wall.resize(1000, 700)
    wall.show()
    app.processEvents()
    tile = wall.tiles[0]
    tile.set_controls_visible(True)
    tile._control_hover_timer.stop()
    tile._controls_hide_timer.stop()
    app.processEvents()
    assert wall._quick_danmaku_layer is None, 'Caption refresh cannot depend on enabled Quick danmaku'
    try:
        with patch('ddm.widgets.QCursor.pos', return_value=tile.video.mapToGlobal(tile.video.rect().center())), \
                patch.object(tile.stream_badge, 'repaint', wraps=tile.stream_badge.repaint) as live, \
                patch.object(tile.title_badge, 'repaint', wraps=tile.title_badge.repaint) as title, \
                patch.object(tile.controls, 'repaint', wraps=tile.controls.repaint) as controls:
            tile.set_controls_visible(True)
            tile._control_hover_timer.stop()
            app.processEvents()
            assert tile.controls.isVisible() and tile.stream_badge.isVisible() and tile.title_badge.isVisible()
            live.reset_mock()
            title.reset_mock()
            controls.reset_mock()
            for _ in range(3):
                tile.move(tile.x() + 5, tile.y() + 5)
            assert not live.called and not title.called and not controls.called
            app.processEvents()
            assert live.call_count == title.call_count == controls.call_count == 1, \
                'Move bursts must repaint caption text and controls once at the final position'
    finally:
        wall.close()


def check_quick_occlusion(app):
    from ddm.video_danmaku_quick import QuickDanmakuLayer

    owner = QWidget()
    owner.setGeometry(100, 100, 800, 600)
    wall = QWidget(owner)
    wall.setGeometry(100, 0, 700, 600)
    owner.show()
    wall.show()
    dialog = QDialog(owner)
    dialog.setGeometry(350, 250, 200, 150)
    notice = QWidget(owner, Qt.Tool)
    notice.setGeometry(220, 110, 300, 100)
    unrelated = QWidget()
    unrelated.setGeometry(400, 400, 100, 100)
    unrelated.show()
    layer = SimpleNamespace(parent=wall, window=Mock(), _occlusion_timer=Mock(), _presentation_window=None)
    try:
        for widget in (dialog, notice):
            widget.show()
            app.processEvents()
            assert QuickDanmakuLayer._update_occlusion(layer)
            region = layer.window.setMask.call_args.args[0]
            point = wall.mapFromGlobal(widget.mapToGlobal(widget.rect().center()))
            assert not region.contains(point), 'Danmaku must not cover dialogs or notices'
            assert region.contains(QPoint(650, 550)), 'Uncovered video must retain danmaku'
            QuickDanmakuLayer.eventFilter(layer, widget, QEvent(QEvent.Move))
            layer._occlusion_timer.start.assert_called_with(0)
        dialog.hide()
        notice.hide()
        app.processEvents()
        assert QuickDanmakuLayer._update_occlusion(layer)
        assert layer.window.setMask.call_args.args[0] == wall.rect()
        dialog.setGeometry(100, 50, 1200, 900)
        dialog.show()
        app.processEvents()
        assert not QuickDanmakuLayer._update_occlusion(layer), 'Full occlusion must hide the layer'
    finally:
        dialog.close()
        notice.close()
        unrelated.close()
        owner.close()


def check_quick_surface_recovery(app):
    from ddm.video_danmaku_quick import QuickDanmakuLayer

    parent = Mock()
    parent.width.return_value, parent.height.return_value = 800, 450
    parent.mapToGlobal.return_value = QPoint(120, 80)
    parent.isVisible.return_value = True
    parent.window.return_value.isMinimized.return_value = False
    layer = SimpleNamespace(parent=parent, window=Mock(), stage=Mock(), _presentation_window=None,
                            _presentation_changing=False,
                            _surface_reset=QTimer(), _surface_dirty=False, _empty_hide=Mock(),
                            _update_occlusion=Mock(return_value=True),
                            _occlusion_timer=Mock(),
                            _set_layered=Mock(), items={1: {"group": 1}}, groups={1: Mock()})
    layer.window.isVisible.return_value = False
    layer._surface_reset.setSingleShot(True)
    for name in ('reset_surface', 'resize', 'show', '_restore_surface'):
        setattr(layer, name, MethodType(getattr(QuickDanmakuLayer, name), layer))
    layer._surface_reset.timeout.connect(layer._restore_surface)
    for kind in (QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange):
        layer.window.reset_mock()
        layer._set_layered.reset_mock()
        assert not QuickDanmakuLayer.eventFilter(layer, parent, QEvent(kind))
        assert layer._surface_reset.isActive(), 'Screen/DPI transition must rebuild transparency'
        layer.window.hide.assert_called_once()
        layer.show()
        layer.window.show.assert_not_called()
        # Repeated transition notifications must coalesce into one rebuild.
        QuickDanmakuLayer.eventFilter(layer, parent, QEvent(kind))
        QTest.qWait(160)
        layer.window.destroy.assert_called_once()
        layer._set_layered.assert_called_once()
        layer.window.show.assert_called_once()
        assert not layer._surface_dirty and not layer._surface_reset.isActive()
    for state in (Qt.WindowMaximized, Qt.WindowFullScreen):
        parent.windowState.return_value = state
        QuickDanmakuLayer.eventFilter(layer, parent, QWindowStateChangeEvent(Qt.WindowNoState))
        assert layer._surface_reset.isActive()
        QTest.qWait(160)
    layer.window.reset_mock()
    parent.isVisible.return_value = False
    layer.reset_surface()
    QTest.qWait(160)
    assert layer._surface_dirty
    layer.window.destroy.assert_not_called()
    parent.isVisible.return_value = True
    layer.show()
    layer.window.show.assert_not_called()
    QTest.qWait(160)
    layer.window.destroy.assert_called_once()
    assert not layer._surface_dirty
    layer.window.reset_mock()
    parent.window.return_value.isMinimized.return_value = True
    layer.reset_surface()
    QTest.qWait(160)
    layer.window.destroy.assert_not_called()
    parent.window.return_value.isMinimized.return_value = False
    layer.show()
    QTest.qWait(160)
    layer.window.destroy.assert_called_once()
    layer.window.reset_mock()
    assert not QuickDanmakuLayer.eventFilter(layer, parent, QEvent(QEvent.Move))
    assert not layer._surface_reset.isActive(), 'Ordinary moves must not recreate surfaces'
    layer.window.setGeometry.assert_called_with(120, 80, 800, 450)
    layer.window.reset_mock()
    layer.items.clear()
    layer.show()
    layer.window.hide.assert_called_once()
    layer.window.show.assert_not_called()
    layer.items[1] = {"group": 1, "item": Mock(), "key": "1"}
    layer.groups[1].isVisible.return_value = False
    layer.show()
    layer.window.show.assert_not_called()
    layer.groups[1].isVisible.return_value = True
    layer.show()
    layer.window.show.assert_called_once()
    layer.window.reset_mock()
    layer.items.clear()
    layer._active_groups = set()
    layer.images = Mock()
    layer.set_group_active = Mock()
    layer.items[1] = {"group": 1, "item": Mock(), "key": "1"}
    QuickDanmakuLayer.remove(layer, 1)
    layer._empty_hide.start.assert_called_once_with(0)
    assert not layer.items, 'Deleting the last tile must not leave an opaque shared window'


def wait_comment_raster(app, overlay):
    deadline = time.perf_counter() + 5
    while (overlay._comment_resize_timer.isActive() or overlay._comment_raster_job is not None):
        assert time.perf_counter() < deadline, 'Comment painting did not finish'
        app.processEvents()
        time.sleep(.002)  # Let Python image providers/render callbacks acquire the GIL.


def check_initial_background_raster(app):
    from ddm.danmaku_raster import CommentRaster
    overlay = VideoDanmaku()
    overlay.set_native_video(False)  # The plugin uses this QWidget picture surface.
    overlay.resize(900, 500)
    overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False,
                                video_danmaku_size=28, video_danmaku_outline_width=2))
    overlay.set_enabled(True)
    overlay.set_active(True)
    app.processEvents()
    original = CommentRaster._render_content
    entered, release = threading.Event(), threading.Event()
    threads = []
    def blocked(renderer, *args):
        threads.append(QThread.currentThread())
        entered.set()
        assert release.wait(5), 'Initial raster worker timed out'
        return original(renderer, *args)
    def wait_entered():
        deadline = time.perf_counter() + 3
        while not entered.is_set():
            assert time.perf_counter() < deadline
            QTest.qWait(5)
    try:
        with patch.object(CommentRaster, '_render_content', blocked), \
                patch.object(overlay, '_render_content', side_effect=AssertionError('Initial painting on GUI')), \
                patch.object(overlay, '_ensure_emoticon'), patch.object(overlay, 'lane_count', return_value=2):
            first = dict(text='first [emote] 中文 😀', emoticons={'[emote]': 'local-emote'}, self_sent=True)
            assert overlay.add_event(first)
            assert overlay.add_event(dict(text='second', color='#aaccff'))
            assert not overlay.add_event(dict(text='bounded backlog'))
            assert len(overlay._pending_comments) == 2 and not overlay.comments
            wait_entered()
            delivered = []
            QTimer.singleShot(0, lambda: delivered.append(True))
            app.processEvents()
            assert delivered and not overlay.comments, 'Blocked painting must leave GUI events available'
            overlay.apply_settings(dict(overlay.settings, video_danmaku_size=40))
            emote = QPixmap(32, 18)
            emote.fill(QColor(220, 30, 80, 150))
            overlay._on_emoticon_loaded('local-emote', emote)
            overlay.set_paused(True)
            layer = Mock(render_thread_animation=True)
            overlay._quick_layer, overlay._quick_group = layer, 37
            release.set()
            wait_comment_raster(app, overlay)
            assert [c.message for c in overlay.comments] == [first['text'], 'second']
            assert threads and all(thread != app.thread() for thread in threads)
            assert not overlay.timer.isActive()
            layer.set_group_active.assert_called_with(37, False)
            for comment in overlay.comments:
                expected = original(overlay._comment_renderer(), comment.text, comment.color,
                                    comment.runs, comment.self_sent)
                assert comment.image.toImage() == expected, 'New comments must retain exact reference pixels'
            comment = overlay.comments[0]
            comment.x = 80
            assert overlay.comment_at(QPoint(85, 5)) is comment
            assert comment.event['text'] == first['text'] and comment.self_sent
            overlay._quick_layer = overlay._quick_group = None
        # Clear, room changes and disabled overlays invalidate work already in flight.
        for action in (overlay.clear, overlay.clear_comments,
                       lambda: overlay.set_enabled(False), lambda: overlay.set_active(False)):
            overlay.clear()
            overlay.set_paused(False)
            entered.clear()
            release.clear()
            with patch.object(CommentRaster, '_render_content', blocked):
                assert overlay.add_event(dict(text='old room'))
                wait_entered()
                action()
                overlay.set_enabled(True)
                overlay.set_active(True)
                assert overlay.add_event(dict(text='new room'))
                release.set()
                wait_comment_raster(app, overlay)
                assert [c.message for c in overlay.comments] == ['new room']
                assert not overlay._pending_comments
        # A running job owns image snapshots, never the widget being destroyed.
        dead = VideoDanmaku()
        dead.setAttribute(Qt.WA_DeleteOnClose)
        dead.set_native_video(False)
        dead.resize(900, 500)
        dead.apply_settings(overlay.settings)
        dead.set_enabled(True)
        dead.set_active(True)
        app.processEvents()
        destroyed = []
        dead.destroyed.connect(lambda: destroyed.append(True))
        entered.clear()
        release.clear()
        with patch.object(CommentRaster, '_render_content', blocked):
            assert dead.add_event(dict(text='closed during painting'))
            wait_entered()
            dead.close()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            assert destroyed
            release.set()
            assert QThreadPool.globalInstance().waitForDone(3000)
            app.processEvents()
    finally:
        release.set()
        overlay._quick_layer = overlay._quick_group = None
        overlay.clear()
        wait_comment_raster(app, overlay)
        overlay.close()
    print('PASS: initial background raster, GUI delivery, bounded admission, order, exact pixels, stale settings/emotes and room invalidation')


def check_resize_rebuild_coalescing(app):
    from ddm.danmaku_raster import CommentRaster
    overlay = VideoDanmaku()
    overlay._quick_requested = False
    overlay.resize(640, 360)
    overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=True,
                                video_danmaku_size=36, video_danmaku_outline_width=2))
    try:
        overlay.set_active(True)
        overlay.set_enabled(True)
        overlay.show()
        app.processEvents()
        assert overlay.add_event({'text': '最终尺寸描边弹幕 ABC 123', 'color': '#aaccff', 'self_sent': True})
        wait_comment_raster(QApplication.instance(), overlay)
        overlay.set_paused(True)
        wait_comment_raster(app, overlay)
        comment = overlay.comments[0]
        comment.x = 200
        progress = (overlay.width()-comment.x)/(overlay.width()+comment.image.width()/comment.image.devicePixelRatioF())
        threads = []
        original = CommentRaster._render_content
        def paint(renderer, *args):
            threads.append(QThread.currentThread())
            return original(renderer, *args)
        with patch.object(CommentRaster, '_render_content', paint), \
                patch.object(overlay, '_render_content', wraps=overlay._render_content) as gui_render:
            for width, height in ((720, 420), (1200, 800), (1000, 700), (960, 540)):
                overlay.resize(width, height)
            assert gui_render.call_count == 0
            wait_comment_raster(app, overlay)
            assert gui_render.call_count == 0, 'Fullscreen resize must never rasterize on the GUI thread'
            assert len(threads) == 1 and threads[0] != app.thread()
        expected = overlay._render_content(comment.text, comment.color, comment.runs, comment.self_sent)
        assert comment.image.toImage() == expected.toImage(), 'Final pixels must retain the reference rendering'
        final_progress = (overlay.width()-comment.x)/(overlay.width()+comment.image.width()/comment.image.devicePixelRatioF())
        assert abs(final_progress-progress) < 1e-6
        # Each live comment retains at most two size variants, including the original size.
        with patch.object(CommentRaster, '_render_content', wraps=original) as cached_render:
            for size in ((640, 360), (960, 540), (980, 540)):
                overlay.resize(*size)
                wait_comment_raster(app, overlay)
            assert cached_render.call_count == 0, 'Cached sizes must reuse their raster'
        assert len(comment.rasters) == 2
        overlay.resize(1000, 600)
        with patch.object(overlay, '_render_content', wraps=overlay._render_content) as render:
            overlay.apply_settings(dict(overlay.settings, video_danmaku_size=40))
            assert render.call_count == 1
            wait_comment_raster(app, overlay)
            assert render.call_count == 1, 'Explicit settings must consume pending resize work'
        # A completed old job must not overwrite a newer size or block GUI events.
        entered, release = threading.Event(), threading.Event()
        def blocked(renderer, *args):
            entered.set()
            assert release.wait(5), 'Worker release timed out'
            return original(renderer, *args)
        with patch.object(CommentRaster, '_render_content', blocked):
            overlay.resize(1100, 650)
            app.processEvents()
            deadline = time.monotonic() + 3
            while not entered.is_set():
                assert time.monotonic() < deadline
                QTest.qWait(5)
            delivered = []
            QTimer.singleShot(0, lambda: delivered.append(True))
            overlay.resize(900, 500)
            app.processEvents()
            assert delivered and overlay._comment_raster_job is not None
            overlay.apply_settings(dict(overlay.settings, video_danmaku_size=42))
            newer = comment.image.toImage()
            release.set()
            wait_comment_raster(app, overlay)
            assert comment.image.toImage() == newer, 'Stale painting must not replace updated settings'
        # Clearing during a batch must not revive deleted comments or old textures.
        with patch.object(CommentRaster, '_render_content', blocked):
            entered.clear()
            release.clear()
            overlay.resize(1200, 700)
            app.processEvents()
            overlay.clear_comments()
            release.set()
            wait_comment_raster(app, overlay)
            assert not overlay.comments
        overlay.set_paused(False)
        overlay.resize(900, 500)
        assert overlay.add_event({'text': 'arrives before the queued resize'})
        wait_comment_raster(QApplication.instance(), overlay)
        overlay.set_paused(True)
        wait_comment_raster(app, overlay)
        assert overlay._comment_width == overlay.width()
        assert overlay.comments[0].x == overlay.width()
        overlay.clear_comments()
        overlay.set_paused(False)
        image = QImage(24, 20, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(255, 80, 40, 180))
        overlay._images['local-emote'] = image
        with patch.object(overlay, '_ensure_emoticon'):
            assert overlay.add_event({'text': 'mixed [emote] ABC', 'emoticons': {'[emote]': 'local-emote'}})
            wait_comment_raster(QApplication.instance(), overlay)
        overlay.set_paused(True)
        entered.clear()
        release.clear()
        def blocked_rich(renderer, *args):
            if QThread.currentThread() != app.thread():
                entered.set()
                assert release.wait(5)
            return original(renderer, *args)
        with patch.object(CommentRaster, '_render_content', blocked_rich):
            overlay.resize(1200, 700)
            app.processEvents()
            deadline = time.monotonic() + 3
            while not entered.is_set():
                assert time.monotonic() < deadline
                QTest.qWait(5)
            updated = QPixmap(24, 20)
            updated.fill(QColor(40, 80, 255, 160))
            before = overlay.comments[0].image.toImage()
            with patch.object(overlay, '_render_content', side_effect=AssertionError('Emoticon callbacks must not rasterize on GUI')):
                overlay._on_emoticon_loaded('local-emote', updated)
                assert overlay.comments[0].image.toImage() == before
            release.set()
            wait_comment_raster(app, overlay)
            comment = overlay.comments[0]
            expected = overlay._render_content(comment.text, comment.color, comment.runs, comment.self_sent).toImage()
            assert overlay.comments[0].image.toImage() == expected, 'Late emoticons invalidate old rich-text jobs'
    finally:
        overlay.clear()
        wait_comment_raster(app, overlay)
        overlay.close()
    print('PASS: background resize raster, exact final pixels/progress, bounded cache, stale results and GUI delivery')


def check_fonts(app):
    assets = Path(theme.ASSETS_DIR)
    source = json.loads((assets / "licenses/source-han-sans-SOURCE.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((assets / source["file"]).read_bytes()).hexdigest() == source["sha256"]
    license_text = (assets / "licenses/source-han-sans-LICENSE.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_text
    assert "Adobe" in license_text
    with patch.object(QFontDatabase, "addApplicationFont", wraps=QFontDatabase.addApplicationFont) as register:
        family = theme.danmaku_font_family()
        assert theme.danmaku_font_family() == family == "Source Han Sans SC"
        assert register.call_count == 1, "内置字体只注册一次"
    font = QFont(family)
    assert QFontInfo(font).family() == family, "必须使用真实字体，不能回退系统字体"
    raw = QRawFont.fromFont(font)
    assert all(raw.supportsCharacter(ord(char)) for char in "弹幕测试简體中文ABC123")
    assert theme.FONT_DEFAULT == "Microsoft YaHei UI", "不修改界面默认字体"

    for settings in ({}, dict(config.DEFAULT_SETTINGS)):
        page = DanmakuSettingsPage(settings)
        assert page.font_box.currentFont().family() == family
        assert page.values()["danmaku_font"] == ""
        page.close()
    panel = DanmakuPanel()
    overlay = VideoDanmaku()
    page = DanmakuSettingsPage({"danmaku_font": theme.FONT_DEFAULT})
    try:
        assert panel._font_family == family
        assert panel.body.font().family() == family
        for selection in ("", theme.FONT_DEFAULT):
            panel.apply_style(selection, 18)
            overlay.apply_settings({"danmaku_font": selection, "video_danmaku_size": 32,
                                    "video_danmaku_scale": False})
            expected = selection or family
            assert panel._font_family == expected
            assert panel.body.font().family() == expected
            assert overlay._font().family() == expected
            assert overlay._font().pixelSize() == 32
            assert not overlay._render_text("思源黑体弹幕 ABC 123", theme.qcolor(theme.TEXT1)).isNull()
        assert page.values()["danmaku_font"] == theme.FONT_DEFAULT, "保留已有自定义字体"
        page.reset()
        assert page.font_box.currentFont().family() == family
        assert page.values()["danmaku_font"] == ""
    finally:
        page.close()
        overlay.close()
        panel.close()


class Client(QThread):
    message = Signal(dict)
    status = Signal(str)

    def __init__(self, room_id, parent=None):
        super().__init__(parent)
        self.stopped = False

    def start(self):
        self.status.emit("已连接")

    def stop(self):
        self.stopped = True


class Snapshot(QThread):
    loaded = Signal(str, list)

    def __init__(self, room_id, parent=None):
        super().__init__(parent)

    def start(self):
        return None


def check_motion(app):
    tile = Tile({"room_id": "1", "live": True})
    tile.resize(900, 540)
    tile.show()
    app.processEvents()
    overlay = tile.video_danmaku
    settings = dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False,
                    video_danmaku_area=50)
    overlay.apply_settings(settings)
    tile.set_video_active(True)
    assert not overlay.isVisible() and not overlay.timer.isActive()
    tile.danmaku_button.click()
    assert overlay.isVisible() and overlay.geometry() == tile.video.geometry()
    try:
        for width in (200, 240, 300, 320, 360, 420, 900):
            tile.resize(width, 540)
            app.processEvents()
            controls = [tile.pause_button, tile.volume_button, tile.volume_slider,
                        tile.volume_label, tile.danmaku_button, tile.recording_button,
                        tile.fullscreen_button]
            visible = [widget for widget in controls if widget.isVisible()]
            assert all(widget.x() >= 0 and widget.geometry().right() < tile.bottom.width()
                       for widget in visible), (width, [(w.text() if hasattr(w, "text")
                                                        else "slider", w.geometry()) for w in visible])
            assert all(a.geometry().right() < b.geometry().left()
                       for a, b in zip(visible, visible[1:])), (width, [w.geometry() for w in visible])
            tile.set_recording_state("record")
            tile.set_recording_elapsed("12:34:56")
            app.processEvents()
            active = [widget for widget in controls[:-1] + [tile.recording_time, tile.fullscreen_button]
                      if widget.isVisible()]
            assert all(a.geometry().right() < b.geometry().left()
                       for a, b in zip(active, active[1:])), (width, [w.geometry() for w in active])
            assert active[-1].geometry().right() < tile.bottom.width()
            tile.set_recording_elapsed("")
            tile.set_recording_state("")
        tile.resize(900, 540)
        app.processEvents()
        assert overlay.font_pixels() == 28
        with patch("ddm.video_danmaku.perf_counter", return_value=100):
            assert overlay.add_event({"text": "短弹幕", "color": "#ff99cc"})
            wait_comment_raster(QApplication.instance(), overlay)
            first = overlay.comments[0]
            speed = first.speed
            for _ in range(overlay.lane_count() - 1):
                assert overlay.add_event({"text": "其他轨道"})
                wait_comment_raster(QApplication.instance(), overlay)
            with patch.object(overlay, '_render_text', side_effect=AssertionError('Full lanes must not rasterize rejected text')):
                assert not overlay.add_event({"text": "轨道满时直接丢弃"})
        with patch("ddm.video_danmaku.perf_counter", return_value=101):
            overlay._tick()
        assert abs(first.x - (overlay.width() - speed)) < 0.01, "滚动必须按实际时间推进"
        assert not overlay._lane_available(first.lane, speed * 10), "长弹幕不能追上前面的短弹幕"
        assert not overlay.add_event({"kind": "gift", "text": "礼物"})
        tile.set_paused(True)
        assert not overlay.timer.isActive()
        assert not overlay.add_event({"text": "暂停时不积压消息"})
        with patch("ddm.video_danmaku.perf_counter", return_value=101):
            tile.set_paused(False)
        assert overlay.timer.isActive()
        with patch("ddm.video_danmaku.perf_counter", return_value=110):
            overlay._tick()
        assert not overlay.comments and not overlay.timer.isActive()
        overlay.apply_settings(dict(settings, video_danmaku_speed=200))
        assert overlay.add_event({"text": "短弹幕"})
        wait_comment_raster(QApplication.instance(), overlay)
        assert abs(overlay.comments[0].speed - speed * 2) < 0.01
        overlay.apply_settings(dict(settings, video_danmaku_size=48, video_danmaku_area=25))
        assert overlay.font_pixels() == 48
        assert overlay.lane_count() * overlay.lane_height() <= overlay.height() * .25
        overlay.apply_settings(dict(settings, video_danmaku_scale=True))
        tile.resize(900, 760)
        app.processEvents()
        assert overlay.font_pixels() == 28
        tile.resize(900, 400)
        app.processEvents()
        assert overlay.font_pixels() < 28
        tile.set_fullscreen_controls_hidden(True)
        assert overlay.height() == tile.video.height() and overlay.isVisible()
        overlay.apply_settings(dict(settings, video_danmaku_area=100))
        overlay.clear()
        assert overlay.add_event({"text": "short" * 6})
        wait_comment_raster(QApplication.instance(), overlay)
        first = overlay.comments[0]
        overlay.comments = [first]
        height = overlay.lane_height()
        dirty_height = math.ceil(first.image.height()/first.image.devicePixelRatioF())
        first.x = 100.25
        overlay._last_tick = 100
        with patch('ddm.video_danmaku.perf_counter', return_value=100.004), \
                patch('ddm.video_danmaku.QPainter') as painter, \
                patch.object(overlay, '_native_layered', return_value=True), \
                patch.object(overlay, 'lane_height', wraps=overlay.lane_height) as metrics:
            dirty = QRect(0, 0, overlay.width(), height)
            overlay.paintEvent(QPaintEvent(dirty))
            point = painter.return_value.drawPixmap.call_args.args[0]
            assert isinstance(point, QPointF) and abs(point.x() - (100.25 - .004*first.speed)) < .001
            assert metrics.call_count == 1, 'Font metrics must be computed once per paint'
            painter.return_value.fillRect.assert_called_once_with(dirty, overlay.COLOR_KEY)
        first.x = 100
        overlay._last_tick = 100
        with patch('ddm.video_danmaku.perf_counter', return_value=100.016), patch.object(overlay, 'update') as update:
            overlay._tick()
            assert update.call_args.args[0] == QRect(0, 0, overlay.width(), dirty_height)
        for rate, interval in ((60, 16), (120, 8), (144, 7), (240, 4)):
            overlay.timer.stop()
            with patch.object(overlay, 'screen', return_value=Mock(refreshRate=lambda: rate)):
                overlay._start_timer()
            assert overlay.timer.interval() == interval
        # Hidden/fullscreen transitions retain progress instead of jumping ahead.
        first.x = 100
        with patch('ddm.video_danmaku.perf_counter', return_value=200):
            overlay.hide()
        with patch('ddm.video_danmaku.perf_counter', return_value=300):
            overlay.show()
        assert first.x == 100
        # Expiring the last comment still invalidates its old row, then sleeps.
        first.x = -first.image.width()/first.image.devicePixelRatioF() + 1
        overlay._last_tick = time.perf_counter() - 1
        with patch.object(overlay, 'update') as update:
            overlay._tick()
            assert update.call_args.args[0].height() == dirty_height
        assert not overlay.comments and not overlay.timer.isActive()
        assert overlay.add_event({"text": "short" * 6})
        wait_comment_raster(QApplication.instance(), overlay)
        first = overlay.comments[0]
        first.x = 100
        assert overlay.add_event({"text": "long" * 50})
        wait_comment_raster(QApplication.instance(), overlay)
        overlay.comments[-1].lane = first.lane
        overlay.comments[-1].x = 700
        tile.resize(320, 540)
        app.processEvents()
        for a, b in zip(overlay.comments, overlay.comments[1:]):
            if a.lane == b.lane:
                assert b.x - a.x - a.image.width() / a.image.devicePixelRatioF() >= overlay.GAP, "缩放后轨道间距不足"
        assert all(c.lane < overlay.lane_count() for c in overlay.comments)
        tile.resize(900, 540)
        app.processEvents()
        overlay.clear()
        assert overlay.add_event({"text": "short" * 6})
        wait_comment_raster(QApplication.instance(), overlay)
        first = overlay.comments[0]
        first.x = 100
        assert overlay.add_event({"text": "short" * 6})
        wait_comment_raster(QApplication.instance(), overlay)
        second = overlay.comments[-1]
        second.lane = first.lane
        second.x = first.x + first.image.width() / first.image.devicePixelRatioF() + overlay.GAP + 10
        overlay.apply_settings(dict(settings, video_danmaku_size=72, video_danmaku_area=25))
        assert len(overlay.comments) == 1 and overlay.comments[0] is first, "字号变大后应舍弃会重叠的后发弹幕"
        assert all(c.lane < overlay.lane_count() for c in overlay.comments)
        with patch("ddm.video_danmaku.perf_counter", return_value=time.perf_counter() + 20):
            overlay._tick()
        assert not overlay.comments and not overlay.timer.isActive(), "缩放后的弹幕也必须按时完全退出"
        tile.danmaku_button.setChecked(False)
        assert not overlay.isVisible() and not overlay.comments and not overlay.timer.isActive()
    finally:
        tile.close()


def check_routing(app):
    rooms = [{"room_id": rid, "uname": rid, "live": True}
             for rid in ("1001", "1001", "1002", "1003")]
    with patch("ddm.app.DanmakuClient", Client), patch("ddm.app.SuperChatSnapshot", Snapshot), \
            patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="2x2",
                            state={"plugins_enabled": []})
        window.resize(1200, 760)
        window.show()
        app.processEvents()
        first, duplicate, second, disabled = window.wall.tiles
        try:
            for tile in window.wall.tiles:
                tile.set_video_active(True)
            for tile in (first, duplicate, second):
                QTest.mouseClick(tile.danmaku_button, Qt.LeftButton)
            assert len(window._danmaku_clients) == 2, "同直播间的两格应共用连接"
            client = window._danmaku_clients["1001"]
            assert client.parent() is window, "主窗口继续拥有连接的 Qt 生命周期"
            with patch.object(client, "start") as restart:
                assert window._ensure_danmaku_client("1001") is client
                restart.assert_not_called()
            client.message.emit({"text": "房间一"})
            wait_comment_raster(app, first.video_danmaku)
            wait_comment_raster(app, duplicate.video_danmaku)
            assert len(first.video_danmaku.comments) == len(duplicate.video_danmaku.comments) == 1
            assert not second.video_danmaku.comments and not disabled.video_danmaku.comments
            window.settings["danmaku_block_words"] = ["广告"]
            client.message.emit({"text": "广告"})
            client.message.emit({"kind": "gift", "text": "礼物"})
            assert len(first.video_danmaku.comments) == 1
            window.wall.set_layout("dm_main2")
            window.sync_danmaku()
            assert window._danmaku is client, "弹幕格应复用画面弹幕连接"
            assert window.wall.danmaku.count.text() == "已连接"
            client.message.emit({"text": "共享消息"})
            assert "共享消息" in window.wall.danmaku.body.toPlainText()
            first.danmaku_button.setChecked(False)
            duplicate.danmaku_button.setChecked(False)
            assert window._danmaku_clients["1001"] is client, "弹幕格仍需使用此连接"
            window.wall.set_layout("2x2")
            window.sync_danmaku()
            assert client.stopped and "1001" not in window._danmaku_clients
            first.set_room({"room_id": "2001", "uname": "新直播间", "live": True})
            first.set_video_active(True)
            first.danmaku_button.setChecked(True)
            client.message.emit({"text": "旧消息"})
            assert not first.video_danmaku.comments, "换房间后忽略旧连接的消息"
            saved = window.current_state()
            _, restored = config.build_rooms(saved)
            assert [room["video_danmaku_enabled"] for room in restored] == [True, False, True, False]
            reopened = MainWindow([], restored, layout_id="2x2", state=saved)
            try:
                assert [tile.danmaku_button.isChecked() for tile in reopened.wall.tiles] == \
                    [True, False, True, False]
            finally:
                reopened.close()
            quick = Mock()
            with patch.object(window.wall, '_quick_danmaku_layer', quick):
                window.wall.set_fullscreen_tile(first)
                quick.reset_surface.assert_called_once()
                window.wall.set_fullscreen_tile(first)
                quick.reset_surface.assert_called_once()
                window.wall.set_fullscreen_tile(None)
                assert quick.reset_surface.call_count == 2, 'Native fullscreen must restore transparency both ways'
            window._on_fullscreen(first)
            assert first.video_danmaku.isVisible()
            assert "1002" not in window._danmaku_clients, "全屏时停止隐藏格子的订阅"
            window._exit_fullscreen()
            app.processEvents()
            window.sync_danmaku()
            assert "1002" in window._danmaku_clients
            second.room["live"] = False
            second.set_video_active(False)  # 实际下播也会停止播放器，不能保留“正在播放”状态。
            window.sync_danmaku()
            assert "1002" not in window._danmaku_clients
            clients = list(window._danmaku_clients.values())
            window.close()
            assert not window._danmaku_clients and all(client.stopped for client in clients)
        finally:
            window.close()


def check_settings(app):
    values = dict(config.DEFAULT_SETTINGS, video_danmaku_size=40, video_danmaku_speed=150,
                  video_danmaku_opacity=35, video_danmaku_area=25, video_danmaku_scale=False)
    dialog = SettingsDialog(values, {})
    dialog.nav.setCurrentRow(2)
    dialog.show()
    app.processEvents()
    page = dialog.danmaku_page
    try:
        curve_keys = {'video_danmaku_scale', 'video_danmaku_scale_curve'}
        watch = {key: value for key, value in values.items()
                 if key.startswith("video_danmaku_") and key not in curve_keys}
        assert not watch.keys() & page.values().keys()
        assert page.values()['video_danmaku_scale'] is False
        points = [[0, .4], [1, 1], [2, 1.5]]
        page.video_danmaku_scale_curve.set_curve(points)
        assert page.values()['video_danmaku_scale_curve'] == points
        labels = [label.text() for label in page.findChildren(QLabel)]
        assert "弹幕格字号" in labels and "屏蔽词（每行一个）" in labels
        assert not {"大小", "滚动速度", "不透明度", "顶部显示区域"}.intersection(labels)
        assert {box.text() for box in page.findChildren(QCheckBox)} == {
            '显示醒目留言（SC）', 'SC 随画面缩放', '同步画面与弹幕栏的 SC 位置', '弹幕随画面缩放'}, \
            'Global danmaku settings expose SC and scaling curves without unrelated rolling-text controls'
        page.super_chat_enabled.setChecked(False)
        page.super_chat_opacity.setValue(35)
        page.super_chat_collapse_delay.setValue(12)
        page.super_chat_scale.setValue(145)
        page.super_chat_scale_with_video.setChecked(True)
        assert page.values()['super_chat_enabled'] is False
        assert page.values()['super_chat_opacity'] == 35
        assert page.values()['super_chat_collapse_delay'] == 12
        assert page.values()['super_chat_scale'] == 145
        assert page.values()['super_chat_scale_with_video'] is True
        page.reset()
        assert page.values()['super_chat_collapse_delay'] == 7
        assert page.values()['super_chat_scale'] == 100
        assert page.values()['super_chat_scale_with_video'] is False
        assert page.values()['video_danmaku_scale'] is True
        from ddm.viewport_scale import scale_curve_points
        assert page.values()['video_danmaku_scale_curve'] == scale_curve_points()
        page.scroll.ensureWidgetVisible(page.block_edit)
        app.processEvents()
        assert page.block_edit.isVisible()
        saved = {**values, **dialog.settings()}
        assert all(saved[key] == value for key, value in watch.items())
        page.reset()
        assert page.values()["danmaku_font_size"] == config.DEFAULT_SETTINGS["danmaku_font_size"]
        assert page.values()["danmaku_max_blocks"] == config.DEFAULT_SETTINGS["danmaku_max_blocks"]
        saved.update(dialog.settings())
        assert all(saved[key] == value for key, value in watch.items()), "恢复本页默认不能覆盖格子观看参数"
    finally:
        dialog.close()


def check_cancel(app):
    with patch("ddm.danmaku.bili.danmaku_conf") as lookup:
        client = DanmakuClient("123")
        client.stop()
        client.start()
        assert client.wait(1000)
        lookup.assert_not_called()
    started, release = threading.Event(), threading.Event()

    def lookup(room_id, **kwargs):
        started.set()
        assert release.wait(3)
        return 123, "token", [{"host": "example.invalid", "wss_port": 443}]

    with patch("ddm.danmaku.bili.danmaku_conf", lookup), \
            patch("ddm.danmaku._Client._init_uid", new_callable=AsyncMock), \
            patch("ddm.danmaku._Client._init_buvid", new_callable=AsyncMock), \
            patch("aiohttp.ClientSession.ws_connect") as connect, \
            patch("ddm.app.SuperChatSnapshot", Snapshot), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow([], [], layout_id="1x1", state={"plugins_enabled": []})
        try:
            client = window._ensure_danmaku_client("123")
            assert started.wait(1)
            before = time.monotonic()
            window._stop_danmaku_client("123")
            assert time.monotonic() - before < .2, "关闭开关不能等待网络请求而卡住界面"
            assert client in window._danmaku_retired
            release.set()
            assert client.wait(1000)
            app.processEvents()
            assert not window._danmaku_retired
            connect.assert_not_called()
        finally:
            release.set()
            window.close()


def check_quick_owner_destruction(app):
    from ddm.video_danmaku_quick import QuickDanmakuLayer
    from shiboken6 import isValid

    owner = QWidget()
    owner.winId()
    with patch.object(QuickDanmakuLayer, '_set_layered'):
        layer = QuickDanmakuLayer(owner)
    owner.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(owner)
    assert not QuickDanmakuLayer.eventFilter(layer, owner, QEvent(QEvent.Show)), \
        'Queued UI events must not dereference a destroyed playback wall'


def check_qt_picture_surface(app):
    # run.cmd requests Quick for native mpv tiles. Plugin Qt pictures have no
    # shared Quick wall and must restore their own raster canvas instead.
    with patch.dict(os.environ, DDM_QTQUICK_DANMAKU='1'), \
            patch.object(VideoDanmaku, '_native_layered', lambda self: self.native_video):
        for clipped in (False, True):
            parent = QWidget()
            parent.resize(640, 360)
            overlay = VideoDanmaku(parent)
            overlay.setGeometry(parent.rect())
            try:
                assert overlay._quick_requested
                region = QRegion(QRect(0, 0, 640, 340)) if clipped else QRegion()
                overlay.setMask(region)
                layer = Mock() if clipped else None
                if layer is not None:
                    overlay._quick_layer, overlay._quick_group = layer, 17
                overlay.set_native_video(False)
                if layer is not None:
                    layer.remove_group.assert_called_once_with(17)
                    assert overlay._quick_layer is None and overlay._quick_group is None
                assert not overlay._quick_requested, 'Qt plugin pictures must not wait for a shared Quick canvas'
                assert overlay.mask() == region, 'Restore the real video mask, not the hidden controller pixel'
                overlay.apply_settings({'video_danmaku_size': 24, 'video_danmaku_area': 100,
                                        'video_danmaku_scale': False, 'video_danmaku_opacity': 100})
                parent.show()
                overlay.set_active(True)
                overlay.set_enabled(True)
                app.processEvents()
                before = overlay.grab().toImage()
                assert overlay.add_event({'text': 'Qt picture comment', 'uname': 'fixture'})
                wait_comment_raster(QApplication.instance(), overlay)
                overlay.set_paused(True)
                overlay.comments[0].x = 80
                overlay.repaint()
                app.processEvents()
                after = overlay.grab().toImage()
                assert before != after, 'Received comments must actually paint over the Qt picture'
            finally:
                overlay.clear()
                parent.close()
    print('PASS: Quick-enabled launcher restores visible scrolling comments on Qt plugin pictures')


def main():
    main_window_only = '--main-window-only' in sys.argv
    if not main_window_only:
        # Keep main-window/QThread fixtures separate from prior raster/Quick fixtures.
        subprocess.run([sys.executable, str(Path(__file__).parent / 'checks/bootstrap.py'),
                        str(Path(__file__).resolve()), '--main-window-only'], check=True, timeout=90)
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    if main_window_only:
        check_routing(app)
        check_settings(app)
        check_cancel(app)
        print('PASS: isolated main-window routing, settings and connection cancellation')
        return
    check_quick_surface_recovery(app)
    check_fonts(app)
    check_initial_background_raster(app)
    check_resize_rebuild_coalescing(app)
    check_qt_picture_surface(app)
    check_quick_occlusion(app)
    check_quick_controller_mask()
    check_super_chat_overlay(app)
    check_move_window_mask()
    check_moved_overlay_refresh(app)
    check_quick_group_follows_tile_move(app)
    check_motion(app)
    check_quick_owner_destruction(app)
    print("画面弹幕滚动、防追尾、设置、底栏、连接共享、换台、全屏及退出：通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
