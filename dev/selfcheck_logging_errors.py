"""Self-check: broad exceptions and legacy diagnostics never fail silently."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject, Signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config, diagnostics, plugins, recording  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


SOURCES = [ROOT / "main.py", *sorted((ROOT / "ddm").glob("*.py"))]
LOGGER_METHODS = {"debug", "info", "warning", "error", "exception",
                  "critical", "log"}
# diagnostics.py 在日志初始化失败时仍需向控制台报错；watchdog.py 可能在没有
# 日志会话的情况下工作，此时只能把卡死/崩溃栈作为最后手段写到 stderr。
PRINT_ALLOWED = {"ddm/diagnostics.py", "ddm/watchdog.py"}
# 独立设置进程用 stdout 传 JSON 协议，不能改成 logging。
PROTOCOL_PRINTS = {("ddm/settings_process.py", "send")}


def _call_name(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else "")


def _is_logger_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _call_name(node) in LOGGER_METHODS


def _raises(node: ast.AST) -> bool:
    return any(isinstance(child, ast.Raise) for child in ast.walk(node))


def _broad_exception(node: ast.ExceptHandler) -> bool:
    broad = {"Exception", "BaseException"}
    if isinstance(node.type, ast.Name):
        return node.type.id in broad
    if isinstance(node.type, ast.Tuple):
        return any(isinstance(item, ast.Name) and item.id in broad
                   for item in node.type.elts)
    return False


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return "<module>"


def violations(path: Path, source: str | None = None) -> list[str]:
    relative = path.relative_to(ROOT).as_posix() if path.is_absolute() else path.as_posix()
    tree = ast.parse(source if source is not None else path.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _broad_exception(node):
            function = _enclosing_function(node, parents)
            reported = any(_is_logger_call(child) for child in ast.walk(node))
            if not reported and not _raises(node):
                result.append(f"{relative}:{node.lineno}: broad exception in {function} has no log")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "traceback"
                    and node.func.attr == "print_exc"):
                result.append(f"{relative}:{node.lineno}: traceback.print_exc is not structured logging")
        if (relative not in PRINT_ALLOWED and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "print"):
            function = _enclosing_function(node, parents)
            if (relative, function) not in PROTOCOL_PRINTS:
                result.append(f"{relative}:{node.lineno}: legacy print bypasses structured logging")
    return result


def static_checks() -> None:
    findings = [item for path in SOURCES for item in violations(path)]
    assert not findings, "\n".join(findings)
    sample = """
def broken():
    try:
        raise RuntimeError("boom")
    except Exception:
        pass
"""
    rejected = violations(Path("sample.py"), sample)
    assert rejected and "has no log" in rejected[0], rejected


def read_log(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def plugin_checks() -> None:
    class Broken(plugins.Plugin):
        name = "故障插件"

        def on_event(self, event, payload):
            raise RuntimeError("plugin-event-selfcheck")

        def tile_actions(self, tile):
            raise RuntimeError("plugin-menu-selfcheck")

    manager = plugins.PluginManager(plugins_dir=str(ROOT / "plugins_user"))
    plugin = Broken()
    plugin.context = plugins.PluginContext(manager, "broken_selfcheck")
    manager.plugins.append(plugin)
    manager.emit("selfcheck.event")
    assert manager.tile_actions(SimpleNamespace(room={})) == []
    manager.run_action(lambda: (_ for _ in ()).throw(
        RuntimeError("plugin-action-selfcheck")),
        plugin_id="broken_selfcheck", action="自检动作")
    text = read_log(diagnostics.get_session().log_path)
    assert "event=plugin_event_failed" in text, text
    assert "plugin_id=broken_selfcheck" in text and "event=selfcheck.event" in text, text
    assert "event=plugin_tile_actions_failed" in text, text
    assert "event=plugin_action_failed" in text, text
    assert "action=自检动作" in text and "plugin-action-selfcheck" in text, text
    assert text.count("Traceback") >= 3, text


def recording_checks() -> None:
    class Tile:
        room = {"room_id": "1001", "uname": "自检主播", "live": True}
        stream_url = "http://127.0.0.1:9/live.flv"
        stream_headers = {}
        stream_codec = "avc"

        @staticmethod
        def isVisible():
            return True

    tile = Tile()
    manager = recording.RecordingManager({
        "recording_enabled": True,
        "recording_dir": str(ROOT / "recordings"),
    })
    with patch.object(recording, "ffmpeg_path", return_value="ffmpeg"), \
            patch.object(manager, "_directory", side_effect=OSError("disk-selfcheck")):
        assert manager.start(tile, recording=True) is False
    text = read_log(diagnostics.get_session().log_path)
    assert "event=recording_failed" in text, text
    assert "room_id=1001" in text and "disk-selfcheck" in text, text
    assert " ERROR " in text, text


def app_checks() -> None:
    events: list[str] = []

    class FakePlugins:
        def emit(self, event, **payload):
            events.append(event)

    class Tile:
        room = {"room_id": "2002", "uname": "取流自检", "live": True}
        quality = 250
        paused = False

        @staticmethod
        def set_status(text):
            return None

        @staticmethod
        def set_buffering(active):
            return None

        @staticmethod
        def set_video_active(active):
            return None

        @staticmethod
        def stop_elapsed_timer():
            return None

        @staticmethod
        def raise_overlays():
            return None

    tile = Tile()
    player = SimpleNamespace(stream_codec="hevc", decode_mode="auto", stream_profile="app")
    owner = SimpleNamespace(
        _closing=False,
        _pending_capture={},
        plugins=FakePlugins(),
        refresh_status=lambda: None,
        _freeze_refreshed=set(),
        _schedule_retry=lambda target: events.append("retry"),
        _retry_count={tile: 2},
        players={tile: player},
        _clear_freeze_recovery=lambda target: None,
    )
    MainWindow._on_resolve_failed(owner, tile, "CDN 403 selfcheck")
    MainWindow._on_player_state(owner, tile, "error")
    status_owner = SimpleNamespace(
        sidebar=SimpleNamespace(count_label=SimpleNamespace(setText=lambda text: None)))
    MainWindow._on_status_failed(status_owner, "status-selfcheck")
    text = read_log(diagnostics.get_session().log_path)
    assert "event=stream_resolve_failed" in text, text
    assert "room_id=2002" in text and "uname=取流自检" in text, text
    assert "reason=CDN 403 selfcheck" in text and " ERROR " in text, text
    assert "event=status_refresh_failed" in text and "status-selfcheck" in text, text
    assert "event=stream_playback_failed" in text, text
    assert "room_id=2002" in text and "uname=取流自检" in text, text
    assert "codec=hevc" in text and "decode_mode=auto" in text, text
    assert "profile=app" in text and "attempt=3" in text, text
    assert " WARNING " in text, text
    assert plugins.EVENT_STREAM_FAILED in events and "retry" in events, events


def qt_slot_checks() -> None:
    application = QCoreApplication.instance() or QCoreApplication([])

    class BrokenSlot(QObject):
        triggered = Signal()

        def __init__(self):
            super().__init__()
            self.triggered.connect(self.fail)

        @staticmethod
        def fail():
            raise RuntimeError("qt-slot-selfcheck")

    receiver = BrokenSlot()
    receiver.triggered.emit()
    application.processEvents()
    session = diagnostics.get_session()
    session._logger.handlers[0].flush()
    text = read_log(session.log_path)
    assert "event=uncaught_exception" in text, text
    assert "qt-slot-selfcheck" in text and "Traceback" in text, text
    assert " CRITICAL " in text, text


def config_checks() -> None:
    with patch.object(config.io, "open", side_effect=PermissionError("read-selfcheck")):
        assert config._read_json("unreadable.json") == {}
    with tempfile.TemporaryDirectory(prefix="ddm-config-log-") as directory, \
            patch.object(config, "CONFIG_PATH", str(Path(directory) / "config.json")), \
            patch.dict(config.os.environ, {"DDM_NO_SAVE": ""}), \
            patch.object(config.io, "open", side_effect=PermissionError("write-selfcheck")):
        config.save({"version": 1})
    text = read_log(diagnostics.get_session().log_path)
    assert "event=config_read_failed" in text and "read-selfcheck" in text, text
    assert "event=config_save_failed" in text and "write-selfcheck" in text, text


def main() -> None:
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    directory = Path(tempfile.mkdtemp(prefix="ddm-error-log-"))
    try:
        static_checks()
        session = diagnostics.start(log_dir=directory, level="DEBUG")
        plugin_checks()
        recording_checks()
        app_checks()
        qt_slot_checks()
        config_checks()
        session._logger.handlers[0].flush()
        text = read_log(session.log_path)
        assert text, "运行自检必须产生日志"
        print(f"PASS: broad exceptions report context ({len(SOURCES)} files checked)")
    finally:
        diagnostics.close()
        sys.stdout, sys.stderr = original_stdout, original_stderr
        import shutil
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    main()
