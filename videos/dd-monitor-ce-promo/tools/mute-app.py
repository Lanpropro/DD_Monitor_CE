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
        print("用法: python mute-app.py <进程名关键字> <mute|unmute|status>")
        return 1
    key, action = sys.argv[1].lower(), sys.argv[2].lower()
    hit = 0
    for s in sessions():
        try:
            name = s.Process.name()
        except Exception:
            continue
        if key not in name.lower():
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
        print(f"没找到名字含「{key}」的音频会话（程序没在出声时不会创建会话）")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
