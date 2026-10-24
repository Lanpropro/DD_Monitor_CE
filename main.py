"""DD监控室CE（重写版界面）启动入口。

    python main.py       # 带控制台，日志直接看
    pythonw main.py      # 不带控制台（run.cmd 用这个）

日志必须在导入 Qt、mpv 和业务模块之前建立，否则这些依赖导入失败时没有现场。
"""
import os
from pathlib import Path
import sys

# Python 3.12 的 WMI 查询可能在导入 aiohttp 时卡住，使用系统版本接口回退。
if sys.platform == "win32":
    import platform

    def _skip_wmi_query(*_args):
        raise OSError("WMI metadata queries are disabled in the app process")

    if hasattr(platform, "_wmi_query"):
        platform._wmi_query = _skip_wmi_query

def _program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROJ = _program_dir()
os.chdir(PROJ)                       # 配置、日志、头像缓存都按这个目录算
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

from ddm import diagnostics       # noqa: E402


def _is_first_run() -> bool:
    return not (PROJ / "utils" / "config.json").is_file()


def _run() -> int:
    session = diagnostics.start(argv=sys.argv)
    logger = diagnostics.get_logger("bootstrap")
    try:
        with session.phase("bootstrap"):
            session.log_startup_context(first_run=_is_first_run(), argv=sys.argv)
            # 旧0.3更新器要求带版本号的入口；该入口只转交到固定名称主程序。
            if getattr(sys, "frozen", False):
                entry = Path(sys.executable)
                fixed = entry.with_name("DD监控室CE.exe")
                if entry.name.startswith("DD监控室CE-v") and fixed.is_file():
                    import subprocess
                    command = [str(fixed), *sys.argv[1:]]
                    if len(sys.argv) == 3 and sys.argv[1] == "--apply-update":
                        raise SystemExit(subprocess.call(command, cwd=entry.parent))
                    subprocess.Popen(command, cwd=entry.parent)
                    raise SystemExit(0)
            if len(sys.argv) == 3 and sys.argv[1] == "--apply-update":
                with session.phase("update_helper"):
                    from ddm.update_install import run_helper
                    return run_helper(sys.argv[2])
            if sys.argv[1:] == ["--settings-worker"]:
                with session.phase("settings_worker"):
                    from ddm.settings_process import run_worker
                    return run_worker()

        with session.phase("import_app"):
            from ddm.app import main
        return main(sys.argv)
    except SystemExit:
        raise
    except BaseException as error:
        phase = session.failed_phase or "bootstrap"
        logger.critical("[启动失败] phase=%s reason=%s:%s log=%s",
                        phase, type(error).__name__, error,
                        session.log_path, exc_info=True)
        detail = f"{type(error).__name__}: {error}"
        try:
            diagnostics.show_startup_failure(
                f"启动阶段失败：{phase}\n{detail}\n\n"
                "请把日志文件提供给开发者以便排查。", str(session.log_path))
        except Exception:  # noqa: BLE001 - 提示失败不能再掩盖原始启动异常
            logger.exception("event=startup_failure_notice_failed phase=%s", phase)
        return 1
    finally:
        diagnostics.close()


if __name__ == "__main__":
    raise SystemExit(_run())
