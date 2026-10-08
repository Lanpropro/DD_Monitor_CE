"""后台用真实 Windows 目录句柄复现解压后 WinError 5，并验证完整更新。"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
from ddm import file_ops, plugin_updates
from ddm.plugins import PluginManager, read_manifest


def main():
    if os.name != "nt":
        print("Skipped: Windows directory sharing test")
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    original = os.replace
    occupied, failures, timers = set(), [], []
    def sharing_lock(source, destination):
        source = Path(source)
        if source.is_dir() and str(source) not in occupied:
            occupied.add(str(source))
            handle = kernel32.CreateFileW(str(source), 0x80000000, 3, None, 3, 0x02000000, None)
            assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
            timer = threading.Timer(.15, kernel32.CloseHandle, args=(handle,))
            timers.append(timer)
            timer.start()
        try:
            return original(source, destination)
        except OSError as error:
            failures.append(error.winerror)
            raise
    with tempfile.TemporaryDirectory(prefix="ddm-plugin-sharing-") as directory:
        root = Path(directory)
        manager = PluginManager(plugins_dir=str(root), enabled=[])
        for plugin_id in ("domestic_live", "global_live"):
            old = root / plugin_id
            old.mkdir()
            (old / "plugin.json").write_text(json.dumps({"id": plugin_id,
                "name": plugin_id, "description": "old", "version": "1.0"}), encoding="utf-8")
            (old / "plugin.py").write_text("# previous installed version", encoding="utf-8")
            (old / "user-data.txt").write_text("keep user data", encoding="utf-8")
        try:
            with patch.object(file_ops.os, "replace", side_effect=sharing_lock):
                for plugin_id in ("domestic_live", "global_live"):
                    package = Path(__file__).resolve().parents[1] / "results" / (plugin_id + "-1.1.zip")
                    plugin_updates.stage(manager, str(package), plugin_id, "1.1")
                    assert read_manifest(str(root / plugin_id), plugin_id)["version"] == "1.0"
                plugin_updates.apply_pending(manager)
            assert not manager.skipped and not plugin_updates.pending_versions(manager)
            for plugin_id in ("domestic_live", "global_live"):
                target = root / plugin_id
                assert read_manifest(str(target), plugin_id)["version"] == "1.1"
                assert (target / "user-data.txt").read_text(encoding="utf-8") == "keep user data"
            assert len(occupied) == 8 and len(failures) >= 8 and set(failures) <= {5, 32, 33}, (occupied, failures)
            # 永久拒绝访问必须抛出原错误，不误报成功；其他错误不重试。
            for code, attempts in ((5, 7), (32, 7), (33, 7), (3, 1)):
                error = OSError("fixture")
                error.winerror = code
                with patch.object(file_ops.os, "replace", side_effect=error) as replace, patch.object(file_ops.time, "sleep"):
                    try:
                        file_ops.replace_directory(root / "missing", root / "destination")
                    except OSError as caught:
                        assert caught is error
                    else:
                        raise AssertionError("Access failure reported as success")
                    assert replace.call_count == attempts
        finally:
            for timer in timers:
                timer.join()
    print("PASS: real Windows sharing denial reproduced; both 1.1 upgrades and data preservation; bounded retry and permanent failure")


if __name__ == "__main__":
    main()
