"""Execute Windows launchers: UTF-8 output, spaced paths and exit codes."""
import os
from pathlib import Path
import subprocess
import tempfile
import time


REPO = Path(__file__).resolve().parent.parent


def invoke(script, env):
    return subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                           script.name], input=b"\r\n", capture_output=True,
                          cwd=script.parent, env=env, timeout=15)


def main():
    with tempfile.TemporaryDirectory(prefix="DDM 启动测试 ") as directory:
        root = Path(directory)
        env = dict(os.environ, PYTHONIOENCODING="gbk", PYTHONUTF8="0")
        # Each launcher must override the incoming console encoding.
        for name in ("run-console.cmd", "run.cmd"):
            data = (REPO / name).read_bytes()
            assert not data.startswith(b"\xef\xbb\xbf")
            assert data.count(b"\r\n") == data.count(b"\n")
            (root / name).write_bytes(data)
        (root / "main.py").write_text(
            'from pathlib import Path\n'
            'import sys\n'
            'print("中文启动正常", flush=True)\n'
            'Path(__file__).with_name("started.txt").write_text("启动成功", encoding="utf-8")\n'
            'sys.exit(7)\n', encoding="utf-8")
        result = invoke(root / "run-console.cmd", env)
        text = result.stdout.decode("utf-8")
        assert result.returncode == 7, (result.returncode, text, result.stderr)
        assert "中文启动正常" in text and "程序已退出，退出码：7。" in text
        assert (root / "started.txt").read_text(encoding="utf-8") == "启动成功"
        (root / "started.txt").unlink()
        result = invoke(root / "run.cmd", env)
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 10
        while not (root / "started.txt").exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (root / "started.txt").read_text(encoding="utf-8") == "启动成功"
        # Missing interpreter errors must also be readable and report failure.
        for name in ("run.cmd", "run-console.cmd"):
            text = (root / name).read_text(encoding="utf-8").replace(
                "F:\\CodexAppManager\\Code\\DD_Monitor-venv\\Scripts\\",
                str(root / "missing") + "\\")
            (root / name).write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
            result = invoke(root / name, env)
            assert result.returncode == 1
            assert "没找到 Python 解释器" in result.stdout.decode("utf-8")
    print("Windows launchers: UTF-8, console/pythonw, spaced Chinese paths and errors passed")


if __name__ == "__main__":
    main()
