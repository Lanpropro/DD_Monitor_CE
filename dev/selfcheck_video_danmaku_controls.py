"""画面弹幕观看浮层、全屏连续性、完整字形边界的离线回归。"""
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from ddm import config, theme
from ddm.app import MainWindow
from ddm.widgets import Tile
from selfcheck_video_danmaku import Client, Snapshot


def progress(overlay, comment):
    return (overlay.width() - comment.x) / (
        overlay.width() + comment.image.width() / comment.image.devicePixelRatioF())


def check_text_style(overlay):
    overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False))
    for color in (QColor("#ffffff"), QColor("#ff6699")):
        image = overlay._render_text("对吧，可爱吧？gyp", color).toImage()
        pixels = [image.pixelColor(x, y) for y in range(image.height())
                  for x in range(image.width())]
        assert any(pixel.alpha() > 240 and
                   max(abs(pixel.red() - color.red()), abs(pixel.green() - color.green()),
                       abs(pixel.blue() - color.blue())) < 8 for pixel in pixels), \
            "弹幕必须保留明亮字芯及平台指定的文字颜色"
        assert not any(pixel.alpha() >= 32 and
                       max(abs(pixel.red() - color.red()), abs(pixel.green() - color.green()),
                           abs(pixel.blue() - color.blue())) > 8 for pixel in pixels), \
            "默认弹幕不应带有黑色描边或阴影"
    print("PASS: bright white/colored text retains its color without a black outline or shadow")


def check_outline(overlay):
    emote = QPixmap(24, 24)
    emote.fill(QColor("#28d17c"))
    url = "https://example.invalid/outline-emote.png"
    overlay._images[url] = emote.toImage()
    for runs in ([("描边 gyp", "")], [("描边 gyp", ""), ("[emoji]", url)]):
        counts = []
        for width in (1, 2, 6):
            overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False,
                                        video_danmaku_outline_width=width))
            image = overlay._render_content("描边 gyp", QColor("#ff77bb"), runs).toImage()
            pixels = [image.pixelColor(x, y) for y in range(image.height())
                      for x in range(image.width())]
            counts.append(sum(p.alpha() > 200 and max(p.red(), p.green(), p.blue()) < 15
                              for p in pixels))
            assert any(p.alpha() > 220 and p.red() > 200 and p.blue() > 150 for p in pixels)
            if len(runs) > 1:
                assert any(p.alpha() > 220 and p.green() > 180 and p.red() < 70 for p in pixels)
            assert all(image.pixelColor(x, y).alpha() == 0
                       for x in range(image.width()) for y in (0, image.height() - 1))
            assert all(image.pixelColor(x, y).alpha() == 0
                       for y in range(image.height()) for x in (0, image.width() - 1))
        assert 0 < counts[0] < counts[1] < counts[2], counts
    emote.fill(QColor(40, 209, 124, 128))
    overlay._images[url] = emote.toImage()
    image = overlay._render_content("描边", QColor("#ff77bb"),
                                    [("描边", ""), ("[emoji]", url)]).toImage()
    greens = [image.pixelColor(x, y) for y in range(image.height())
              for x in range(image.width())
              if image.pixelColor(x, y).green() > 180 and image.pixelColor(x, y).red() < 70]
    alphas = sorted(pixel.alpha() for pixel in greens)
    assert alphas and 125 <= alphas[len(alphas) // 2] <= 130, \
        "描边不能让半透明表情被重复绘制而加深"
    overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False))
    print("PASS: adjustable black outlines preserve text/emote colors and glyph padding")


def check_text(app):
    tile = Tile({"room_id": "1", "live": True})
    tile.resize(900, 540)
    tile.show()
    app.processEvents()
    overlay = tile.video_danmaku
    tile.set_video_active(True)
    tile.danmaku_button.setChecked(True)
    try:
        check_text_style(overlay)
        check_outline(overlay)
        for size in (12, 28, 48, 64):
            overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_size=size,
                                        video_danmaku_scale=False))
            for text in ("虞出 合成大西瓜", "gypjq 吃西瓜", "这是默认字体的完整下沿"):
                overlay.clear()
                assert overlay.add_event({"text": text})
                image = overlay.comments[0].image.toImage()
                points = [(x, y) for y in range(image.height()) for x in range(image.width())
                          if image.pixelColor(x, y).alpha()]
                assert points
                assert min(x for x, y in points) >= 2
                assert min(y for x, y in points) >= 2
                assert max(x for x, y in points) < image.width() - 2
                assert max(y for x, y in points) < image.height() - 2, (size, text)
        overlay.set_paused(True)
        comment = overlay.comments[0]
        comment.x = 80
        before = progress(overlay, comment)
        image_key = comment.image.cacheKey()
        overlay.apply_settings(dict(overlay.settings, video_danmaku_opacity=25))
        assert overlay.comments == [comment] and comment.image.cacheKey() == image_key
        assert abs(progress(overlay, comment) - before) < 1e-6
        speed = comment.speed
        overlay.apply_settings(dict(overlay.settings, video_danmaku_speed=200))
        assert abs(comment.speed - speed * 2) < 1e-6
        overlay.apply_settings(dict(overlay.settings, video_danmaku_size=32))
        assert comment.image.cacheKey() != image_key
        assert abs(progress(overlay, comment) - before) < 1e-6
        tile.hide()
        tile.resize(1600, 900)
        tile.show()
        app.processEvents()
        assert overlay.comments == [comment] and abs(progress(overlay, comment) - before) < 1e-6, \
            (len(overlay.comments), before, progress(overlay, comment), overlay.size(), comment.x)
        assert not overlay.timer.isActive(), "暂停中的弹幕在缩放或重新显示时仍应暂停"
        tile.set_room({"room_id": "2", "live": True})
        assert not overlay.comments
    finally:
        tile.close()
    print("PASS: default CJK/descenders have padding, live changes retain progress and pixmaps, hide/resize retains paused comments")


def check_controls(app):
    rooms = [{"room_id": str(i), "uname": str(i), "live": True} for i in (1001, 1002)]
    with patch("ddm.app.DanmakuClient", Client), patch("ddm.app.SuperChatSnapshot", Snapshot), \
            patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="1x2",
                            state={"plugins_enabled": []})
        window.resize(1200, 760)
        window.show()
        app.processEvents()
        first, second = window.wall.tiles
        try:
            for tile in window.wall.tiles:
                tile.set_video_active(True)
                tile.danmaku_button.setChecked(True)
                assert tile.video_danmaku.add_event({"text": "全屏切换时继续滚动"})
                tile.video_danmaku.set_paused(True)
            overlay = first.video_danmaku
            comment = overlay.comments[0]
            comment.x = 50
            before = progress(overlay, comment)
            QTest.mouseClick(first.danmaku_settings_button, Qt.LeftButton)
            app.processEvents()
            menu = first.danmaku_settings_menu
            assert menu.isVisible() and QApplication.activePopupWidget() is menu
            assert menu.geometry().bottom() < first.danmaku_settings_button.mapToGlobal(QPoint()).y()
            slider = menu.controls["video_danmaku_size"]
            slider.setFocus()
            QTest.keyClick(slider, Qt.Key_Right)
            assert window.settings["video_danmaku_size"] == config.DEFAULT_SETTINGS["video_danmaku_size"] + 1
            for key, value in (("video_danmaku_area", 25), ("video_danmaku_opacity", 45),
                               ("video_danmaku_speed", 150), ("super_chat_collapse_delay", 12),
                               ("super_chat_scale", 135)):
                menu.controls[key].setValue(value)
                assert window.settings[key] == value
                assert second.video_danmaku.settings[key] == value
                assert second.danmaku_settings_menu.controls[key].value() == value
                assert window.current_state()['settings'][key] == value
            first.video_danmaku.superChatSettingsChanged.emit({'super_chat_position': [0.0, 1.0]})
            assert window.current_state()['settings']['super_chat_position'] == [0.0, 1.0]
            assert second.video_danmaku.settings['super_chat_position'] == [0.0, 1.0]
            QTest.mouseClick(menu.scale, Qt.LeftButton, pos=QPoint(8, menu.scale.height() // 2))
            assert window.settings["video_danmaku_scale"] is False
            assert second.video_danmaku.settings["video_danmaku_scale"] is False
            width_slider = menu.controls["video_danmaku_outline_width"]
            assert width_slider.minimum() == 0 and width_slider.isEnabled()
            assert width_slider.value() == 0
            assert not hasattr(menu, "outline"), "描边只保留从零开始的宽度滑条"
            image_key = comment.image.cacheKey()
            for width in (1, 6, 2, 0):
                width_slider.setValue(width)
                assert window.settings["video_danmaku_outline_width"] == width
                assert second.video_danmaku.settings["video_danmaku_outline_width"] == width
                assert window.current_state()["settings"]["video_danmaku_outline_width"] == width
                assert second.danmaku_settings_menu.controls["video_danmaku_outline_width"].value() == width
                assert bool(overlay.outline_width()) == bool(width)
            assert comment.image.cacheKey() != image_key
            assert "video_danmaku_outline" not in window.current_state()["settings"]
            assert overlay.comments == [comment] and abs(progress(overlay, comment) - before) < 1e-6
            assert window._save_timer.isActive()
            assert window.current_state()["settings"]["video_danmaku_opacity"] == 45
            QTest.keyClick(menu, Qt.Key_Escape)
            assert not menu.isVisible()
            QTest.mouseClick(first.danmaku_settings_button, Qt.LeftButton)
            assert menu.labels["video_danmaku_opacity"].text() == "45%"
            menu.hide()
            with patch.object(window, "open_settings") as advanced:
                menu.actions()[-1].trigger()
                advanced.assert_called_once_with("danmaku")
            def inspect_settings(dialog):
                assert dialog.nav.currentRow() == 2
                return QDialog.Rejected
            with patch("ddm.app.SettingsDialog.exec", inspect_settings):
                assert window.open_settings("danmaku") is False
            window._on_fullscreen(first)
            window._clear_fullscreen_cover()
            app.processEvents()
            assert overlay.comments == [comment] and abs(progress(overlay, comment) - before) < 1e-6
            first.set_fullscreen_controls_hidden(True)
            assert overlay.comments == [comment] and not overlay.timer.isActive()
            first.set_fullscreen_controls_hidden(False)
            QTest.mouseClick(first.danmaku_settings_button, Qt.LeftButton)
            assert menu.isVisible(), "全屏时仍可打开右下角观看设置"
            menu.hide()
            window._exit_fullscreen()
            window._clear_fullscreen_cover()
            app.processEvents()
            assert overlay.comments == [comment] and abs(progress(overlay, comment) - before) < 1e-6
        finally:
            window.close()
    # 最窄格子保留输入空间，观看设置可从右键菜单打开；宽格保留齿轮。
    tile = Tile({"room_id": "1", "live": True})
    tile.show()
    try:
        for width in (200, 220, 240, 260, 280, 300, 320, 360, 420, 900):
            tile.resize(width, 540)
            tile.set_recording_state("record")
            tile.set_recording_elapsed("12:34:56")
            app.processEvents()
            controls = [tile.pause_button, tile.volume_button, tile.volume_slider,
                        tile.volume_label, tile.danmaku_button, tile.danmaku_settings_button,
                        tile.recording_button, tile.recording_time, tile.fullscreen_button]
            visible = [w for w in controls if w.isVisible()]
            if width >= 300:
                assert tile.danmaku_settings_button.isVisible()
            else:
                menu = tile.build_menu()
                action = next((a for a in menu.actions() if a.text() == "弹幕观看设置…"), None)
                assert action is not None, "窄格隐藏齿轮后仍需可用的观看设置入口"
                action.trigger()
                app.processEvents()
                assert tile.danmaku_settings_menu.isVisible()
                assert tile.danmaku_settings_menu.controls["video_danmaku_size"].isEnabled()
                tile.danmaku_settings_menu.hide()
                menu.deleteLater()
            assert all(w.x() >= 0 and w.geometry().right() < tile.bottom.width() for w in visible), width
            assert all(a.geometry().right() < b.geometry().left() for a, b in zip(visible, visible[1:])), \
                (width, [w.geometry() for w in visible])
    finally:
        tile.close()
    print("PASS: real popup/keyboard/checkbox, shared settings/save, advanced link, fullscreen continuity and narrow controls")


def check_overlay_mask(app):
    tile = Tile({"room_id": "1", "uname": "Mask regression", "live": True})
    tile.resize(900, 540)
    tile.show()
    app.processEvents()
    overlay = tile.video_danmaku
    layer = MagicMock()
    overlay._quick_layer, overlay._quick_group = layer, 1
    overlay._quick_mask_signature = None
    try:
        tile.set_controls_visible(True)
        image = layer.set_group_mask.call_args.args[1]
        origin = tile.controls.pos() - overlay.pos()
        button_point = origin + tile.reload_button.geometry().center()
        scale = image.devicePixelRatioF()
        alpha = lambda image, point: image.pixelColor(round(point.x() * scale),
                                                     round(point.y() * scale)).alpha()
        assert alpha(image, button_point) == 0
        # Hiding controls does not change the cached video geometry.
        tile.set_controls_visible(False)
        hidden = layer.set_group_mask.call_args.args[1]
        for point in (QPoint(10, 10), QPoint(overlay.width() - 11, 10)):
            assert alpha(hidden, point) == 255, '透明圆角补边不能挖掉12像素方块弹幕'
        assert alpha(hidden, QPoint(0, 0)) == 0, '视频外侧仍应保留圆角裁切'
        assert alpha(hidden, button_point) == 255, ("收起悬浮条后必须恢复弹幕遮罩",
            button_point, overlay.size(), tile.controls.isVisible(),
            overlay._quick_mask_signature, alpha(hidden, button_point))
        for _ in range(3):
            tile.set_controls_visible(True)
            image = layer.set_group_mask.call_args.args[1]
            gap = origin + QPoint(tile.quality_button.geometry().right() + 2,
                                  tile.reload_button.geometry().center().y())
            assert not tile.controls.mask().contains(gap - origin)
            assert alpha(image, gap) == 255, "按钮之间的透明间隙不能裁掉弹幕"
            tile.set_controls_visible(False)
            assert alpha(layer.set_group_mask.call_args.args[1], button_point) == 255
    finally:
        overlay._quick_layer, overlay._quick_group = None, None
        tile.close()
    print("PASS: hover mask restores after hide and preserves transparent control gaps")


def check_outline_migration(app):
    cases = [({}, 0), ({"video_danmaku_outline_width": 0}, 0),
             ({"video_danmaku_outline_width": 4}, 4),
             ({"video_danmaku_outline": False, "video_danmaku_outline_width": 4}, 0),
             ({"video_danmaku_outline": True, "video_danmaku_outline_width": 3}, 3),
             ({"video_danmaku_outline": True}, 2)]
    with patch("ddm.app.DanmakuClient", Client), patch("ddm.app.SuperChatSnapshot", Snapshot), \
            patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        for settings, expected in cases:
            window = MainWindow([], [], state={"plugins_enabled": [], "settings": settings})
            try:
                saved = window.current_state()["settings"]
                assert saved["video_danmaku_outline_width"] == expected, (settings, saved)
                assert "video_danmaku_outline" not in saved
            finally:
                window.close()
                app.processEvents()
    print("PASS: outline settings migrate the legacy toggle and preserve zero on reload")


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    check_text(app)
    check_controls(app)
    check_overlay_mask(app)
    check_outline_migration(app)


if __name__ == "__main__":
    main()
