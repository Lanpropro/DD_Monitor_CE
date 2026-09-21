"""拖动期间把鼠标滚轮借过来（Windows 低级鼠标钩子 WH_MOUSE_LL）。

Windows 上 Qt 的 ``QDrag::exec()`` 走的是 OLE ``DoDragDrop``，那个模态循环期间
滚轮不再派发给 Qt 控件（这不是 Qt 的 bug，是拖放 API 的性质：D+D 期间没有可识别
的焦点，D+D 事件也不报告滚轮运动）。``WH_MOUSE_LL`` 是**系统在消息入队前**回调的，
不经过那条循环，所以拖动的时候能把滚轮接住。

安全约定（很重要）：
  - 只在拖动那一下 start()、松手立刻 stop()，平时不装；
  - 回调里**永远** CallNextHookEx 放行，只读不吃，对别的程序零影响；
  - 任何一步失败都静默降级（返回 False）—— 拖动和"贴边自动滚"照常工作。
"""
import ctypes
import os

WH_MOUSE_LL = 14
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
HC_ACTION = 0
#: 滚轮一格；高精度滚轮/触控板的 delta 是它的整数倍（可能带小数）
WHEEL_DELTA = 120


def _load():
    """把 user32 的签名填好；非 Windows 或失败返回 None。"""
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class MouseHookStruct(ctypes.Structure):
            _fields_ = [("pt", wintypes.POINT),
                        ("mouseData", wintypes.DWORD),
                        ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_void_p)]

        result = ctypes.c_ssize_t
        proc = ctypes.WINFUNCTYPE(result, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # 64 位下必须写死签名：HHOOK 当 int 传会被截断，Unhook 就会失败、钩子残留
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, proc,
                                            wintypes.HANDLE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = result
        return user32, MouseHookStruct, proc
    except Exception:  # noqa: BLE001
        return None


class WheelHook:
    """拖动期间临时收滚轮；用法 ``hook.start()`` ... ``hook.stop()``。

    ``on_wheel(delta)`` 在**主线程**被回调（钩子装在主线程，系统通过它的消息循环
    投递），delta 正数=往上滚。装了以后 ``active`` 为 True。
    """

    def __init__(self, on_wheel=None):
        self._on_wheel = on_wheel
        self._hook = None
        self._callback = None
        self._struct = None          # MSLLHOOKSTRUCT 类型；自检要拿它造样本

    @property
    def active(self) -> bool:
        return self._hook is not None

    def start(self) -> bool:
        if self._hook is not None:
            return True
        loaded = _load()
        if loaded is None or self._on_wheel is None:
            return False
        user32, mouse_hook_struct, proc = loaded
        self._struct = mouse_hook_struct

        def _proc(code, wparam, lparam):            # noqa: ANN001, ANN202
            self._dispatch(code, wparam, lparam)
            # 只读不吃：一定放行，免得影响别的程序
            return user32.CallNextHookEx(None, code, wparam, lparam)

        try:
            callback = proc(_proc)
            handle = user32.SetWindowsHookExW(WH_MOUSE_LL, callback, None, 0)
        except Exception:                           # noqa: BLE001
            return False
        if not handle:
            return False
        self._callback = callback        # 必须留引用：被 GC 掉钩子就失效了
        self._hook = handle
        return True

    def _dispatch(self, code, wparam, lparam) -> int:
        """钩子回调的解析部分。

        单独抽出来是为了自检能直接喂它一个造出来的 MSLLHOOKSTRUCT —— 真实拖动时
        发系统级滚轮会干扰桌面，没必要。
        """
        if self._struct is None or code != HC_ACTION:
            return 0
        if wparam not in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            return 0
        try:
            data = ctypes.cast(ctypes.c_void_p(lparam),
                               ctypes.POINTER(self._struct)).contents
            delta = ctypes.c_short((data.mouseData >> 16) & 0xFFFF).value
        except Exception:  # noqa: BLE001
            return 0
        if delta and self._on_wheel is not None:
            self._on_wheel(delta)
        return delta

    def stop(self) -> None:
        handle, self._hook = self._hook, None
        self._callback = None
        if not handle:
            return
        loaded = _load()
        if loaded is None:
            return
        try:
            loaded[0].UnhookWindowsHookEx(handle)
        except Exception:  # noqa: BLE001
            pass
