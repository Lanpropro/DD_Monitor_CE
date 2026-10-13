"""Stable palette QSS must render like the previous literal-colour stylesheet."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout
from ddm import theme


def main():
    app = QApplication([])
    theme.apply('dark')
    window = QWidget()
    window.setObjectName('Root')
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    layout = QVBoxLayout(window)
    for name in ('PrimaryButton', 'IconButton', 'ChipButton', 'TileCtrl', 'AppearanceChoice'):
        button = QPushButton(name, window)
        button.setObjectName(name)
        layout.addWidget(button)
    layout.addWidget(QLineEdit('Palette text', window))
    for name in ('NavThumbHint', 'NavThumbCover', 'DanmakuCount', 'TilePlaceholder'):
        label = QLabel(name, window)
        label.setObjectName(name)
        label.setProperty('state', 'connected')
        layout.addWidget(label)
    window.resize(400, 600)
    window.show()
    QTest.qWait(20)
    stable = app.styleSheet()
    for mode in ('light', 'dark', 'light'):
        with patch.object(app, 'setStyleSheet', side_effect=AssertionError('Global stylesheet changed')):
            theme.apply(mode)
        QTest.qWait(20)
        fast = window.grab().toImage()
        app.setStyleSheet(theme.qss())
        QTest.qWait(20)
        reference = window.grab().toImage()
        assert fast == reference, f'{mode}: palette QSS changed the existing rendered design'
        theme.apply(mode)
        assert app.styleSheet() == stable
    editor = window.findChild(QLineEdit)
    palette = editor.palette()
    palette.setColor(QPalette.PlaceholderText, QColor('#8a8f98'))
    editor.setPalette(palette)
    for mode in ('dark', 'light'):
        theme.apply(mode)
        assert editor.palette().color(QPalette.PlaceholderText) == QColor('#8a8f98')
    # A widget created after the change must also get light-mode media exceptions.
    new = QPushButton('New media control', window)
    new.setObjectName('TileCtrl')
    layout.addWidget(new)
    QTest.qWait(20)
    assert '#F7F9FC' in new.styleSheet()
    theme.apply('dark')
    assert new.styleSheet() == '', 'New widget must restore its original dark stylesheet'
    window.close()
    print('PASS: identical rendered dark/light designs, stable global QSS, and newly created controls')


if __name__ == '__main__':
    main()
