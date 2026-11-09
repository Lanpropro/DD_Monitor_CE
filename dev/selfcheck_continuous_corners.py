"""Shape, style-state, theme and native content regressions without user data."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainterPath
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidget
from ddm import theme
from ddm import continuous_corners as corners
from ddm.corner_geometry import continuous_path

APP = QApplication.instance() or QApplication([])


class ContinuousCornersTests(unittest.TestCase):
    def setUp(self):
        theme.apply('dark')
        self.host = QWidget()
        self.host.setAttribute(Qt.WA_DontShowOnScreen)
        self.host.resize(400, 500)
        self.box = QVBoxLayout(self.host)

    def tearDown(self):
        self.host.close()
        self.host.deleteLater()
        APP.processEvents()

    def show(self):
        self.host.show()
        APP.processEvents()

    def test_continuous_curve_differs_from_circle_but_keeps_bounds(self):
        rect = QRectF(0, 0, 100, 60)
        path = continuous_path(rect, 12)
        ordinary = QPainterPath()
        ordinary.addRoundedRect(rect, 12, 12)
        self.assertEqual(path.boundingRect(), rect)
        self.assertNotEqual(path, ordinary)
        self.assertTrue(path.contains(rect.center()))
        self.assertFalse(path.contains(QPointF(0, 0)))
        self.assertTrue(path.contains(QPointF(50, .01)))
        for point in (QPointF(1,20),QPointF(8,8),QPointF(3,3)):
            self.assertEqual(path.contains(point), path.contains(QPointF(100-point.x(),point.y())))

    def test_circles_capsules_and_square_corners_are_preserved(self):
        for width,height in ((32,32),(120,32)):
            rect = QRectF(0,0,width,height)
            circle = QPainterPath()
            circle.addRoundedRect(rect, height/2, height/2)
            self.assertEqual(continuous_path(rect,height/2), circle)
        path = continuous_path(QRectF(0,0,100,60), 10, corners=(0,0,10,10))
        self.assertTrue(path.contains(QPointF(.1,.1)))
        self.assertFalse(path.contains(QPointF(.1,59.9)))

    def test_input_text_editing_and_geometry_survive_custom_surface(self):
        editor = QLineEdit('before',self.host)
        self.box.addWidget(editor)
        self.show()
        size = editor.size()
        editor.selectAll()
        QTest.keyClicks(editor,'after')
        self.assertEqual(editor.text(),'after')
        self.assertEqual(editor.size(),size)
        values = corners._filter.values(editor)
        self.assertEqual(values['border-radius'],'8px')
        self.assertNotEqual(editor.grab().toImage().pixelColor(editor.width()//2,3).alpha(),0)

    def test_local_surface_states_update_without_changing_layout(self):
        button = QPushButton('Action',self.host)
        button.setObjectName('CornerFixture')
        button.setCheckable(True)
        button.setStyleSheet('#CornerFixture {background: #123456; border: 1px solid #567890; border-radius: 8px; padding: 5px;} '
                            '#CornerFixture:checked {background: #227744;} '
                            '#CornerFixture[attention="true"] {border-color: #cc3344;}')
        self.box.addWidget(button)
        self.show()
        before = button.size()
        self.assertEqual(corners._filter.values(button)['background'],'#123456')
        button.click()
        self.assertEqual(corners._filter.values(button)['background'],'#227744')
        button.setProperty('attention',True)
        self.assertEqual(corners._filter.values(button)['border-color'],'#cc3344')
        self.assertEqual(button.size(),before)
        self.assertEqual(button.grab().toImage().pixelColor(button.width()//2,4),QColor('#227744'))

    def test_identical_native_rules_keep_distinct_local_colors(self):
        widgets = []
        for color in ('#123456','#227744'):
            panel = QFrame(self.host)
            panel.setStyleSheet(f'background: {color}; border-radius: 8px;')
            panel.setFixedHeight(50)
            self.box.addWidget(panel)
            widgets.append(panel)
        self.show()
        for panel,color in zip(widgets,('#123456','#227744')):
            self.assertEqual(panel.grab().toImage().pixelColor(panel.width()//2,10),QColor(color))

    def test_skin_image_uses_the_same_corner_clip(self):
        with tempfile.TemporaryDirectory() as directory:
            image = QImage(8,8,QImage.Format_ARGB32)
            image.fill(QColor('#227744'))
            path = Path(directory)/'skin.png'
            image.save(str(path))
            panel = QFrame(self.host)
            panel.setStyleSheet('border-radius: 12px; border: none; border-image: url("'+path.as_posix()+'") 0 0 0 0 stretch stretch;')
            self.box.addWidget(panel)
            self.show()
            snapshot = panel.grab().toImage()
            self.assertEqual(snapshot.pixelColor(panel.width()//2,20),QColor('#227744'))
            self.assertNotEqual(snapshot.pixelColor(0,0),QColor('#227744'))

    def test_local_rounding_does_not_rewrite_unrelated_widget_styles(self):
        corners.stylesheet('QPushButton {background: #123456; border-radius: 8px;}')
        plain = 'QPushButton {background: #227744; border: none;}'
        self.assertEqual(corners.stylesheet(plain),plain)

    def test_theme_uses_stable_qss_and_current_surface_palette(self):
        editor = QLineEdit(self.host)
        self.box.addWidget(editor)
        self.show()
        stable = APP.styleSheet()
        for mode in ('light','dark','light'):
            theme.apply(mode)
            APP.processEvents()
            self.assertEqual(APP.styleSheet(),stable)
            image = editor.grab().toImage()
            self.assertEqual(image.pixelColor(editor.width()//2,4),theme.qcolor(theme.CONTENT))

    def test_menu_and_checkbox_keep_original_actions(self):
        check = QCheckBox('Enable',self.host)
        self.box.addWidget(check)
        self.show()
        QTest.keyClick(check,Qt.Key_Space)
        self.assertTrue(check.isChecked())
        self.assertEqual(corners._filter.values(check,'indicator')['border-radius'],'4px')
        menu = QMenu(self.host)
        calls = []
        action = menu.addAction('Open')
        action.triggered.connect(lambda: calls.append('open'))
        action.trigger()
        self.assertEqual(calls,['open'])
        self.assertIn('border-radius',corners._filter.values(menu,'item',{'selected':True}))

    def test_switch_drawing_is_not_overlaid_by_the_checkbox_indicator(self):
        from ddm.settings_notifications import NotificationSwitch
        switch = NotificationSwitch('Enable', self.host)
        self.box.addWidget(switch)
        switch.setChecked(True)
        self.show()
        painted = switch.grab().toImage()
        with patch.object(corners, '_paint'):
            owned_only = switch.grab().toImage()
        self.assertEqual(painted, owned_only, 'The switch must own its complete surface, without an extra checkbox indicator')


if __name__ == '__main__':
    unittest.main()
