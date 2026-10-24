"""自检：导入失败和首次启动都生成可定位的启动日志。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

IMPORT_FAILURE_CHILD = r"""
import sys
from pathlib import Path
import main
main.PROJ = Path(sys.argv[1])
sys.modules["ddm.app"] = None
from ddm import diagnostics
diagnostics.show_startup_failure = lambda *args, **kwargs: None
sys.exit(main._run())
"""

QT_FAILURE_CHILD = r"""
import builtins
import sys
from pathlib import Path
import main
main.PROJ = Path(sys.argv[1])
original_import = builtins.__import__
def blocked_import(name, *args, **kwargs):
    if name == "PySide6" or name.startswith("PySide6."):
        raise ImportError("simulated missing Qt")
    return original_import(name, *args, **kwargs)
builtins.__import__ = blocked_import
from ddm import diagnostics
diagnostics.show_startup_failure = lambda *args, **kwargs: None
sys.exit(main._run())
"""

WINDOW_FAILURE_CHILD = r"""
import sys
from pathlib import Path
import types
import main
main.PROJ = Path(sys.argv[1])
from ddm import diagnostics
diagnostics.show_startup_failure = lambda *args, **kwargs: None
def fail_window(argv):
    with diagnostics.get_session().phase("window_build"):
        raise RuntimeError("simulated window failure")
module = types.ModuleType("ddm.app")
module.main = fail_window
sys.modules["ddm.app"] = module
sys.exit(main._run())
"""

SUCCESS_CHILD = r"""
import sys
from pathlib import Path
import types
import main
main.PROJ = Path(sys.argv[1])
module = types.ModuleType("ddm.app")
module.main = lambda argv: 0
sys.modules["ddm.app"] = module
sys.exit(main._run())
"""


def run_child(script: str, project: Path, log_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, DDM_LOG_DIR=str(log_dir), DDM_NO_SAVE="1")
    return subprocess.run([sys.executable, "-c", script, str(project)],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ddm-startup-log-") as directory:
        root = Path(directory)
        project = root / "first-run"
        project.mkdir()
        log_dir = root / "failure-logs"
        result = run_child(IMPORT_FAILURE_CHILD, project, log_dir)
        assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
        log_file = log_dir / "ddm.log"
        assert log_file.is_file(), list(log_dir.iterdir()) if log_dir.exists() else []
        text = log_file.read_text(encoding="utf-8")
        assert "[启动失败]" in text, text
        assert "phase=import_app" in text, text
        assert "ImportError" in text or "ModuleNotFoundError" in text, text
        assert "Traceback" in text, text
        assert "first_run=True" in text, text
        assert "log=" in text and str(log_file).endswith("failure-logs\\ddm.log"), text
        crash_file = log_dir / "ddm-crash.log"
        assert crash_file.is_file(), "启动失败也应建立崩溃现场文件"

        qt_logs = root / "qt-failure-logs"
        qt_failure = run_child(QT_FAILURE_CHILD, project, qt_logs)
        assert qt_failure.returncode == 1, (
            qt_failure.returncode, qt_failure.stdout, qt_failure.stderr)
        qt_text = (qt_logs / "ddm.log").read_text(encoding="utf-8")
        assert "phase=import_app" in qt_text and "simulated missing Qt" in qt_text, qt_text
        assert "[启动失败]" in qt_text and "Traceback" in qt_text, qt_text

        window_logs = root / "window-failure-logs"
        window_failure = run_child(WINDOW_FAILURE_CHILD, project, window_logs)
        assert window_failure.returncode == 1, (
            window_failure.returncode, window_failure.stdout, window_failure.stderr)
        window_text = (window_logs / "ddm.log").read_text(encoding="utf-8")
        assert "phase=window_build" in window_text, window_text
        assert "simulated window failure" in window_text, window_text
        assert "[启动失败]" in window_text and "Traceback" in window_text, window_text

        first_log = root / "first-success-logs"
        first = run_child(SUCCESS_CHILD, project, first_log)
        assert first.returncode == 0, (first.returncode, first.stdout, first.stderr)
        first_text = (first_log / "ddm.log").read_text(encoding="utf-8")
        assert "first_run=True" in first_text, first_text

        (project / "utils").mkdir()
        (project / "utils" / "config.json").write_text("{}", encoding="utf-8")
        next_log = root / "next-success-logs"
        following = run_child(SUCCESS_CHILD, project, next_log)
        assert following.returncode == 0, (
            following.returncode, following.stdout, following.stderr)
        next_text = (next_log / "ddm.log").read_text(encoding="utf-8")
        assert "first_run=False" in next_text, next_text
        print("PASS: startup failure and first-run state are recorded with context")


if __name__ == "__main__":
    main()
