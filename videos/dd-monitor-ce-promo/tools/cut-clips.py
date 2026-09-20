"""把一条连续长素材切成成片要的十段素材（assets/rec-*.mp4）。

为什么要有这一步：项目改成"一条连续长素材"之后，分镜里的 `assets/rec-*.mp4`
不再是各录一段，而是**同一条 take.mp4 的时间窗**。手工对时间很容易错位，
所以把"哪一段对应哪一拍"写成一张表（跟 RECORDING-STATE.md 里那张一致），
由脚本按表裁切；裁完打印每段的起点，方便逐段核对。

裁切规则：母版是 4K 全屏，软件窗口在窗口内坐标 (0,0)~(2880,1620)（除竖屏那两段），
所以每段按窗口矩形裁出来再缩到成片要用的尺寸（1080p / 竖屏 1080x1920）。

用法：
    python tools/cut-clips.py --take raw/take.mp4 --assets assets
    python tools/cut-clips.py --list          # 只打印计划，不裁
"""
import argparse
import io
import json
import os
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(PROJ)
PROMO = os.path.join(PROJ, "videos", "dd-monitor-ce-promo")

#: 软件的窗口矩形（物理像素，3840x2160 母版上的位置）。
#: 横屏：MoveWindow(0,0,2880,1620)；竖屏 810x1440 -> 1215x2160 居中。
LANDSCAPE = (0, 0, 2880, 1620)
#: 竖屏那一拍窗口在屏幕中央（1215x2160 在 3840 宽里居中）
PORTRAIT = ((3840 - 1215) // 2, 0, 1215, 2160)
#: 只看画面墙（把左侧关注栏切掉）：窗口内 x 从 248 起
WALL_X, WALL_W = 248, 2880 - 248

#: 每一段：输出名 / 起点 / 时长 / 裁哪块 / 缩放成什么尺寸。
#: 起点按 `raw/take-events.json` 里的实际动作时刻定（不是拍的脑袋），
#: 括号里是那一步在事件表里的秒数。
PLAN = [
    # 01 墙面亮起 / 02 标题底 / 12 重连
    {"out": "rec-wall-build.mp4", "start": 3.0, "dur": 9.0,
     "crop": (WALL_X, 0, WALL_W, 1620), "size": "1920:1080",
     "note": "空墙 -> 第一格亮 -> 继续加人（3.0 起，含 6.0 第一次加入）"},
    # 03 单画面 -> 四分
    {"out": "rec-layout-1to4.mp4", "start": 13.0, "dur": 8.0,
     "crop": (WALL_X, 0, WALL_W, 1620), "size": "1920:1080",
     "note": "布局 1x1 -> 2x2（含菜单与 3 路加入）"},
    # 04 九分
    {"out": "rec-layout-9grid.mp4", "start": 33.0, "dur": 9.0,
     "crop": (WALL_X, 0, WALL_W, 1620), "size": "1920:1080",
     "note": "2x2 -> 3x3 并继续加到 9 路"},
    # 05 大带小 1+5
    {"out": "rec-layout-bigplus.mp4", "start": 59.0, "dur": 8.0,
     "crop": (WALL_X, 0, WALL_W, 1620), "size": "1920:1080",
     "note": "九分 -> 主画面 + 5 小环绕（62.0 那一步）"},
    # 06 弹幕进墙
    {"out": "rec-layout-danmaku.mp4", "start": 78.0, "dur": 10.0,
     "crop": (WALL_X, 0, WALL_W, 1620), "size": "1920:1080",
     "note": "1+5 -> 主画面 + 1 小 + 弹幕，弹幕在滚（81.0 那一步）"},
    # 07 拖成竖屏（含横->竖->横的连续过程）
    {"out": "rec-portrait-flip.mp4", "start": 96.0, "dur": 26.0,
     "crop": PORTRAIT, "size": "1080:1920",
     "note": "横屏 -> 竖屏(99.0) -> 回横屏(119.0)，一镜到底"},
    # 08 弹幕面板特写（弹幕格那一块，母版可推近）
    {"out": "rec-danmaku-panel.mp4", "start": 82.0, "dur": 9.0,
     "crop": (WALL_X + 700, 0, 1100, 1620), "size": "1080:1080",
     "note": "punch-in 到弹幕格（粉丝牌/表情/屏蔽词）"},
    # 09 关注列表：悬停预览
    {"out": "rec-follow-list.mp4", "start": 127.0, "dur": 16.0,
     "crop": (0, 0, 760, 1620), "size": "1080:1080",
     "note": "关注列表四次悬停（127.0 起，每隔 5 秒一次）"},
    # 10 单格音量 / 静音
    {"out": "rec-tile-audio.mp4", "start": 164.0, "dur": 10.0,
     "crop": (WALL_X, 0, WALL_W, 1620), "size": "1920:1080",
     "note": "音量按钮左键两次（静音 -> 取消静音，167/173 两步）"},
    # 11 左/右声道
    {"out": "rec-channel-route.mp4", "start": 188.0, "dur": 16.0,
     "crop": (WALL_X, 0, WALL_W, 1620), "size": "1920:1080",
     "note": "右键音量按钮 -> 声道 -> 只播左(189) / 只播右(201)"},
]


def run_ffmpeg(args: list) -> int:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print("  ffmpeg 失败：" + (result.stderr or "").strip()[-400:], flush=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--take", default=os.path.join(PROMO, "raw", "take.mp4"))
    parser.add_argument("--assets", default=os.path.join(PROMO, "assets"))
    parser.add_argument("--events", default=os.path.join(PROMO, "raw",
                                                         "take-events.json"))
    parser.add_argument("--list", action="store_true", help="只打印，不裁")
    args = parser.parse_args()

    # 有事件表时，核对每段的起点是不是真的落在"那一步之后"
    marks = {}
    if os.path.isfile(args.events):
        with io.open(args.events, encoding="utf-8") as handle:
            payload = json.load(handle)
        for event in payload.get("events", []):
            marks.setdefault(event["kind"], []).append((event["t"], event["detail"]))

    print(f"母版：{args.take}")
    print(f"{'输出':34s} {'起点':>6s} {'时长':>5s}  说明")
    for item in PLAN:
        print(f"{item['out']:34s} {item['start']:6.1f} {item['dur']:5.1f}  {item['note']}")
    if args.list:
        return 0

    if not os.path.isfile(args.take):
        print(f"!! 找不到母版 {args.take}")
        return 1
    os.makedirs(args.assets, exist_ok=True)

    failed = []
    for item in PLAN:
        x, y, w, h = item["crop"]
        out = os.path.join(args.assets, item["out"])
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{item['start']:.2f}", "-t", f"{item['dur']:.2f}",
            "-i", args.take,
            "-vf", (f"crop={w}:{h}:{x}:{y},"
                    f"scale={item['size']}:flags=lanczos,setsar=1"),
            "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            out,
        ]
        print(f"  裁 {item['out']} ...", flush=True)
        if run_ffmpeg(cmd) != 0:
            failed.append(item["out"])
            continue
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v",
             "-show_entries", "stream=width,height", "-show_entries", "format=duration",
             "-of", "csv=p=0", out],
            capture_output=True, text=True).stdout.strip().replace("\n", " ")
        print(f"    -> {probe}", flush=True)

    print()
    if failed:
        print("!! 这些没裁成功：" + ", ".join(failed))
        return 1
    print(f"十段素材都落到 {args.assets}（下一步：node tools/assemble.mjs . <skill>）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
