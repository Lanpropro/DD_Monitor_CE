"""无控制台启动也要保存 Qt 警告与致命错误现场。"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
from PySide6.QtCore import QtMsgType, qInstallMessageHandler, qWarning  # noqa: E402
from ddm import app as app_module  # noqa: E402


def main():
    original_stderr = sys.stderr
    installed = []
    def install(handler):
        installed.append(handler)
        return qInstallMessageHandler(handler)
    with tempfile.TemporaryDirectory() as directory:
        try:
            sys.stderr = None  # pythonw.exe 的运行环境
            previous = qInstallMessageHandler(None)
            with patch.object(app_module.config_module, "REPO", directory), \
                    patch.object(app_module, "qInstallMessageHandler", side_effect=install):
                path = app_module.setup_file_log()
            qWarning("quality switch diagnostic")
            with patch.object(app_module.faulthandler, "dump_traceback") as dump:
                installed[0](QtMsgType.QtFatalMsg, None, "fatal quality switch diagnostic")
                dump.assert_called_once()
                assert dump.call_args.kwargs["all_threads"]
                handle = dump.call_args.kwargs["file"]
            contents = Path(path).read_text(encoding="utf-8")
            assert "[Qt QtWarningMsg] quality switch diagnostic" in contents
            assert "[Qt QtFatalMsg] fatal quality switch diagnostic" in contents
        finally:
            qInstallMessageHandler(previous)
            sys.stderr = original_stderr
            handle.close()
    print("PASS: Qt messages and fatal stack logging without a console")


if __name__ == "__main__":
    main()
