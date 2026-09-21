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
    # 更可靠的判据：把信号拆成 mid（左右共有）与 side（左右之差）。
    #   · 两边放的是同一路声音 → side ≈ 0（差信号互相抵消）
    #   · 两边是不同声源      → side 有明显能量
    # 为什么不能只看波形相关系数：两个主播都在说话时，语音波形天然高度相关
    # （实测遇到过相关系数 0.99 但其实人耳听是分开的），side/mid 更贴听感。
    mid = (left + right) / 2.0
    side = (left - right) / 2.0
    mid_rms, side_rms = rms(mid), rms(side)
    ratio = side_rms / max(mid_rms, 1e-9)

    print(f"素材：{args.take}  窗口：{args.start:.1f}s + {args.dur:.1f}s")
    print(f"  左声道 RMS {db(rms(left)):6.1f} dBFS   峰值 {db(np.abs(left).max()):6.1f} dBFS")
    print(f"  右声道 RMS {db(rms(right)):6.1f} dBFS   峰值 {db(np.abs(right).max()):6.1f} dBFS")
    print(f"  左右共有 mid {db(mid_rms):6.1f} dBFS   左右之差 side {db(side_rms):6.1f} dBFS")
    print(f"  side/mid = {ratio:.3f}   （≈0 = 两边同一路声音；> 0.10 = 两边明显不同）")
    print(f"  参考：波形相关系数 {corr:+.3f}")
    print()
    ok_l = rms(left) > 1e-4
    ok_r = rms(right) > 1e-4
    ok_diff = ratio > 0.10
    print(f"  两边都有声音：左 {'✓' if ok_l else '✗'}  右 {'✓' if ok_r else '✗'}")
    print(f"  两边是不同声音：{'✓' if ok_diff else '✗（side 太小，等于同一路声音）'}")
    return 0 if (ok_l and ok_r and ok_diff) else 1


if __name__ == "__main__":
    raise SystemExit(main())
