"""按进程静音/取消静音某个程序的音频会话（Windows Core Audio）。

为什么需要它：软件的画面墙里格子显示「已静音」，但实测它仍在出声
（关掉软件后回环电平从 -32dB 掉到 -91dB，即数字静音，证明声源就是它）。
录制宣传片时这个声音会一直响，所以要按程序把它的音频会话掐掉 —— 而不是掐整个
输出设备，那样会连累用户正在用的其他程序。

用法：
    python mute-app.py <进程名关键字> <mute|unmute|status>
"""

import sys

from pycaw.pycaw import AudioUtilities


def sessions():
    for s in AudioUtilities.GetAllSessions():
        if s.Process is None:
            continue
        yield s


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: python mute-app.py <进程名关键字|pid:1234> <mute|unmute|status>")
        return 1
    key, action = sys.argv[1].lower(), sys.argv[2].lower()

    # 目标既可以是「进程名关键字」也可以是「pid:1234」。
    # 为什么一定要支持 PID：这台机器上同时开着好几个 pythonw（软件本体、探测脚本、
    # 驱动脚本……），按名字找会**同时命中好几个会话**（实测同一进程名有的 MUTED
    # 有的 unmuted），解静音可能落到别的会话上 —— 录出来的"要出声"那两拍就是死的。
    want_pid = None
    if key.startswith("pid:"):
        try:
            want_pid = int(key[4:])
        except ValueError:
            print(f"pid 解析失败：{key}")
            return 1

    hit = 0
    for s in sessions():
        try:
            pid = int(s.ProcessId)
            name = s.Process.name()
        except Exception:
            continue
        if want_pid is not None:
            if pid != want_pid:
                continue
        elif key not in name.lower():
            continue
        vol = s.SimpleAudioVolume
        if action == "mute":
            vol.SetMute(1, None)
        elif action == "unmute":
            vol.SetMute(0, None)
        state = "MUTED" if vol.GetMute() else "unmuted"
        print(f"{name} (pid {s.ProcessId}) -> {state}")
        hit += 1
    if hit == 0:
        what = f"pid {want_pid}" if want_pid is not None else f"名字含「{key}」"
        print(f"没找到 {what} 的音频会话（程序没在出声时不会创建会话）")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
