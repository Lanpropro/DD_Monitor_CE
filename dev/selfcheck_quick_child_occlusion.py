"""Check moving native child holes on a Quick overlay without showing a video."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication, QWidget

from ddm.video_danmaku_quick import QuickDanmakuLayer


def main():
    app = QApplication([])
    owner = QWidget()
    owner.setAttribute(Qt.WA_DontShowOnScreen)
    owner.resize(400, 250)
    owner.show()
    layer = QuickDanmakuLayer(owner)
    try:
        clip = QRegion(QRect(20, 20, 60, 45))
        for region, old_visible, new_visible in (
                (clip, False, True), (clip.translated(80, 0), True, False), (QRegion(), True, True)):
            layer.set_child_occlusion(region)
            assert layer._update_occlusion()
            assert layer.window.mask().contains(QPoint(40, 40)) == old_visible
            assert layer.window.mask().contains(QPoint(120, 40)) == new_visible
        layer.setProperty('matchWindowedDanmaku', True)
        group = layer.create_group(0, 0, 400, 250)
        layer.set_child_occlusion(clip)
        assert layer._update_occlusion()
        for height in (170, 250):
            layer.begin_group_move(group, 0, 0, 400, height)
            assert layer.window.mask().contains(QPoint(120, 40)), 'Stable lanes must remain exposed'
            assert not layer.window.mask().contains(QPoint(40, 40)), 'Keep the child cutout'
            assert not layer.window.mask().contains(QPoint(120, 210)), 'Clip the changing strip'
            layer.set_group_geometry(group, 0, 0, 400, height)
            epoch = layer.window._move_epoch
            layer.window._after_move_sync(epoch)
            layer.window._after_move_frame(epoch)
        layer.begin_group_move(group, 10, 0, 400, 250)
        assert not layer.window.mask().contains(QPoint(120, 40)), 'A translated group still needs full clipping'
        layer.window.cancel_move(group)
        dialog = QWidget(owner, Qt.Tool)
        dialog.setProperty('settingsGlassWindow', True)
        dialog.resize(70, 50)
        dialog.move(owner.mapToGlobal(QPoint(110, 30)))
        with patch.object(layer, '_occluding_widgets', return_value=[dialog]), patch(
                'ddm.video_danmaku_quick._stack_below', return_value=True) as stack, patch(
                'ddm.video_danmaku_quick.QApplication.platformName', return_value='windows'):
            assert layer._update_occlusion()
            stack.assert_called_once_with(layer.window, [int(dialog.winId())])
            layer._occlusion_timer.stop()
            layer.eventFilter(dialog, QEvent(QEvent.Move))
            assert not layer._occlusion_timer.isActive()
            stack.return_value = False
            assert layer._update_occlusion()
            inside = owner.mapFromGlobal(dialog.frameGeometry().center())
            assert not layer.window.mask().contains(inside), 'Fallback clips the dialog'
            layer.eventFilter(dialog, QEvent(QEvent.Move))
            assert layer._occlusion_timer.isActive()
        print('PASS: moving child mask, restored background, and no comment texture changes.')
    finally:
        layer.window.close()
        owner.close()
        app.shutdown()


if __name__ == '__main__':
    main()
