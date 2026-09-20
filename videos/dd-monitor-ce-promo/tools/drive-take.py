"""录屏动作驱动：在软件**进程内**按动作计划走一遍。

为什么不用系统鼠标（tools/record-session.ps1 那条路）：
本环境实测 SetCursorPos + mouse_event 点不动窗口，连 PostMessageW 也不行
（见 tools/check-synth-input.py），而进程内 QTest / sendEvent 是通的
（见 tools/check-qt-inject.py）。上一轮 session4.mp4 能用，是用户自己点的鼠标。

这个驱动做三件事：
  1. 把真光标移到目标位置（成片里要看得到光标轨迹）；
  2. 用 QTest / sendEvent 在进程内把点击、右键菜单、悬停真的打给控件；
  3. 每一步记一条事件（相对开录的秒数、命中的控件名），给剪辑取时间窗用。

坐标一律「窗口内坐标」：真光标的屏幕点 = GetWindowRect 外框左上角 + 窗口内坐标。
点击则**按控件对象**打事件（先用同一套坐标反查是哪个控件），所以不吃像素精度。

用法（分三趟跑，每趟一段，互不干扰）：
    python tools/drive-take.py --plan <plan.json> --mode picker|tile|basic [--dry]
"""
import argparse
import ctypes
import ctypes.wintypes
import io
import json
import os
import subprocess
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

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer      # noqa: E402
from PySide6.QtGui import QMouseEvent                       # noqa: E402
from PySide6.QtTest import QTest                            # noqa: E402
from PySide6.QtWidgets import QApplication                  # noqa: E402

from ddm import config as config_module                     # noqa: E402
from ddm import theme                                       # noqa: E402
from ddm.app import MainWindow                              # noqa: E402
from ddm.widgets import VolumeButton                        # noqa: E402

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
HWND_TOPMOST = ctypes.c_void_p(-1)
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040

TARGET = (1920, 1080)                     # 量坐标时的逻辑尺寸（物理 2880x1620）
MUTE_SCRIPT = os.path.join(PROJ, "videos", "dd-monitor-ce-promo", "tools", "mute-app.py")
LOOPBACK_PY = os.path.join(PROJ, "work", "musicgen-venv", "Scripts", "python.exe")


def frame_rect(win):
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(int(win.winId())), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def keep_topmost(win):
    user32.SetWindowPos(ctypes.c_void_p(int(win.winId())), HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)


def force_geometry(win, logical=TARGET, tries=6):
    """摆成量坐标时那个尺寸（和 record-session.ps1 的 Set-Window-Geometry 同一条路）。"""
    scale = win.devicePixelRatioF()
    want = (int(logical[0] * scale), int(logical[1] * scale))
    handle = ctypes.c_void_p(int(win.winId()))
    for _ in range(tries):
        user32.ShowWindow(handle, 9)                     # SW_RESTORE
        user32.MoveWindow(handle, 0, 0, want[0], want[1], True)
        QApplication.processEvents()
        left, top, right, bottom = frame_rect(win)
        if (right - left, bottom - top) == want:
            break
        time.sleep(0.8)
    keep_topmost(win)
    return frame_rect(win)


class Driver:
    """按计划走动作。所有"点击"都打在真控件上，坐标只用来选控件和放光标。"""

    def __init__(self, win, mode, dry=False):
        self.win = win
        self.mode = mode
        self.dry = dry
        self.log = []
        self.plan_path = ""
        self._menu_action = None
        self._menu_point = None
        self.action_log = []

    # ---- 记录 ----
    def note(self, kind, detail, t):
        self.log.append({"t": round(t, 3), "kind": kind, "detail": detail})
        print(f"  [{t:7.2f}s] {kind:10s} {detail}", flush=True)

    # ---- 坐标 ----
    def origin(self):
        return self.win.mapToGlobal(self.win.rect().topLeft())

    def put_cursor(self, x, y):
        """把**真光标**放到窗口内坐标 (x,y) 对应的屏幕点。"""
        left, top = frame_rect(self.win)[:2]
        user32.SetCursorPos(left + int(x), top + int(y))

    def frame_of(self, widget):
        origin = self.origin()
        top_left = widget.mapToGlobal(widget.rect().topLeft())
        return (top_left.x() - origin.x(), top_left.y() - origin.y(),
                widget.width(), widget.height())

    # ---- 控件定位 ----
    def widgets(self):
        """当前该认识的控件：布局按钮 / 关注条目 / 格子底栏 / 弹层卡片。"""
        win = self.win
        side = win.sidebar
        found = [("layout_button", side.layout_button),
                 ("settings_button", side.settings_button),
                 ("import_button", side.import_button),
                 ("add_button", side.add_button),
                 ("search", side.search)]
        for index, item in enumerate(side._items):            # noqa: SLF001
            found.append((f"nav_{index}", item))
        for index, tile in enumerate(win.wall.tiles):
            if not tile.isVisible():
                continue
            found.append((f"tile_{index}", tile))
            for button in tile.findChildren(VolumeButton):
                found.append((f"volume_{index}", button))
            for label, widget in (("quality", tile.quality_button),
                                  ("close", tile.close_button)):
                if widget is not None:
                    found.append((f"{label}_{index}", widget))
        picker = getattr(side, "_picker", None)
        if picker is not None:
            # 三栏的卡片全登记：只登记当前栏的话，刚切完标签页那一瞬
            # 目标卡片可能还没被 Qt 标成可见，按名字就找不到了
            for group in picker._cards.values():                  # noqa: SLF001
                for card in group:
                    found.append((f"card_{card.property('layoutId')}", card))
            for name, tab in picker._tabs.items():                # noqa: SLF001
                found.append((f"tab_{name}", tab))
        return found

    def locate(self, x, y, label=None, pick=None):
        """窗口内坐标 (x,y) 命中哪个控件。

        label  —— 直接按名字取（动作计划里写死，最准）；
        pick   —— 只在这一类里挑（"card"/"volume"/"nav"/"tile"），
                  因为**格子的几何会随布局变**（1x1 时 tile0 是 1625x1011，
                  九分时是 536x332），拿固定坐标去比最近邻会选错控件。
        都没给时才用"包含该点优先、否则最近"的兜底。
        """
        items = self.widgets()
        if label:
            for name, widget in items:
                if name == label:
                    return name, widget
        if pick:
            wanted = [(name, widget) for name, widget in items
                      if name.split("_")[0] == pick]
            if wanted:
                items = wanted
        inside = []
        nearest = []
        for name, widget in items:
            if not widget.isVisible():
                continue
            fx, fy, fw, fh = self.frame_of(widget)
            center = (fx + fw / 2, fy + fh / 2)
            dist = (center[0] - x) ** 2 + (center[1] - y) ** 2
            nearest.append((dist, name, widget))
            if fx <= x <= fx + fw and fy <= y <= fy + fh:
                inside.append((dist, name, widget))
        pool = inside or nearest
        if not pool:
            return None, None
        _dist, name, widget = min(pool, key=lambda item: item[0])
        return name, widget

    # ---- 动作 ----
    def act_move(self, step, t):
        x, y = int(step["x"]), int(step["y"])
        name, widget = self.locate(x, y, step.get("target"), step.get("pick"))
        if widget is not None:
            # 坐标只用来选控件；光标放到控件真实中心，成片里才看得出"停在它上面"
            fx, fy, fw, fh = self.frame_of(widget)
            self.put_cursor(fx + fw // 2, fy + fh // 2)
            # 真光标移动不产生 Qt 事件，补一次 Enter/MouseMove：
            # 关注条目的悬停预览、格子底栏的显隐都挂在 enterEvent 上
            QApplication.sendEvent(widget, QEvent(QEvent.Enter))
            QApplication.sendEvent(widget, QMouseEvent(
                QEvent.MouseMove, QPointF(widget.rect().center()),
                widget.mapToGlobal(widget.rect().center()),
                Qt.NoButton, Qt.NoButton, Qt.NoModifier))
            QApplication.processEvents()
        else:
            self.put_cursor(x, y)
        self.note("move", f"{step.get('note', '')} -> {name or '?'}", t)

    def act_click(self, step, t):
        x, y = int(step["x"]), int(step["y"])
        name, widget = self.locate(x, y, step.get("target"), step.get("pick"))
        if widget is None:
            self.note("click", f"!! ({x},{y}) 没找到控件：{step.get('note', '')}", t)
            return
        # 加了个 target 但控件还是隐藏的（弹层换了标签页、卡片刚 setVisible），
        # 编译期没法保证 Qt 已经把它显示出来；这里显式 show 一下，
        # 否则 QTest 打到隐藏控件上不会触发（实测：切完标签页立刻点卡片会落到别的卡上）。
        if not widget.isVisible():
            widget.show()
            QApplication.processEvents()
        # 光标放到控件真实中心（坐标只用来选控件，位置以控件为准）
        fx, fy, fw, fh = self.frame_of(widget)
        self.put_cursor(fx + fw // 2, fy + fh // 2)
        QApplication.processEvents()
        QTest.mouseClick(widget, Qt.LeftButton)
        QApplication.processEvents()
        self.note("click", f"{step.get('note', '')} -> {name}", t)

    def act_mute(self, step, t):
        action = step.get("action", "mute")
        if not self.dry and os.path.isfile(MUTE_SCRIPT) and os.path.isfile(LOOPBACK_PY):
            subprocess.run([LOOPBACK_PY, MUTE_SCRIPT, "python", action],
                           capture_output=True, text=True)
        self.note("mute", f"软件音频 {action}：{step.get('note', '')}", t)

    def act_resize(self, step, t):
        want = (int(step["w"]), int(step["h"]))
        rect = force_geometry(self.win, want)
        QApplication.processEvents()
        time.sleep(0.6)
        QApplication.processEvents()
        layout = self.win.wall.layout_id
        self.note("resize", f"{want[0]}x{want[1]} -> 物理 "
                            f"{rect[2] - rect[0]}x{rect[3] - rect[1]} "
                            f"布局={layout}（{step.get('note', '')}）", t)

    def act_rightclick(self, step, t):
        """右键 -> 菜单项 -> （子菜单）目标项。

        两种菜单走两条路：格子的菜单可以自己弹自己关；关注条目的菜单是
        `NavItem.contextMenuEvent` 里阻塞的 `menu.exec()`，只能在它跑起来的
        事件循环里排队选。按"命中的控件是不是在格子里"自动分流，
        这样 --mode 只是给个默认倾向，不会因为计划里混了两种而卡住。
        """
        x, y = int(step["x"]), int(step["y"])
        name, widget = self.locate(x, y, step.get("target"))
        in_tile = widget is not None and self.tile_of(widget) is not None
        if self.mode == "tile" and in_tile:
            self.rightclick_tile(step, t)
        elif self.mode == "nav" or (self.mode != "tile" and not in_tile):
            self.rightclick_nav(step, t)
        elif in_tile:
            self.rightclick_tile(step, t)
        else:
            self.rightclick_nav(step, t)

    @staticmethod
    def tile_of(widget):
        node = widget
        while node is not None:
            if node.__class__.__name__ == "Tile":
                return node
            node = node.parentWidget()
        return None

    # -- 格子的右键菜单（音量按钮在底栏，菜单是 Tile 的）--
    def rightclick_tile(self, step, t):
        x, y = int(step["x"]), int(step["y"])
        menu_spec = step.get("menu", {}) or {}
        name, widget = self.locate(x, y, step.get("target"), "volume")
        if widget is None:
            self.note("rightclick", f"!! ({x},{y}) 没找到音量按钮", t)
            return
        fx, fy, fw, fh = self.frame_of(widget)
        self.put_cursor(fx + fw // 2, fy + fh // 2)
        QApplication.processEvents()
        tile = self.tile_of(widget)
        if tile is None:
            self.note("rightclick", f"!! {name} 不在格子里", t)
            return
        menu = tile.build_menu()
        menu.popup(widget.mapToGlobal(widget.rect().center()))
        QApplication.processEvents()
        time.sleep(0.45)
        QApplication.processEvents()
        self.pick_menu_action(menu, menu_spec.get("note", ""), t,
                              sub_text=menu_spec.get("item_note", ""))
        self.note("rightclick", f"{step.get('note', '')} -> {name} / "
                                f"格子状态 声道={tile.audio_channel} 静音={tile.muted}", t)

    # -- 关注条目的右键菜单（阻塞的 exec，用排队的方式选）--
    def rightclick_nav(self, step, t):
        x, y = int(step["x"]), int(step["y"])
        want = (step.get("menu", {}) or {}).get("note", "")
        name, item = self.locate(x, y, step.get("target"), "nav")
        if item is None:
            self.note("rightclick", f"!! ({x},{y}) 没找到关注条目", t)
            return
        fx, fy, fw, fh = self.frame_of(item)
        self.put_cursor(fx + fw // 2, fy + 24)
        QApplication.processEvents()
        menu = item._context_menu()                            # noqa: SLF001
        action = self.find_action(menu, want)
        if action is None:
            labels = [a.text() for a in menu.actions() if not a.isSeparator()]
            self.note("rightclick", f"!! 菜单里没有「{want}」，只有 {labels}", t)
            return
        self._menu_action = action
        self._menu_point = item.mapToGlobal(item.rect().center())

        def choose() -> None:
            rect = menu.actionGeometry(action)
            point = menu.mapToGlobal(rect.center())
            user32.SetCursorPos(point.x(), point.y())
            self.action_log.append(action.text().replace("&", ""))
            action.trigger()                 # 直接触发，不依赖菜单的点击投递
            menu.close()

        QTimer.singleShot(500, choose)
        menu.exec(self._menu_point)          # 阻塞在这一句里，choose 会在其中执行
        QApplication.processEvents()
        self.note("rightclick", f"{step.get('note', '')} -> {name} / {want}", t)

    # -- 菜单里按文字找动作，然后**直接 trigger** --
    def run_menu(self, menu, text, t, sub_text=""):
        """在已打开的菜单里选一项并执行。

        为什么不"点"而是 trigger：实测 QTest 往 QMenu 上打点击不生效
        （动作没被触发），而 trigger() 走的就是菜单项自己的槽，效果等价且确定。
        菜单本身照样会显示出来（popup/exec 已经把它画出来），
        光标也照样停在那一项上 —— 成片里看到的就是"点了这一项"。
        子菜单不展开也能拿到它的 action 列表，不用去模拟悬停。
        """
        action = self.find_action(menu, text)
        if action is None:
            labels = [a.text() for a in menu.actions() if not a.isSeparator()]
            self.note("menu", f"!! 菜单里没有「{text}」，只有 {labels}", t)
            menu.close()
            return None
        self.note("menu", f"（找到「{action.text().replace('&', '')}」"
                          f" 有子菜单={action.menu() is not None}）", t)
        rect = menu.actionGeometry(action)
        point = menu.mapToGlobal(rect.center())
        user32.SetCursorPos(point.x(), point.y())
        QApplication.processEvents()
        target = action
        submenu = action.menu()
        if submenu is not None:
            sub_action = self.find_action(submenu, sub_text)
            if sub_action is None:
                labels = [a.text() for a in submenu.actions() if not a.isSeparator()]
                self.note("menu", f"!! 子菜单里没有「{sub_text}」，只有 {labels}", t)
                menu.close()
                return None
            self.note("menu", f"（父项 {action.text().replace('&', '')} 里找到 "
                              f"{sub_action.text().replace('&', '')}）", t)
            sub_point = submenu.mapToGlobal(submenu.actionGeometry(sub_action).center())
            user32.SetCursorPos(sub_point.x(), sub_point.y())
            QApplication.processEvents()
            target = sub_action
        label = target.text().replace("&", "")
        target.trigger()
        QApplication.processEvents()
        try:
            menu.close()
        except RuntimeError:
            pass
        QApplication.processEvents()
        self.note("menu", f"选了「{label}」", t)
        return target

    def pick_menu_action(self, menu, text, t, sub_text=""):
        self.run_menu(menu, text, t, sub_text)

    def act_probe_menu(self, step, t):
        """诊断用：把格子右键菜单的结构打出来（项名 + 子菜单项名）。"""
        x, y = int(step["x"]), int(step["y"])
        name, widget = self.locate(x, y, step.get("target"), "volume")
        tile = self.tile_of(widget) if widget is not None else None
        if tile is None:
            self.note("probe", f"!! 没找到格子（命中 {name}）", t)
            return
        menu = tile.build_menu()
        for action in menu.actions():
            if action.isSeparator():
                continue
            submenu = action.menu()
            label = action.text().replace("&", "") or "(自定义控件)"
            if submenu is None:
                self.note("probe", f"{label}  [普通项]", t)
            else:
                kids = [kid.text().replace("&", "") for kid in submenu.actions()
                        if not kid.isSeparator()]
                self.note("probe", f"{label}  -> 子菜单 {kids}", t)
        menu.close()

    @staticmethod
    def find_action(menu, text):
        """按文字找菜单项。

        匹配规则要小心：菜单里有个**文字为空的**自定义控件项（音量滑条那段），
        如果拿"空串是任何串的子串"去比，它会被当成命中，结果点了滑条、
        声道根本没变（踩过）。所以：先精确相等，再"目标文字被包含"，
        **不做反向包含**，并且空文字永远不匹配。
        """
        if not text:
            return None
        exact, partial = None, None
        for action in menu.actions():
            if action.isSeparator():
                continue
            label = action.text().replace("&", "")
            if not label:
                continue
            if label == text:
                exact = action
                break
            if partial is None and text in label:
                partial = action
        return exact or partial

    # ---- 主流程 ----
    def run(self, plan, lead):
        self.note("begin", f"模式={self.mode} 计划 {len(plan)} 步 窗口 {frame_rect(self.win)}",
                  0.0)
        time.sleep(lead)
        t0 = time.monotonic()
        for step in plan:
            target = float(step["at"])
            while True:
                elapsed = time.monotonic() - t0
                if target - elapsed <= 0.02:
                    break
                QApplication.processEvents()
                time.sleep(min(0.02, max(0.0, target - elapsed - 0.01)))
            t = time.monotonic() - t0
            kind = step["type"]
            if kind == "wait":
                self.note("wait", step.get("note", ""), t)
            elif kind == "move":
                self.act_move(step, t)
            elif kind == "click":
                self.act_click(step, t)
            elif kind == "rightclick":
                self.act_rightclick(step, t)
            elif kind == "mute":
                self.act_mute(step, t)
            elif kind == "resize":
                self.act_resize(step, t)
            elif kind == "probe_menu":
                self.act_probe_menu(step, t)
            else:
                self.note("skip", f"未知动作 {kind}", t)
            # 弹层开着的这一小段要让它真的画出来（弹层是 Popup，需要事件循环）
            QApplication.processEvents()
        self.note("end", f"窗口 {frame_rect(self.win)}", time.monotonic() - t0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--mode", default="basic",
                        choices=["basic", "picker", "tile", "nav"])
    parser.add_argument("--events", default="")
    parser.add_argument("--lead", type=float, default=3.0,
                        help="先等几秒让画面稳下来再开始动作")
    parser.add_argument("--dry", action="store_true", help="不切静音、不真点")
    args = parser.parse_args()

    with io.open(args.plan, encoding="utf-8") as handle:
        plan = json.load(handle)
    events_path = args.events or (os.path.splitext(args.plan)[0] + "-events.json")

    app = QApplication([sys.argv[0]])
    app.setApplicationName("DD监控室CE · take")
    app.setStyleSheet(theme.qss())
    state = config_module.load()
    sidebar, wall = config_module.build_rooms(state) if state else ([], [])
    win = MainWindow(sidebar, wall,
                     layout_id=(state.get("ui") or {}).get("layout") or "",
                     state=state)
    win.showMaximized()
    driver = Driver(win, args.mode, dry=args.dry)
    driver.plan_path = args.plan

    def run_later() -> None:
        error = None
        try:
            rect = force_geometry(win)
            QApplication.processEvents()
            time.sleep(1.0)
            QApplication.processEvents()
            # 自检：量出来的坐标必须命中真控件，否则别开录（先修坐标再录）
            checks = [("layout_button", (95, 967)), ("nav_0", (110, 154))]
            for label, point in checks:
                name, widget = driver.locate(*point)
                ok = "OK " if (name or "").startswith(label.split("_")[0]) else "BAD"
                print(f"  [{ok}] 自检 {label} {point} -> {name}", flush=True)
            # 复算一遍关键控件的窗口内坐标：动作计划里的数就是从这里来的，
            # 录制前对一眼，偏了就先改计划再录（别录完才发现点偏）
            print("  [坐标复算] 窗口内坐标（动作计划的口径）", flush=True)
            for label, widget in (
                ("layout_button", win.sidebar.layout_button),
                ("nav_0", win.sidebar._items[0] if win.sidebar._items else None),  # noqa: SLF001
                ("volume_tile0",
                 win.wall.tiles[0].findChildren(VolumeButton)[0]
                 if win.wall.tiles and win.wall.tiles[0].findChildren(VolumeButton)
                 else None),
                ("tile0", win.wall.tiles[0] if win.wall.tiles else None),
            ):
                if widget is None:
                    continue
                fx, fy, fw, fh = driver.frame_of(widget)
                print(f"    {label:14s} ({fx},{fy}) {fw}x{fh} "
                      f"中心=({fx + fw // 2},{fy + fh // 2})", flush=True)
            print(f"窗口 {rect}  dpr={win.devicePixelRatioF()}  "
                  f"模式={args.mode}", flush=True)
            driver.run(plan, args.lead)
        except Exception:
            import traceback
            error = traceback.format_exc()
        finally:
            payload = {"mode": args.mode, "plan": os.path.basename(args.plan),
                       "events": driver.log}
            if error:
                payload["error"] = error
            with io.open(events_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=1)
            print(f"\n事件写进 {events_path}", flush=True)
            sys.stdout.flush()
            os._exit(1 if error else 0)

    QTimer.singleShot(6000, run_later)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
