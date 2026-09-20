"""量取录屏要用到的控件坐标（窗口内逻辑坐标）。

为什么需要它：`tools/action-plan.json` 里每个动作都写「窗口内相对坐标」，
而菜单卡片 / 单格音量按钮的位置靠猜会打偏（实测过一次）。与其反复录一遍
看有没有点中，不如让软件自己把控件几何报出来。

量到的坐标是**窗口内**的，脚本自己减掉了窗口在屏幕上的位置 —— 软件会自己
挪窗口、启动后还会恢复 saveGeometry，所以绝对坐标不可信，相对坐标才稳。

用法（必须在没关掉控制台的前提下，让窗口真的画出来才量得准）：

    F:\\CodexAppManager\\Code\\DD_Monitor-venv\\Scripts\\python.exe ^
        videos\\dd-monitor-ce-promo\\tools\\measure-ui.py [输出 json]
"""
import ctypes
import ctypes.wintypes
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

from PySide6.QtCore import QPoint, QTimer               # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from ddm import config as config_module                # noqa: E402
from ddm import theme                                  # noqa: E402
from ddm.app import MainWindow                         # noqa: E402
from ddm.widgets import LayoutPicker                   # noqa: E402

#: 量的目标逻辑尺寸。和 record-session.ps1 的 -LogicalWidth/-LogicalHeight 对齐：
#: 菜单弹出位置挂在「布局预设」按钮上，按钮位置会随窗口尺寸走。
TARGET_W, TARGET_H = 1920, 1080
#: 设成 0 就是不改尺寸，只报告当前窗口矩形
if len(sys.argv) > 2:
    TARGET_W, TARGET_H = (int(part) for part in sys.argv[2].split("x"))

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    PROJ, "videos", "dd-monitor-ce-promo", "raw", "ui-metrics.json")


def window_rect(win):
    """窗口在屏幕上的物理像素矩形（DWM 外框，和 record-session.ps1 用的一致）。

    用 ctypes 而不是 pywin32：这个 venv 里没装 pywin32。
    """
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(int(win.winId())), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def force_geometry(win, logical_w: int, logical_h: int) -> tuple:
    """把窗口摆成和录制时一样的物理尺寸（逻辑 × 缩放），并报告实际矩形。

    这一步不能省：控件坐标随窗口尺寸变，量出来必须就是录制当时的那个尺寸。
    和 record-session.ps1 的 Set-Window-Geometry 是同一条路（MoveWindow），
    软件把方向切换挂在 resizeEvent 上，所以这样做等价于手动拖窗口。
    """
    scale = win.devicePixelRatioF()
    want = (int(logical_w * scale), int(logical_h * scale))
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    handle = ctypes.c_void_p(int(win.winId()))
    for _attempt in range(6):
        user32.ShowWindow(handle, 9)                 # SW_RESTORE：先退出最大化
        user32.MoveWindow(handle, 0, 0, want[0], want[1], True)
        QApplication.processEvents()
        left, top, right, bottom = window_rect(win)
        if (right - left, bottom - top) == want:
            return window_rect(win)
        time.sleep(0.8)
    return window_rect(win)


def local(win, widget):
    """控件在窗口内的坐标矩形 {x,y,w,h} —— 以**窗口外框左上角**为原点。

    这一点很关键，踩过一次：Qt 的 mapToGlobal 给的是**客户区**原点（外框内有
    标题栏和边框，实测差 (7,30)），而录屏脚本（record-session.ps1）是按
    GetWindowRect 的外框左上角加偏移点击的。两者混用会整整偏一个标题栏，
    表现就是「点菜单点在列表上」。所以这里统一把客户区原点换算成外框原点。
    """
    if widget is None:
        return None
    top_left = widget.mapToGlobal(widget.rect().topLeft())
    origin = win.mapToGlobal(win.rect().topLeft())
    # _frame_dx/_frame_dy 由 frame_offset() 算好：外框原点 - 客户区原点
    dx = getattr(win, "_frame_dx", 0)
    dy = getattr(win, "_frame_dy", 0)
    x = top_left.x() - origin.x() + dx
    y = top_left.y() - origin.y() + dy
    return {
        "x": x,
        "y": y,
        "w": widget.width(),
        "h": widget.height(),
        "cx": x + widget.width() // 2,
        "cy": y + widget.height() // 2,
    }


def frame_offset(win) -> dict:
    """量出「窗口外框原点」和「Qt 客户区原点」差多少（物理像素）。

    GetWindowRect 给外框；Qt 的 mapToGlobal 给客户区。两者不等价，
    而录屏脚本用前者、Qt 控件几何用后者，所以必须显式换算一次。
    """
    left, top, right, bottom = window_rect(win)
    origin = win.mapToGlobal(win.rect().topLeft())
    dpr = win.devicePixelRatioF()
    # 客户区原点在屏幕上的物理像素
    client_x = origin.x() * dpr
    client_y = origin.y() * dpr
    dx = int(round(left - client_x))
    dy = int(round(top - client_y))
    win._frame_dx = dx
    win._frame_dy = dy
    return {"x": dx, "y": dy,
            "win32_left_top": {"x": left, "y": top},
            "client_physical": {"x": client_x, "y": client_y}}


def measure_picker(win, current: str) -> dict:
    """开一次布局弹层，把每一栏、每一张卡片的窗口内坐标报出来。"""
    picker = LayoutPicker(current, win, portrait=False)
    picker.adjustSize()
    picker.move(0, 0)                # 位置无所谓，只要它真的画出来
    picker.show()
    picker.repaint()
    QApplication.processEvents()
    origin = win.mapToGlobal(win.rect().topLeft())
    anchor = picker.mapToGlobal(picker.rect().topLeft())
    result = {
        "size": {"w": picker.width(), "h": picker.height()},
        # 真弹层的位置随「布局预设」按钮走，这里只记它相对窗口的位置，
        # 供 action-plan 核对（y 会是负的：弹层从按钮上方弹出来）
        "origin": {"x": anchor.x() - origin.x() + getattr(win, "_frame_dx", 0),
                   "y": anchor.y() - origin.y() + getattr(win, "_frame_dy", 0)},
        "groups": {},
    }
    for group in picker._cards:                                  # noqa: SLF001
        picker.set_group(group)
        QApplication.processEvents()
        entry = {"size": {"w": picker.width(), "h": picker.height()},
                 "tabs": {}, "cards": {}, "sections": {}}
        for name, button in picker._tabs.items():                # noqa: SLF001
            entry["tabs"][name] = local(win, button)
        for name, headings in picker._sections.items():          # noqa: SLF001
            entry["sections"][name] = [local(win, item) for item in headings]
        for card in picker._cards[group]:                        # noqa: SLF001
            entry["cards"][card.property("layoutId")] = dict(
                local(win, card) or {}, name=card.text())
        result["groups"][group] = entry
    picker.close()
    picker.deleteLater()
    QApplication.processEvents()
    return result


def measure_tiles(win) -> list:
    """每一格的底栏控件（音量按钮就是左键切静音 / 右键出声道菜单的那个）。"""
    from ddm.widgets import VolumeButton
    out = []
    for index, tile in enumerate(win.wall.tiles):
        if not tile.isVisible():
            continue
        buttons = tile.findChildren(VolumeButton)
        out.append({
            "index": index,
            "room": str(tile.room.get("room_id") or ""),
            "uname": tile.room.get("uname", ""),
            "rect": local(win, tile),
            "volume_button": local(win, buttons[0]) if buttons else None,
            "volume_slider": local(win, tile.volume_slider),
            "quality_button": local(win, getattr(tile, "quality_button", None)),
        })
    return out


def menu_actions(menu) -> dict:
    """菜单里每一项相对菜单左上角的中心点。

    上下文菜单弹在光标处，所以「右键点某处 + 这里的偏移」就是那一项的位置——
    录屏脚本的 click 只认固定偏移，必须先量出来再写死进动作计划。
    """
    out = {}
    for action in menu.actions():
        if action.isSeparator():
            continue
        rect = menu.actionGeometry(action)
        out[action.text().replace("&", "")] = {
            "cx": rect.x() + rect.width() // 2,
            "cy": rect.y() + rect.height() // 2,
        }
    return out


def measure_menus(win) -> dict:
    """量两个上下文菜单：格子上的（音量/画质/声道）和关注条目的（加入画面墙）。

    音量按钮自己没有菜单：右键落在按钮上会冒泡到格子，弹出的是**格子**的菜单
    （Tile.contextMenuEvent -> Tile.build_menu），所以声道那一组要从这里量。
    """
    from ddm.widgets import VolumeButton
    result = {"tile": {}, "nav": {}, "submenus": {}}

    tile = next((item for item in win.wall.tiles if item.isVisible()), None)
    buttons = tile.findChildren(VolumeButton) if tile is not None else []
    if tile is not None and buttons:
        menu = tile.build_menu()
        point = buttons[0].mapToGlobal(buttons[0].rect().center())
        menu.popup(point)
        QApplication.processEvents()
        time.sleep(0.4)
        QApplication.processEvents()
        result["tile"] = {
            "size": {"w": menu.width(), "h": menu.height()},
            "actions": menu_actions(menu),
            "origin": {
                "x": menu.pos().x() - point.x(),
                "y": menu.pos().y() - point.y(),
            },
        }
        # 「画质」/「声道」是子菜单：父项几何和子项几何都要量。
        # 点击路径是两步（先把光标移到父项把它展开，再点子项），而且之后光标会
        # 一直停在父项上，所以子项的坐标是相对**父项中心**算的，不是相对菜单原点。
        for action in menu.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            parent = menu.actionGeometry(action)
            parent_center = QPoint(parent.x() + parent.width() // 2,
                                   parent.y() + parent.height() // 2)
            submenu.popup(menu.mapToGlobal(parent_center))
            QApplication.processEvents()
            time.sleep(0.4)
            QApplication.processEvents()
            # 子菜单自己会被摆到父菜单右边，用菜单原点算偏移。
            # 减掉父项中心，就得到「光标停在父项中心时，子项在窗口内的哪一点」。
            offset = submenu.pos() - menu.pos()
            anchor_x, anchor_y = int(offset.x()), int(offset.y())
            center_x, center_y = int(parent_center.x()), int(parent_center.y())
            result["submenus"][action.text().replace("&", "")] = {
                "size": {"w": submenu.width(), "h": submenu.height()},
                "parent_center": {"cx": center_x, "cy": center_y},
                "parent_to_menu": {"x": anchor_x, "y": anchor_y},
                "actions": {
                    name: {
                        "cx": anchor_x + int(spot["cx"]) - center_x,
                        "cy": anchor_y + int(spot["cy"]) - center_y,
                    }
                    for name, spot in menu_actions(submenu).items()
                },
            }
            submenu.close()
            QApplication.processEvents()
        menu.close()
        menu.deleteLater()
        QApplication.processEvents()

    item = win.sidebar._items[0] if win.sidebar._items else None      # noqa: SLF001
    if item is not None:
        menu = item._context_menu()                                   # noqa: SLF001
        point = item.mapToGlobal(item.rect().center())
        menu.popup(point)
        QApplication.processEvents()
        time.sleep(0.4)
        QApplication.processEvents()
        result["nav"] = {
            "size": {"w": menu.width(), "h": menu.height()},
            "actions": menu_actions(menu),
            # 菜单左上角相对「右键点在哪」的偏移：Qt 把菜单摆在光标处，
            # 贴到屏幕边缘时会被推回来，录制脚本按这个偏移算菜单项位置。
            "origin": {
                "x": menu.pos().x() - point.x(),
                "y": menu.pos().y() - point.y(),
            },
        }
        menu.close()
        menu.deleteLater()
        QApplication.processEvents()
    return result


def collect(win) -> dict:
    app = QApplication.instance()
    win_rect = window_rect(win)
    offset = frame_offset(win)          # 必须先量：local() 依赖它做换算
    data = {
        "target": f"{TARGET_W}x{TARGET_H}",
        "window_rect": win_rect,
        "window_size": {"w": win_rect[2] - win_rect[0],
                        "h": win_rect[3] - win_rect[1]},
        "device_pixel_ratio": win.devicePixelRatioF(),
        "layout_id": win.wall.layout_id,
        "orientation": win.orientation,
        "sidebar": {
            "collapsed": bool(win.sidebar.collapsed),
            "card_mode": bool(win.sidebar.card_mode),
            "height": win.sidebar.height(),
            # 侧栏是竖排的，几个底栏控件的先后顺序会互相顶位置（多选条一露出来，
            # 下面的账号行/工具行/操作条都会往上挪），所以每个都量、都记可见性。
            "layout_button": local(win, win.sidebar.layout_button),
            "settings_button": local(win, win.sidebar.settings_button),
            "batch_button": local(win, win.sidebar.batch_button),
            "batch_bar": local(win, win.sidebar.batch_bar),
            "batch_cancel": local(win, win.sidebar.cancel_button),
            "account_row": local(win, win.sidebar.account_row),
            "tool_row": local(win, win.sidebar.tool_row),
            "normal_bar": local(win, win.sidebar.normal_bar),
            "list_box": local(win, win.sidebar.list_box),
            "scroll": local(win, win.sidebar.scroll),
            "items": [],
            "visible": {
                "batch_bar": bool(win.sidebar.batch_bar.isVisible()),
                "select_mode": bool(win.sidebar.select_mode),
            },
        },
        "tiles": measure_tiles(win),
        "picker": measure_picker(win, win.wall.layout_id),
        "menus": measure_menus(win),
    }
    # 坐标换算自检：窗口在屏幕上的物理矩形、Qt 认为的窗口全局原点、
    # 以及「布局预设」按钮的全局点 —— 三个数必须互相自洽，
    # 否则「窗口内坐标 -> 屏幕物理坐标」这一步就是错的（录制脚本按后者点击）。
    origin = win.mapToGlobal(win.rect().topLeft())
    button = win.sidebar.layout_button.mapToGlobal(
        win.sidebar.layout_button.rect().center())
    data["crosscheck"] = {
        "win32_rect": win_rect,
        "frame_offset": offset,
        "qt_window_origin": {"x": origin.x(), "y": origin.y()},
        "qt_layout_button": {"x": button.x(), "y": button.y()},
        "device_pixel_ratio": win.devicePixelRatioF(),
        "screen_dpr_at_origin": (
            app.screenAt(origin).devicePixelRatio() if app.screenAt(origin) else None),
    }
    for room_id, item in enumerate(win.sidebar._items):          # noqa: SLF001
        data["sidebar"]["items"].append(dict(
            local(win, item) or {},
            room=str(item.room.get("room_id") or ""),
            uname=item.room.get("uname", ""),
        ))
    danmaku = getattr(win.wall, "danmaku", None)
    if danmaku is not None:
        data["danmaku"] = dict(local(win, danmaku) or {},
                               visible=bool(danmaku.isVisible()))
    return data


def main() -> int:
    app = QApplication([sys.argv[0]])
    app.setApplicationName("DD监控室CE · measure")
    app.setStyleSheet(theme.qss())
    state = config_module.load()
    sidebar, wall = config_module.build_rooms(state) if state else ([], [])
    win = MainWindow(sidebar, wall,
                     layout_id=(state.get("ui") or {}).get("layout") or "",
                     state=state)
    win.showMaximized()             # 和 main() 一样：先把 saveGeometry 恢复完
    print(f"关注 {len(sidebar)} 个，画面墙 {len(wall)} 格")

    def run() -> None:
        error = None
        try:
            rect = force_geometry(win, TARGET_W, TARGET_H)
            QApplication.processEvents()
            time.sleep(1.0)                        # 等 resizeEvent 那一轮重排落地
            QApplication.processEvents()
            data = collect(win)
            with open(OUT, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
            print(f"窗口矩形 {data['window_rect']}  目标逻辑 {TARGET_W}x{TARGET_H}  "
                  f"DPR {data['device_pixel_ratio']}  布局 {data['layout_id']}")
            print(f"弹层尺寸 {data['picker']['size']}  写进 {OUT}")
        except Exception:                          # noqa: BLE001
            # 软件的日志刷屏会把 traceback 淹掉，单独落一份文件
            import traceback
            error = traceback.format_exc()
            with open(OUT + ".error.txt", "w", encoding="utf-8") as handle:
                handle.write(error)
        finally:
            # VLC 析构在退出瞬间会偶发崩，配置/输出都已经落盘，直接退最稳
            sys.stdout.flush()
            os._exit(1 if error else 0)

    QTimer.singleShot(6000, run)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
