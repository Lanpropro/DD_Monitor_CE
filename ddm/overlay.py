"""检测注入本进程的第三方图形覆盖层（FPS Monitor / RTSS / 游戏内覆盖等）。

FPS Monitor 这类工具会注入目标进程、hook DXGI 的 Present 来做画面叠加。VLC 用
D3D11 渲染时，两边的生命周期撞在一起，就会在用户机器上出现
``Windows fatal exception: access violation``（2026-09-20 那个新用户机器正是）。

这里只做一件事：把注入进来的可疑模块列出来写进日志，方便排查现场（哪个第三方
工具挂在进程里）。所有调用都吞异常，检测失败不影响启动，也**不改动任何行为**。
"""
import os

#: 已知会 hook 图形管线的覆盖层/注入模块关键字（小写，按模块文件名匹配）
#: FPS Monitor 实测注入的是 ``fps-mon64.dll``（带连字符），所以两种写法都要匹配。
OVERLAY_HINTS = (
    "fps-mon", "fpsmon",                    # FPS Monitor
    "rtss", "rivatuner", "afterburner",     # RivaTuner / MSI Afterburner
    "discord",                              # Discord 覆盖层
    "gameoverlay",                          # Steam 覆盖层
    "nvcamera", "nvspcap",                  # NVIDIA 抓屏
    "obs",                                  # OBS 游戏捕获注入
    "overlay",
)


def module_paths() -> list[str]:
    """枚举本进程已加载的模块路径；失败返回空表。"""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # noqa: BLE001
        return []
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        # 64 位下必须写死签名：HANDLE 当 int 传会被截断，EnumProcessModules 直接失败
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.EnumProcessModules.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE),
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        psapi.EnumProcessModules.restype = wintypes.BOOL
        psapi.GetModuleFileNameExW.argtypes = [
            wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        psapi.GetModuleFileNameExW.restype = wintypes.DWORD

        handle = kernel32.GetCurrentProcess()
        hmods = (wintypes.HMODULE * 2048)()
        needed = wintypes.DWORD(0)
        if not psapi.EnumProcessModules(handle, hmods, ctypes.sizeof(hmods),
                                        ctypes.byref(needed)):
            return []
        count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), 2048)
        paths: list[str] = []
        for index in range(count):
            buf = ctypes.create_unicode_buffer(1024)
            if psapi.GetModuleFileNameExW(handle, hmods[index], buf, 1024):
                paths.append(buf.value)
        return paths
    except Exception:  # noqa: BLE001
        return []


def overlays(paths: list[str] | None = None) -> list[str]:
    """返回命中的覆盖层模块文件名（可能为空）。"""
    hits: list[str] = []
    for path in (module_paths() if paths is None else paths):
        name = os.path.basename(path)
        lowered = name.lower()
        if any(hint in lowered for hint in OVERLAY_HINTS):
            hits.append(name)
    return hits


#: 自家解释器/运行时的模块前缀（不算「注入」）
_OWN_PREFIXES = ("python", "vcruntime", "_ctypes", "_socket", "_ssl", "libffi",
                 "libcrypto", "libssl", "select", "unicodedata", "msvcp", "api-ms")


def foreign_modules(paths: list[str] | None = None) -> list[str]:
    """返回非系统、非自身运行时的模块名 —— 大概率是第三方注入进来的，写日志用。"""
    import sys

    roots: list[str] = []
    for candidate in (getattr(sys, "base_prefix", ""), getattr(sys, "prefix", ""),
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      os.path.dirname(os.path.abspath(sys.executable))):
        if candidate:
            roots.append(os.path.normcase(os.path.abspath(candidate)))

    result: list[str] = []
    for path in (module_paths() if paths is None else paths):
        lowered = path.lower()
        if "\\windows\\" in lowered:
            continue
        name = os.path.basename(path)
        if name.lower().startswith(_OWN_PREFIXES):
            continue
        norm = os.path.normcase(os.path.abspath(path))
        if any(norm.startswith(root) for root in roots):
            continue
        result.append(name)
    return result
