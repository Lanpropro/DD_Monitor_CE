"""设置切页复用快照、连续打断、缩放收尾及录制页内部滚动。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import config, motion, theme
from ddm.dialogs import SettingsDialog


class PaintedPage(QWidget):
    def __init__(self, color):
        super().__init__()
        self.color = color
        self.paints = 0

    def paintEvent(self, event):
        self.paints += 1
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.color))


def check_transition(app):
    stack = motion.SettingsStack()
    stack.resize(600, 400)
    pages = [PaintedPage(color) for color in ('red', 'green', 'blue')]
    for page in pages:
        stack.addWidget(page)
    stack.show()
    app.processEvents()
    with patch.object(motion, 'enabled', return_value=True):
        stack.show_page(1, animate=True)
        app.processEvents()
        start_paints = pages[1].paints
        # 模拟视频预览等内容持续更新；动画帧只应合成一次取得的页面快照。
        for frame in range(10, 160, 10):
            stack._fade.setCurrentTime(frame)
            pages[1].update()
            app.processEvents()
        extra_paints = pages[1].paints - start_paints
        assert extra_paints == 0, f'动画期间重复绘制设置内容 {extra_paints} 次'
        opacity = stack._effect.opacity()
        stack.show_page(2, animate=True)
        app.processEvents()
        assert stack._effect.opacity() >= opacity
        snapshot = stack.grab().toImage()
        assert snapshot.pixelColor(300, 200).blue() > snapshot.pixelColor(300, 200).green()
        stack.resize(640, 420)
        app.processEvents()
        assert stack.graphicsEffect() is None
        assert stack._fade.state() == QAbstractAnimation.Stopped
        assert pages[2].size() == stack.contentsRect().size()
        stack.show_page(1, animate=True)
        stack.hide()
        assert stack.graphicsEffect() is None
        stack.show()
        stack.show_page(0, animate=False)
        assert stack.graphicsEffect() is None
        with patch.object(motion, 'enabled', return_value=False):
            stack.show_page(1, animate=True)
            assert stack.graphicsEffect() is None
    stack.close()
    print('PASS: 页面内容在动画期间重复绘制 0 次；切页、缩放、隐藏及关闭动画正常')


def check_recording_scroll(app):
    dialog = SettingsDialog(config.DEFAULT_SETTINGS, {})
    dialog.show()
    app.processEvents()
    original_size = dialog.size()
    dialog.nav.setCurrentRow(3)
    app.processEvents()
    assert dialog.size() == original_size, (original_size, dialog.size())
    page = dialog.recording_page
    scroll = page.scroll
    assert scroll.verticalScrollBar().maximum() > 0
    assert scroll.horizontalScrollBar().maximum() == 0
    scroll.ensureWidgetVisible(page.lock_quality)
    app.processEvents()
    bottom = page.lock_quality.mapTo(scroll.viewport(), page.lock_quality.rect().bottomRight())
    assert scroll.viewport().rect().contains(bottom)
    assert dialog.reset_button.isVisible()
    assert page.values()['recording_segment_minutes'] == config.DEFAULT_SETTINGS['recording_segment_minutes']
    dialog.nav.setCurrentRow(0)
    app.processEvents()
    assert dialog.size() == original_size
    dialog.reject()
    print('PASS: 录制页不撑高设置窗口，末尾选项可滚动访问，无横向滚动')


if __name__ == '__main__':
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    check_transition(app)
    check_recording_scroll(app)
