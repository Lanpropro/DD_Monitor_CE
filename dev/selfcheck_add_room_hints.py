"""添加窗口只展示已装载插件提供的说明，不包含输入示例。"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QDialog
from ddm.app import MainWindow
from ddm.dialogs import AddRoomDialog


def main():
    app = QApplication([])
    plain = AddRoomDialog()
    assert plain.hint.text() == '支持 B 站房间号' and plain.hint.wordWrap()
    assert plain.edit.placeholderText() == '输入房间号或链接'
    plain.edit.setText('https://live.bilibili.com/1001')
    plain.accept()
    assert plain.room_id == '1001'
    plain.close()
    for enabled, names in (([], ()), (['domestic_live'], ('虎牙', '斗鱼', '抖音')),
                           (['global_live'], ('Twitch', 'YouTube')),
                           (['domestic_live', 'global_live'], ('虎牙', '斗鱼', '抖音', 'Twitch', 'YouTube'))):
        with patch('ddm.app.QTimer.singleShot'):
            window = MainWindow([], [], state={'plugins_enabled': enabled})
        captured = []
        def inspect(dialog):
            captured.append(dialog.hint.text())
            assert dialog.hint.wordWrap()
            return QDialog.Rejected
        try:
            with patch.object(AddRoomDialog, 'exec', new=inspect):
                window.open_add_room()
            hint = captured[-1]
            assert hint.startswith('支持 B 站房间号')
            for name in ('虎牙', '斗鱼', '抖音', 'Twitch', 'YouTube'):
                assert (name in hint) == (name in names), (enabled, hint)
            assert ('个人主页链接' in hint) == ('抖音' in names)
            # 新插件的说明无需修改本体；旧插件没有可选字段也不会导致窗口打不开。
            window.plugins.platforms = {'custom': SimpleNamespace(room_input_hint='自定义链接格式'),
                                        'legacy': SimpleNamespace(label='旧平台')}
            with patch.object(AddRoomDialog, 'exec', new=inspect):
                window.open_add_room()
            assert captured[-1] == '支持 B 站房间号；自定义链接格式'
        finally:
            window.close()
            app.processEvents()
    print('PASS: no/domestic/global/all plugins; custom hint; legacy platform; no examples; Bilibili input')


if __name__ == '__main__':
    main()
