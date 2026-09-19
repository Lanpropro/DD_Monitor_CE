"""界面卡死看门狗：主线程长时间不响应，就把所有线程的调用栈写进日志。

背景：有用户反馈「鼠标一到关注列表卡片上，预览不出来、窗口卡死也不退出」。
这种卡死多半发生在某个阻塞的 C 调用里（libvlc 的 stop / set_hwnd / release、
原生窗口之间的消息往返……），现场没有崩溃转储，日志又只写到最后一个 print
就断了 —— 光看日志没法判断主线程到底停在哪一行。

做法：主线程里放一个 QTimer 定期调 ``tick()`` 报平安，另起一条守护线程盯着
这个时间戳。超过 ``timeout`` 秒没报平安，就用 faulthandler 把所有线程的
Python 调用栈追加到日志里（同一次卡死只写一次；恢复之后再卡会再写一次）。
看门狗只读调用栈、不碰界面，自己也不会被卡住 —— 主线程恢复后照常工作。
"""
import faulthandler
import os
import sys
import threading
import time

DEFAULT_TIMEOUT = 8.0            # 主线程多久没报平安算卡死
TICK_MS = 500                    # 主线程报平安的间隔（给 QTimer 用）
CHECK_INTERVAL = 1.0             # 看门狗自己检查的间隔
MARK = "[卡死]"                  # 日志里的标记，方便直接搜


class UiWatchdog:
    """盯主线程心跳的看门狗。``start()`` 之后线程一直活着，直到 ``stop()``。"""

    def __init__(self, log_path: str = "", timeout: float = DEFAULT_TIMEOUT):
        self.log_path = log_path or ""
        self.timeout = float(timeout)
        self._last_tick = time.monotonic()
        self._reported = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._handle = None
        self._lock = threading.Lock()
        self.dumps = 0                       # 写过几次调用栈（自检要看）

    # ---- 生命周期 ----
    def start(self) -> bool:
        if self._running:
            return True
        self._last_tick = time.monotonic()
        self._reported = False
        self._running = True
        self._thread = threading.Thread(target=self._watch, name="ddm-watchdog",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass

    @property
    def running(self) -> bool:
        return self._running

    # ---- 主线程报平安 ----
    def tick(self) -> None:
        self._last_tick = time.monotonic()
        if self._reported:
            self._reported = False           # 缓过来了，下一次卡死可以再报

    # ---- 看门狗线程 ----
    def _watch(self) -> None:
        while self._running:
            time.sleep(CHECK_INTERVAL)
            if not self._running:
                return
            stalled = time.monotonic() - self._last_tick
            if stalled < self.timeout or self._reported:
                continue
            self._reported = True
            self._dump(stalled)

    def _dump(self, stalled: float) -> None:
        handle = self._open()
        if handle is None:
            return
        try:
            handle.write(f"\n{MARK} 界面 {stalled:.1f} 秒没有响应，"
                         f"下面是所有线程此刻的调用栈"
                         f"（{time.strftime('%Y-%m-%d %H:%M:%S')}）：\n")
            handle.flush()
            faulthandler.dump_traceback(file=handle, all_threads=True)
            handle.write(f"{MARK} 调用栈结束\n")
            handle.flush()
            self.dumps += 1
        except Exception as error:  # noqa: BLE001
            print(f"{MARK} 写调用栈失败: {error}", file=sys.stderr, flush=True)

    def _open(self):
        if self._handle is not None:
            return self._handle
        if not self.log_path:
            return sys.stderr if hasattr(sys.stderr, "fileno") else None
        try:
            directory = os.path.dirname(self.log_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with self._lock:
                if self._handle is None:
                    self._handle = open(self.log_path, "a", encoding="utf-8",
                                        buffering=1)
                return self._handle
        except Exception as error:  # noqa: BLE001
            print(f"{MARK} 打不开日志 {self.log_path}: {error}",
                  file=sys.stderr, flush=True)
            return None


#: 全局那一个：main() 启动它，主线程用 QTimer 定期 tick()
WATCHDOG = UiWatchdog()


def start(log_path: str = "", timeout: float = DEFAULT_TIMEOUT) -> UiWatchdog:
    WATCHDOG.log_path = log_path or ""
    WATCHDOG.timeout = float(timeout)
    WATCHDOG.start()
    return WATCHDOG


def tick() -> None:
    WATCHDOG.tick()


def stop() -> None:
    WATCHDOG.stop()
