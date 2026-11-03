"""DD监控室CE（重写版界面）启动入口。

    python main.py       # 带控制台，日志直接看
    pythonw main.py      # 不带控制台（run.cmd 用这个）

"""
import os
import sys

# Python 3.12 的 WMI 查询可能在导入 aiohttp 时卡住，使用系统版本接口回退。
if sys.platform == "win32":
    import platform

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
    from ddm.settings_process import run_worker
    raise SystemExit(run_worker())

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
    from ddm.diagnostic_session import requested_mode, install as install_diagnostic_session
    diagnostic_mode = requested_mode(sys.argv[1:])
    if diagnostic_mode:
        install_diagnostic_session(diagnostic_mode, os.path.join(config.data_root(), 'logs'))
    else:
        if '--diagnose-douyu' in sys.argv or '--diagnose-douyu-deep' in sys.argv:
            from ddm.douyu_diagnostics import install as install_douyu_diagnostics
            install_douyu_diagnostics(os.path.join(config.data_root(), 'logs', 'douyu-playback.jsonl'),
                                     deep='--diagnose-douyu-deep' in sys.argv)
        if os.environ.get('DDM_THEME_CAPTURE') == '1':
            from ddm.responsiveness import install_theme_capture, install_theme_animation_capture
            theme_probe = install_theme_capture(os.path.join(config.data_root(), 'logs', 'theme-switch.jsonl'),
                                               profile_calls='--diagnose-responsiveness' in sys.argv)
            install_theme_animation_capture(theme_probe)
        if os.environ.get('DDM_FULLSCREEN_CAPTURE') == '1' or '--diagnose-fullscreen' in sys.argv:
            from ddm.fullscreen_diagnostics import install as install_fullscreen_capture
            install_fullscreen_capture(os.path.join(config.data_root(), 'logs', 'fullscreen.jsonl'),
                                       profile_calls='--diagnose-fullscreen' in sys.argv)
        if '--diagnose-responsiveness' in sys.argv:
            from ddm.responsiveness import install
            install(os.path.join(config.data_root(), 'logs', 'responsiveness.jsonl'))
        elif os.environ.get('DDM_FOLDER_MOTION_CAPTURE') == '1':
            from ddm.responsiveness import install_folder_capture
            install_folder_capture(os.path.join(config.data_root(), 'logs', 'folder-motion.jsonl'))
    raise SystemExit(main())
