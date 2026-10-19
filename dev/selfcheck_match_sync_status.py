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
from PySide6.QtGui import QColor, QPixmap, QHelpEvent, QFontDatabase, QFont
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
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
            assert row.match_text in row.status.detail and '历史缓存约 48' in row.status.detail
            assert row.status.accessibleDescription() == row.status.detail
            assert row.status.toolTip() == ''
            row.status.resize(900, 24)
            row.status.grab()
            assert len(row.status.hit_regions) == 4
            for index, (rect, hint) in enumerate(row.status.hit_regions):
                assert row.status.tooltip_at(rect.center()) == hint
                with patch.object(module.QToolTip, 'showText') as show:
                    QApplication.sendEvent(row.status, QHelpEvent(module.QEvent.ToolTip, rect.center(),
                                                               row.status.mapToGlobal(rect.center())))
                    assert show.call_args.args[1] == hint
                assert hint != row.status.detail and '弹幕已连接' not in hint
                if index == 0:
                    assert hint == row.video_text
                elif index == 1:
                    assert hint == row.match_text
                elif index == 3:
                    assert '静音' in hint and '历史缓存' not in hint
            with patch.object(module.QToolTip, 'hideText') as hide:
                point = module.QPoint(899, 12)
                QApplication.sendEvent(row.status, QHelpEvent(module.QEvent.ToolTip, point,
                                                           row.status.mapToGlobal(point)))
                hide.assert_called_once()
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
            assert row.status.hints[-1] == row.buffer_text
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
            for embedded in (False, True):
                for widget in viewer.add_controls:
                    widget.setVisible(not embedded)
                for width in (1100, 2200):
                    viewer.resize(width, 700)
                    for visible in (False, True):
                        viewer.late_notice.setVisible(visible)
                        app.processEvents()
                        gap = viewer.compare.x() - viewer.automatic.geometry().right() - 1
                        assert 0 <= gap <= 8, f'Comparison moved away from automatic toggle: {gap}'
                        assert viewer.automatic.width() <= viewer.automatic.sizeHint().width() + 2
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
