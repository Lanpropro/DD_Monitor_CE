"""DD监控室CE（重写版界面）启动入口。

    python main.py       # 带控制台，日志直接看
    pythonw main.py      # 不带控制台（run.cmd 用这个）

"""
import os
import sys

# Python 3.12 的 WMI 查询可能在导入 aiohttp 时卡住，使用系统版本接口回退。
if sys.platform == "win32":
    import platform

    if not getattr(sys, "frozen", False):
        from pathlib import Path

        # Qt searches PATH for OpenSSL. Prefer the pair shipped with Python.
        openssl_dir = Path(sys.base_prefix) / "DLLs"
        if all((openssl_dir / name).is_file() for name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll")):
            dll_path = os.environ.get("PATH", "")
            if dll_path.split(os.pathsep, 1)[0] != str(openssl_dir):
                os.environ["PATH"] = str(openssl_dir) + os.pathsep + dll_path

    def _skip_wmi_query(*_args):
        raise OSError("WMI metadata queries are disabled in the app process")

    if hasattr(platform, "_wmi_query"):
        platform._wmi_query = _skip_wmi_query

# 旧0.3更新器要求带版本号的入口；该入口只转交到固定名称主程序。
if __name__ == "__main__" and getattr(sys, "frozen", False):
    from pathlib import Path
    entry = Path(sys.executable)
    fixed = entry.with_name("DD监控室CE.exe")
    if entry.name.startswith("DD监控室CE-v") and fixed.is_file():
        import subprocess
        command = [str(fixed), *sys.argv[1:]]
        if len(sys.argv) == 3 and sys.argv[1] in ("--apply-update", "--apply-update-elevated"):
            raise SystemExit(subprocess.call(command, cwd=entry.parent))
        subprocess.Popen(command, cwd=entry.parent)
        raise SystemExit(0)

if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--apply-update":
    from ddm.update_install import run_helper
    raise SystemExit(run_helper(sys.argv[2]))

if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--apply-update-elevated":
    from ddm.update_install import run_elevated_helper
    raise SystemExit(run_elevated_helper(sys.argv[2]))

if __name__ == "__main__" and sys.argv[1:] == ["--settings-worker"]:
    from ddm.native_diagnostics import start_worker
    start_worker(os.environ.get('DDM_DIAGNOSTIC_LOG_DIR'))
    from ddm.settings_process import run_worker
    raise SystemExit(run_worker())

if __name__ == "__main__" and sys.argv[1:2] == ["--plugin-worker"]:
    if len(sys.argv) != 4:
        raise SystemExit('Usage: --plugin-worker DIRECTORY MODULE')
    from ddm.plugin_worker import run_worker
    raise SystemExit(run_worker(sys.argv[2], sys.argv[3]))

PROJ = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJ)                       # 配置、日志、头像缓存都按这个目录算
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

from ddm import config           # noqa: E402

try:
    config.initialize_paths()
except (OSError, ValueError) as error:
    if __name__ == "__main__":
        import tempfile
        import traceback
        from ddm import diagnostics
        diagnostics.start(os.path.join(tempfile.gettempdir(), 'DDMonitorCE-startup-logs'))
        traceback.print_exc()
    from PySide6.QtWidgets import QApplication, QMessageBox
    _error_app = QApplication(sys.argv)
    QMessageBox.critical(None, '无法打开数据目录', str(error))
    raise SystemExit(1)

if __name__ == "__main__":
    from ddm import diagnostics
    diagnostics.start(os.path.join(config.data_root(), 'logs'))

from ddm.app import main         # noqa: E402


if __name__ == "__main__":
    startup_diagnostics = None
    if not getattr(sys, 'frozen', False) and not sys.argv[1:]:
        from pathlib import Path
        from ddm.diagnostic_startup_request import consume
        try:
            request = consume(Path(PROJ))
        except OSError as error:
            print(f"[MCP 诊断] 无法读取启动请求：{error}", file=sys.stderr, flush=True)
        else:
            if request is not None:
                from importlib import import_module
                try:
                    install = import_module('dev.startup_diagnostics').install
                    startup_diagnostics = install(Path(PROJ), Path(config.data_root()) / 'logs', request)
                except (ImportError, OSError, RuntimeError) as error:
                    print(f"[MCP 诊断] 无法启用 {request['mode']}：{error}", file=sys.stderr, flush=True)
                else:
                    print(f"[MCP 诊断] 已启用 {request['mode']}，请求 {request['request_id']}",
                          file=sys.stderr, flush=True)
    raise SystemExit(main(startup_diagnostics=startup_diagnostics))
