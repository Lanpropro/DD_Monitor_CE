"""滚动文字改色回归；隔离数据，不连接直播或加载本机插件。"""
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QWidget

from ddm import config, theme
from ddm.app import MainWindow
from ddm.danmaku_raster import CommentRaster
from ddm.video_danmaku import VideoDanmaku
from selfcheck_video_danmaku import Client, Snapshot, wait_comment_raster


def has_color(image, color):
    target = QColor(color)
    return any(pixel.alpha() > 220 and
               max(abs(pixel.red() - target.red()), abs(pixel.green() - target.green()),
                   abs(pixel.blue() - target.blue())) < 8
               for y in range(image.height()) for x in range(image.width())
               for pixel in (image.pixelColor(x, y),))


def check_recolor(app):
    overlay = VideoDanmaku()
    overlay.set_native_video(False)
    overlay.resize(900, 500)
    settings = dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False)
    overlay.apply_settings(settings)
    overlay.set_enabled(True)
    overlay.set_active(True)
    try:
        assert overlay._comment_color({}).name() == '#ffffff'
        assert overlay._comment_color({'color': 'invalid'}).name() == '#ffffff'
        assert overlay.add_event({'text': 'Blue original', 'color': '#0000ff'})
        wait_comment_raster(app, overlay)
        overlay.set_paused(True)
        comment = overlay.comments[0]
        comment.x = 120
        assert has_color(comment.image.toImage(), '#0000ff')
        entered, release = threading.Event(), threading.Event()
        original = CommentRaster._render_content

        def blocked(renderer, *args):
            entered.set()
            assert release.wait(5)
            return original(renderer, *args)

        with patch.object(CommentRaster, '_render_content', blocked):
            settings.update(video_danmaku_color_mode='custom', video_danmaku_color='#ff0000')
            overlay.apply_settings(settings)
            deadline = time.monotonic() + 3
            while not entered.is_set():
                assert time.monotonic() < deadline
                QTest.qWait(5)
            # Keep an old red batch in flight while the user switches to white.
            overlay.set_paused(False)
            assert overlay.add_event({'text': 'Pending blue', 'color': '#0000ff'})
            overlay.set_paused(True)
            settings['video_danmaku_color'] = '#ffffff'
            overlay.apply_settings(settings)
            release.set()
            wait_comment_raster(app, overlay)
        assert len(overlay.comments) == 2 and overlay.comments[0] is comment
        assert abs(comment.x - 120) < 2, 'Changing color must not restart comment motion'
        assert all(has_color(c.image.toImage(), '#ffffff') for c in overlay.comments)
        settings['video_danmaku_color_mode'] = 'original'
        overlay.apply_settings(settings)
        wait_comment_raster(app, overlay)
        assert all(has_color(c.image.toImage(), '#0000ff') for c in overlay.comments)
        assert all(c.event['color'] == '#0000ff' for c in overlay.comments)
        # Mixed text/images: tint only the text, retaining image pixels.
        emote = QImage(24, 24, QImage.Format_ARGB32_Premultiplied)
        emote.fill(QColor('#28d17c'))
        overlay._images['fixture-emote'] = emote
        settings.update(video_danmaku_color_mode='custom', video_danmaku_color='#ff0000')
        overlay.apply_settings(settings)
        renderer = overlay._comment_renderer()
        image = renderer._render_content('Text', overlay._comment_color({}),
                                         [('Text', ''), ('[emote]', 'fixture-emote')])
        assert has_color(image, '#ff0000') and has_color(image, '#28d17c')
        settings['video_danmaku_color'] = 'invalid'
        overlay.apply_settings(settings)
        assert overlay._comment_color({'color': '#0000ff'}).name() == '#ffffff'
        wait_comment_raster(app, overlay)
    finally:
        overlay.clear()
        overlay.close()
    print('PASS: default/source colors, in-flight/pending recolor, original restore, motion and emote pixels')


def check_controls(app):
    with patch('ddm.app.DanmakuClient', Client), patch('ddm.app.SuperChatSnapshot', Snapshot), \
            patch.object(MainWindow, 'start_tile'), patch.object(MainWindow, 'refresh_status'), \
            patch.object(MainWindow, 'refresh_stats'):
        rooms = [dict(room_id=str(i), live=True) for i in (1, 2)]
        window = MainWindow(rooms, rooms, layout_id='1x2', state={'plugins_enabled': []})
        window.move(-4000, -4000)
        window.show()
        app.processEvents()
        first, second = window.wall.tiles
        menu = first.danmaku_settings_menu
        try:
            events = []
            menu.settingsChanged.connect(events.append)
            menu.apply_settings({})
            assert not events and menu.color_mode.currentData() == 'original'
            assert not menu.color_button.isEnabled()
            for mode in ('light', 'dark'):
                theme.apply(mode)
                menu.apply_settings(window.settings)
                assert menu.color_button.text() == '#FFFFFF'
                assert not menu.color_button.isEnabled()
            menu.color_mode.setCurrentIndex(1)
            assert menu.color_button.isEnabled()
            assert second.video_danmaku.settings['video_danmaku_color_mode'] == 'custom'
            menu.color_button.click()
            picker = first.findChild(QColorDialog)
            assert picker is not None and picker.parentWidget() is first
            picker.setCurrentColor(QColor('#ff0000'))
            picker.reject()
            assert window.settings['video_danmaku_color'] == '#ffffff', 'Cancel must not save preview'
            app.sendPostedEvents()
            menu.color_button.click()
            pickers = [p for p in first.findChildren(QColorDialog) if p.isVisible()]
            assert len(pickers) == 1
            pickers[0].setCurrentColor(QColor('#ff0000'))
            pickers[0].accept()
            saved = window.current_state()['settings']
            assert saved['video_danmaku_color'] == '#ff0000'
            assert second.video_danmaku.settings['video_danmaku_color'] == '#ff0000'
            assert second.danmaku_settings_menu.color_button.text() == '#FF0000'
            assert window._save_timer.isActive()
            assert second.video_danmaku._comment_color({'color': '#0000ff'}).name() == '#ff0000'
            menu.color_mode.setCurrentIndex(0)
            assert second.video_danmaku._comment_color({'color': '#0000ff'}).name() == '#0000ff'
            menu.color_mode.setCurrentIndex(1)
            saved = window.current_state()['settings']
            assert saved['video_danmaku_color'] == '#ff0000', 'Original mode must remember chosen color'
            window._on_fullscreen(first)
            app.processEvents()
            menu.color_button.click()
            pickers = [p for p in first.findChildren(QColorDialog) if p.isVisible()]
            assert len(pickers) == 1 and pickers[0].windowHandle().transientParent() is first.windowHandle()
            pickers[0].reject()
            window._exit_fullscreen()
            app.processEvents()
        finally:
            window.close()
        reloaded = MainWindow([], [], state={'plugins_enabled': [], 'settings': saved})
        try:
            assert reloaded.settings['video_danmaku_color_mode'] == 'custom'
            assert reloaded.settings['video_danmaku_color'] == '#ff0000'
        finally:
            reloaded.close()
    print('PASS: picker accept/cancel, all tiles, save snapshot and reload')


def check_quick_pixels(app):
    from ddm.video_danmaku_quick import QuickDanmakuLayer
    owner = QWidget()
    owner.setAttribute(Qt.WA_ShowWithoutActivating)
    owner.setGeometry(-4000, -4000, 320, 160)
    owner.show()
    app.processEvents()
    layer = QuickDanmakuLayer(owner)
    group = layer.create_group(0, 0, 320, 160, opacity=100, rounded=False)
    overlay = VideoDanmaku()
    overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False))
    try:
        for color in ('#ffffff', '#ff0000', '#0000ff'):
            image = overlay._comment_renderer()._render_text('RGB TEST', QColor(color))
            identifier = layer.add(group, image, 20, 20,
                                   image.width() / image.devicePixelRatioF(),
                                   image.height() / image.devicePixelRatioF())
            layer.show()
            QTest.qWait(150)
            frame = layer.window.grabWindow()
            assert not frame.isNull() and has_color(frame, color), ('Quick texture color', color)
            layer.remove(identifier)
    finally:
        layer.remove_group(group)
        layer.window.hide()
        overlay.close()
        owner.close()
    print('PASS: native Quick texture preserves white/red/blue RGB pixels')


if __name__ == '__main__':
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    if '--native' in sys.argv:
        check_quick_pixels(app)
    else:
        check_recolor(app)
        check_controls(app)
