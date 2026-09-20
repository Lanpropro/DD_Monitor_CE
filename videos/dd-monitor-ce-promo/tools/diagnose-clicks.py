"""诊断：录屏动作计划里那几个「点菜单」的坐标，真的能点中吗。

为什么不用截图判断：Qt::Popup 弹层（布局弹层 / 右键菜单）在 DWM 合成下
**抓不进 GDI 截图**（CopyFromScreen 只看到软件主窗口），所以"看截图"这条路
验证不了菜单项。改成**看行为**：按计划里的坐标真的点一下，然后读软件的状态
（当前布局 id / 这一格的声道），状态变了就说明点中了。

这个脚本自己就是一次真点击（SetCursorPos + mouse_event），和
record-session.ps1 的 click/rightclick 走同一条路，所以验证结果可以直接信。

用法：
    python tools/diagnose-clicks.py            # 跑全部用例
    python tools/diagnose-clicks.py picker      # 只跑布局弹层
"""
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

from PySide6.QtCore import QPoint, QTimer                # noqa: E402
from PySide6.QtWidgets import QApplication               # noqa: E402

from ddm import config as config_module                  # noqa: E402
from ddm import theme                                    # noqa: E402
from ddm.app import MainWindow                           # noqa: E402

OUT = os.path.join(PROJ, "videos", "dd-monitor-ce-promo", "raw",
                   "diagnose-clicks.json")
METRICS = os.path.join(PROJ, "videos", "dd-monitor-ce-promo", "raw",
                       "ui-metrics.json")

user32 = ctypes.windll.user32

#: 坐标缩放。实测：Qt 的 mapToGlobal 已经是**屏幕物理像素**（widgetAt 反查确认），
#: 所以「窗口内坐标 + 窗口外框左上角」直接就是屏幕坐标，这里必须是 1.0。
SCALE = 1.0

# 计划里的坐标（窗口外框原点，逻辑像素）。和 tools/verify-plan.json 保持同步。
PICKER_BUTTON = (95, 982)
CARD_FOUR = (561, 673)
CARD_NINE = (235, 742)
CARD_CORNER = (235, 833)
TAB_DANMAKU = (117, 603)
CARD_DM_MAIN2 = (398, 654)
NAV_ITEM_1 = (110, 154)
NAV_MENU_ADD = (55, 58)
VOLUME_BUTTON = (1723, 964)
CHANNEL_PARENT = (102, 104)
CHANNEL_LEFT = (85, 49)


def win_rect(win):
    user32.SetProcessDPIAware()
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(int(win.winId())), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def force_geometry(win, lw=1920, lh=1080):
    scale = win.devicePixelRatioF()
    user32.SetProcessDPIAware()
    handle = ctypes.c_void_p(int(win.winId()))
    for _ in range(6):
        user32.ShowWindow(handle, 9)
        user32.MoveWindow(handle, 0, 0, int(lw * scale), int(lh * scale), True)
        QApplication.processEvents()
        left, top, right, bottom = win_rect(win)
        if right - left == int(lw * scale) and bottom - top == int(lh * scale):
            break
        time.sleep(0.8)


def click(win, point, right=False):
    """按「窗口外框原点 + 窗口内坐标」真点一下（和录屏脚本同一条路）。

    坐标换算有坑：Qt 的 mapToGlobal 是**逻辑**坐标（缩放 150%），而
    SetCursorPos / mouse_event 收**物理**像素，所以要乘设备像素比。
    """
    left, top = win_rect(win)[:2]
    x, y = left + point[0] * SCALE, top + point[1] * SCALE
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    flags = (0x0008, 0x0010) if right else (0x0002, 0x0004)
    user32.mouse_event(flags[0], 0, 0, 0, None)
    time.sleep(0.07)
    user32.mouse_event(flags[1], 0, 0, 0, None)
    time.sleep(0.35)
    QApplication.processEvents()
    if point == PICKER_BUTTON:
        point_now = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point_now))
        print(f"    [diag] 目标物理=({int(x)},{int(y)}) "
              f"光标实际=({point_now.x},{point_now.y}) "
              f"前台={user32.GetForegroundWindow() == int(win.winId())}", flush=True)


def move(win, point):
    left, top = win_rect(win)[:2]
    user32.SetCursorPos(int(left + point[0] * SCALE), int(top + point[1] * SCALE))
    time.sleep(0.15)
    QApplication.processEvents()


def picker_size(win):
    """弹层的真实尺寸（从量出来的 ui-metrics.json 读，和计划同一份数据）。"""
    with io.open(METRICS, encoding="utf-8") as handle:
        return json.load(handle)["picker"]["size"]


def run(app, win, cases):
    report = []
    side = win.sidebar

    def record(name, ok, detail):
        report.append({"case": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'OK ' if ok else 'BAD'}] {name}: {detail}", flush=True)

    # ---- 1. 布局弹层：开 -> 点四分 ----
    if "picker" in cases:
        win.wall.set_layout("1x1")
        side.set_layout_name("1x1")
        QApplication.processEvents()
        click(win, PICKER_BUTTON)
        picker = getattr(side, "_picker", None)
        opened = picker is not None and picker.isVisible()
        record("picker-opens", opened, f"可见={opened}")
        if opened:
            # 弹层底部（外框系）压住按钮上沿，点按钮会把它关掉；卡片行看得到
            size = picker_size(win)
            origin = picker.mapToGlobal(picker.rect().topLeft())
            frame = win.mapToGlobal(win.rect().topLeft())
            bottom = origin.y() - frame.y() + size["h"] - 45
            record("picker-fits-window", 0 < bottom < win.height(),
                   f"弹层底边 y={bottom}（按钮上沿 y={PICKER_BUTTON[1]}）")
            click(win, CARD_FOUR)
            record("picker-card-four", win.wall.layout_id == "2x2",
                   f"布局={win.wall.layout_id}")
            # 九分
            click(win, PICKER_BUTTON)
            click(win, CARD_NINE)
            record("picker-card-nine", win.wall.layout_id == "3x3",
                   f"布局={win.wall.layout_id}")
            # 弹幕标签页 + 卡片
            click(win, PICKER_BUTTON)
            click(win, TAB_DANMAKU)
            picker = getattr(side, "_picker", None)
            group = picker.group() if picker is not None else ""
            click(win, CARD_DM_MAIN2)
            record("picker-card-danmaku",
                   win.wall.layout_id == "dm_main2",
                   f"标签页={group} 布局={win.wall.layout_id}")
            # 1+5
            click(win, PICKER_BUTTON)
            click(win, CARD_CORNER)
            record("picker-card-corner", win.wall.layout_id == "corner",
                   f"布局={win.wall.layout_id}")

    # ---- 2. 关注条目右键 -> 加入画面墙 ----
    if "nav" in cases:
        for tile in win.wall.tiles:
            tile.set_room({})
        click(win, (300, 300))                     # 先收掉可能残留的弹层
        before = win.wall.layout_id
        click(win, NAV_ITEM_1, right=True)
        moved = move(win, (NAV_ITEM_1[0] + NAV_MENU_ADD[0],
                           NAV_ITEM_1[1] + NAV_MENU_ADD[1]))
        click(win, (NAV_ITEM_1[0] + NAV_MENU_ADD[0],
                    NAV_ITEM_1[1] + NAV_MENU_ADD[1]))
        used = sum(1 for tile in win.wall.tiles if tile.room.get("room_id"))
        record("nav-menu-add-to-wall", used >= 1,
               f"墙上有 {used} 路（布局={before}->{win.wall.layout_id}）")

    # ---- 3. 音量按钮右键 -> 声道 -> 只播左声道 ----
    if "channel" in cases:
        tile = win.wall.tiles[0] if win.wall.tiles else None
        if tile is None or not tile.room.get("room_id"):
            record("channel-left", False, "第一格没有房间，先跑 nav 用例")
        else:
            before = tile.audio_channel
            click(win, VOLUME_BUTTON, right=True)
            move(win, (VOLUME_BUTTON[0] + CHANNEL_PARENT[0],
                       VOLUME_BUTTON[1] + CHANNEL_PARENT[1]))
            time.sleep(0.45)
            move(win, (VOLUME_BUTTON[0] + CHANNEL_PARENT[0],
                       VOLUME_BUTTON[1] + CHANNEL_PARENT[1]))
            click(win, (VOLUME_BUTTON[0] + CHANNEL_PARENT[0] + CHANNEL_LEFT[0],
                        VOLUME_BUTTON[1] + CHANNEL_PARENT[1] + CHANNEL_LEFT[1]))
            record("channel-left", tile.audio_channel == 3,
                   f"声道 {before} -> {tile.audio_channel}（3=只播左声道）")
            # 再切到只播右声道
            click(win, VOLUME_BUTTON, right=True)
            move(win, (VOLUME_BUTTON[0] + CHANNEL_PARENT[0],
                       VOLUME_BUTTON[1] + CHANNEL_PARENT[1]))
            time.sleep(0.45)
            click(win, (VOLUME_BUTTON[0] + CHANNEL_PARENT[0] + CHANNEL_LEFT[0],
                        VOLUME_BUTTON[1] + CHANNEL_PARENT[1] + 77))
            record("channel-right", tile.audio_channel == 4,
                   f"声道 -> {tile.audio_channel}（4=只播右声道）")

    with io.open(OUT, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
    bad = [item for item in report if not item["ok"]]
    print(f"\n{len(report) - len(bad)}/{len(report)} 通过；结果写进 {OUT}", flush=True)
    return bad


def main() -> int:
    cases = set(sys.argv[1:]) or {"picker", "nav", "channel"}
    app = QApplication([sys.argv[0]])
    app.setApplicationName("DD监控室CE · diagnose-clicks")
    app.setStyleSheet(theme.qss())
    state = config_module.load()
    sidebar, wall = config_module.build_rooms(state) if state else ([], [])
    win = MainWindow(sidebar, wall,
                     layout_id=(state.get("ui") or {}).get("layout") or "",
                     state=state)
    win.showMaximized()

    def run_later() -> None:
        try:
            force_geometry(win)
            QApplication.processEvents()
            time.sleep(1.0)
            QApplication.processEvents()
            # 先确认「窗口内坐标」在 Qt 眼里到底落在哪个控件上。
            # widgetAt 收的是逻辑屏幕坐标，而 mapToGlobal 的口径要实测确认，
            # 所以两种候选都问一遍，看哪个命中真控件。
            origin = win.mapToGlobal(win.rect().topLeft())
            dpr = win.devicePixelRatioF()
            button_center = win.sidebar.layout_button.mapToGlobal(
                win.sidebar.layout_button.rect().center())
            for label, pt in (("picker-button", PICKER_BUTTON),
                              ("card-four", CARD_FOUR),
                              ("nav-item-1", NAV_ITEM_1),
                              ("volume-button", VOLUME_BUTTON)):
                raw = QApplication.widgetAt(origin.x() + pt[0], origin.y() + pt[1])
                scaled = QApplication.widgetAt((origin.x() + pt[0]) / dpr,
                                               (origin.y() + pt[1]) / dpr)
                raw_name = raw.__class__.__name__ if raw else None
                scaled_name = scaled.__class__.__name__ if scaled else None
                print(f"  [命中] {label} {pt}: 原样->{raw_name} / 除DPR->{scaled_name}",
                      flush=True)
            at_raw = QApplication.widgetAt(button_center.x(), button_center.y())
            at_scaled = QApplication.widgetAt(button_center.x() / dpr,
                                              button_center.y() / dpr)
            print(f"  [按钮中心] mapToGlobal=({button_center.x()},{button_center.y()}) "
                  f"原样->{at_raw.__class__.__name__ if at_raw else None} "
                  f"除DPR->{at_scaled.__class__.__name__ if at_scaled else None}",
                  flush=True)
            print(f"  [窗口] 全局原点=({origin.x()},{origin.y()}) DPR={dpr} "
                  f"尺寸={win.width()}x{win.height()} "
                  f"外框={win_rect(win)}", flush=True)
            print("开始按计划坐标真点...", flush=True)
            run(app, win, cases)
        except Exception:
            import traceback
            with io.open(OUT + ".error.txt", "w", encoding="utf-8") as handle:
                handle.write(traceback.format_exc())
        finally:
            sys.stdout.flush()
            os._exit(0)

    QTimer.singleShot(6000, run_later)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
