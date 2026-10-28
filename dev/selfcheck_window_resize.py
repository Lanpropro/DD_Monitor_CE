"""Offline MainWindow resize regression; timings measure Qt work, not decoder FPS."""
import argparse
import json
import math
import os
import socket
import subprocess
import sys
import time
import types
from collections import Counter, defaultdict
from contextlib import ExitStack
from itertools import pairwise
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

if "--baseline" in sys.argv:
    for module_name in ("video_surface", "widgets", "app"):
        source = subprocess.check_output(
            ["git", "show", f"7d2464fc3c4ec4428043794c39ca9b46207024c9:ddm/{module_name}.py"],
            cwd=ROOT)
        module = types.ModuleType(f"ddm.{module_name}")
        module.__file__ = str(ROOT / "ddm" / f"{module_name}.py")
        module.__package__ = "ddm"
        sys.modules[module.__name__] = module
        exec(compile(source, module.__file__, "exec"), module.__dict__)  # noqa: S102

from ddm import app as app_module
from ddm import theme
from ddm.app import MainWindow
from dev.selfcheck_tile_fullscreen import SilentPoller


def settle(milliseconds=220):
    QTest.qWait(milliseconds)
    QApplication.processEvents()


def wait_orientation(window, expected):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        settle(25)
        timer = getattr(window, "_resize_idle_timer", None)
        if (window.orientation == expected and (timer is None or not timer.isActive())
                and not getattr(window, "_resize_dirty", False)):
            return
    raise AssertionError(f"orientation did not settle to {expected}: "
                         f"{window.width()}x{window.height()}, {window.orientation}")


class Events(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.counts: Counter[str] = Counter()

    def eventFilter(self, watched, event):
        names = {QEvent.Type.Resize: "resize", QEvent.Type.Move: "move", QEvent.Type.Paint: "paint"}
        if event.type() in names:
            self.counts[names[event.type()]] += 1
        return False


class Work:
    def __init__(self, window, stack):
        self.calls: Counter[str] = Counter()
        self.milliseconds: defaultdict[str, float] = defaultdict(float)
        for owner, name in ((window, "_apply_orientation"),
                            (window.wall, "relayout"),
                            (window.wall, "finish_resize"),
                            (window.wall, "_relayout_preset"),
                            (window.wall, "_relayout_corner")):
            original = getattr(owner, name, None)
            if original is None:
                continue

            def measured(*args, _name=name, _original=original, **kwargs):
                before = time.perf_counter()
                self.calls[_name] += 1
                try:
                    return _original(*args, **kwargs)
                finally:
                    self.milliseconds[_name] += (time.perf_counter() - before) * 1000

            stack.enter_context(patch.object(owner, name, measured))

    def reset(self):
        self.calls.clear()
        self.milliseconds.clear()

    def snapshot(self):
        return {"calls": dict(self.calls), "work_ms": {
            name: round(value, 3) for name, value in self.milliseconds.items()}}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def latest_geometry(window):
    wall = window.wall
    widgets = wall.visible_tiles()
    check(bool(widgets), "wall has no visible panes")
    bounds = widgets[0].geometry()
    for tile in widgets[1:]:
        bounds = bounds.united(tile.geometry())
    area = wall._corner_area()
    check(bounds == area, f"stale geometry: panes={bounds}, latest wall={area}")
    check(all(tile.width() > 0 and tile.height() > 0 for tile in widgets),
          "pane collapsed")
    return [area.x(), area.y(), area.width(), area.height()]


def native_message(window, message):
    import ctypes
    from ctypes import wintypes

    send = ctypes.windll.user32.SendMessageW
    send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    send.restype = ctypes.c_ssize_t
    send(int(window.winId()), message, 0, 0)


def interactive(window, active, baseline, native=False):
    if baseline:
        return
    method = "_begin_interactive_resize" if active else "_finish_interactive_resize"
    if native and not baseline:
        check(QApplication.platformName() == "windows", "native messages require Windows Qt")
        native_message(window, 0x0231 if active else 0x0232)
        check(window._interactive_resize == active, "native resize message was not handled")
    elif hasattr(window, method):
        getattr(window, method)()
    elif not baseline:
        raise AssertionError(f"missing MainWindow.{method}()")


def sustained(window, work, events, baseline, native):
    window.resize(1420, 860)
    settle()
    tiles = list(window.wall.visible_tiles())
    hwnds = [int(tile.video.winId()) for tile in tiles]
    players = dict(window.players)
    work.reset()
    events.counts.clear()
    window.start_tile.reset_mock()
    ticks = []
    heartbeat = QTimer(window)
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
    heartbeat.start()
    before = time.perf_counter()
    bursts = []
    burst_ms = []
    interactive(window, True, baseline, native)
    for burst in range(8):
        burst_start = time.perf_counter()
        previous = sum(work.calls[name] for name in ("_relayout_preset", "_relayout_corner"))
        for sample in range(12):
            window.resize(1420 + burst * 9 + sample * 2, 860 + burst * 3 + sample % 3)
            QApplication.processEvents()
        settle(45)
        current = sum(work.calls[name] for name in ("_relayout_preset", "_relayout_corner"))
        bursts.append(current - previous)
        burst_ms.append(round((time.perf_counter() - burst_start) * 1000, 2))
    interactive(window, False, baseline, native)
    finish_wall = latest_geometry(window)
    settle()
    heartbeat.stop()
    result = work.snapshot()
    result.update(input_events=96, bursts=bursts, burst_ms=burst_ms, events=dict(events.counts),
                  heartbeat_ticks=len(ticks), elapsed_ms=round((time.perf_counter() - before) * 1000, 2),
                  max_heartbeat_gap_ms=round(max((b - a for a, b in pairwise(ticks)), default=0) * 1000, 2),
                  final_window=[window.width(), window.height()],
                  finish_wall=finish_wall,
                  final_wall=latest_geometry(window))
    check([int(tile.video.winId()) for tile in tiles] == hwnds, "video HWND changed")
    check(window.players == players, "same-orientation resize replaced players")
    check(not any(player.release.called or player.play.called for player in players.values()),
          "same-orientation resize restarted/released a player")
    window.start_tile.assert_not_called()
    check(window.orientation == "landscape", "wide resize changed orientation")
    if not baseline:
        check(work.calls["_apply_orientation"] == 0, "same orientation was reapplied")
        check(work.calls["relayout"] == 0, "same orientation rebuilt wall")
        check(all(count <= math.ceil(duration / 33) + 1
                  for count, duration in zip(bursts, burst_ms)),
              f"geometry work exceeded the 33ms timer budget: {bursts}, {burst_ms}")
        check(sum(bursts) < 96, f"geometry work was not coalesced: {bursts}")
        check(len(ticks) >= 8, "Qt timer events starved during resize")
    return result


def orientations(window, work, baseline, native):
    window.resize(1420, 850)
    settle()
    tiles = list(window.wall.visible_tiles())
    hwnds = [int(tile.video.winId()) for tile in tiles]
    players = dict(window.players)
    work.reset()
    interactive(window, True, baseline, native)
    during = []
    for width in (1200, 1080, 1000, 940, 850):
        window.resize(width, 1100)
        settle(45)
        during.append(window.orientation)
    interactive(window, False, baseline, native)
    settle()
    result = {"during_drag": during, "after_finish": window.orientation, **work.snapshot()}
    if not baseline:
        check(during == ["landscape"] * 5, f"orientation changed during drag: {during}")
        check(window.orientation == "portrait", "finish did not apply latest orientation")
        check(work.calls["_apply_orientation"] == 1, "finish must apply orientation once")
        check([int(tile.video.winId()) for tile in tiles] == hwnds, "orientation replaced video HWND")
        check(window.players == players, "orientation replaced players")
        check(not any(player.release.called or player.play.called for player in players.values()),
              "orientation restarted/released a player")
    for direction, initial in (("portrait", (800, 1100)), ("landscape", (1420, 1000))):
        window.resize(*initial)
        wait_orientation(window, direction)
        work.reset()
        observed = []
        effective = []
        for ratio in (.91, .99, .92, .98, .94, .96):
            window.resize(round(1000 * ratio), 1000)
            settle(190)
            observed.append(window.orientation)
            effective.append([window.width(), window.height()])
        result[f"hysteresis_{direction}"] = {"observed": observed, "actual_sizes": effective, **work.snapshot()}
        if not baseline:
            check(observed == [direction] * 6, f"hysteresis oscillation: {observed}, sizes={effective}")
            check(work.calls["_apply_orientation"] == 0, "hysteresis reapplied orientation")
    for size, expected in (((800, 1100), "portrait"), ((1420, 850), "landscape")):
        window.resize(*size)
        QApplication.processEvents()
        if not baseline:
            check(window.orientation != expected, "programmatic orientation was not deferred")
        settle(300)
        check(window.orientation == expected, "idle orientation did not settle")
    window.resize(1420, 850)
    wait_orientation(window, "landscape")
    work.reset()
    interactive(window, True, baseline, native)
    window.move(window.x() + 7, window.y() + 5)
    settle(60)
    interactive(window, False, baseline, native)
    settle()
    result["move_only"] = work.snapshot()
    check(not any(work.calls.values()), f"move-only session caused work: {work.calls}")
    if not baseline:
        interactive(window, True, False, native)
        window.resize(800, 1100)
        QApplication.processEvents()
        window._on_layout_changed("portrait_main2")
        settle(300)
        check(window.orientation == "portrait", "explicit portrait selection was lost")
        interactive(window, True, False, native)
        window.resize(1420, 850)
        QApplication.processEvents()
        window._on_layout_changed("3x2")
        settle(300)
        check(window.orientation == "landscape", "explicit landscape selection was lost")
        for identifier in ("3x2", "corner"):
            window._on_layout_changed("corner")
            window.resize(1420, 850)
            wait_orientation(window, "landscape")
            current_tiles = list(window.wall.tiles)
            current_hwnds = [int(tile.video.winId()) for tile in current_tiles]
            current_players = dict(window.players)
            interactive(window, True, False, native)
            window.resize(800, 1100)
            QApplication.processEvents()
            check(window.orientation == "landscape" and window._resize_orientation() == "portrait",
                  "explicit preset regression requires pending portrait geometry")
            check(window._resize_dirty, "pending drag was not marked dirty")
            window._on_layout_changed(identifier)
            check(window.wall.layout_id == identifier and window.orientation == "landscape",
                  f"explicit {identifier} selection was not applied immediately")
            interactive(window, False, False, native)
            settle(300)
            check(window.wall.layout_id == identifier and window.orientation == "landscape",
                  f"pending drag overwrote explicit {identifier} selection")
            check(window.width() >= window.height(), f"explicit {identifier} did not reshape window")
            check(not window._interactive_resize and not window.wall._interactive_resize
                  and not window._resize_dirty and not window._resize_idle_timer.isActive()
                  and not window.wall._resize_timer.isActive(),
                  f"explicit {identifier} left resize work pending")
            check(list(window.wall.tiles) == current_tiles
                  and [int(tile.video.winId()) for tile in current_tiles] == current_hwnds,
                  f"explicit {identifier} replaced tiles or video HWNDs")
            check(window.players == current_players, f"explicit {identifier} replaced players")
            result[f"pending_explicit_{identifier}"] = {
                "actual_size": [window.width(), window.height()], "layout": window.wall.layout_id,
                "orientation": window.orientation}
    return result


def cancellation(window, work, baseline, native):
    if baseline:
        return {"skipped": "baseline has no resize callback cancellation interface"}
    result = {}
    for action, dragging in (("fullscreen", True), ("hide", True),
                             ("hide", False), ("close", False)):
        window.resize(1420, 850)
        window.show()
        wait_orientation(window, "landscape")
        if dragging:
            interactive(window, True, False, native)
        window.resize(800, 1100)
        QApplication.processEvents()
        if action == "fullscreen":
            window._on_fullscreen(window.wall.tiles[0])
        else:
            getattr(window, action)()
        QApplication.processEvents()
        work.reset()
        settle(300)
        result[f"{action}_{'drag' if dragging else 'idle'}"] = work.snapshot()
        check(work.calls["_apply_orientation"] == 0,
              f"late orientation callback after {action}: {work.calls}")
        check(not window._interactive_resize and not window.wall._interactive_resize,
              f"interactive resize survived {action}")
        timers = [timer for timer in (getattr(window, "_resize_idle_timer", None),
                                      getattr(window.wall, "_resize_timer", None)) if timer]
        check(not any(timer.isActive() for timer in timers), f"resize timer survived {action}")
        if action == "fullscreen":
            check(window._fullscreen_tile is not None, "fullscreen did not enter")
            window._exit_fullscreen()
            settle(400)
        elif action == "hide":
            hidden_size = [window.width(), window.height()]
            check(window.orientation == "landscape", "hidden pending direction was applied early")
            work.reset()
            window.show()
            wait_orientation(window, "portrait")
            settle(100)
            check(work.calls["_apply_orientation"] == 1, "reshow must settle orientation exactly once")
            result[f"reshow_{'drag' if dragging else 'idle'}"] = {
                "hidden_size": hidden_size, "shown_size": [window.width(), window.height()],
                "final_wall": latest_geometry(window), **work.snapshot()}
    return result


def fullscreen_band(window, work):
    window._on_layout_changed("portrait_main2")
    window.resize(950, 1000)
    wait_orientation(window, "portrait")
    work.reset()
    window._on_fullscreen(window.wall.tiles[0])
    settle(100)
    window._exit_fullscreen()
    wait_orientation(window, "portrait")
    settle(100)
    ratio = window.width() / window.height()
    check(.91 <= ratio <= .99, f"fullscreen restore left the hysteresis band: {ratio}")
    check(work.calls["_apply_orientation"] == 0, "fullscreen exit changed portrait in hysteresis band")
    return {"actual_size": [window.width(), window.height()], "orientation": window.orientation,
            "final_wall": latest_geometry(window), **work.snapshot()}


def run_case(app, count, identifier, baseline, native, result):
    rooms = [{"room_id": str(9000 + index), "uname": f"Offline {index}",
              "live": False, "muted": True} for index in range(count)]
    window = MainWindow(rooms, [dict(room) for room in rooms], layout_id=identifier,
                        state={"plugins_enabled": [], "settings": {
                            "auto_update": False, "preview_on_hover": False,
                            "recording_enabled": False, "recording_replay_enabled": False}})
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.setGeometry(-9000, 40, 1420, 860)
    window.show()
    settle(300)
    if count == 6:
        window.resize(500, 1000)
        settle(250)
        result["minimum_probe"] = {"requested": [500, 1000],
                                   "actual": [window.width(), window.height()],
                                   "ratio": round(window.width() / window.height(), 4),
                                   "minimum": [window.minimumWidth(), window.minimumHeight()],
                                   "orientation": window.orientation}
        print("minimum_probe=" + json.dumps(result["minimum_probe"]), flush=True)
        window.resize(1420, 860)
        settle(300)
    window._audio_audit_timer.stop()
    window._audio_device_timer.stop()
    for tile in window.wall.visible_tiles():
        window.players[tile] = MagicMock(name=f"player_{tile.room['room_id']}")
    events = Events(window)
    window.installEventFilter(events)
    window.wall.installEventFilter(events)
    try:
        with ExitStack() as measured:
            work = Work(window, measured)
            result["sustained"] = sustained(window, work, events, baseline, native)
            if count == 6:
                result["orientation"] = orientations(window, work, baseline, native)
                fullscreen_error = None
                if not baseline:
                    try:
                        result["fullscreen_band"] = fullscreen_band(window, work)
                    except AssertionError as exc:
                        fullscreen_error = str(exc)
                        result["fullscreen_band"] = {"error": fullscreen_error}
                result["cancellation"] = cancellation(window, work, baseline, native)
                check(fullscreen_error is None, fullscreen_error)
            return result
    finally:
        window.settings["close_behavior"] = "exit"
        window.close()
        app.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--native-messages", action="store_true",
                        help="dispatch WM_ENTERSIZEMOVE/WM_EXITSIZEMOVE through nativeEvent")
    args = parser.parse_args()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    report = {"mode": "baseline" if args.baseline else "regression",
              "source": ("7d2464fc3c4ec4428043794c39ca9b46207024c9: app/widgets/video_surface"
                         if args.baseline else "working tree"),
              "platform": app.platformName(), "native_messages": args.native_messages,
              "scope": "Mock players; Qt event/layout timings are not hardware or decoder FPS guarantees.",
              "cases": [], "failures": []}
    with ExitStack() as stack:
        for method in ("start_tile", "refresh_status", "refresh_stats", "refresh_account",
                       "sync_danmaku", "load_avatars_for", "load_room_avatars",
                       "load_cached_covers", "load_cached_avatars", "_hold_fullscreen_frame",
                       "_check_startup_update"):
            stack.enter_context(patch.object(MainWindow, method))
        stack.enter_context(patch.object(app_module, "StatusPoller", SilentPoller))
        stack.enter_context(patch.object(app_module, "StatsPoller", SilentPoller))
        network = [stack.enter_context(patch.object(owner, name,
                    side_effect=AssertionError("network forbidden")))
                   for owner, name in ((socket.socket, "connect"),
                                       (socket.socket, "connect_ex"), (socket, "getaddrinfo"))]
        for count, identifier in ((1, "1x1"), (6, "corner"), (16, "4x4")):
            result = {"panes": count, "layout": identifier}
            report["cases"].append(result)
            try:
                run_case(app, count, identifier, args.baseline, args.native_messages, result)
            except Exception as exc:  # noqa: BLE001
                report["failures"].append({"panes": count, "error": str(exc)})
                import traceback
                traceback.print_exc()
        report["network_attempts"] = sum(mock.call_count for mock in network)
        if report["network_attempts"]:
            report["failures"].append({"error": "unexpected network attempt"})
    directory = ROOT / "results" / "resize-20261019"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("baseline.json" if args.baseline else "metrics.json")
    path.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")), flush=True)
    return bool(report["failures"])


if __name__ == "__main__":
    raise SystemExit(main())
