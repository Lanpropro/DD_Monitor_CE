"""按「现在到底哪些直播间在播」生成录屏动作计划。

为什么要有这一步（踩过的坑）：上一版 take-plan.json 里写死了「关注第 1/2/3 项」，
结果把**没开播**的直播间拖上了墙 —— 格子黑着、也没有声音，整条素材一半是废的。
分镜要的是「真实亮着的画面墙」，所以计划必须按**当次的直播状态**生成。

这个脚本在软件进程里：
  1. 拉一次直播状态（refresh_status），等侧栏把 live 标出来；
  2. 取出「正在播」的房间，按侧栏顺序编号（侧栏排序是"开播优先"，所以前几个就是）；
  3. 模拟一遍布局/墙的容量变化（哪一步墙上有几格、哪一步能放下几路），
     只挑**放得下**的在播房间写进计划；
  4. 落一份 take-plan.json（结构不变，仍然是 at/type/x/y/target 那套）。

用法：
    python tools/make-take-plan.py                    # 写 tools/take-plan.json
    python tools/make-take-plan.py --out /tmp/plan.json --min-live 6
"""
import argparse
import ctypes
import ctypes.wintypes
import io
import json
import os
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

VLC_DLL = os.path.join(PROJ, "libvlc.dll")
if os.path.isfile(VLC_DLL):
    os.environ.setdefault("PYTHON_VLC_LIB_PATH", VLC_DLL)

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from ddm import config as config_module                # noqa: E402
from ddm import layouts                                # noqa: E402
from ddm import theme                                  # noqa: E402
from ddm.app import MainWindow                         # noqa: E402

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
HWND_TOPMOST = ctypes.c_void_p(-1)
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
TARGET = (1920, 1080)


def frame_rect(win):
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(int(win.winId())), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def force_geometry(win, logical=TARGET, tries=6):
    scale = win.devicePixelRatioF()
    want = (int(logical[0] * scale), int(logical[1] * scale))
    handle = ctypes.c_void_p(int(win.winId()))
    for _ in range(tries):
        user32.ShowWindow(handle, 9)
        user32.MoveWindow(handle, 0, 0, want[0], want[1], True)
        QApplication.processEvents()
        left, top, right, bottom = frame_rect(win)
        if (right - left, bottom - top) == want:
            break
        time.sleep(0.8)
    user32.SetWindowPos(handle, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    return frame_rect(win)


def build_plan(win, live_slots: list, min_live: int) -> tuple[list, dict]:
    """live_slots 是「在播房间在侧栏里的下标」（按侧栏顺序，开播优先）。

    返回 (计划, 说明)。墙位按 (布局容量, 空格优先填空位) 推演，
    推不出来的那几路就不写进计划 —— 宁可少录一路，也不要墙上黑一块。
    """
    plan: list = []
    notes = {"live_total": len(live_slots), "slots": [], "skipped": []}

    # 墙的状态：开始时按起点（1 格空格）
    wall = [""]                               # 每格一个 room_id，"" 表示空格
    cursor = 0                                # 下一个要用哪个在播房间
    used_slots: list = []

    def capacity(layout_id: str) -> int:
        layout = layouts.BY_ID.get(layout_id)
        spec = layout.get("spec") if layout else None
        return len(spec[2]) if spec else 0

    def resize(slot_index: int, layout_id: str) -> None:
        """按布局容量补空格/裁空格，模拟软件的 ensure_slots。"""
        need = capacity(layout_id)
        del layout_id
        used = sum(1 for item in wall if item)
        target = max(need, used, 1)
        while len(wall) < target:
            wall.append("")
        while len(wall) > target:
            for index in range(len(wall) - 1, -1, -1):
                if not wall[index]:
                    del wall[index]
                    break
            else:
                break

    def add_room() -> int | None:
        """把下一个在播房间加进墙；返回它在侧栏里的下标（没得加就 None）。"""
        nonlocal cursor
        if cursor >= len(live_slots):
            return None
        slot = live_slots[cursor]
        cursor += 1
        for index, item in enumerate(wall):
            if not item:
                wall[index] = f"nav_{slot}"
                used_slots.append(index)
                return slot
        return None

    def at(second: float, kind: str, note: str, **extra) -> None:
        plan.append(dict(at=second, type=kind, note=note, **extra))

    # ---- 0. 空墙静置 ----
    at(0, "wait", "空墙起步（起点已预置成 1 格空墙 + 单画面）")
    at(2, "move", note="光标进在播列表第一项", x=110, y=154, target="nav_0")

    # ---- 1. 第一路进墙，逐格亮起 ----
    first = add_room()
    if first is None:
        return plan, notes
    notes["slots"].append(first)
    at(4, "move", "空墙再静一下", x=600, y=800,
       target=f"nav_{first}")
    at(6, "rightclick", f"第 1 路（在播）进墙", x=110, y=154,
       target=f"nav_{first}", menu={"note": "加入画面墙"})
    at(9, "move", "第 1 格亮起来", x=700, y=400, target="tile_0")

    # ---- 2. 单画面 → 四分（放到 4 路）----
    at(11, "resize", "摆回基准尺寸（菜单坐标的基准）", w=1920, h=1080)
    resize(11, "2x2")
    at(13, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(16, "click", "选四分", x=561, y=673, target="card_2x2")
    second = 18
    while len([item for item in wall if item]) < min(4, len(live_slots)):
        slot = add_room()
        if slot is None:
            break
        notes["slots"].append(slot)
        at(second, "move", f"第 {len(notes['slots'])} 路", x=110,
           y=154 + 130 * (len(notes["slots"]) - 1), target=f"nav_{slot}")
        at(second + 2, "rightclick", "加入画面墙", x=110,
           y=154 + 130 * (len(notes["slots"]) - 1), target=f"nav_{slot}",
           menu={"note": "加入画面墙"})
        second += 3
    at(second + 2, "move", "四分满了，停一下给成片留素材", x=900, y=500)

    # ---- 3. 九分（放到 9 路）----
    at(second + 4, "resize", "摆回基准尺寸", w=1920, h=1080)
    resize(second + 4, "3x3")
    at(second + 6, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(second + 9, "click", "选九分", x=235, y=742, target="card_3x3")
    third = second + 11
    while len([item for item in wall if item]) < min(9, len(live_slots)):
        slot = add_room()
        if slot is None:
            break
        notes["slots"].append(slot)
        index = len(notes["slots"]) - 1
        y = 154 + 130 * (index % 5)
        at(third, "move", f"第 {index + 1} 路", x=110, y=y, target=f"nav_{slot}")
        at(third + 2, "rightclick", "加入画面墙", x=110, y=y, target=f"nav_{slot}",
           menu={"note": "加入画面墙"})
        third += 3
    at(third + 2, "move", "九分铺满，停住给成片取窗", x=1500, y=800)

    # ---- 4. 大带小 1+5 ----
    at(third + 4, "resize", "摆回基准尺寸", w=1920, h=1080)
    at(third + 6, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(third + 9, "click", "选主画面 + 5 小环绕（1+5）", x=235, y=833,
       target="card_corner")
    at(third + 12, "move", "主画面钉住，五小环绕", x=640, y=240)
    at(third + 17, "move", "1+5 停住", x=1500, y=800)

    # ---- 5. 弹幕布局 ----
    at(third + 20, "resize", "摆回基准尺寸", w=1920, h=1080)
    at(third + 22, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(third + 25, "click", "切到「弹幕布局」标签页", x=117, y=603,
       target="tab_弹幕布局")
    at(third + 28, "click", "选「主画面 + 1 小 + 弹幕」", x=398, y=654,
       target="card_dm_main2")
    at(third + 30, "move", "弹幕开始滚（全片唯一允许的持续运动）", x=1100, y=600)
    at(third + 38, "move", "弹幕继续滚，别碰鼠标", x=1600, y=300)

    # ---- 6. 拖成竖屏 → 回横屏 ----
    at(third + 46, "resize", "拖成竖屏（布局自动接上对映预设）", w=810, h=1440)
    at(third + 56, "move", "竖屏停住", x=300, y=900)
    at(third + 66, "resize", "回横屏", w=1920, h=1080)
    at(third + 72, "move", "横屏停住", x=900, y=500)

    # ---- 7. 关注列表悬停（在播的那几个）----
    hover_start = third + 75
    for offset in range(min(4, len(live_slots))):
        slot = live_slots[offset]
        at(hover_start + offset * 5, "move", f"在播第 {offset + 1} 项：悬停出封面预览",
           x=110, y=154 + 130 * offset, target=f"nav_{slot}")
    at(hover_start + 22, "move", "回到第 1 项，预览卡完整露一次",
       x=110, y=154, target=f"nav_{live_slots[0]}")

    # ---- 8. 单格音量/静音 + 左/右声道（要出声的那两拍）----
    audio_start = hover_start + 25
    at(audio_start, "resize", "音量那两拍前摆回基准尺寸", w=1920, h=1080)
    at(audio_start + 2, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(audio_start + 5, "click", "回到九分（要看得见格子底栏）", x=235, y=742,
       target="card_3x3")
    at(audio_start + 9, "move", "鼠标停在主画面格的音量按钮上", x=1723, y=964,
       target="volume_0")
    at(audio_start + 14, "mute", "这一拍要真出声", action="unmute",
       target="volume_0", x=1723, y=964)
    at(audio_start + 20, "click", "左键点音量按钮 -> 静音这一路", x=1723, y=964,
       target="volume_0")
    at(audio_start + 26, "click", "再点一次 -> 取消静音", x=1723, y=964,
       target="volume_0")
    at(audio_start + 32, "resize", "摆回基准尺寸", w=1920, h=1080)
    at(audio_start + 34, "rightclick", "右键音量按钮 -> 声道 -> 只播左声道",
       x=1723, y=964, target="volume_0",
       menu={"note": "声道", "item_note": "左声道"})
    at(audio_start + 40, "move", "L 标记亮起，这一路只走左耳", x=1723, y=964,
       target="volume_0")
    at(audio_start + 46, "rightclick", "右键音量按钮 -> 声道 -> 只播右声道",
       x=1723, y=964, target="volume_0",
       menu={"note": "声道", "item_note": "右声道"})
    at(audio_start + 52, "move", "R 标记亮起", x=1723, y=964, target="volume_0")
    at(audio_start + 56, "rightclick", "声道调回「默认（跟随片源）」",
       x=1723, y=964, target="volume_0",
       menu={"note": "声道", "item_note": "跟随片源"})
    at(audio_start + 60, "mute", "这两拍拍完了，软件重新按进程静音", action="mute",
       target="volume_0", x=1723, y=964)
    at(audio_start + 62, "move", "收尾", x=1500, y=900)

    notes["used_slots"] = used_slots
    notes["live_total"] = len(live_slots)
    notes["planned_rooms"] = len(notes["slots"])
    notes["min_live_required"] = min_live
    return plan, notes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(
        PROJ, "videos", "dd-monitor-ce-promo", "tools", "take-plan.json"))
    parser.add_argument("--min-live", type=int, default=6,
                        help="在播房间少于这个数就拒绝生成（宁可等，也别录一堆黑格）")
    parser.add_argument("--wait", type=float, default=20.0,
                        help="等在播状态拉回来的最长时间（秒）")
    args = parser.parse_args()

    app = QApplication([sys.argv[0]])
    app.setApplicationName("DD监控室CE · take-plan")
    app.setStyleSheet(theme.qss())
    state = config_module.load()
    sidebar, wall = config_module.build_rooms(state) if state else ([], [])
    win = MainWindow(sidebar, wall,
                     layout_id=(state.get("ui") or {}).get("layout") or "",
                     state=state)
    win.showMaximized()
    result = {}

    def run() -> None:
        try:
            force_geometry(win)
            QApplication.processEvents()
            time.sleep(1.0)
            QApplication.processEvents()
            win.refresh_status()
            deadline = time.monotonic() + args.wait
            live: list = []
            while time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.5)
                live = [index for index, item in enumerate(win.sidebar._items)   # noqa: SLF001
                        if item.room.get("live")]
                if len(live) >= args.min_live:
                    break
            names = {index: win.sidebar._items[index].room.get("uname", "?")     # noqa: SLF001
                     for index in live}
            print(f"在播 {len(live)} 个（侧栏下标）：{names}", flush=True)
            result["live"] = names
            if len(live) < args.min_live:
                result["refused"] = (f"在播只有 {len(live)} 个，少于 --min-live "
                                     f"{args.min_live}，不生成计划")
                print("!! " + result["refused"], flush=True)
                return
            plan, notes = build_plan(win, live, args.min_live)
            result["notes"] = notes
            result["plan_seconds"] = max(step["at"] for step in plan)
            with io.open(args.out, "w", encoding="utf-8") as handle:
                json.dump(plan, handle, ensure_ascii=False, indent=1)
            result["out"] = args.out
            print(f"计划 {len(plan)} 步，{result['plan_seconds']:.0f} 秒，写进 {args.out}",
                  flush=True)
            print("用到的在播房间下标：" + str(notes["slots"]), flush=True)
        except Exception:
            import traceback
            result["error"] = traceback.format_exc()
        finally:
            with io.open(os.path.join(PROJ, "videos", "dd-monitor-ce-promo", "raw",
                                      "make-take-plan.json"), "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=1)
            sys.stdout.flush()
            os._exit(0)

    QTimer.singleShot(5000, run)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
