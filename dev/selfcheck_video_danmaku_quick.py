"""Windows Quick checks; --surface-only covers monitors/fullscreen in a visible test window."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ["DDM_QTQUICK_DANMAKU"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from PySide6.QtTest import QTest

from ddm import config, theme
from ddm.auto_quality import AUTO_QUALITY
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from selfcheck_video_danmaku import Client, Snapshot


def settle(app, seconds=0.15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def capture(tile):
    screen = tile.screen()
    if screen is None:
        return QImage()
    point = tile.video.mapToGlobal(QPoint()) - screen.geometry().topLeft()
    return screen.grabWindow(0, point.x(), point.y(),
                             tile.video.width(), tile.video.height()).toImage()


def brightest_text(image, tile):
    scale = image.devicePixelRatioF()
    comment = tile.video_danmaku.comments[0]
    left = max(0, round(comment.x * scale))
    top = round(comment.lane * tile.video_danmaku.lane_height() * scale)
    width = round(comment.image.width() / comment.image.devicePixelRatioF() * scale)
    height = round(comment.image.height() / comment.image.devicePixelRatioF() * scale)
    return max(image.pixelColor(x, y).green()
               for y in range(top, min(image.height(), top + height))
               for x in range(left, min(image.width(), left + width)))


def check_screen_surfaces(app, window, layer, players):
    target = window.wall.tiles[0]
    handles = {tile: int(tile.video.winId()) for tile in window.wall.tiles}
    main_handle = int(window.winId())
    groups = dict(layer.groups)
    items = {key: record for key, record in layer.items.items()
             if record["group"] == target.video_danmaku._quick_group}
    before = [float(player._prop("time-pos", 0) or 0) for player in players]
    target.quality = AUTO_QUALITY  # Keep the synthetic video source in fullscreen.
    screens = app.screens()
    for screen in screens + screens[:1]:
        area = screen.availableGeometry()
        window._begin_interactive_resize()
        window.showNormal()
        window.setGeometry(area.x() + 30, area.y() + 30,
                           min(1100, area.width() - 60), min(700, area.height() - 60))
        window._finish_interactive_resize()
        window.activateWindow()
        settle(app, .5)
        assert window.screen() is screen, "Test window must reach the selected monitor"
        window.showMaximized()
        settle(app, .6)
        assert not layer._surface_dirty
        assert layer.window.parent() is None
        assert layer.window.position() == window.wall.mapToGlobal(QPoint())
        assert layer.window.size() == window.wall.size()
        desktop = capture(target)
        pixel = desktop.pixelColor(desktop.width() * 3 // 4, desktop.height() // 2)
        assert pixel.blue() > 180 and pixel.red() < 50, ("Maximized video hidden", screen.name(), pixel.name())
        print("maximized desktop video:", screen.name(), pixel.name())
        window.showNormal()
        settle(app, .4)
        for fullscreen in (True, False):
            if fullscreen:
                window._on_fullscreen(target)
            else:
                window._exit_fullscreen()
            window._clear_fullscreen_cover()
            target.set_controls_visible(True)
            target._controls_hide_timer.stop()
            settle(app, .6)
            assert not layer._surface_dirty and not layer._surface_reset.isActive()
            assert int(window.winId()) == main_handle
            assert all(tile in window.wall.tiles and int(tile.video.winId()) == handle
                       for tile, handle in handles.items())
            assert all(layer.groups.get(key) is group for key, group in groups.items())
            assert all(layer.items.get(key) is record for key, record in items.items()), \
                "Visible tile must retain its comment objects; hidden tiles may clear theirs"
            # Fullscreen changes mask geometry; every group must retain its source.
            assert all(layer.groups[record["group"]].property("maskLoaded")
                       for record in layer.items.values())
            assert all(record["item"].property("imageLoaded") for record in layer.items.values())
            image = layer.window.grabWindow()
            assert not image.isNull(), "Restored Quick surface must render"
            pixel = image.pixelColor(image.width() * 3 // 4, image.height() * 3 // 4)
            assert pixel.alpha() == 0, "Empty Quick surface must remain transparent"
            if int(ctypes.windll.user32.GetForegroundWindow()) == main_handle:
                desktop = capture(target)
                pixel = desktop.pixelColor(desktop.width() * 3 // 4, desktop.height() // 2)
                assert pixel.blue() > 180 and pixel.red() < 50, \
                    "Cross-screen fullscreen must show blue video underneath danmaku"
                print("desktop video visible:", screen.name(), fullscreen, pixel.name())
            print("surface recovered:", screen.name(), "DPR", screen.devicePixelRatio(),
                  "fullscreen", fullscreen, "alpha", image.hasAlphaChannel())
        window.showMaximized()
        settle(app, .4)
    assert all(float(player._prop("time-pos", 0) or 0) > old
               for player, old in zip(players, before)), "All local players must continue"
    print("Cross-screen/fullscreen surface, alpha, textures and stable video HWNDs: PASS")


def check_native_occlusion(app, owner, layer):
    foreground = int(ctypes.windll.user32.GetForegroundWindow())
    origin = layer.parent.mapToGlobal(QPoint())
    dialog = QDialog(owner)
    notice = QWidget(owner, Qt.Tool | Qt.WindowDoesNotAcceptFocus)
    try:
        for widget in (dialog, notice):
            widget.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
            widget.setAttribute(Qt.WA_ShowWithoutActivating)
            widget.setGeometry(origin.x() + 40, origin.y() + 40, 200, 120)
            widget.show()
            settle(app)
            point = widget.mapToGlobal(widget.rect().center()) - origin
            assert layer.parent.rect().contains(point), ('Dialog fixture outside wall', point, widget.geometry())
            assert not layer.window.mask().contains(point), 'Native overlay covers application UI'
            widget.move(origin.x() + 350, origin.y() + 200)
            settle(app)
            assert layer.window.mask().contains(point), 'Moving UI must restore old danmaku area'
            moved = widget.mapToGlobal(widget.rect().center()) - origin
            assert not layer.window.mask().contains(moved)
            widget.hide()
            settle(app)
            assert layer.window.mask().contains(moved), 'Closing UI must restore danmaku'
        assert int(ctypes.windll.user32.GetForegroundWindow()) == foreground, 'Background check stole focus'
    finally:
        dialog.close()
        notice.close()
def check_raster_fallback(app):
    from ddm.video_danmaku import VideoDanmaku

    owner = QWidget()
    owner.setAttribute(Qt.WA_ShowWithoutActivating)
    owner.setGeometry(-25000, -25000, 400, 240)
    with patch.dict(os.environ, {'DDM_QTQUICK_DANMAKU': '0'}):
        overlay = VideoDanmaku(owner)
    try:
        overlay.setGeometry(owner.rect())
        region = QRegion(owner.rect())
        overlay.setMask(region)
        overlay.set_enabled(True)
        overlay.set_active(True)
        owner.show()
        settle(app, .05)
        assert not overlay._quick_requested and overlay.mask() == region
        user32 = ctypes.windll.user32
        user32.GetLayeredWindowAttributes.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
                                                    ctypes.POINTER(wintypes.BYTE), ctypes.POINTER(wintypes.DWORD)]
        key, alpha, flags = wintypes.DWORD(), wintypes.BYTE(), wintypes.DWORD()
        assert user32.GetLayeredWindowAttributes(int(overlay.winId()), ctypes.byref(key),
                                               ctypes.byref(alpha), ctypes.byref(flags))
        assert flags.value & 1 and not overlay.mask().intersected(overlay.rect()).isEmpty(), \
            'Raster fallback must keep its visible color-key canvas'
    finally:
        owner.close()


def check_quick_controller_surface(tile):
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE]
    gdi32.CreateRectRgn.argtypes = [ctypes.c_int] * 4
    gdi32.CreateRectRgn.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.CombineRgn.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.c_int]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    region = gdi32.CreateRectRgn(0, 0, 0, 0)
    client_region = None
    try:
        overlay = tile.video_danmaku
        assert overlay._quick_requested
        assert overlay._quick_video_mask == tile.video.mask(), 'Quick logical clipping must retain video corners'
        assert overlay.mask().intersected(overlay.rect()).isEmpty(), 'Qt canvas clipping must exclude its client area'
        hwnd = int(overlay.winId())
        assert user32.GetWindowRgn(hwnd, region)
        bounds = wintypes.RECT()
        assert user32.GetClientRect(hwnd, ctypes.byref(bounds))
        client_region = gdi32.CreateRectRgn(0, 0, bounds.right, bounds.bottom)
        assert gdi32.CombineRgn(region, region, client_region, 1) == 1, \
            'Quick mode must not expose a second native raster canvas over the video and badges'
    finally:
        gdi32.DeleteObject(region)
        if client_region:
            gdi32.DeleteObject(client_region)


def check_quick_toggle_badges(tile):
    visible = tile._overlay_visible
    tile.set_controls_visible(True)
    badges = (tile.stream_badge, tile.title_badge, tile.controls)
    images = [badge.grab().toImage() for badge in badges]
    try:
        for _ in range(3):
            tile.video_danmaku.set_enabled(False)
            tile.video_danmaku.set_enabled(True)
            check_quick_controller_surface(tile)
            assert images == [badge.grab().toImage() for badge in badges], \
                'Opening Quick danmaku must not darken badge backgrounds or lose caption glyphs'
    finally:
        tile.set_controls_visible(visible)


def check_native_swap_submission(app, owner, layer):
    tiles = list(owner.wall.tiles)
    by_group = {tile.video_danmaku._quick_group: tile for tile in tiles}
    handles = {tile: int(tile.video.winId()) for tile in tiles}
    textures = {key: (record['item'], record['key']) for key, record in layer.items.items()}
    first = tiles[0]
    overlay_visible = first._overlay_visible
    first.set_controls_visible(True)
    first._control_hover_timer.stop()
    first._controls_hide_timer.stop()
    settle(app)
    caption_images = [badge.grab().toImage() for badge in (first.stream_badge, first.title_badge)]
    submitted = []
    original = layer.set_group_geometry
    user32 = ctypes.windll.user32
    user32.MapWindowPoints.argtypes = [wintypes.HWND, wintypes.HWND,
                                      ctypes.POINTER(wintypes.POINT), wintypes.UINT]

    def submit(identifier, x, y, width, height):
        tile = by_group[identifier]
        native = wintypes.POINT()
        user32.MapWindowPoints(handles[tile], int(owner.wall.winId()), ctypes.byref(native), 1)
        scale = owner.wall.devicePixelRatioF()
        assert abs(native.x - x * scale) <= 1 and abs(native.y - y * scale) <= 1, \
            'Quick geometry must match the already-moved native video HWND'
        original(identifier, x, y, width, height)
        submitted.append(identifier)

    try:
        with patch.object(layer, 'set_group_geometry', side_effect=submit), \
                patch('ddm.widgets.QCursor.pos', side_effect=lambda: first.mapToGlobal(first.rect().center())), \
                patch.object(first.stream_badge, 'repaint', wraps=first.stream_badge.repaint) as live_repaint, \
                patch.object(first.title_badge, 'repaint', wraps=first.title_badge.repaint) as title_repaint:
            owner.wall.tiles[0], owner.wall.tiles[1] = tiles[1], tiles[0]
            owner.wall.relayout(force=True)
            time.sleep(0.12)
            assert not submitted, 'A stalled GUI must not submit Quick positions inside native moves'
            for tile in tiles[:2]:
                group = layer.groups[tile.video_danmaku._quick_group]
                old_centre = QPoint(int(group.x() + group.width() / 2), int(group.y() + group.height() / 2))
                mask = layer.window.mask()
                assert not mask.isEmpty() and not mask.contains(old_centre), \
                    'Native mask must hide old-position textures during GUI stalls'
            unchanged = layer.groups[tiles[2].video_danmaku._quick_group]
            assert layer.window.mask().contains(QPoint(int(unchanged.x() + unchanged.width() / 2),
                                                      int(unchanged.y() + unchanged.height() / 2)))
            settle(app)
            assert {tiles[0].video_danmaku._quick_group,
                    tiles[1].video_danmaku._quick_group} <= set(submitted)
            assert not layer.window._move_regions, 'Fresh frames must restore all moved groups'
            assert live_repaint.called and title_repaint.called, 'Moved captions must request a fresh native repaint'
            assert caption_images == [badge.grab().toImage() for badge in (first.stream_badge, first.title_badge)], \
                'Caption glyphs and backgrounds must remain intact after native moves'
    finally:
        first.set_controls_visible(overlay_visible)
        owner.wall.tiles[:] = tiles
        owner.wall.relayout(force=True)
        settle(app)
    assert all(int(tile.video.winId()) == handle for tile, handle in handles.items())
    assert textures == {key: (record['item'], record['key']) for key, record in layer.items.items()}
    print('Native video HWND geometry before coalesced Quick swap submission: PASS')


def main():
    visible = "--visible" in sys.argv or "--surface-only" in sys.argv
    app = QApplication(sys.argv)
    if app.platformName() != "windows":
        print("跳过：需要 Windows 原生窗口")
        return
    app.setStyleSheet(theme.qss())
    check_raster_fallback(app)
    rooms = [{"room_id": str(1000 + i), "uname": f"本地视频 {i}", "live": True}
             for i in range(4)]
    with tempfile.TemporaryDirectory(prefix="ddm-video-dm-quick-") as temp, \
            patch("ddm.app.DanmakuClient", Client), patch("ddm.app.SuperChatSnapshot", Snapshot), \
            patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch("ddm.plugins.PluginManager.load"), patch("ddm.plugins.PluginManager.catalog", return_value=[]), \
            patch("ddm.online.load_plugin_cache", return_value={}):
        source = str(Path(temp) / "blue.mp4")
        subprocess.run([ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30",
                        "-t", "30", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", source], check=True)
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="2x2",
                            state={"plugins_enabled": [], "settings": {"auto_update": False}})
        if "--surface-only" in sys.argv:
            window.setWindowFlag(Qt.WindowStaysOnTopHint)
        window.setAttribute(Qt.WA_ShowWithoutActivating, not visible)
        window.setGeometry(40 if visible else -20000, 60 if visible else -20000, 1200, 800)
        window.show()
        if visible:
            window.activateWindow()
        user32 = ctypes.windll.user32
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = wintypes.LONG
        if visible:
            user32.SetForegroundWindow(int(window.winId()))
        settle(app, 0.3)
        try:
            players = []
            for tile in window.wall.tiles:
                player = TilePlayer(tile.video, tile, silent=True)
                window.players[tile] = player
                players.append(player)
                player.play(source)
                tile.set_video_active(True)
                tile.danmaku_button.setChecked(True)
                check_quick_controller_surface(tile)
                check_quick_toggle_badges(tile)
            settle(app, 2)
            assert all(float(player._prop("time-pos", 0) or 0) > 0
                       for player in players), "本地 libmpv 测试视频必须持续播放"
            assert window.wall._quick_danmaku_layer is None, "无弹幕消息时不应创建 Quick 窗口"

            for index, tile in enumerate(window.wall.tiles):
                overlay = tile.video_danmaku
                overlay.apply_settings(dict(config.DEFAULT_SETTINGS,
                                            video_danmaku_scale=False,
                                            video_danmaku_size=32,
                                            video_danmaku_area=100,
                                            video_danmaku_opacity=100))
                if index == 0:
                    emote_url = "https://example.invalid/quick-emote.png"
                    emote = QPixmap(32, 16)
                    emote.fill(QColor("#28d17c"))
                    overlay._images[emote_url] = emote.toImage()
                    event = {"text": "粉色 [小熊] 🫶", "color": "#ff77bb",
                             "emoticons": {"[小熊]": emote_url}}
                else:
                    event = {"text": f"GPU 场景图弹幕 {index} 🫶", "color": "#ffffff"}
                assert overlay.add_event(event)
                layer = window.wall._quick_danmaku_layer
                assert layer is not None, "首条弹幕应建立共享 Qt Quick 窗口"
                overlay.set_paused(True)
                comment = overlay.comments[0]
                comment.x = 36
                comment.lane = 2
                layer.move(comment.render_id, comment.x,
                           comment.lane * overlay.lane_height())
                layer.set_group_active(overlay._quick_group, False)

            target = window.wall.tiles[0]
            overlay = target.video_danmaku
            held = overlay.comments[0]
            with patch.object(overlay, '_poll_hover'):
                overlay.set_paused(False)
                overlay._set_hover(held)
                settle(app, .15)
                assert held.held and layer.items[held.render_id].get('held')
                assert layer.items[held.render_id]['item'].property('motionPaused')
                before = held.x
                settle(app, .15)
                assert held.x == before, 'Hovered Quick comment must remain still'
                overlay._set_hover(None)
                settle(app, .15)
                assert held.x < before and not layer.items[held.render_id].get('held')
                overlay.set_paused(True)
                held.x = 36
                layer.move(held.render_id, held.x, held.lane * overlay.lane_height())
            with patch('ddm.danmaku_actions.show_comment_menu') as toolbar:
                global_point = target.mapToGlobal(overlay.pos() + QPoint(46, held.lane * overlay.lane_height() + 8))
                point = target.video.mapFromGlobal(global_point)
                hit = overlay.mapFromGlobal(global_point)
                assert overlay.comment_at(hit) is held, (hit, held.x, held.lane, overlay.size(),
                    overlay._quick_video_mask.contains(hit), overlay.mask(),
                    held.image.size(), held.image.devicePixelRatioF(), len(overlay.comments))
                QTest.mouseClick(target.video, Qt.LeftButton, pos=point)
                toolbar.assert_called_once()
                assert toolbar.call_args.args[1] == held.event, 'Native video click must target the comment'
            assert layer.window.rendererInterface().graphicsApi().name == "Direct3D11"
            assert len(layer.groups) == 4
            assert all(tile.video_danmaku._quick_layer is layer for tile in window.wall.tiles)
            check_native_swap_submission(app, window, layer)
            for tile in window.wall.tiles:
                tile._round_video()
                check_quick_controller_surface(tile)
            assert all(layer.groups[tile.video_danmaku._quick_group].property("maskImage").scheme() == "image"
                       for tile in window.wall.tiles), "共享组必须获得控件/圆角遮罩纹理"
            overlay = target.video_danmaku
            overlay.set_super_chats([{
                "kind": "super_chat", "id": "sc-quick", "super_chat_id": "sc-quick",
                "uname": "老板", "message": "醒目留言", "price": 30,
                "start_time": int(time.time()),
                "end_time": int(time.time()) + 120,
                "background_color": "#ffdd00",
                "background_price_color": "#ff8800",
            }])
            settle(app)
            card_rect = overlay.super_chat_overlay.card_rects()[0]
            card_point = card_rect.center()
            local_card_point = card_point - overlay.super_chat_overlay._content_origin
            assert overlay.super_chat_overlay.mask().contains(local_card_point.toPoint()), \
                'SC sibling must use the video mask, not the hidden Quick controller mask'
            card_image = overlay.super_chat_overlay.render_image()
            card_scale = card_image.devicePixelRatio()
            assert card_image.pixelColor(round(local_card_point.x() * card_scale),
                                         round(local_card_point.y() * card_scale)).alpha() > 0, \
                'SC card pixels must actually be painted inside the visible region'
            mask_key = layer.group_masks[overlay._quick_group]
            mask_image = layer.images.images[mask_key]
            scale = mask_image.devicePixelRatioF()
            assert mask_image.pixelColor(round(card_point.x() * scale),
                                         round(card_point.y() * scale)).alpha() == 0, \
                "Quick 遮罩必须给固定 SC 卡片留出透明区域"
            normal_comment_point = target.video_danmaku.comments[0]
            normal_y = normal_comment_point.lane * overlay.lane_height()
            assert mask_image.pixelColor(
                round(12 * scale), round((normal_y + overlay.lane_height() / 2) * scale)
            ).alpha() > 0, "SC 区域之外必须继续显示普通弹幕"
            overlay.set_super_chats([])
            settle(app)
            mask_key = layer.group_masks[overlay._quick_group]
            mask_image = layer.images.images[mask_key]
            scale = mask_image.devicePixelRatioF()
            assert mask_image.pixelColor(round(card_point.x() * scale),
                                         round(card_point.y() * scale)).alpha() > 0
            if "--surface-only" in sys.argv:
                check_screen_surfaces(app, window, layer, players)
                return
            assert layer.window.parent() is None, "Quick overlay must not use a native child swap chain"
            assert layer.window.transientParent() is window.windowHandle()
            assert layer.window.flags() & Qt.WindowDoesNotAcceptFocus
            check_native_occlusion(app, window, layer)
            assert not user32.GetWindowLongW(int(layer.window.winId()), -16) & 0x40000000, \
                "Cross-monitor danmaku must not use WS_CHILD"
            frames = []
            layer.window.frameSwapped.connect(lambda: frames.append(time.perf_counter_ns()))
            for tile in window.wall.tiles:
                tile.video_danmaku.set_paused(False)
            deadline = time.monotonic() + 2
            while len(frames) <= 10 and time.monotonic() < deadline:
                settle(app, 0.05)
            assert len(frames) > 10, f"有滚动弹幕时 Quick 必须连续提交帧：{len(frames)} 帧"
            for tile in window.wall.tiles:
                tile.video_danmaku.set_paused(True)
            settle(app, 0.2)
            is_foreground = int(user32.GetForegroundWindow()) == int(window.winId())
            print("exposed=", layer.window.isExposed(),
                  "api=", layer.window.rendererInterface().graphicsApi().name,
                  "alpha_buffer=", layer.window.format().alphaBufferSize(),
                  "clear_color=", layer.window.color().getRgb(),
                  "provider_keys=", list(layer.images.images),
                  "foreground=", hex(int(user32.GetForegroundWindow())),
                  "main_hwnd=", hex(int(window.winId())),
                  "items=", len(layer.items), "groups=", len(layer.groups))
            for record in layer.items.values():
                assert record["item"].property("imageSource").scheme() == "image"
            assert all(record["item"].property("imageLoaded")
                       for record in layer.items.values()), "QML Image 必须成功载入 Qt 纹理提供器"
            assert all(group.property("maskLoaded") for group in layer.groups.values()), \
                "QML MultiEffect 必须载入每格透明区域遮罩"
            assert all(layer.groups[tile.video_danmaku._quick_group].property("content").childItems()
                       for tile in window.wall.tiles), "每个 Quick 裁剪组都必须包含弹幕纹理项"
            assert layer.groups[target.video_danmaku._quick_group].property("rounded") is True
            target.set_controls_visible(True)
            target._controls_hide_timer.stop()
            settle(app)
            mask_key = layer.group_masks[target.video_danmaku._quick_group]
            mask_image = layer.images.images[mask_key]
            control_origin = target.controls.pos() - target.video_danmaku.pos()
            control_point = control_origin + QPoint(target.controls.width() // 2,
                                                     target.controls.height() // 2)
            scale = mask_image.devicePixelRatioF()
            assert mask_image.pixelColor(round(control_point.x() * scale),
                                         round(control_point.y() * scale)).alpha() == 0, \
                "Quick 遮罩必须给视频控制浮层留透明区域"

            # Read the Quick framebuffer, without sampling or activating the desktop.
            overlay = target.video_danmaku
            comment = overlay.comments[0]
            comment.x = max(0, control_origin.x() - 40)
            comment.lane = 0
            layer.move(comment.render_id, comment.x, 0)
            target.set_controls_visible(False)
            settle(app)
            group = layer.groups[overlay._quick_group]
            frame = layer.window.grabWindow()
            assert not frame.isNull(), "必须能读取 Quick 渲染帧"
            frame_scale = frame.devicePixelRatioF()
            area = QRect(round((group.x() + comment.x) * frame_scale),
                         round(group.y() * frame_scale),
                         round((overlay.width() - comment.x) * frame_scale),
                         round(overlay.lane_height() * frame_scale))
            baseline = frame.copy(area)
            assert any(baseline.pixelColor(x, y).alpha() > 100
                       for y in range(baseline.height()) for x in range(baseline.width()))
            image_key, render_id = comment.image.cacheKey(), comment.render_id
            for _ in range(3):
                target.set_controls_visible(True)
                settle(app)
                assert layer.window.grabWindow().copy(area) != baseline, \
                    "显示按钮时应只遮住按钮位置的弹幕"
                target.set_controls_visible(False)
                settle(app)
                assert layer.window.grabWindow().copy(area) == baseline, \
                    "收起悬浮条后原有弹幕必须完整恢复，不能保留截断"
                assert comment.image.cacheKey() == image_key and comment.render_id == render_id
            comment.x, comment.lane = 36, 2
            layer.move(comment.render_id, comment.x, comment.lane * overlay.lane_height())
            print("Quick framebuffer: hover occlusion restores the same comment texture after repeated hide/show")

            overlay = target.video_danmaku
            comment = overlay.comments[0]
            colors = [comment.image.toImage().pixelColor(x, y)
                      for y in range(comment.image.height())
                      for x in range(comment.image.width())]
            assert any(color.alpha() > 220 and color.red() > color.green() + 30
                       and color.blue() > color.green() + 30 for color in colors), \
                "颜色弹幕必须保留原文字颜色"
            assert any(color.alpha() > 220 and color.green() > color.red() + 30
                       for color in colors), "内联表情必须保留源图颜色"
            old_height = comment.image.height()
            overlay.apply_settings(dict(overlay.settings, video_danmaku_size=40))
            assert comment.image.height() > old_height, "字号变化必须重建 Quick 纹理"
            settle(app)
            assert all(record["item"].property("imageLoaded")
                       for record in layer.items.values()), "重建后的纹理也必须重新载入"
            large_height = comment.image.height()
            overlay.apply_settings(dict(overlay.settings, video_danmaku_scale=True))
            assert comment.image.height() < large_height, "随格子缩放必须更新纹理尺寸"
            overlay.apply_settings(dict(overlay.settings, video_danmaku_scale=False,
                                        video_danmaku_size=32))
            settle(app)
            overlay.apply_settings(dict(overlay.settings, video_danmaku_opacity=20))
            assert abs(layer.groups[overlay._quick_group].opacity() - .2) < .001
            overlay.apply_settings(dict(overlay.settings, video_danmaku_opacity=100))

            for width in (1, 6):
                overlay.apply_settings(dict(overlay.settings, video_danmaku_outline_width=width))
                settle(app)
                assert all(record["item"].property("imageLoaded")
                           for record in layer.items.values())
                image = comment.image.toImage()
                assert any(image.pixelColor(x, y).alpha() > 220 and
                           max(image.pixelColor(x, y).red(), image.pixelColor(x, y).green(),
                               image.pixelColor(x, y).blue()) < 15
                           for y in range(image.height()) for x in range(image.width())), \
                    "开启描边后 Quick 贴图必须含有黑色边缘"
            overlay.apply_settings(dict(overlay.settings, video_danmaku_outline_width=0))

            user32.WindowFromPoint.argtypes = [wintypes.POINT]
            user32.WindowFromPoint.restype = wintypes.HWND
            point = target.video.mapToGlobal(target.video.rect().center())
            hit = user32.WindowFromPoint(wintypes.POINT(point.x(), point.y()))
            style = user32.GetWindowLongW(int(layer.window.winId()), -20)
            assert style & 0x00000020, "Quick HWND 必须带 WS_EX_TRANSPARENT"
            if visible and is_foreground:
                high_image = capture(target)
                shot = Path(__file__).resolve().parents[1] / "work" / "danmaku-smoothness" / "qquick-selfcheck.png"
                high_image.save(str(shot))
                layer.window.hide()
                settle(app, 0.1)
                underlay = capture(target)
                underlay.save(str(shot.with_name("qquick-selfcheck-underlay.png")))
                layer.window.show()
                layer.raise_()
                settle(app, 0.1)
                assert int(hit or 0) != int(layer.window.winId()), "Quick 窗口必须鼠标穿透"
                high = brightest_text(high_image, target)
                center = high_image.pixelColor(high_image.width() // 2, high_image.height() // 2)
                base = underlay.pixelColor(underlay.width() // 2, underlay.height() // 2)
                print("quick_center=", center.name(), "underlay_center=", base.name())
                assert high > 190, "前台窗口截图应看到弹幕"
                assert center.blue() > 200 and center.red() < 40, "透明区域不能遮黑 libmpv 视频"
            else:
                print("未采集桌面；本次不核验 Quick 与 libmpv 的最终桌面合成像素")

            x = comment.x
            settle(app, 0.12)
            assert comment.x == x, "暂停期间弹幕位置必须保持不变"
            overlay.set_paused(False)
            settle(app, 0.08)
            assert overlay.timer.isActive(), "恢复后滚动计时器必须重新启动"
            overlay.set_paused(True)
            target.pause_button.click()
            assert target.paused and target.pause_button.paused, "暂停按钮必须切换原有播放状态"
            target.pause_button.click()
            assert not target.paused and not target.pause_button.paused, "暂停按钮必须恢复播放"

            group = overlay._quick_group
            if visible:
                window._on_fullscreen(target)
            else:
                window.wall.set_fullscreen_tile(target)
            window._clear_fullscreen_cover()
            target.set_controls_visible(True)
            target._controls_hide_timer.stop()
            settle(app)
            assert overlay._quick_group == group and not layer.groups[group].property("rounded")
            mask_key = layer.group_masks[group]
            mask_image = layer.images.images[mask_key]
            pause_point = (target.bottom.pos() - overlay.pos() + target.pause_button.pos()
                           + QPoint(target.pause_button.width() // 2,
                                    target.pause_button.height() // 2))
            scale = mask_image.devicePixelRatioF()
            assert mask_image.pixelColor(round(pause_point.x() * scale),
                                         round(pause_point.y() * scale)).alpha() == 0, \
                "Quick 遮罩必须给全屏暂停按钮留透明区域"
            if visible:
                window._exit_fullscreen()
            else:
                window.wall.set_fullscreen_tile(None)
            window._clear_fullscreen_cover()
            settle(app)
            assert layer.groups[group].property("rounded")

            for tile in window.wall.tiles:
                tile.video_danmaku.clear()
            frames.clear()
            idle_start = time.perf_counter_ns()
            settle(app, 0.6)
            late_frames = [stamp for stamp in frames if stamp - idle_start > 200_000_000]
            assert not late_frames, ("清空后的场景必须停止持续刷新；"
                                     f"总帧={len(frames)}，末帧延迟="
                                     f"{(frames[-1] - idle_start) / 1e6 if frames else None}ms")
            assert not layer.window.isVisible(), "Clearing all comments must hide the shared window"
            assert overlay.add_event({"text": "resume after empty scene"})
            settle(app, .15)
            assert layer.window.isVisible(), "A new comment must restore the overlay"
            overlay.clear()
            settle(app, .1)
            assert not layer.window.isVisible()
            print("共享 Quick 窗口、D3D11、4 格纹理、不透明度状态、鼠标穿透样式、暂停/恢复、全屏圆角状态及空闲停刷：通过")
        finally:
            window.settings["close_behavior"] = "exit"
            window.close()


if __name__ == "__main__":
    main()
