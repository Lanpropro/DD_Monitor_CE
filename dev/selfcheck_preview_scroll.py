"""隔离复现：紧凑列表滚轮换人、迟到取流、漏发Leave和悬停重绘。"""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
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


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
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
