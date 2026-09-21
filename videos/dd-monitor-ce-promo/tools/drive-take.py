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
    """按计划走动作。所有"点击"都打在真控件上，坐标只用来选控件。"""

    #: 出声的格子保持这个音量（用户 2026-09-21 指定：50）
    TARGET_VOLUME = 50

    def __init__(self, win, mode, dry=False):
        self.win = win
        self.mode = mode
        self.dry = dry
        self.log = []
        self.plan_path = ""
        self._menu_action = None
        self._menu_point = None
        self.action_log = []
        self.audio_on = False
        self._park = None            # 真光标停靠点（屏幕右下角，见 park_cursor）
        self._session_unmuted = False
        self._sound_locked = False   # 计划里显式 mute 过就不再自动补声
        self._offline_warned = ()    # 上次警告过的"未开播房间"名单

    # ---- 记录 ----
    def note(self, kind, detail, t):
        self.log.append({"t": round(t, 3), "kind": kind, "detail": detail})
        print(f"  [{t:7.2f}s] {kind:10s} {detail}", flush=True)

    # ---- 坐标 ----
    def origin(self):
        return self.win.mapToGlobal(self.win.rect().topLeft())

    def park_cursor(self):
        """把真光标顶到屏幕最右下角（窗口区域之外）。

        用户要求：**录制画面里不要有鼠标**，光标后期在合成里补（虚拟鼠标）。
        成片只裁窗口区域（2880x1620），而屏幕是 3840x2160 —— 把光标停在
        屏幕右下角就不会出现在裁切范围内。Qt 事件是直接打给控件的（不靠光标），
        所以动作照常生效。
        """
        if self._park is None:
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            self._park = (width - 2, height - 2)
        user32.SetCursorPos(int(self._park[0]), int(self._park[1]))

    def put_cursor(self, x, y):
        """历史接口：以前是"把光标移到目标上"。现在按用户要求不录光标，
        一律改成把光标停在屏幕角落；参数保留是为了不动调用点。"""
        del x, y
        self.park_cursor()

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
        # ★只有**明确要求悬停**的步骤才补 Enter 事件。
        #   关注列表的预览卡挂在 enterEvent 上，之前这里对所有 move 都发 Enter，
        #   于是"光标明明停在屏幕角落，预览卡还是弹出来"（用户报的）。
        #   现在改成：计划里写了 "hover": true 才发 —— 只有成片真正要预览卡的那几拍才写。
        if widget is not None and step.get("hover"):
            QApplication.sendEvent(widget, QEvent(QEvent.Enter))
            QApplication.sendEvent(widget, QMouseEvent(
                QEvent.MouseMove, QPointF(widget.rect().center()),
                widget.mapToGlobal(widget.rect().center()),
                Qt.NoButton, Qt.NoButton, Qt.NoModifier))
            QApplication.processEvents()
        self.put_cursor(x, y)
        self.note("move", f"{step.get('note', '')} -> {name or '?'}"
                          f"{'（悬停触发预览）' if step.get('hover') else ''}", t)

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
        """把"软件到底出不出声"这件事同时管住两层。

        踩过的坑：画面墙上的格子显示"已静音"但软件**实际还在出声**，反过来
        按进程静音（mute-app.py）之后，格子就算点成"未静音"也不会有声音 ——
        两层都要管，否则录出来的那两拍是死的（实测：整条 4 分钟 take 的音频
        都是 -91dB，连"要出声"的窗口也静音）。

          · 格子层：tile.set_muted(...) —— 决定软件自己要不要播声音
          · 会话层：mute-app.py —— 决定系统混音里还有没有它

        两个动作都要等到真正生效（会话开关是异步的），否则录到的还是旧状态。
        """
        action = step.get("action", "mute")
        want_muted = action == "mute"

        # 1) 格子层：没有 target 就按计划坐标找那个格子
        tile = None
        if step.get("target"):
            name, widget = self.locate(int(step.get("x", 0)), int(step.get("y", 0)),
                                       step["target"], "volume")
            tile = self.tile_of(widget) if widget is not None else None
        if tile is not None and not want_muted:
            # ★解除静音要"双保险"（用户要求：第二个格子的静音也必须自己解掉，
            #   不能靠用户手动点）：
            #   1) tile.set_muted(False) —— 改格子状态 + 发 muteToggled 信号；
            #   2) 直接 player.set_muted(False) —— 信号走事件循环可能慢一步，
            #      直接同步到播放器最稳（切声道会重建播放器，靠信号容易被重置）。
            changed = []
            if tile.volume != self.TARGET_VOLUME:
                tile.set_volume(self.TARGET_VOLUME)
                changed.append(f"音量 -> {self.TARGET_VOLUME}")
            tile.set_muted(False)
            player = self.win.players.get(tile)
            if player is not None:
                try:
                    player.set_muted(False)
                    player.set_volume(self.TARGET_VOLUME)
                except Exception:          # noqa: BLE001
                    pass
            QApplication.processEvents()
            state = "、".join(changed) if changed else "本来就有声"
            self.note("mute", f"格子「{tile.room.get('uname', '?')}」{state}"
                              f"（声道={tile.audio_channel} 音量={tile.volume}"
                              f" 静音={tile.muted}）", t)
        elif tile is not None and want_muted and not tile.muted:
            tile.set_muted(True)
            QApplication.processEvents()
            self.note("mute", f"格子「{tile.room.get('uname', '?')}」已静音", t)

        # 2) 会话层 + 等生效。**按 PID 挑会话**：这台机器上同时有多个 pythonw
        #    （软件本体、探测脚本、驱动脚本），按名字找会命中好几个会话，
        #    解静音可能落到别的会话上（这就是上一版录出来全程静音的原因）。
        if not self.dry and os.path.isfile(MUTE_SCRIPT) and os.path.isfile(LOOPBACK_PY):
            subprocess.run([LOOPBACK_PY, MUTE_SCRIPT, f"pid:{os.getpid()}", action],
                           capture_output=True, text=True)
        self.audio_on = not want_muted
        if want_muted:
            # 计划里显式要求静音：别让 ensure_sound 又给补回来
            self._sound_locked = True
        else:
            self._sound_locked = False
        self.note("mute", f"软件音频 {action}：{step.get('note', '')}", t)

    def act_slideout(self, step, t):
        """把窗口**连续**移出画面（给 09「竖屏布局滑出画面」用）。

        为什么不一步 MoveWindow：那在录屏里是"啪"地消失，看起来像卡了；
        分步移动（每步 30ms、约 22 步）才像用户真的把窗口拖出去。
        """
        want = (int(step["w"]), int(step["h"]))
        direction = step.get("direction", "right")
        rect = force_geometry(self.win, want)
        handle = ctypes.c_void_p(int(self.win.winId()))
        screen_w = user32.GetSystemMetrics(0)
        start_x = rect[0]
        end_x = screen_w if direction == "right" else -rect[2]
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        steps = 22
        for index in range(1, steps + 1):
            x = int(start_x + (end_x - start_x) * index / steps)
            user32.MoveWindow(handle, x, 0, width, height, True)
            QApplication.processEvents()
            time.sleep(0.03)
        self.note("slideout", f"窗口滑出到 x={end_x}（{step.get('note', '')}）", t)

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

    def warn_offline_tiles(self, t: float) -> None:
        """墙上有**未在播**的房间就记一条警告（只在变化时记一次）。

        为什么需要：录出来的格子黑着、还没声音，多半就是不小心把没开播的房间
        拖上了墙（踩过：测试计划里写死 nav_0/nav_1，那两路当时没开播，
        整条素材音频 -180dB，还误判成"软件切声道导致没声音"）。
        """
        offline = sorted(tile.room.get("uname", "?") for tile in self.win.wall.tiles
                         if tile.isVisible() and tile.room.get("room_id")
                         and not tile.room.get("live"))
        key = tuple(offline)
        if offline and key != self._offline_warned:
            self._offline_warned = key
            self.note("warn", "!! 墙上有未开播的房间：" + "、".join(offline), t)

    def ensure_sound(self, t: float = 0.0) -> None:
        """保证「至少一路在出声」，全程反复调用（幂等、便宜）。

        用户要求（2026-09-21 修正）：**整条素材必须一直有直播声音** ——
        需不需要静音后期再定，但不能录出来是哑的。所以不再"默认静音、
        某一拍才放开"，改成开录之后就一路托住：
          1) 会话层按 PID 放开（只做一次）；
          2) 墙上有房间的格子里挑第一路，音量托到 MIN_AUDIBLE_VOLUME、取消静音。
        每一步动作后都会调用它，所以中途切布局/换播放器导致静音也能自动补回来。
        """
        if self.dry or self._sound_locked:
            return
        if not self._session_unmuted \
                and os.path.isfile(MUTE_SCRIPT) and os.path.isfile(LOOPBACK_PY):
            result = subprocess.run([LOOPBACK_PY, MUTE_SCRIPT,
                                     f"pid:{os.getpid()}", "unmute"],
                                    capture_output=True, text=True)
            tail = (result.stdout or result.stderr or "").strip().splitlines()
            self._session_unmuted = True
            self.note("audio", "会话解静音：" + (tail[-1] if tail else "（无输出）"), t)

        tile = next((item for item in self.win.wall.tiles
                     if item.isVisible() and item.room.get("room_id")), None)
        if tile is None:
            return
        changed = []
        if tile.volume != self.TARGET_VOLUME:
            tile.set_volume(self.TARGET_VOLUME)
            changed.append(f"音量 -> {self.TARGET_VOLUME}")
        if tile.muted:
            tile.set_muted(False)
            changed.append("取消静音")
        if changed:
            QApplication.processEvents()
            self.audio_on = True
            self.note("audio", f"「{tile.room.get('uname', '?')}」"
                              f"{'、'.join(changed)}（全程保持有声）", t)

    def _tile_named(self, label):
        if not label:
            return None
        name, widget = self.locate(0, 0, label, "volume")
        return self.tile_of(widget) if widget is not None else None

    # ---- 主流程 ----
    def run(self, plan, lead):
        self._plan = plan
        self.note("begin", f"模式={self.mode} 计划 {len(plan)} 步 窗口 {frame_rect(self.win)}",
                  0.0)
        time.sleep(lead)
        t0 = time.monotonic()
        self._time0 = t0
        self.park_cursor()             # 开录前先把真光标藏到屏幕角落（不录进画面）
        self.ensure_sound(0.0)
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
            elif kind == "slideout":
                self.act_slideout(step, t)
            elif kind == "probe_menu":
                self.act_probe_menu(step, t)
            else:
                self.note("skip", f"未知动作 {kind}", t)
            # 弹层开着的这一小段要让它真的画出来（弹层是 Popup，需要事件循环）
            QApplication.processEvents()
            # 全程保证有一路在出声（用户要求：素材不能是哑的）；幂等、便宜
            self.ensure_sound(t)
            self.warn_offline_tiles(t)
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
