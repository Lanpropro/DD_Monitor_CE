"""Offline playback badge state, painting and ownership checks; no player or network."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QMovie, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from ddm import theme
from ddm.playback_badges import StreamBadge, TimeBadge, TitleBadge, LoadingIndicator, PauseIndicator


class PlaybackBadgeTests(unittest.TestCase):
    def test_standalone_import_and_legacy_exports(self):
        import subprocess
        result = subprocess.run([sys.executable, '-c',
            "import sys; import ddm.playback_badges; "
            "assert not {'ddm.widgets', 'ddm.player', 'ddm.app'} & sys.modules.keys()"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        from ddm import playback_badges, widgets
        for name in ('StreamBadge', 'TimeBadge', 'TitleBadge', 'LoadingIndicator', 'LoadingLabel',
                     'BADGE_HEIGHT', 'HOLE_SIZE', 'HOLE_MARGIN', 'ASSETS_DIR', '_badge_font'):
            self.assertIs(getattr(widgets, name), getattr(playback_badges, name))

    def setUp(self):
        self.owner = QWidget()
        self.addCleanup(self.owner.close)
        self.addCleanup(self.owner.deleteLater)

    def test_live_offline_and_compact_states(self):
        badge = StreamBadge(self.owner)
        badge.set_state(True, '123456 viewers')
        full = badge.width()
        self.assertEqual(badge.full_width(), full)
        badge.set_compact(True)
        self.assertLess(badge.width(), full)
        badge.set_compact(False)
        self.assertEqual(badge.width(), full)
        badge.set_offline()
        self.assertEqual(badge._text(), '已下播')
        badge.set_state(False)
        self.assertEqual(badge._text(), '未开播')
        self.assertFalse(badge.offline)
        self.assertIs(badge.parent(), self.owner)

    def test_title_and_time_fit_and_paint_in_both_themes(self):
        title, clock = TitleBadge(self.owner), TimeBadge(self.owner)
        title.set_max_width(180)
        title.set_text('很长的主播名字' * 4, '直播间标题' * 20)
        self.assertLessEqual(title.width(), 180)
        self.assertLess(len(title._name_text), len(title.uname))
        clock.set_text('123:45:56')
        self.assertEqual(clock.text, '123:45:56')
        for mode in ('dark', 'light'):
            theme.apply(mode)
            for badge in (title, clock, StreamBadge(self.owner)):
                for scale in (1, 1.5, 2):
                    image = QImage(round(badge.width() * scale), round(badge.height() * scale),
                                   QImage.Format_ARGB32_Premultiplied)
                    image.setDevicePixelRatio(scale)
                    image.fill(Qt.transparent)
                    painter = QPainter(image)
                    badge.paint_badge(painter)
                    painter.end()
                    self.assertGreater(image.pixelColor(image.width() // 2, image.height() // 2).alpha(), 0)
                    self.assertEqual(image.pixelColor(0, 0).alpha(), 0)

    def test_loading_movie_and_text_only_keep_owner_and_stop(self):
        for icon in (True, False):
            badge = LoadingIndicator(self.owner, text='连接中…', icon=icon)
            self.assertIs(badge.parent(), self.owner)
            badge.start()
            self.assertFalse(badge.isHidden())
            if icon:
                self.assertTrue(badge._movie.isValid(), 'Bundled loading.gif must resolve after extraction')
                self.assertEqual(badge._movie.state(), QMovie.Running)
            else:
                self.assertIsNone(badge._movie)
            badge.stop()
            self.assertTrue(badge.isHidden())
            if icon:
                self.assertEqual(badge._movie.state(), QMovie.NotRunning)

    def test_loading_feedback_can_show_two_lines_and_restore_connection_text(self):
        badge = LoadingIndicator(self.owner)
        original = badge.natural_size()
        badge.start()
        badge.set_text('断流，10 秒后重连（第 2 次）\n网络连接异常，请检查网络或代理')
        self.assertGreaterEqual(badge.natural_size().height(), original.height())
        self.assertGreaterEqual(badge._text.height(), 2 * badge._text.fontMetrics().height())
        self.assertEqual(badge._movie.state(), QMovie.Running)
        badge.set_presentation_scale(.6)
        self.assertEqual(badge.height(), round(badge.natural_size().height() * .6))
        badge.set_text('连接中…')
        badge.set_presentation_scale(1)
        self.assertEqual(badge.natural_size(), original)
        badge.stop()

    def test_pause_indicator_is_static_accessible_and_mouse_transparent(self):
        from PySide6.QtWidgets import QLabel
        badge = PauseIndicator(self.owner)
        self.assertEqual(badge.accessibleName(), '已暂停')
        self.assertTrue(badge.testAttribute(Qt.WA_TransparentForMouseEvents))
        self.assertEqual(badge.findChildren(QLabel), [])
        badge.start()
        self.assertFalse(badge.isHidden())
        for mode in ('dark', 'light'):
            theme.apply(mode)
            for dpi in (1, 1.5, 2):
                image = QImage(round(48 * dpi), round(48 * dpi), QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(dpi)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                badge._render_badge(painter)
                painter.end()
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                self.assertGreater(image.pixelColor(round(18 * dpi), round(24 * dpi)).alpha(), 0)
        badge.stop()
        self.assertTrue(badge.isHidden())

    def test_loading_uniform_scale_keeps_animation_and_restores_normal_size(self):
        for icon in (True, False):
            badge = LoadingIndicator(self.owner, icon=icon)
            badge.start()
            normal = badge.size()
            self.assertEqual(normal, badge.natural_size())
            badge.set_presentation_scale(.75)
            self.assertEqual(badge.width(), round(normal.width() * .75))
            self.assertEqual(badge.height(), round(normal.height() * .75))
            badge.start()
            self.assertEqual(badge._presentation_scale, .75)
            badge.adjustSize()
            self.assertEqual(badge.size(), badge.sizeHint())
            self.assertEqual(badge.width(), round(normal.width() * .75))
            if icon:
                self.assertEqual(badge._movie.state(), QMovie.Running)
                self.assertEqual(badge._movie.scaledSize().width(), round(32 * .75 * badge.devicePixelRatioF()))
            for mode in ('dark', 'light'):
                theme.apply(mode)
                self.assertEqual(badge._presentation_scale, .75)
                for dpi in (1, 1.5, 2):
                    image = QImage(round(badge.width() * dpi), round(badge.height() * dpi), QImage.Format_ARGB32_Premultiplied)
                    image.setDevicePixelRatio(dpi)
                    image.fill(Qt.transparent)
                    painter = QPainter(image)
                    badge._render_badge(painter)
                    painter.end()
                    self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                    self.assertGreater(image.pixelColor(image.width() // 2, image.height() // 2).alpha(), 0)
            badge.set_presentation_scale(1)
            self.assertEqual(badge.size(), badge.natural_size())
            self.assertEqual(badge._icon.size().width() if icon else 32, 32)
            badge.stop()


if __name__ == '__main__':
    app = QApplication.instance() or QApplication([])
    unittest.main()
