"""Crop buttons have readable rendered colors in both themes, with no live stream."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QPushButton, QWidget
from ddm import plugins, theme
from dev.selfcheck_match_sync import FakeDecoder, jpeg
from plugins_user._match_sync import viewer as module


def luminance(color):
    channels = (color.redF(), color.greenF(), color.blueF())
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
    return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))


def contrast(first, second):
    values = sorted((luminance(first), luminance(second)))
    return (values[1] + .05) / (values[0] + .05)


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        host = QWidget()
        host.settings = {}
        context = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'crop_style')
        viewer = module.Viewer(context, {})
        viewer.add_room('1', {'alias': 'main'})
        row = viewer.rows['1']
        row.decoder = FakeDecoder('1', {})
        viewer.canvas.set_frame((100, jpeg()))
        try:
            for mode in ('dark', 'light'):
                theme.apply(mode)
                def inspect(dialog):
                    dialog.show()
                    app.processEvents()
                    box = dialog.findChild(QDialogButtonBox)
                    confirm = box.button(QDialogButtonBox.Ok)
                    cancel = box.button(QDialogButtonBox.Cancel)
                    reset = next(button for button in dialog.findChildren(QPushButton) if button.text() == '使用整个画面')
                    for button in (reset, confirm, cancel):
                        button.ensurePolished()
                        foreground = button.palette().color(QPalette.ButtonText)
                        background = button.palette().color(QPalette.Button)
                        assert contrast(foreground, background) >= 4.5, (mode, button.text(), foreground.name(), background.name())
                        image = button.grab().toImage()
                        rendered = image.pixelColor(8, image.height() // 2)
                        assert contrast(foreground, rendered) >= 4.5, (mode, button.text(), rendered.name())
                    assert confirm.palette().color(QPalette.Button) == QColor('#006a92')
                    assert confirm.palette().color(QPalette.ButtonText) == QColor('#ffffff')
                    for background in ('#007ba8', '#005778'):
                        assert contrast(QColor('white'), QColor(background)) >= 4.5
                    confirm.setEnabled(False)
                    app.processEvents()
                    assert confirm.palette().color(QPalette.Disabled, QPalette.Button) != QColor('#006a92')
                    dialog.hide()
                    return QDialog.Rejected
                with patch.object(module.QDialog, 'exec', inspect):
                    viewer.choose_crop(row)
        finally:
            viewer.close()
            host.close()
            theme.apply('dark')
            app.processEvents()
    print('PASS: rendered crop button contrast >= 4.5 in dark/light themes, primary hover/press contrast and distinct disabled state')


if __name__ == '__main__':
    main()
