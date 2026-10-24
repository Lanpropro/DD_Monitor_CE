"""自检：诊断日志的镜像、级别、轮转、异常钩子与脱敏。不联网。"""
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ddm import diagnostics  # noqa: E402


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main() -> None:
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    directory = Path(tempfile.mkdtemp(prefix="ddm-logging-"))
    try:
        assert diagnostics.MAX_BYTES == 5 * 1024 * 1024
        assert diagnostics.BACKUP_COUNT == 5
        assert diagnostics.RETENTION_DAYS == 14
        session = diagnostics.start(log_dir=directory, level="DEBUG")
        assert diagnostics.start(log_dir=directory) is session, "start() 必须幂等"

        print("镜像标准输出")
        print("镜像标准错误", file=sys.stderr)
        logger = diagnostics.get_logger("selfcheck")
        logger.debug("debug detail")
        logger.warning("warning detail")
        session.log_system_info({"cpu": "selfcheck-cpu", "gpu": "selfcheck-gpu"})
        token = "SESSDATA=very-secret"
        query = "https://example.invalid/live.m3u8?sign=secret-sign&t=1"
        cookie = "Cookie: SESSDATA=very-secret; bili_jct=csrf-secret"
        authorization = "Authorization: Bearer auth-secret"
        proxy = "Proxy-Authorization: Basic proxy-secret"
        logger.error("credential %s url %s", token, query)
        logger.error("%s", cookie)
        logger.error("%s", authorization)
        logger.error("%s", proxy)
        home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
        if home:
            logger.info("home path %s", os.path.join(home, "DDMonitor"))

        stdout_mirror = session._stdout_mirror
        stdout_mirror.flush()
        stderr_mirror = session._stderr_mirror
        stderr_mirror.flush()
        text = read(session.log_path)
        assert "镜像标准输出" in text and "镜像标准错误" in text, text
        assert "DEBUG" in text and "debug detail" in text
        assert "system_info cpu=selfcheck-cpu" in text
        assert "very-secret" not in text and "secret-sign" not in text
        assert "csrf-secret" not in text and "auth-secret" not in text, text
        assert "proxy-secret" not in text, text
        assert "Cookie: <redacted>" in text, text
        assert "Authorization: <redacted>" in text, text
        assert "Proxy-Authorization: <redacted>" in text, text
        assert "<redacted>" in text, text
        if home:
            assert home not in text, "用户目录必须脱敏"

        original_hook = sys.excepthook
        try:
            raise RuntimeError("uncaught-selfcheck")
        except RuntimeError:
            original_hook(*sys.exc_info())
        text = read(session.log_path)
        assert "uncaught_exception" in text and "uncaught-selfcheck" in text

        def fail_in_thread() -> None:
            raise ValueError("thread-selfcheck")

        thread = threading.Thread(target=fail_in_thread, name="selfcheck-boom")
        thread.start()
        thread.join()
        text = read(session.log_path)
        assert "thread_exception" in text and "thread-selfcheck" in text, text
        assert "selfcheck-boom" in text

        session.dump_crash("selfcheck crash")
        crash = read(session.crash_path)
        assert "[崩溃]" in crash and "selfcheck crash" in crash

        with session.phase("selfcheck_phase"):
            pass
        try:
            with session.phase("selfcheck_failure"):
                raise KeyError("phase-selfcheck")
        except KeyError:
            pass
        text = read(session.log_path)
        assert "phase=selfcheck_phase" in text and "phase=selfcheck_failure" in text
        assert "phase-selfcheck" in text
        info = diagnostics.collect_system_info()
        assert info.get("system"), "系统信息至少要有系统名"
        assert info.get("cpu_logical", 0) >= 1, "应记录逻辑 CPU 数量"
        assert info.get("python") == sys.version.split()[0]
        session.log_system_info(info)
        text = read(session.log_path)
        assert "system_info system=" in text, "完整系统信息要进入日志"
        assert "cpu_logical=" in text
        original_gpu = diagnostics._registry_gpu_details
        diagnostics._registry_gpu_details = lambda: (_ for _ in ()).throw(
            RuntimeError("collector-selfcheck"))
        try:
            partial = diagnostics.collect_system_info()
        finally:
            diagnostics._registry_gpu_details = original_gpu
        assert partial.get("system"), "单项采集失败仍要返回基础系统信息"
        text = read(session.log_path)
        assert "system_info_collector_failed collector=gpu_registry" in text, text

        # 轮转：不真正写 5 MiB，直接用小上限验证历史文件命名和保留数量。
        logger.info("rotation marker")
        session.close()
        assert sys.stdout is original_stdout and sys.stderr is original_stderr
        diagnostics.close()

        rotated_dir = directory / "rotated"
        rotated_dir.mkdir()
        rotation = diagnostics.LogSession(rotated_dir, logging.INFO)
        handler = next(item for item in rotation._handlers
                       if isinstance(item, logging.handlers.RotatingFileHandler))
        handler.maxBytes = 200
        handler.backupCount = 2
        rotation._logger.info("x" * 300)
        rotation._logger.info("y" * 300)
        rotation._logger.info("z" * 300)
        rotation.close()
        backups = sorted(path.name for path in rotated_dir.glob("ddm.log.*"))
        assert backups == ["ddm.log.1", "ddm.log.2"], backups

        expired_dir = directory / "expired"
        expired_dir.mkdir()
        old = expired_dir / "ddm-2020-01-01.log"
        old.write_text("old", encoding="utf-8")
        old_time = 1_600_000_000
        os.utime(old, (old_time, old_time))
        cleanup = diagnostics.LogSession(expired_dir, logging.INFO)
        cleanup.close()
        assert not old.exists(), "过期的旧日志应被清理"

        print(json.dumps({"status": "PASS", "demo_log": str(directory / diagnostics.LOG_NAME)},
                         ensure_ascii=False))
    finally:
        diagnostics.close()
        sys.stdout, sys.stderr = original_stdout, original_stderr
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    main()
