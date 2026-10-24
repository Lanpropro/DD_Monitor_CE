"""无控制台启动也要保存 Qt 警告与致命错误现场。"""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
from PySide6.QtCore import QtMsgType, qInstallMessageHandler, qWarning  # noqa: E402
from ddm import diagnostics  # noqa: E402


def main():
    original_stderr = sys.stderr
    with tempfile.TemporaryDirectory() as directory:
        try:
            sys.stderr = None  # pythonw.exe 的运行环境
            previous = qInstallMessageHandler(None)
            session = diagnostics.start(log_dir=directory, level="DEBUG")
            session.install_qt_messages()
            qWarning("quality switch diagnostic")
            session._qt_handler(QtMsgType.QtFatalMsg, None,
                                "fatal quality switch diagnostic")
            contents = session.log_path.read_text(encoding="utf-8")
            crash = session.crash_path.read_text(encoding="utf-8")
            assert "quality switch diagnostic" in contents
            assert "fatal quality switch diagnostic" in contents
            assert "CRITICAL" in contents
            assert "[崩溃] Qt fatal" in crash, crash
        finally:
            qInstallMessageHandler(previous)
            diagnostics.close()
            sys.stderr = original_stderr
    print("PASS: Qt messages and fatal stack logging without a console")


if __name__ == "__main__":
    main()
