"""Render review-only tile separation and folder icon dialog prototypes."""
import os
from pathlib import Path
import platform
import sys
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
platform._wmi_query = lambda *a: (_ for _ in ()).throw(OSError('Isolated preview'))
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout)
from ddm import app as module, motion, theme
from ddm.folder_icons import COLORS, NAMES, folder_icon
from ddm.follow_folders import ICON_NAMES
from dev.selfcheck_tile_fullscreen import SilentPoller


class IconPrototype(QDialog):
    def __init__(self, dark=False):
        super().__init__()
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName('IconPrototype')
        self.setFixedWidth(430)
        self.name, self.color = 'star', 'pink'
        bg, text, secondary, border, card = (
            ('#24262B', '#F1F2F5', '#B8BDC5', '#424650', '#2D3036') if dark else
            ('#F7F9FC', '#202630', '#5E6A7D', '#D7DDE7', '#FFFFFF'))
        self.setStyleSheet(f'''
            #IconPrototype {{background: {bg}; border: 1px solid {border}; border-radius: 14px;}}
            #IconPrototype QLabel {{color: {text}; background: transparent;}}
            #IconPrototype QLabel[hint="true"] {{color: {secondary}; font-size: 12px;}}
            #IconPrototype QFrame#Current {{background: {card}; border: 1px solid {border}; border-radius: 10px;}}
            #IconPrototype QToolButton#Choice {{background: {card}; color: {text}; border: 1px solid {border}; border-radius: 9px; padding: 8px;}}
            #IconPrototype QToolButton#Choice:checked {{background: {'#243A44' if dark else '#ECF7FC'}; border: 1px solid #00A1D6;}}
            #IconPrototype QPushButton {{background: {card}; color: {text}; border: 1px solid {border}; border-radius: 8px; padding: 7px 12px;}}
            #IconPrototype QPushButton#Save {{background: #00A1D6; border-color: #00A1D6; color: white;}}
            #IconPrototype QPushButton#Reset {{background: transparent; border: none; color: {secondary};}}
        ''')
        body = QVBoxLayout(self)
        body.setContentsMargins(22, 20, 22, 18)
        body.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel('修改文件夹图标')
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        heading.addWidget(title, 1)
        close = QPushButton('×')
        close.setFixedSize(26, 26)
        close.setStyleSheet(f'border: none; background: transparent; color: {secondary}; padding: 0; font-size: 20px;')
        close.clicked.connect(self.reject)
        heading.addWidget(close)
        body.addLayout(heading)
        current = QFrame()
        current.setObjectName('Current')
        row = QHBoxLayout(current)
        row.setContentsMargins(14, 12, 14, 12)
        self.preview = QLabel()
        self.preview.setFixedSize(40, 40)
        self.preview.setAlignment(Qt.AlignCenter)
        row.addWidget(self.preview)
        labels = QVBoxLayout()
        labels.setSpacing(3)
        labels.addWidget(QLabel('Apex'))
        hint = QLabel('普通文件夹 · 9 个直播间')
        hint.setProperty('hint', True)
        labels.addWidget(hint)
        row.addLayout(labels, 1)
        body.addWidget(current)
        body.addWidget(QLabel('内置图标'))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.choices = []
        for index, name in enumerate(ICON_NAMES):
            choice = QToolButton()
            choice.setObjectName('Choice')
            choice.setFixedSize(122, 66)
            choice.setIconSize(QSize(24, 24))
            choice.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            choice.setCheckable(True)
            choice.clicked.connect(lambda _checked=False, value=name: self.select(value))
            self.choices.append(choice)
            grid.addWidget(choice, index//3, index%3)
        body.addLayout(grid)
        colors = QHBoxLayout()
        colors.addWidget(QLabel('图标颜色'))
        colors.addStretch()
        self.swatches = {}
        for name, color in COLORS.items():
            swatch = QPushButton()
            swatch.setFixedSize(24, 24)
            swatch.setToolTip(name)
            swatch.setStyleSheet(f'background: {color or secondary}; border: 3px solid {bg}; border-radius: 12px; padding: 0;')
            self.swatches[name] = swatch
            swatch.clicked.connect(lambda _checked=False, value=name: self.select(self.name, value))
            colors.addWidget(swatch)
        body.addLayout(colors)
        import_button = QPushButton('＋  选择本地图片…')
        body.addWidget(import_button)
        hint = QLabel('支持 PNG / JPEG / ICO，最大 5MB\n图片保留原色，导入后可预览深浅底色。')
        hint.setProperty('hint', True)
        body.addWidget(hint)
        footer = QHBoxLayout()
        reset = QPushButton('恢复默认')
        reset.setObjectName('Reset')
        footer.addWidget(reset)
        footer.addStretch()
        cancel = QPushButton('取消')
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton('保存')
        save.setObjectName('Save')
        footer.addWidget(save)
        body.addLayout(footer)
        self.refresh()

    def select(self, name, color=None):
        self.name = name
        if color is not None:
            self.color = color
        self.refresh()

    def refresh(self):
        for name, button in self.swatches.items():
            button.setText('✓' if name == self.color else '')
            if name == self.color:
                button.setStyleSheet(f'background: {COLORS[name] or "#5E6A7D"}; color: white; border: 2px solid #00A1D6; border-radius: 12px; padding: 0;')
            else:
                button.setStyleSheet(f'background: {COLORS[name] or "#5E6A7D"}; border: none; border-radius: 12px; padding: 0;')
        for name, label, button in zip(ICON_NAMES, NAMES, self.choices):
            button.setChecked(name == self.name)
            button.setText(label + (' ✓' if name == self.name else ''))
            button.setIcon(folder_icon({'type': 'normal', 'icon': {'type': 'builtin',
                'name': name, 'color': self.color}}, self, 24))
        self.preview.setPixmap(folder_icon({'type': 'normal', 'icon': {'type': 'builtin',
            'name': self.name, 'color': self.color}}, self, 32).pixmap(32, 32))


def main():
    app = QApplication([])
    module.StatusPoller = module.StatsPoller = SilentPoller
    rooms = [{'room_id': str(i), 'uname': name, 'title': '直播间预览', 'live': False}
             for i, name in enumerate(('大东彦', '玩机器 Machine', 'CS-advent', 'CSBOY', 'KMD', '星宫sumi'), 1)]
    with patch('PySide6.QtCore.QTimer.singleShot'):
        window = module.MainWindow(rooms, [], layout_id='corner', state={
            'plugins_enabled': [], 'settings': {'auto_update': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    window.resize(2560, 1440)
    with patch.object(motion, 'enabled', return_value=False):
        window.set_appearance('light')
    window.sidebar.create_folder('Apex')
    window.sidebar.account_row.set_account('预览用户', uid='100000')
    window.wall.setObjectName('WallPrototype')
    window.wall.setAttribute(Qt.WA_StyledBackground, True)
    window.wall.setStyleSheet('#WallPrototype {background: #E6EBF2;}')
    window.wall.grid.setSpacing(10)
    window.show()
    QTest.qWait(30)
    for tile in window.wall.tiles:
        tile.setStyleSheet(tile.styleSheet() + '\n#Tile, #Tile[empty="true"] {background: #FFFFFF; border: 1px solid #BCC8D8; border-radius: 12px;}')
        tile.video.setStyleSheet(tile.video.styleSheet() + '\n#TileVideo {background: #FFFFFF;}')
        tile.bottom.setStyleSheet(tile.bottom.styleSheet() + '\n#TileBottom {background: #F0F3F8; border-top: 1px solid #D7DDE7;}')
    QTest.qWait(100)
    output = ROOT/'work/appearance-delivery'
    output.mkdir(parents=True, exist_ok=True)
    assert len(window.wall.tiles) == 6
    assert window.grab().save(str(output/'prototype-light-tiles.png'))
    first = window.wall.tiles[0]
    assert first.video.grab().toImage().pixelColor(20, 20) == QColor('#FFFFFF')
    for dark in (False, True):
        theme.apply('dark' if dark else 'light')
        dialog = IconPrototype(dark)
        dialog.setAttribute(Qt.WA_ShowWithoutActivating)
        dialog.move(-10000, -10000)
        dialog.show()
        app.processEvents()
        assert dialog.width() == 430 and sum(b.isChecked() for b in dialog.choices) == 1
        dialog.select('heart', 'blue')
        assert dialog.choices[2].isChecked()
        dialog.select('star', 'pink')
        assert dialog.grab().save(str(output/('prototype-icons-dark.png' if dark else 'prototype-icons-light.png')))
        dialog.close()
    window.close()
    print('PASS: isolated real 1+5 layout, differentiated light tiles, compact light/dark icon editor and selection preview')


if __name__ == '__main__':
    main()
