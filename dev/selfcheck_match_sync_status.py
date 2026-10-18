"""Compact native status icons retain full diagnostics and never move comparison."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget, QStyle
from PySide6.QtGui import QColor, QPixmap
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    # Some platform icon providers return larger pixmaps than requested.
    # The icon must still stay in its 16 logical pixel slot at every DPI.
    label = module.CompactStatus()
    label.resize(80, 30)
    baseline = label.grab().toImage()
    oversized = QPixmap(48, 48)
    oversized.fill(QColor('#ffffff'))
    style = SimpleNamespace(standardIcon=lambda _: SimpleNamespace(pixmap=lambda *args: oversized.copy()))
    label.set_status([(QStyle.SP_MediaPlay, '')], 'play')
    with patch.object(label, 'style', return_value=style):
        painted = label.grab().toImage()
    ratio = label.devicePixelRatioF()
    assert any(painted.pixel(x, y) != baseline.pixel(x, y)
               for x in range(round(16 * ratio)) for y in range(painted.height()))
    assert all(painted.pixel(x, y) == baseline.pixel(x, y)
               for x in range(round(17 * ratio), painted.width()) for y in range(painted.height())), 'Icon overlaps adjacent text'
    label.close()
    with tempfile.TemporaryDirectory() as directory, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(
            plugins.PluginManager(window=host, plugins_dir=directory), 'status'), {})
        try:
            viewer.resize(1800, 700)
            viewer.show()
            viewer.add_room('1')
            viewer.add_room('2')
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            row = viewer.rows['2']
            row.video_text = '取流已连接'
            row.chat_text = '弹幕已连接'
            row.match_text = '未找到共同的动态比赛画面；可扩大匹配区域或对照微调'
            row.buffer_text = '历史缓存约 48 秒，同步目标前方可播放约 5.2 秒（候选偏移，尚未验证） · 本路暂时静音'
            viewer.independent_shifts['2'] = -5
            row.refresh_status()
            assert row.status.text() == '搜索中 · 独立播放'
            assert row.status.parts[0] == ('connected', '')
            assert (QStyle.SP_MediaVolumeMuted, '') in row.status.parts
            assert '5.2s' not in row.status.text()
            assert row.match_text in row.status.toolTip() and '历史缓存约 48' in row.status.toolTip()
            assert row.status.accessibleDescription() == row.status.toolTip()
            assert not row.status.testAttribute(module.Qt.WA_TransparentForMouseEvents)
            viewer.independent_shifts.clear()
            row.sync_state = '已同步'
            row.match_confirmed = True
            row.mix_gain = 1
            row.volume.setValue(40)
            row.audible.setChecked(True)
            row.buffer_text = '历史缓存约 48 秒，同步目标前方可播放约 5.2 秒'
            row.refresh_status()
            assert row.status.text() == '已对齐 · 5.2s'
            assert (QStyle.SP_MediaVolumeMuted, '') not in row.status.parts
            row.volume.setValue(0)
            assert (QStyle.SP_MediaVolumeMuted, '') in row.status.parts
            row.volume.setValue(40)
            row.audible.setChecked(False)
            assert (QStyle.SP_MediaVolumeMuted, '') in row.status.parts
            row.buffer_text = '当前播放偏移超出范围（目标内容尚未收到，缺少约 1.4 秒）'
            row.sync_state = '恢复缓存'
            row.refresh_status()
            assert '等待缓存' in row.status.text() and '缺少 1.4s' in row.status.text()
            row.video_text = '连接或解码失败；稍后重试'
            row.refresh_status()
            assert '连接异常' in row.status.text()
            row.video_text = '正在重新连接…'
            row.refresh_status()
            assert '重连中' in row.status.text()
            row.paused = True
            row.refresh_status()
            assert '已暂停' in row.status.text()
            app.processEvents()
            position = viewer.compare.pos()
            viewer.late_notice.setText('副路持续晚到；切换较晚的一路为主画面可更快对齐')
            viewer.late_notice.show()
            app.processEvents()
            assert viewer.compare.pos() == position
            assert viewer.late_notice.x() > viewer.compare.x()
            for width in (100, 450, 900):
                row.status.resize(width, 24)
                assert not row.status.grab().isNull()
                assert not row.status.wordWrap()
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: compact icons, effective mute, candidate exclusion, full hover diagnostics, narrow paint and stable comparison position')


if __name__ == '__main__':
    main()
