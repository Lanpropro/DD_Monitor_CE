"""Execute Windows launchers: UTF-8 output, spaced paths and exit codes."""
import os
from pathlib import Path
import subprocess
import tempfile
import time


REPO = Path(__file__).resolve().parent.parent


def invoke(script, env, args=()):
    return subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                           script.name, *args], input=b"\r\n", capture_output=True,
                          cwd=script.parent, env=env, timeout=15)


def main():
    with tempfile.TemporaryDirectory(prefix="DDM 启动测试 ") as directory:
        root = Path(directory)
        env = dict(os.environ, PYTHONIOENCODING="gbk", PYTHONUTF8="0",
                   DDM_QTQUICK_DANMAKU="0", DDM_SETTINGS_PROCESS="0")
        # Each launcher must override the incoming console encoding.
        for name in ("run-console.cmd", "run.cmd"):
            data = (REPO / name).read_bytes()
            assert not data.startswith(b"\xef\xbb\xbf")
            assert data.count(b"\r\n") == data.count(b"\n")
            (root / name).write_bytes(data)
        (root / "main.py").write_text(
            'from pathlib import Path\n'
            'import os, sys\n'
            'print("中文启动正常", flush=True)\n'
            'Path(__file__).with_name("quick.txt").write_text(os.environ.get("DDM_QTQUICK_DANMAKU", ""), encoding="utf-8")\n'
            'Path(__file__).with_name("settings.txt").write_text(os.environ.get("DDM_SETTINGS_PROCESS", ""), encoding="utf-8")\n'
            'Path(__file__).with_name("pythonpath.txt").write_text(os.environ.get("PYTHONPATH", ""), encoding="utf-8")\n'
            'Path(__file__).with_name("started.txt").write_text("启动成功", encoding="utf-8")\n'
            'sys.exit(7)\n', encoding="utf-8")
        (root / 'dev').mkdir()
        (root / 'dev/diagnose_drag_windows.py').write_text(
            'from pathlib import Path\nimport runpy\n'
            'root = Path(__file__).resolve().parents[1]\n'
            '(root / "trace-enabled.txt").write_text("1")\n'
            'runpy.run_path(str(root / "main.py"), run_name="__main__")\n', encoding='utf-8')
        (root / 'dev/sc_simulator.py').write_text(
            'from pathlib import Path\nimport sys\n'
            'Path(__file__).resolve().parents[1].joinpath("simulator.txt").write_text(" ".join(sys.argv[1:]))\n',
            encoding='utf-8')
        result = invoke(root / "run-console.cmd", env)
        text = result.stdout.decode("utf-8")
        assert result.returncode == 7, (result.returncode, text, result.stderr)
        assert "中文启动正常" in text and "程序已退出，退出码：7。" in text
        assert (root / "started.txt").read_text(encoding="utf-8") == "启动成功"
        assert (root / "settings.txt").read_text(encoding="utf-8") == "1"
        assert (root / "quick.txt").read_text(encoding="utf-8") == "1"
        assert not (root / 'trace-enabled.txt').exists(), 'Console launcher retains its normal entry'
        (root / "started.txt").unlink()
        deps = root / 'work/deps/PySide6'
        deps.mkdir(parents=True)
        (deps / 'QtCore.pyd').touch()
        result = invoke(root / "run.cmd", env)
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 10
        while not (root / "started.txt").exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (root / "started.txt").read_text(encoding="utf-8") == "启动成功"
        assert (root / "settings.txt").read_text(encoding="utf-8") == "1"
        assert (root / "quick.txt").read_text(encoding="utf-8") == "1", \
            "run.cmd must enable Quick in the launched Python process"
        assert (root / 'pythonpath.txt').read_text(encoding='utf-8').startswith(str(deps.parent)), \
            'Daily launcher must select the same work/deps used by freezing'
        assert (root / 'trace-enabled.txt').read_text() == '1', 'run.cmd must enable temporary drag tracing'
        (root / 'trace-enabled.txt').unlink()
        result = invoke(root / 'run.cmd', env, ('--sc-simulator', '--smoke'))
        assert result.returncode == 0
        deadline = time.monotonic() + 10
        while not (root / 'simulator.txt').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (root / 'simulator.txt').read_text() == '--smoke'
        assert not (root / 'trace-enabled.txt').exists(), 'Simulator keeps its independent entry'
        # Missing interpreter errors must also be readable and report failure.
        for name in ("run.cmd", "run-console.cmd"):
            text = (root / name).read_text(encoding="utf-8").replace(
                "F:\\CodexAppManager\\Code\\DD_Monitor-venv\\Scripts\\",
                str(root / "missing") + "\\")
            (root / name).write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
            result = invoke(root / name, env)
            assert result.returncode == 1
            assert "没找到 Python 解释器" in result.stdout.decode("utf-8")
    print("Windows launchers: UTF-8, console/pythonw, Quick opt-in, spaced Chinese paths and errors passed")


if __name__ == "__main__":
    main()
