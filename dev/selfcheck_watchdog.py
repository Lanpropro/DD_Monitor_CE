"""自查：界面卡死看门狗 —— 主线程不报平安时，把调用栈写进日志。不联网。"""
import io
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import watchdog  # noqa: E402

LOG = os.path.join(REPO, "work", "watchdog_selfcheck.log")
TIMEOUT = 0.6


def wait_for(predicate, timeout: float = 6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return bool(predicate())


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    if os.path.isfile(LOG):
        os.remove(LOG)

    print("=== 1. 主线程一直在报平安：不写调用栈 ===")
    guard = watchdog.UiWatchdog(LOG, timeout=TIMEOUT)
    assert guard.start() and guard.running
    for _ in range(6):
        guard.tick()
        time.sleep(0.15)
    print(f"  报平安 6 次、共 0.9 秒：写了 {guard.dumps} 次调用栈（应该是 0）")
    assert guard.dumps == 0
    assert not os.path.isfile(LOG), "没卡死就不该动日志文件"

    print("\n=== 2. 主线程停住：阈值之后写出所有线程的调用栈 ===")
    stopped_at = time.time()
    assert wait_for(lambda: guard.dumps == 1), "超过了阈值应该写出调用栈"
    text = io.open(LOG, encoding="utf-8").read()
    print(f"  停住 {time.time() - stopped_at:.1f} 秒后写出，日志 {len(text)} 字")
    print("  日志开头：" + text.strip().splitlines()[0][:60])
    assert watchdog.MARK in text, "调用栈要带醒目的标记，方便在日志里搜"
    assert "selfcheck_watchdog" in text, "写出来的应该是当前线程的调用栈（含本文件）"
    assert "Thread" in text, "要看得到线程名 / 线程号"

    print("\n=== 3. 同一次卡死只写一次（不刷屏） ===")
    time.sleep(2.0)
    print(f"  再等 2 秒：写了 {guard.dumps} 次（还是 1）")
    assert guard.dumps == 1, "同一次卡死只该写一次"

    print("\n=== 4. 缓过来之后再卡一次：会再写一次 ===")
    guard.tick()
    time.sleep(0.4)
    print(f"  报过一次平安：写了 {guard.dumps} 次")
    assert wait_for(lambda: guard.dumps == 2), "缓过来之后再卡死要能再写一次"
    print(f"  第二次卡死：写了 {guard.dumps} 次")

    print("\n=== 5. stop 之后线程收工、不再写 ===")
    guard.stop()
    assert not guard.running
    time.sleep(1.5)
    print(f"  stop 之后：running={guard.running} 写了 {guard.dumps} 次")
    assert guard.dumps == 2

    print("\n=== 6. 日志路径给空：退回 stderr，不炸 ===")
    fallback = watchdog.UiWatchdog("", timeout=TIMEOUT)
    fallback.start()
    assert wait_for(lambda: fallback.dumps == 1), "没有日志文件时也要能写出来"
    fallback.stop()
    print(f"  无日志文件时也写出了 {fallback.dumps} 次（写到 stderr）")

    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
