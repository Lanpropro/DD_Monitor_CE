"""PyInstaller 运行时钩子：把 PySide6 / shiboken6 目录加进 DLL 搜索路径。

运行时钩子先于应用导入执行，为冻结目录中的绑定库添加 DLL 搜索位置。
开发与发布统一使用 requirements.txt 固定的 Qt 版本；仅 DDM_PYI_DEBUG=1 时写诊断文件。
"""
import os
import sys

if getattr(sys, "frozen", False):
    # Match run.cmd, including the verified cross-screen composition fix.
    os.environ.setdefault("DDM_QTQUICK_DANMAKU", "1")
    os.environ.setdefault("DDM_SETTINGS_PROCESS", "1")

_bases = []
_exe_dir = os.path.dirname(os.path.abspath(sys.executable))
for _candidate in (getattr(sys, "_MEIPASS", None), _exe_dir,
                   os.path.join(_exe_dir, "_internal")):
    if _candidate and _candidate not in _bases:
        _bases.append(_candidate)

_added = []
for _base in _bases:
    for _name in ("shiboken6", "PySide6"):
        _path = os.path.join(_base, _name)
        if os.path.isdir(_path):
            try:
                os.add_dll_directory(_path)
            except (AttributeError, OSError):    # 非 Windows 或路径异常：忽略
                pass
            os.environ["PATH"] = _path + os.pathsep + os.environ.get("PATH", "")
            _added.append(_path)

if getattr(sys, "frozen", False) and os.environ.get("DDM_PYI_DEBUG") == "1":
    # 默认不写文件：发布包里不该多出排查用的东西。要查的时候
    # 设 DDM_PYI_DEBUG=1 跑一次，信息会落在 exe 旁边。
    try:
        with open(os.path.join(_exe_dir, "ddm-pyinstaller-paths.txt"), "w",
                  encoding="utf-8") as handle:
            handle.write(f"executable={sys.executable}\n")
            handle.write(f"_MEIPASS={getattr(sys, '_MEIPASS', None)}\n")
            handle.write("added:\n" + "".join(f"  {item}\n" for item in _added))
    except OSError:
        pass
