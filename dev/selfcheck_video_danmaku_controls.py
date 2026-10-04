"""画面弹幕观看浮层、全屏连续性、完整字形边界的离线回归。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from ddm import config, theme
from ddm.app import MainWindow
from ddm.widgets import Tile
from selfcheck_video_danmaku import Client


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
    with patch("ddm.app.DanmakuClient", Client), patch.object(MainWindow, "start_tile"), \
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
                               ("video_danmaku_speed", 150)):
                menu.controls[key].setValue(value)
                assert window.settings[key] == value
                assert second.video_danmaku.settings[key] == value
                assert second.danmaku_settings_menu.controls[key].value() == value
            QTest.mouseClick(menu.scale, Qt.LeftButton, pos=QPoint(8, menu.scale.height() // 2))
            assert window.settings["video_danmaku_scale"] is False
            assert second.video_danmaku.settings["video_danmaku_scale"] is False
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
                assert dialog.nav.currentRow() == 1
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
    # 最窄格子、录制时长出现时仍能看到并点击弹幕设置。
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
            assert tile.danmaku_settings_button.isVisible()
            assert all(w.x() >= 0 and w.geometry().right() < tile.bottom.width() for w in visible), width
            assert all(a.geometry().right() < b.geometry().left() for a, b in zip(visible, visible[1:])), \
                (width, [w.geometry() for w in visible])
    finally:
        tile.close()
    print("PASS: real popup/keyboard/checkbox, shared settings/save, advanced link, fullscreen continuity and narrow controls")


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    check_text(app)
    check_controls(app)


if __name__ == "__main__":
    main()
