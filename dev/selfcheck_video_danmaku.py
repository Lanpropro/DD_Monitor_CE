"""离线画面弹幕回归：滚动、防追尾、显示参数、独立开关和共享连接。"""
import os
import math
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import AsyncMock, Mock, patch
from types import MethodType, SimpleNamespace

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QPaintEvent, QRawFont, QRegion, QWindowStateChangeEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel

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
        with patch.object(tile.stream_badge, 'repaint', wraps=tile.stream_badge.repaint) as live, \
                patch.object(tile.title_badge, 'repaint', wraps=tile.title_badge.repaint) as title, \
                patch.object(tile.controls, 'repaint', wraps=tile.controls.repaint) as controls:
            for _ in range(3):
                tile.move(tile.x() + 5, tile.y() + 5)
            assert not live.called and not title.called and not controls.called
            app.processEvents()
            assert live.call_count == title.call_count == controls.call_count == 1, \
                'Move bursts must repaint caption text and controls once at the final position'
    finally:
        wall.close()


def check_quick_surface_recovery(app):
    from ddm.video_danmaku_quick import QuickDanmakuLayer

    parent = Mock()
    parent.width.return_value, parent.height.return_value = 800, 450
    parent.mapToGlobal.return_value = QPoint(120, 80)
    parent.isVisible.return_value = True
    parent.window.return_value.isMinimized.return_value = False
    layer = SimpleNamespace(parent=parent, window=Mock(), stage=Mock(),
                            _surface_reset=QTimer(), _surface_dirty=False, _empty_hide=Mock(),
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
            first = overlay.comments[0]
            speed = first.speed
            for _ in range(overlay.lane_count() - 1):
                assert overlay.add_event({"text": "其他轨道"})
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
        first = overlay.comments[0]
        first.x = 100
        assert overlay.add_event({"text": "long" * 50})
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
        first = overlay.comments[0]
        first.x = 100
        assert overlay.add_event({"text": "short" * 6})
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
    with patch("ddm.app.DanmakuClient", Client), patch.object(MainWindow, "start_tile"), \
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
            client.message.emit({"text": "房间一"})
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
            window._clear_fullscreen_cover()
            assert first.video_danmaku.isVisible()
            assert "1002" not in window._danmaku_clients, "全屏时停止隐藏格子的订阅"
            window._exit_fullscreen()
            window._clear_fullscreen_cover()
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
        watch = {key: value for key, value in values.items() if key.startswith("video_danmaku_")}
        assert not watch.keys() & page.values().keys()
        labels = [label.text() for label in page.findChildren(QLabel)]
        assert "弹幕格字号" in labels and "屏蔽词（每行一个）" in labels
        assert not {"大小", "滚动速度", "不透明度", "顶部显示区域"}.intersection(labels)
        assert not page.findChildren(QCheckBox), "总设置不再显示画面弹幕随屏幕缩放选项"
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


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    check_quick_surface_recovery(app)
    check_fonts(app)
    check_move_window_mask()
    check_moved_overlay_refresh(app)
    check_quick_group_follows_tile_move(app)
    check_motion(app)
    check_routing(app)
    check_settings(app)
    check_cancel(app)
    print("画面弹幕滚动、防追尾、设置、底栏、连接共享、换台、全屏及退出：通过")


if __name__ == "__main__":
    main()
