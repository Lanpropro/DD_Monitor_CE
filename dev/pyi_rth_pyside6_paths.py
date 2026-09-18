"""PyInstaller 运行时钩子：把 PySide6 / shiboken6 目录加进 DLL 搜索路径。

PyInstaller 6.22 + PySide6 6.11 冻出来的 exe，一 `import QtCore` 就报
「DLL load failed while importing QtCore: 找不到指定的程序」。原因不是文件缺失
（`Qt6Core.dll`、`pyside6.abi3.dll` 都在 `_internal/PySide6/` 里，用干净的
Python 手动 `add_dll_directory` 后能正常加载，已验证），而是这两个目录没进
DLL 搜索路径。

运行时钩子比用户代码先跑，所以在这里把**所有可能的位置**都补上：onedir 的
`_MEIPASS`、exe 所在目录、exe 目录下的 `_internal`。同时写一份排查信息到
`ddm-pyinstaller-paths.txt`（在 exe 旁边），出问题时有据可查。
"""
import os
import sys

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

if getattr(sys, "frozen", False):
    try:
        with open(os.path.join(_exe_dir, "ddm-pyinstaller-paths.txt"), "w",
                  encoding="utf-8") as handle:
            handle.write(f"executable={sys.executable}\n")
            handle.write(f"_MEIPASS={getattr(sys, '_MEIPASS', None)}\n")
            handle.write("added:\n" + "".join(f"  {item}\n" for item in _added))
    except OSError:
        pass
