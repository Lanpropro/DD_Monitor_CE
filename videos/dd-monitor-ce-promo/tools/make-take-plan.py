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


def build_plan_v2(win, live_slots: list, min_live: int) -> tuple[list, dict]:
    """按 `SCRIPT-v2.md` 的排轴生成录制计划（14 拍、一条连续流程）。

    和 v1 的区别：**不拍"逐格加人"的过程**，而是"一个窗口一路变过去"：
      单窗口 → 左右两分 → 四分 → 九分 → 1+5 → 同布局弹幕版 → 竖屏 → 滑出
      → 回横屏 1+5 → 关注栏预览 → 左右两分（两路分别只播左/只播右声道）。

    所以这里只在必要的地方加人（先把墙填到 1 路，后面按布局容量补），
    其余时间都留给"停在某个布局上、画面亮着在播"。

    布局 id 对应关系：
      1x1 单画面 / 1x2 左右两分 / 2x2 四分 / 3x3 九分 /
      corner 主画面+5小环绕 / dm_main4 主画面+3小+弹幕
      （弹幕布局里最接近 1+5 的那一套 —— 软件没有"1+5 + 弹幕"这个预设）
    """
    plan: list = []
    notes = {"live_total": len(live_slots), "slots": [], "layout_version": "v2"}

    wall = [""]
    cursor = 0
    used_slots: list = []

    def capacity(layout_id: str) -> int:
        layout = layouts.BY_ID.get(layout_id)
        spec = layout.get("spec") if layout else None
        return len(spec[2]) if spec else 0

    def fit(layout_id: str) -> None:
        """按布局容量补空格/裁空格，模拟软件的 ensure_slots。"""
        need = capacity(layout_id)
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

    def nav_y(order: int) -> int:
        """侧栏第 order 项（0 起）的窗口内 y。侧栏条目高 130，列表顶 y=154。"""
        return 154 + 130 * (order % 5)

    def add_nth(target_used: int, second: float) -> float:
        """把墙补到 target_used 路，返回下一个可用时刻。"""
        while len([item for item in wall if item]) < min(target_used, len(live_slots)):
            slot = add_room()
            if slot is None:
                break
            order = len(notes["slots"])
            notes["slots"].append(slot)
            at(second, "move", f"第 {order + 1} 路（在播）", x=110, y=nav_y(order),
               target=f"nav_{slot}")
            at(second + 2, "rightclick", "加入画面墙", x=110, y=nav_y(order),
               target=f"nav_{slot}", menu={"note": "加入画面墙"})
            second += 3.5
        return second

    # ---- A. 单窗口播放（给 03 开头）----
    at(0, "wait", "起点：空墙 1 格 + 单画面布局")
    at(2, "move", "光标进在播列表第 1 项", x=110, y=nav_y(0),
       target=f"nav_{live_slots[0]}")
    t = add_nth(1, 4)                                    # 第 1 路进墙
    at(t, "move", "单窗口开始播（03 的单窗口播放段）", x=700, y=400,
       target="tile_0")
    at(t + 8, "move", "单窗口停住", x=900, y=520)
    t += 10

    # ---- B. 左右两分（点击动效 + 分裂）----
    at(t, "resize", "摆回基准尺寸（菜单坐标的基准）", w=1920, h=1080)
    fit("1x2")
    at(t + 2, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(t + 5, "click", "选「左右两分」（03 的分裂）", x=398, y=673,
       target="card_1x2")
    at(t + 8, "move", "左右两分停住（分裂过程本身是素材）", x=900, y=500)
    at(t + 14, "move", "左右两分再停一下", x=1500, y=700)
    t += 16

    # ---- C. 四分 ----
    fit("2x2")
    at(t, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(t + 3, "click", "选四分", x=561, y=673, target="card_2x2")
    t = add_nth(4, t + 6)                                # 补到 4 路
    at(t, "move", "四分停住", x=900, y=500)
    t += 8

    # ---- D. 九分 ----
    fit("3x3")
    at(t, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(t + 3, "click", "选九分", x=235, y=742, target="card_3x3")
    t = add_nth(9, t + 6)                                # 补到 9 路
    at(t, "move", "九分铺满（05 的素材）", x=1500, y=800)
    t += 10

    # ---- E. 1+5 小画面环绕 ----
    fit("corner")
    at(t, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(t + 3, "click", "选主画面 + 5 小环绕（1+5）", x=235, y=833,
       target="card_corner")
    at(t + 6, "move", "主画面钉住，五小环绕（06 的素材）", x=640, y=240)
    at(t + 12, "move", "1+5 停住", x=1500, y=800)
    t += 14

    # ---- F. 同布局弹幕版（07，镜头后面推近弹幕格）----
    fit("dm_main4")
    at(t, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(t + 3, "click", "切到「弹幕布局」标签页", x=117, y=603,
       target="tab_弹幕布局")
    at(t + 6, "click", "选「主画面 + 3 小 + 弹幕」（1+5 的弹幕版）",
       x=72, y=723, target="card_dm_main4")
    at(t + 9, "move", "弹幕开始滚（07 的聚焦素材，别碰鼠标）", x=1100, y=600)
    at(t + 17, "move", "弹幕继续滚", x=1600, y=300)
    t += 20

    # ---- G. 动态切竖屏 ----
    at(t, "resize", "动态切竖屏（布局自动接上对映预设）", w=810, h=1440)
    at(t + 6, "move", "竖屏停住（08 的素材）", x=300, y=900)
    at(t + 14, "move", "竖屏再停一下", x=400, y=1200)
    t += 16

    # ---- H. 竖屏滑出画面（09）----
    at(t, "slideout", "竖屏窗口滑出画面（09 的素材）", w=810, h=1440,
       direction="right")
    at(t + 4, "move", "滑出后保持干净", x=300, y=900)
    t += 6

    # ---- I. 回横屏 1+5（10）----
    at(t, "resize", "回横屏", w=1920, h=1080)
    at(t + 3, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(t + 6, "click", "回到 1+5（10 的素材）", x=235, y=833, target="card_corner")
    at(t + 9, "move", "横屏 1+5 停住", x=900, y=500)
    t += 12

    # ---- J. 关注栏悬停预览（11）----
    for offset in range(min(4, len(live_slots))):
        slot = live_slots[offset]
        at(t + offset * 5, "move", f"在播第 {offset + 1} 项：悬停出封面预览",
           x=110, y=nav_y(offset), target=f"nav_{slot}")
    at(t + 22, "move", "回到第 1 项，预览卡完整露一次", x=110, y=nav_y(0),
       target=f"nav_{live_slots[0]}")
    t += 25

    # ---- K. 左右两个画面 + 左/右声道（12；用两个**不同**直播间）----
    fit("1x2")
    at(t, "resize", "分屏前摆回基准尺寸", w=1920, h=1080)
    at(t + 2, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(t + 5, "click", "选「左右两分」（左格第 1 路、右格第 2 路）", x=398, y=673,
       target="card_1x2")
    at(t + 9, "rightclick", "左格：声道 -> 只播左声道", x=1100, y=500,
       target="volume_0", menu={"note": "声道", "item_note": "左声道"})
    at(t + 15, "move", "光标停在左格音量按钮上（L 标记）", x=1100, y=500,
       target="volume_0")
    at(t + 19, "rightclick", "右格：声道 -> 只播右声道", x=2100, y=500,
       target="volume_1", menu={"note": "声道", "item_note": "右声道"})
    at(t + 25, "move", "光标停在右格音量按钮上（R 标记）", x=2100, y=500,
       target="volume_1")
    # 两格都要出声：会话层放开 + 两个格子各自未静音
    at(t + 29, "mute", "两路都放开声音（会话层）", action="unmute",
       target="volume_0", x=1100, y=500)
    at(t + 31, "mute", "左格未静音", action="unmute", target="volume_1",
       x=2100, y=500)
    at(t + 34, "move", "左右两路各走各的声道，停住（12 的素材）", x=1600, y=540)
    at(t + 44, "move", "再停一下，让左右声音听清楚", x=1600, y=540)
    at(t + 52, "mute", "12 拍收尾：重新按进程静音", action="mute", target="volume_0",
       x=1100, y=500)
    t += 56

    # ---- L. 15 拍要的「墙静置」素材（切回软件后做纵向滚动用）----
    # 两种墙各留一段：九分（信息量最大）+ 1+5（有主次）。全部在播、别碰鼠标。
    fit("3x3")
    at(t, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(t + 3, "click", "回到九分（15 拍的墙静置段）", x=235, y=742,
       target="card_3x3")
    at(t + 6, "move", "九分静置：全墙在播，别碰鼠标", x=1500, y=800)
    at(t + 16, "move", "九分继续静置（纵向滚动的素材）", x=1500, y=800)
    t += 18

    fit("corner")
    at(t, "click", "开布局弹层", x=95, y=967, target="layout_button")
    at(t + 3, "click", "切到 1+5（15 拍的第二种墙）", x=235, y=833,
       target="card_corner")
    at(t + 6, "move", "1+5 静置", x=640, y=240)
    at(t + 14, "move", "1+5 继续静置（素材）", x=1500, y=800)
    t += 16

    at(t, "move", "全片收尾", x=1500, y=900)
    t += 2

    notes["used_slots"] = used_slots
    notes["planned_rooms"] = len(notes["slots"])
    notes["plan_seconds"] = t
    notes["min_live_required"] = min_live
    notes["twins"] = notes["slots"][:2]      # 12 拍用的两路（不同的直播间）
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
            plan, notes = build_plan_v2(win, live, args.min_live)
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
