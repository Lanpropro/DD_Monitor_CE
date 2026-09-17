"""试听：把 VLC 的几种声道模式逐个放一遍，用耳朵确认哪个真的只出左/右。

背景：这台机器上「只播左声道 / 只播右声道」到底有没有用，没法靠录音判定
（环回抓到的左右两路内容总是一样）。所以这个脚本把差异做得非常夸张：

    左声道 = 440Hz 低音，右声道 = 3520Hz 高音

改由人耳判断最可靠：
  - 只有低音        -> 这一档真的只出左声道
  - 只有高音        -> 这一档真的只出右声道
  - 低音+高音都在   -> 这一档没用（还是立体声）

用法（先戴上耳机，把音量调小）：
    python dev\\audition_channels.py           # 逐个播，每档之间有提示
    python dev\\audition_channels.py 3         # 只试第 3 档（只播左声道）

退出码为 0 表示脚本正常跑完，不代表哪一档有效——结论靠你听。
"""
import math
import os
import struct
import sys
import tempfile
import time
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("PYTHON_VLC_LIB_PATH", os.path.join(REPO, "libvlc.dll"))

import vlc  # noqa: E402

RATE = 48000
LEFT_HZ = 440        # 低音 = 左声道的内容
RIGHT_HZ = 3520      # 高音 = 右声道的内容
SECONDS = 6

MODES = [
    (0, "默认（跟随片源）"),
    (3, "只播左声道"),
    (4, "只播右声道"),
    (1, "原声"),
    (2, "反向立体声"),
    (5, "杜比音效"),
]


def make_probe(path: str) -> None:
    """左低音、右高音，两路幅度都拉满，差异一听就出来。"""
    with wave.open(path, "w") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        frames = bytearray()
        for index in range(RATE * SECONDS):
            left = int(20000 * math.sin(2 * math.pi * LEFT_HZ * index / RATE))
            right = int(20000 * math.sin(2 * math.pi * RIGHT_HZ * index / RATE))
            frames += struct.pack("<hh", left, right)
        handle.writeframes(bytes(frames))


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass

    wanted = None
    if len(argv) > 1:
        try:
            wanted = int(argv[1])
        except ValueError:
            print(f"用法: {os.path.basename(__file__)} [模式编号]\n"
                  f"模式: {', '.join(str(v) for v, _ in MODES)}")
            return 2
        if wanted not in [value for value, _ in MODES]:
            print(f"模式编号只能是: {', '.join(str(v) for v, _ in MODES)}")
            return 2

    path = os.path.join(tempfile.gettempdir(), "ddm_audition.wav")
    make_probe(path)

    instance = vlc.Instance("--no-video-title-show", "--quiet")
    player = instance.media_player_new()
    player.audio_set_volume(45)

    print(f"测试音：左声道 {LEFT_HZ}Hz（低音） / 右声道 {RIGHT_HZ}Hz（高音）")
    print("每档播约 4 秒。听清是「只有低音」「只有高音」还是「两个都有」。")
    print("把音量调小一点再继续。\n")
    time.sleep(1.5)

    for value, label in MODES:
        if wanted is not None and value != wanted:
            continue
        media = instance.media_new(path)
        player.set_media(media)
        player.play()
        # 关键：要在播放起来之后再设，play() 之前设会被音频输出模块初始化冲掉
        time.sleep(1.0)
        player.audio_set_channel(value)
        print(f"  [{value}] {label} ... 正在播（约 4 秒）")
        time.sleep(4.0)
        player.stop()
        time.sleep(0.6)

    player.release()
    instance.release()
    print("\n播完了。哪几档能分开左右，就把结论告诉我：")
    print("  - 能分开的档位编号")
    print("  - 如果都没有一档能分开，我就得换别的实现（进程内改音频采样）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
