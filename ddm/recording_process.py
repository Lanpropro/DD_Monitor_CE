"""Windows FFmpeg background priority and orphan process ownership."""
import ctypes
import os
import subprocess
import sys

#: FFmpeg 子进程的创建标志（Windows）。
#:   CREATE_NO_WINDOW          —— 别弹控制台窗口
#:   BELOW_NORMAL_PRIORITY_CLASS —— **把录制的优先级压到「低于正常」**：
#:        录制是后台活，用户在打游戏时它不该跟游戏抢 CPU。压一级之后 Windows 会
#:        优先满足前台进程，录制慢一点无所谓（-c copy 下本身几乎不吃 CPU，
#:        真正会抢的是磁盘 IO 和网络，优先级能让调度偏向游戏）。
#: 进程起来之后还会再调一次 `_adopt_process()`：把 CPU 和**磁盘 IO** 一起压到
#: 更低的后台模式，并挂进 Job Object 兜住孤儿进程。
_FFMPEG_FLAGS = 0
if os.name == "nt":                                    # pragma: no cover - 平台分支
    _FFMPEG_FLAGS = subprocess.CREATE_NO_WINDOW | 0x00004000

# --------------------------------------------------------------- Windows 后台化
#
# `BELOW_NORMAL_PRIORITY_CLASS` 只压 CPU；磁盘 IO 优先级还是「正常」，录制写盘
# 照样和前台程序平起平坐。`PROCESS_MODE_BACKGROUND_BEGIN`（后台模式）会把 CPU
# 和 IO 优先级一起降到最低，正是「别影响我打游戏」要的效果。
# 它不能和别的优先级类一起作为**创建标志**传给 CreateProcess，所以在进程起来
# 之后再单独设。

_PROCESS_MODE_BACKGROUND_BEGIN = 0x00100000
_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

_kernel32 = None
_job_handle = None
if os.name == "nt":                                    # pragma: no cover - 平台分支
    try:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # 64 位下句柄是 64 位；不声明 restype，ctypes 会按 int32 截断，句柄就废了。
        _kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        _kernel32.SetInformationJobObject.restype = ctypes.c_int
        _kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        _kernel32.OpenProcess.restype = ctypes.c_void_p
        _kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        _kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        _kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        _kernel32.SetPriorityClass.restype = ctypes.c_int
        _kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        _kernel32.CloseHandle.restype = ctypes.c_int
        _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    except OSError:                                    # pragma: no cover
        _kernel32 = None


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class _IoCounters(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64)]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _ensure_job():
    """建一个「句柄一关就杀光里面进程」的 Job Object，并一直持有句柄。

    句柄**故意不关**：主进程无论怎么退出（正常关闭、崩溃、被任务管理器强杀），
    Windows 都会关掉这个句柄，内核随即杀掉 Job 里剩下的 ffmpeg。没有这层兜底时，
    主进程被强杀就会留下孤儿 ffmpeg 继续录 —— 用户实测过「软件已经关了，后台
    还在录，一路攒到 4.3 GB」。
    """
    global _job_handle
    if _job_handle is not None or _kernel32 is None:
        return _job_handle
    try:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            ctypes.c_void_p(job), _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            _kernel32.CloseHandle(ctypes.c_void_p(job))
            return None
        _job_handle = job
    except OSError:                                    # pragma: no cover
        return None
    return _job_handle


def _adopt_process(process: subprocess.Popen) -> None:
    """把刚起来的 ffmpeg 收进 Job，并把它的 CPU / IO 优先级压到「后台」。

    全是尽力而为：收不进 Job（例如本进程已经在一个不允许嵌套的 Job 里）不影响
    录制，只是少了退出时的兜底。
    """
    if _kernel32 is None:
        return
    access = _PROCESS_SET_INFORMATION | _PROCESS_SET_QUOTA | _PROCESS_TERMINATE
    raw = _kernel32.OpenProcess(access, False, process.pid)
    if not raw:
        return
    handle = ctypes.c_void_p(raw)
    try:
        _kernel32.SetPriorityClass(handle, _PROCESS_MODE_BACKGROUND_BEGIN)
        job = _ensure_job()
        if job:
            _kernel32.AssignProcessToJobObject(ctypes.c_void_p(job), handle)
    except OSError:                                    # pragma: no cover
        pass
    finally:
        _kernel32.CloseHandle(handle)
