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
            'Path(__file__).with_name("no-save.txt").write_text(os.environ.get("DDM_NO_SAVE", ""), encoding="utf-8")\n'
            'Path(__file__).with_name("fullscreen-input.txt").write_text(os.environ.get("DDM_FULLSCREEN_INPUT_CAPTURE", ""), encoding="utf-8")\n'
            'Path(__file__).with_name("legacy-capture.txt").write_text("".join(os.environ.get(key, "") for key in '
            '("DDM_FOLDER_MOTION_CAPTURE", "DDM_THEME_CAPTURE", "DDM_FULLSCREEN_CAPTURE")), encoding="utf-8")\n'
            'Path(__file__).with_name("arguments.txt").write_text(" ".join(sys.argv[1:]), encoding="utf-8")\n'
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
        for name in ('DDM_FOLDER_MOTION_CAPTURE', 'DDM_THEME_CAPTURE', 'DDM_FULLSCREEN_CAPTURE'):
            env.pop(name, None)
        deps = root / 'work/deps/PySide6'
        deps.mkdir(parents=True)
        (deps / 'QtCore.pyd').touch()
        foreign = root / 'external test runtime'
        foreign.mkdir()
        (foreign / 'sitecustomize.py').write_text(
            'import os\nfrom pathlib import Path\n'
            'Path(__file__).with_name("injected.txt").write_text(os.environ.get("DDM_NO_SAVE", ""))\n',
            encoding='utf-8')
        inherited = dict(env, PYTHONPATH=str(foreign), DDM_NO_SAVE='1')
        result = invoke(root / "run.cmd", inherited)
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 10
        while not (root / "started.txt").exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (root / "started.txt").read_text(encoding="utf-8") == "启动成功"
        assert (root / "settings.txt").read_text(encoding="utf-8") == "1"
        assert (root / "quick.txt").read_text(encoding="utf-8") == "1", \
            "run.cmd must enable Quick in the launched Python process"
        assert not (foreign / 'injected.txt').exists(), 'Normal startup must ignore inherited Python startup hooks'
        assert Path((root / 'pythonpath.txt').read_text(encoding='utf-8')) == deps.parent, \
            'Daily launcher must only use its own work/deps'
        assert (root / 'no-save.txt').read_text(encoding='utf-8') == '1', 'Keep an explicit no-save request'
        assert not (root / 'trace-enabled.txt').exists(), 'Normal launch must bypass temporary drag tracing'
        assert not (root / 'legacy-capture.txt').read_text(), 'Normal launch must not start specialist captures'
        (root / 'fullscreen-input.txt').unlink()
        result = invoke(root / 'run.cmd', inherited, ('--diagnose-fullscreen-input',))
        assert result.returncode == 0
        deadline = time.monotonic() + 10
        while not (root / 'fullscreen-input.txt').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (root / 'fullscreen-input.txt').read_text() == '1'
        assert (foreign / 'injected.txt').read_text() == '1', 'Explicit diagnostics allow isolated fixtures'
        assert (root / 'trace-enabled.txt').read_text() == '1', 'Unmigrated diagnostics use the specialist launcher'
        (root / 'trace-enabled.txt').unlink()
        (root / 'started.txt').unlink()
        result = invoke(root / 'run.cmd', env, ('--diagnose-session=drag',))
        assert result.returncode == 0
        deadline = time.monotonic() + 10
        while not (root / 'started.txt').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (root / 'arguments.txt').read_text(encoding='utf-8') == '--diagnose-session=drag'
        assert not (root / 'trace-enabled.txt').exists(), 'Explicit session must bypass the ordinary trace launcher'
        (root / 'started.txt').unlink()
        result = invoke(root / 'run.cmd', env, ('--diagnose-session', 'dock-hover'))
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 10
        while not (root / 'started.txt').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (root / 'arguments.txt').read_text(encoding='utf-8') == '--diagnose-session=dock-hover'
        (root / 'started.txt').unlink()
        (root / 'quoted-session.cmd').write_bytes(b'@echo off\r\ncall run.cmd "--diagnose-session=drag"\r\n')
        result = invoke(root / 'quoted-session.cmd', env)
        assert result.returncode == 0
        deadline = time.monotonic() + 10
        while not (root / 'started.txt').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (root / 'arguments.txt').read_text(encoding='utf-8') == '--diagnose-session=drag'
        assert not (root / 'trace-enabled.txt').exists()
        (root / 'started.txt').unlink()
        for args in (('--diagnose-douyu',), ('--diagnose-fullscreen',), ('--diagnose-notice-close',),
                     ('--diagnose-session', 'fullscreen'), ('--diagnose-session', 'douyu'),
                     ('--diagnose-session', 'notices')):
            result = invoke(root / 'run.cmd', env, args)
            assert result.returncode == 2 and b'capture_diagnostics' in result.stdout, (args, result)
            assert not (root / 'started.txt').exists() and not (root / 'trace-enabled.txt').exists()
        result = invoke(root / 'run.cmd', env, ('--sc-simulator', '--smoke'))
        assert result.returncode == 0
        deadline = time.monotonic() + 10
        while not (root / 'simulator.txt').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (root / 'simulator.txt').read_text() == '--smoke'
        assert not (root / 'trace-enabled.txt').exists(), 'Simulator keeps its independent entry'
        (root / 'dev/run_checks.py').write_text(
            'from pathlib import Path\nimport sys\n'
            'with Path(__file__).resolve().parents[1].joinpath("checks.txt").open("a") as record:\n'
            '    record.write(" ".join(sys.argv[1:]) + "\\n")\n',
            encoding='utf-8')
        checks = root / 'checks.txt'
        result = invoke(root / 'run.cmd', env, ('--check-image-cache',))
        assert result.returncode == 0
        assert checks.read_text().splitlines() == ['--script selfcheck_image_cache', '--script selfcheck_extra_cache']
        checks.unlink()
        result = invoke(root / 'run.cmd', env, ('--check-qt-log',))
        assert result.returncode == 0
        assert checks.read_text().splitlines() == ['--script selfcheck_logging', '--script selfcheck_qt_log']
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
