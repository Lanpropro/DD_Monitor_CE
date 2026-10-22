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
from PySide6.QtGui import QColor, QCursor, QPixmap
from PySide6.QtWidgets import QApplication

from ddm import config, theme
from ddm.auto_quality import AUTO_QUALITY
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from selfcheck_video_danmaku import Client


def settle(app, seconds=0.15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def capture(tile):
    point = tile.video.mapToGlobal(QPoint()) - tile.screen().geometry().topLeft()
    return tile.screen().grabWindow(0, point.x(), point.y(),
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


def main():
    visible = "--visible" in sys.argv or "--surface-only" in sys.argv
    app = QApplication(sys.argv)
    if app.platformName() != "windows":
        print("跳过：需要 Windows 原生窗口")
        return
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": str(1000 + i), "uname": f"本地视频 {i}", "live": True}
             for i in range(4)]
    with tempfile.TemporaryDirectory(prefix="ddm-video-dm-quick-") as temp, \
            patch("ddm.app.DanmakuClient", Client), patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        source = str(Path(temp) / "blue.mp4")
        subprocess.run([ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30",
                        "-t", "30", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", source], check=True)
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="2x2",
                            state={"plugins_enabled": []})
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
            assert layer.window.rendererInterface().graphicsApi().name == "Direct3D11"
            assert len(layer.groups) == 4
            assert all(tile.video_danmaku._quick_layer is layer for tile in window.wall.tiles)
            assert all(layer.groups[tile.video_danmaku._quick_group].property("maskImage").scheme() == "image"
                       for tile in window.wall.tiles), "共享组必须获得控件/圆角遮罩纹理"
            if "--surface-only" in sys.argv:
                check_screen_surfaces(app, window, layer, players)
                return
            assert layer.window.parent() is None, "Quick overlay must not use a native child swap chain"
            assert layer.window.transientParent() is window.windowHandle()
            assert layer.window.flags() & Qt.WindowDoesNotAcceptFocus
            assert not user32.GetWindowLongW(int(layer.window.winId()), -16) & 0x40000000, \
                "Cross-monitor danmaku must not use WS_CHILD"
            frames = []
            layer.window.frameSwapped.connect(lambda: frames.append(time.perf_counter_ns()))
            for tile in window.wall.tiles:
                tile.video_danmaku.set_paused(False)
            settle(app, 0.3)
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
            window.close()


if __name__ == "__main__":
    main()
