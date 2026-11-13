"""隔离复现：紧凑列表滚轮换人、迟到取流、漏发Leave和悬停重绘。"""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'windows' if '--native' in sys.argv else 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, QPoint, QPointF, Signal, Qt, qVersion
from PySide6.QtGui import QCursor, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget
from ddm import theme
from ddm.preview import HoverPreview
from ddm.widgets import Sidebar


class Resolver(QObject):
    resolved = Signal(str, str, int, str, list)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, room_id, *_args, **_kwargs):
        parent = _args[1] if len(_args) > 1 else None
        super().__init__(parent)
        self.room_id = room_id
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


class Player:
    def __init__(self, *_args, **_kwargs):
        self.stateChanged = Mock()
        self.play = Mock()
        self.stop = Mock()
        self.release = Mock()
        self.set_muted = Mock()
        self.set_volume = Mock()

    def bind(self):
        pass


def settle(app, seconds=.03):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(.001)


def check_drag_preview(app):
    for card_mode in (False, True):
        host = QWidget()
        host.setGeometry(-20000, -20000, 1100, 760)
        rooms = [dict(room_id=str(i), uname='Fixture', live=True) for i in (1, 2)]
        sidebar = Sidebar(rooms, host, card_mode=card_mode, auto_compact=False)
        sidebar.setGeometry(0, 0, sidebar.width(), 700)
        preview = HoverPreview(sidebar, host)
        players = []
        def create_player(*args, **kwargs):
            player = Player()
            players.append(player)
            return player
        pointer, buttons = [QPoint()], [Qt.NoButton]
        with patch('ddm.preview.StreamResolver', wraps=Resolver) as resolve, \
                patch('ddm.preview.TilePlayer', side_effect=create_player), \
                patch('ddm.sidebar_thumbnail.TilePlayer', side_effect=create_player), \
                patch.object(QCursor, 'pos', side_effect=lambda: pointer[0]), \
                patch.object(QApplication, 'mouseButtons', side_effect=lambda: buttons[0]):
            host.show()
            app.processEvents()
            try:
                pointer[0] = sidebar.items()[0].mapToGlobal(QPoint(20, 20))
                preview.on_hover(rooms[0])
                preview._begin_resolve()
                pending = preview._resolver
                assert pending is not None
                preview._ready_to_show = True
                buttons[0] = Qt.LeftButton
                pending.resolved.emit('1', 'fixture.flv', 80, 'web', [])
                assert not any(player.play.called for player in players), \
                    'A queued response started playback while dragging'
                assert pending.cancelled, 'Drag must invalidate the outstanding preview request'
                count = resolve.call_count
                player_count = len(players)
                pointer[0] = sidebar.items()[1].mapToGlobal(QPoint(20, 20))
                preview.on_hover(rooms[1])
                preview._begin_resolve()
                preview._show_now()
                preview._check_hover()
                assert resolve.call_count == count and len(players) == player_count
                assert not any(player.stop.called for player in players), \
                    'Drag must defer native player teardown until release'
                buttons[0] = Qt.NoButton
                preview._check_hover()
                preview._begin_resolve()
                current = preview._resolver
                assert current is not None and current.room_id == '2', \
                    'Release must resume preview for the current pointer target'
                preview._show_now()
                current.resolved.emit('2', 'fixture.flv', 80, 'web', [])
                assert sum(player.play.call_count for player in players) == 1
                buttons[0] = Qt.LeftButton
                preview._check_hover()
                preview.cancel()  # Closing/disabling previews must cancel automatic resume.
                buttons[0] = Qt.NoButton
                preview._check_hover()
                assert not preview._hover_watch.isActive()
            finally:
                preview.stop()
                host.close()
    print('PASS: drag suppresses queued/new previews, defers teardown and resumes at current pointer')


def check_inline_scroll(app, native=False):
    import contextlib
    import ctypes
    from ctypes import wintypes
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory(prefix='ddm-preview-scroll-') as directory, contextlib.ExitStack() as stack:
        source = str(Path(directory) / 'preview.mp4')
        if native:
            subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                            '-i', 'testsrc2=s=320x180:r=30', '-t', '15', '-c:v', 'libx264',
                            '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', source], check=True, timeout=30)
        else:
            stack.enter_context(patch('ddm.sidebar_thumbnail.TilePlayer', Player))
        stack.enter_context(patch('ddm.preview.StreamResolver', Resolver))
        pointer = [QPoint(-30000, -30000)]
        stack.enter_context(patch.object(QCursor, 'pos', side_effect=lambda: pointer[0]))
        host = QWidget()
        host.setGeometry(-18000, 0, 1100, 800)
        rooms = [dict(room_id=str(i), uname='Fixture', live=True) for i in range(12)]
        sidebar = Sidebar(rooms, host, card_mode=True, auto_compact=False)
        sidebar.setGeometry(0, 0, sidebar.width(), 700)
        preview = HoverPreview(sidebar, host)
        host.show()
        settle(app)
        try:
            item = sidebar.items()[3]
            pointer[0] = item.mapToGlobal(QPoint(30, item.height() // 2))
            home_pointer = QPoint(pointer[0])
            preview.on_hover(item.room)
            preview._begin_resolve()
            preview._show_now()
            preview._resolve_delay.stop()
            preview._delay.stop()
            preview._resolver.resolved.emit(item.room['room_id'], source, 80, 'web', [])
            video, player = item.thumb.video, item.thumb._player
            generation = preview._generation
            home_mask = video.mask()
            if native:
                end = time.monotonic() + 12
                while time.monotonic() < end and not player._prop('vo-configured', False):
                    settle(app, .05)
                assert player._prop('vo-configured', False), 'Local preview never opened video output'
                core, hwnd = player.player, int(video.winId())
                position = player._prop('time-pos', 0)
                get_rect = ctypes.windll.user32.GetWindowRect
                get_rect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            bar = sidebar.scroll.verticalScrollBar()
            for value in [40, 0] * 12:
                bar.setValue(value)
                settle(app, .01)
                assert video.isVisible() and preview._generation == generation, 'Small scroll restarted preview'
                if native:
                    expected = item.thumb.mapToGlobal(video.pos())
                    assert video.mapToGlobal(QPoint()) == expected, 'Native preview stayed at the old card position'
                    area = wintypes.RECT()
                    assert get_rect(hwnd, ctypes.byref(area))
                    dpr = video.devicePixelRatioF()
                    assert abs(area.left - expected.x() * dpr) <= 1
                    assert abs(area.top - expected.y() * dpr) <= 1, 'HWND diverged from its card'
                    assert player.player is core and int(video.winId()) == hwnd
                    assert not item.thumb.testAttribute(Qt.WA_NativeWindow), 'Preview promoted the card to native'
            if native:
                settle(app, .15)
                assert player._prop('time-pos', 0) > position, 'Scrolling interrupted local playback'
            # Keep hovering the exposed half at the top of the viewport.
            half_scroll = item.thumb.mapTo(sidebar.list_box, QPoint()).y() + video.height() // 2
            pointer[0] = sidebar.scroll.viewport().mapToGlobal(QPoint(40, video.height() // 4))
            bar.setValue(half_scroll)
            settle(app, .02)
            assert video.isVisible(), 'Partially visible hovered preview was cancelled'
            expected_clip = video.rect().intersected(
                sidebar.scroll.viewport().rect().translated(
                    item.thumb.mapFromGlobal(sidebar.scroll.viewport().mapToGlobal(QPoint()))))
            assert video.mask().boundingRect() == expected_clip, 'Preview was not clipped to the scroll viewport'
            if native:
                gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
                gdi32.CreateRectRgn.restype = wintypes.HANDLE
                gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
                user32.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE]
                gdi32.PtInRegion.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_int]
                region = gdi32.CreateRectRgn(0, 0, 0, 0)
                try:
                    assert user32.GetWindowRgn(hwnd, region) > 0
                    assert not gdi32.PtInRegion(region, 20, 2), 'HWND still draws above the viewport'
                    assert gdi32.PtInRegion(region, 20, int((video.height()-2)*video.devicePixelRatioF()))
                finally:
                    gdi32.DeleteObject(region)
                outputs = []
                callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
                user32.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
                user32.MapWindowPoints.argtypes = [wintypes.HWND, wintypes.HWND,
                                                  ctypes.POINTER(wintypes.POINT), wintypes.UINT]
                def collect_output(child, _unused):
                    name = ctypes.create_unicode_buffer(128)
                    user32.GetClassNameW(child, name, len(name))
                    if name.value.lower().startswith('mpv'):
                        outputs.append(child)
                    return True
                user32.EnumChildWindows(hwnd, callback_type(collect_output), 0)
                assert outputs, 'Local preview has no native mpv output to check'
                for child in outputs:
                    region = gdi32.CreateRectRgn(0, 0, 0, 0)
                    point = wintypes.POINT(20, 2)
                    user32.MapWindowPoints(hwnd, child, ctypes.byref(point), 1)
                    try:
                        assert user32.GetWindowRgn(child, region) > 0
                        assert not gdi32.PtInRegion(region, point.x, point.y), 'mpv child escapes the viewport mask'
                    finally:
                        gdi32.DeleteObject(region)
            pointer[0] = home_pointer
            bar.setValue(0)
            assert video.mask() == home_mask, 'Returning preview did not restore its viewport clip'
            original_stop = player.stop
            def stop_after_hide(*args, **kwargs):
                assert video.isHidden(), 'Preview stayed visible during synchronous player shutdown'
                return original_stop(*args, **kwargs)
            with patch.object(player, 'stop', side_effect=stop_after_hide), \
                    patch.object(item.thumb, 'sync_preview_position', wraps=item.thumb.sync_preview_position) as sync:
                bar.setValue(180)
                assert not sync.called, 'Scroll-away moved the doomed native video before hiding it'
            assert not video.isVisible(), 'Inline preview survived scrolling away from the pointer'
            assert not preview._grace.isActive(), 'Scroll-away incorrectly retained the mouse-leave grace'
            print('PASS: inline scroll alignment, stable playback and immediate ownership release; native=', native)
        finally:
            preview.stop()
            host.close()
            settle(app)


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    if '--native' in sys.argv:
        check_inline_scroll(app, native=True)
        return
    check_inline_scroll(app)
    check_drag_preview(app)
    host = QWidget()
    host.setAttribute(Qt.WA_ShowWithoutActivating)
    host.setGeometry(-20000, -20000, 1100, 760)
    rooms = [dict(room_id=str(1000+i), uname=f'Fixture {i}', live=True) for i in range(65)]
    sidebar = Sidebar(rooms, host, card_mode=False, auto_compact=False)
    sidebar.setGeometry(0, 0, sidebar.width(), host.height())
    preview = HoverPreview(sidebar, host)
    sidebar.previewHovered.connect(preview.on_hover)
    sidebar.previewUnhovered.connect(preview.on_unhover)
    pointer = [QPoint(-30000, -30000)]
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    with patch('ddm.preview.StreamResolver', Resolver), patch('ddm.preview.TilePlayer', Player), \
            patch.object(QCursor, 'pos', side_effect=lambda: pointer[0]):
        host.show()
        settle(app)
        try:
            item = sidebar.items()[1]
            # Only the mocked cursor moves: no Enter/MouseMove is delivered.
            item._set_hovered(False)
            plain_color = item.grab().toImage().pixelColor(item.width() // 2, 2)
            pointer[0] = item.mapToGlobal(item.rect().center())
            settle(app, .1)
            check(item.property('hovered') is True, 'Missing Enter left the row without hover highlight')
            hover_color = item.grab().toImage().pixelColor(item.width() // 2, 2)
            check(hover_color != plain_color, 'Recovered hover must change the painted card background')
            pointer[0] = host.mapToGlobal(QPoint(700, 500))
            settle(app, .1)
            check(item.property('hovered') is False, 'Missing Leave left the row highlighted')
            offline = sidebar.items()[2]
            offline.room['live'] = False
            pointer[0] = offline.mapToGlobal(offline.rect().center())
            settle(app, .1)
            check(offline.property('hovered') is True, 'Offline rows need highlight without a preview')
            pointer[0] = host.mapToGlobal(QPoint(700, 500))
            settle(app, .1)
            offline.room['live'] = True
            preview.cancel()
            preview.enabled = False
            pointer[0] = item.name_label.mapToGlobal(item.name_label.rect().center())
            settle(app, .1)
            check(item.property('hovered') is True, 'Disabled previews must not disable row highlighting')
            hovered = []
            item.hovered.connect(lambda room: hovered.append(room['room_id']))
            settle(app, .12)
            check(not hovered, 'Stable cursor must not repeatedly restart hover previews')
            probe_start = time.perf_counter()
            for _ in range(1000):
                sidebar._sync_pointer_hover()
            elapsed_ms = (time.perf_counter()-probe_start) * 1000
            hit_test_mean_ms = elapsed_ms / 1000
            pointer[0] = host.mapToGlobal(QPoint(700, 500))
            settle(app, .1)
            preview.enabled = True
            pointer[0] = item.mapToGlobal(item.rect().center())
            preview.on_hover(item.room)
            preview._begin_resolve()
            old = preview._resolver
            generation = preview._generation
            prepared = preview._popup_player
            # No Leave is delivered: scroll the item away while its URL is pending.
            sidebar.scroll.verticalScrollBar().setValue(170)
            check(preview._generation > generation, 'Pending preview survived scrolling away before popup show')
            check(not prepared.stop.called, 'Idle prepared preview core was stopped on every hover')
            old.resolved.emit(old.room_id, 'fixture.flv', 80, 'web', [])
            preview._show_now()
            check(not preview._popup.isVisible(), 'Late URL resurrected scrolled-away preview')
            preview.cancel()
            sidebar.scroll.verticalScrollBar().setValue(0)
            pointer[0] = item.mapToGlobal(item.rect().center())
            preview.on_hover(item.room)
            preview._begin_resolve()
            preview._show_now()
            resolver = preview._resolver
            resolver.resolved.emit(resolver.room_id, 'fixture.flv', 80, 'web', [])
            check(preview._popup.isVisible(), 'Valid hovered preview failed to show')
            # Native child windows can swallow Leave; coordinate ownership must recover.
            pointer[0] = host.mapToGlobal(QPoint(700, 500))
            settle(app, .22)
            check(not preview._popup.isVisible(), 'Missing Leave left an active popup stuck')
            check(prepared.stop.call_count == 1, 'A playing popup must still be stopped')
            prepared.stop.assert_called_once_with(keep_core=True)
            preview.cancel()
            sidebar.scroll.verticalScrollBar().setValue(0)
            pointer[0] = sidebar.items()[1].mapToGlobal(sidebar.items()[1].rect().center())
            wheel_count = 0
            for _ in range(24):
                target = next((entry for entry in sidebar.items() if preview._cursor_on_item(entry)), None)
                if target is None:
                    break
                preview.on_hover(target.room)
                preview._begin_resolve()
                pending = preview._resolver
                viewport = sidebar.scroll.viewport()
                event = QWheelEvent(QPointF(viewport.mapFromGlobal(pointer[0])), QPointF(pointer[0]),
                                    QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                                    Qt.ScrollUpdate, False)
                app.sendEvent(viewport, event)
                pending.resolved.emit(pending.room_id, 'fixture.flv', 80, 'web', [])
                preview._show_now()
                check(not preview._popup.isVisible(), 'Sequential wheel previews resurrected an old popup')
                wheel_count += 1
            check(wheel_count >= 10, 'Fixture must exercise repeated wheel-based preview changes')
            clipped = sidebar.items()[0]
            pointer[0] = clipped.mapToGlobal(clipped.rect().center())
            check(not preview._cursor_on_item(clipped), 'Clipped rows must not retain hover ownership')
            preview.cancel()
            # Re-polishing a dynamic property must request paint on Qt 6.9 as well.
            item._set_hovered(False)
            with patch.object(item, 'update', wraps=item.update) as update:
                item._set_hovered(True)
                check(update.called, 'Hover property changed without requesting a repaint')
            times = []
            for _ in range(30):
                for entry in sidebar.items()[:12]:
                    start = time.perf_counter()
                    entry._set_hovered(True)
                    entry._set_hovered(False)
                    times.append((time.perf_counter()-start)*1000)
            print(json.dumps({'qt': qVersion(), 'hover_toggle_max_ms': round(max(times), 3),
                              'hover_toggle_mean_ms': round(sum(times)/len(times), 3),
                              'wheel_changes': wheel_count,
                              'pointer_hit_test_mean_ms': round(hit_test_mean_ms, 4),
                              'failures': errors}, ensure_ascii=False), flush=True)
        finally:
            preview.stop()
            host.hide()
            check(not sidebar._hover_sync_timer.isActive(), 'Hidden sidebar must stop pointer polling')
            host.close()
    assert not errors, errors


if __name__ == '__main__':
    main()
