"""用 WASAPI 回环抓「正在播放的声音」，写 WAV。只抓软件自己的声音 ——
用户已把其他软件静音，所以默认输出设备上的混音就等于 DD监控室CE 的声音。

为什么不用 ffmpeg：dshow 没有立体声混音/回环设备（虚拟声卡端点被停用，
又没有管理员权限启用）。soundcard 走 WASAPI 原生回环，不需要任何额外设备。

用法：
    python loopback-rec.py <输出wav> <秒数> [设备名子串]
"""

import sys
import wave

import numpy as np
import soundcard as sc

SR = 48000


def pick(name_hint: str | None):
    if name_hint:
        for m in sc.all_microphones(include_loopback=True):
            if m.isloopback and name_hint in m.name:
                return m
        raise SystemExit(f"没找到名字含「{name_hint}」的回环设备")
    spk = sc.default_speaker()
    return sc.get_microphone(spk.name, include_loopback=True)


def main() -> int:
    out, secs = sys.argv[1], float(sys.argv[2])
    hint = sys.argv[3] if len(sys.argv) > 3 else None
    mic = pick(hint)
    print(f"回环设备: {mic.name}", flush=True)

    frames = int(secs * SR)
    data = mic.record(samplerate=SR, numframes=frames, channels=2)
    mono = data.mean(axis=1)
    rms = float(np.sqrt(np.mean(mono**2)))
    peak = float(np.max(np.abs(mono)))

    pcm = np.clip(data * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

    print(f"写出 {out}  时长 {len(pcm)/SR:.2f}s")
    print(f"回环电平: RMS {rms:.5f}  峰值 {peak:.5f}  ({20*np.log10(max(rms,1e-9)):.1f} dBFS)")
    print("判定: " + ("有信号 ✓" if rms > 1e-4 else "静音 —— 软件当前没出声，或输出设备不是默认设备"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
