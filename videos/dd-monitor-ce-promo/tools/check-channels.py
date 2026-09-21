"""验证录屏里 12 拍那一段：左右声道是不是真的"各走各的"。

为什么要测：成片 12 拍要说"左边那路只走左耳、右边那路只走右耳"。
光看设置状态（声道=3/4）不够 —— 万一两路声音最后混在一起，
观众听起来还是"两边一样"，这一拍就白拍了。

做法：把有声窗口的音频拆成 L / R 两个单声道，算三个数：
  · 各自的 RMS（两边都得有声音）
  · 两声道波形的相关系数（越接近 0 越说明是**两个不同的声源**）
  · 交叉相关的峰值（如果在 0 延迟处峰值不高，说明内容真的不同）

用法：
    python tools/check-channels.py --take raw/take.mp4 --start 213 --dur 20
"""
import argparse
import io
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(PROJ)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--take", default=os.path.join(
        "videos", "dd-monitor-ce-promo", "raw", "take.mp4"))
    parser.add_argument("--start", type=float, default=213.0)
    parser.add_argument("--dur", type=float, default=20.0)
    parser.add_argument("--work", default=os.path.join(
        "videos", "dd-monitor-ce-promo", "raw", "channels.wav"))
    args = parser.parse_args()

    if os.path.exists(args.work):
        os.remove(args.work)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{args.start}", "-t", f"{args.dur}", "-i", args.take,
        "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", args.work,
    ], check=True)

    data, rate = sf.read(args.work, always_2d=True)
    left, right = data[:, 0], data[:, 1]

    def rms(signal):
        return float(np.sqrt(np.mean(signal ** 2)))

    def db(value):
        return 20 * np.log10(max(value, 1e-9))

    corr = float(np.corrcoef(left, right)[0, 1]) if len(left) > 1 else 0.0
    # 交叉相关：把右声道平移一点再比，看峰值是否只在 0 延迟处
    window = min(len(left), rate * 5)                 # 取 5 秒足够
    a = left[:window] - left[:window].mean()
    b = right[:window] - right[:window].mean()
    norm = np.sqrt((a ** 2).sum() * (b ** 2).sum())
    xcorr = np.correlate(a, b, mode="full") / (norm if norm else 1.0)
    peak_index = int(np.argmax(np.abs(xcorr)))
    peak_lag = (peak_index - (len(b) - 1)) / rate
    peak_value = float(np.abs(xcorr[peak_index]))
    zero_value = float(np.abs(xcorr[len(b) - 1]))

    print(f"素材：{args.take}  窗口：{args.start:.1f}s + {args.dur:.1f}s")
    print(f"  左声道 RMS {db(rms(left)):6.1f} dBFS   峰值 {db(np.abs(left).max()):6.1f} dBFS")
    print(f"  右声道 RMS {db(rms(right)):6.1f} dBFS   峰值 {db(np.abs(right).max()):6.1f} dBFS")
    print(f"  左右相关系数 {corr:+.3f}（0 附近 = 两个不同声源；+1 = 完全同源）")
    print(f"  交叉相关峰值 {peak_value:.3f} @ {peak_lag*1000:+.0f} ms"
          f"（0 延迟处 {zero_value:.3f}）")
    print()
    ok_l = rms(left) > 1e-4
    ok_r = rms(right) > 1e-4
    ok_diff = abs(corr) < 0.9
    print(f"  两边都有声音：左 {'✓' if ok_l else '✗'}  右 {'✓' if ok_r else '✗'}")
    print(f"  两边不是同一路声音：{'✓' if ok_diff else '✗（相关系数太高，可能混在一起了）'}")
    return 0 if (ok_l and ok_r and ok_diff) else 1


if __name__ == "__main__":
    raise SystemExit(main())
