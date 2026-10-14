"""Skin transparency/light theme, main hover handoff and unsafe alignment fallback."""
import os
from pathlib import Path
import sys
import tempfile
from array import array
from contextlib import ExitStack
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('DDM_NO_SAVE','1')
from PySide6.QtCore import QObject, Signal, QPoint
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPalette
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QCheckBox
from ddm import plugins, theme
from ddm.skins import BackgroundLayer
from dev.selfcheck_match_sync import FakeDecoder, FakeChat, FakeSink, FakeDevice, jpeg
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.engine import Match

class Controller(QObject):
    changed=Signal()
    def __init__(self, host, root):
        super().__init__(host)
        self.layer=BackgroundLayer(root,host)
        self.layer.path='synthetic'
        self.layer.image=QImage(100,100,QImage.Format_RGB32)
        self.layer.image.fill(QColor('#25ac63'))
        self.layer.mask=0

def main():
    app=QApplication([])
    font_id = QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/'msyh.ttc'))
    assert font_id >= 0
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0]))
    now=[120.0]
    with tempfile.TemporaryDirectory() as rootdir, patch.object(module,'Decoder',FakeDecoder), \
            patch.object(module,'Chat',FakeChat), patch.object(module.AudioPump,'start',lambda _:None), \
            patch.object(module.time,'monotonic',side_effect=lambda:now[0]):
        host=QMainWindow()
        root=QWidget()
        root.setObjectName('SkinTestRoot')
        root.setStyleSheet('#SkinTestRoot {background:transparent;}')
        host.setCentralWidget(root)
        host.settings={}
        host.skin_controller=Controller(host,root)
        ctx=plugins.PluginContext(plugins.PluginManager(window=host,plugins_dir=rootdir),'appearance_check')
        viewer=module.Viewer(ctx,{})
        viewer.embed(root)
        layout=QVBoxLayout(root)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(viewer)
        host.resize(1320,1000)
        try:
            theme.apply('light')
            theme.set_skin_active(True)
            for key in ('1','2'):
                viewer.add_room(key,{'alias':key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image = jpeg()
            for row in viewer.rows.values():
                for stamp in range(60*60,122*60):
                    row.decoder.history.append(stamp/60,image)
                row.decoder.last_frame_received=now[0]
            viewer.alignment.lags['2']=0
            viewer.rows['2'].match_confirmed=True
            viewer.render()
            viewer.show_comparison('2')
            host.show()
            viewer.show()
            host.skin_controller.layer.show()
            host.skin_controller.layer.lower()
            app.processEvents()
            assert viewer.skin_visible and isinstance(viewer.lock_delay,QCheckBox)
            assert viewer.lock_delay.height()==viewer.compare.height()==viewer.automatic.height()
            assert viewer.lock_delay.y()==viewer.compare.y()==viewer.automatic.y()
            assert 'background: transparent' in viewer.body_split.styleSheet()
            for label in viewer.panel.bar.findChildren(module.QLabel):
                assert label.palette().color(QPalette.WindowText).lightness()<130
            # Sample empty letterbox and chat viewport points, away from text.
            def sample(widget, local):
                point=widget.mapTo(root,local)
                return root.grab().toImage().pixelColor(point)
            compare_canvas=viewer.comparison_panel.cards['2'][2]
            points=[(compare_canvas,QPoint(3,3)),(viewer.panel.body.viewport(),QPoint(8,200)),
                    (viewer.settings_panel,QPoint(4,30))]
            colors=[sample(w,p) for w,p in points]
            video_point = QPoint(compare_canvas.width()//2, compare_canvas.height()//2)
            video_pixel = sample(compare_canvas, video_point)
            print('MEASURE: readable panel samples',[c.name() for c in colors])
            assert all(c.red()>160 and c.green()>c.red()+10 for c in colors), 'A light theme veil must retain some skin without losing readability'
            assert viewer.panel_alpha == .72
            viewer.panel.add_event({'uname':'测试主播','text':'弹幕与字号颜色检查','color':'#fb7299'})
            host.skin_controller.layer.mask=35
            host.skin_controller.layer.update()
            host.skin_controller.changed.emit()
            app.processEvents()
            medium=[sample(w,p) for w,p in points]
            assert viewer.panel_alpha > .72
            assert all(c.red()>old.red() for c,old in zip(medium,colors)), 'Increasing mask must strengthen the panel veil'
            host.grab().save(str(Path(tempfile.gettempdir())/'match-sync-appearance-light.png'))
            host.skin_controller.layer.mask=100
            host.skin_controller.layer.update()
            host.skin_controller.changed.emit()
            app.processEvents()
            masked=[sample(w,p) for w,p in points]
            assert all(abs(c.red()-c.green())<35 for c in masked), 'Host mask must control every transparent region'
            assert sample(compare_canvas, video_point) == video_pixel, 'The veil must not change video pixels'
            theme.apply('dark')
            app.processEvents()
            assert all(label.palette().color(QPalette.WindowText).lightness()>150
                       for label in viewer.panel.bar.findChildren(module.QLabel))
            host.skin_controller.layer.mask=35
            host.skin_controller.layer.update()
            host.skin_controller.changed.emit()
            app.processEvents()
            host.grab().save(str(Path(tempfile.gettempdir())/'match-sync-appearance-dark.png'))
            host.skin_controller.layer.mask=0
            host.skin_controller.layer.update()
            host.skin_controller.changed.emit()
            app.processEvents()
            assert all(sample(w,p).lightness()<95 for w,p in points), 'Dark panels must remain legible even with zero host mask'
            def luminance(color):
                channels = [color.redF(), color.greenF(), color.blueF()]
                linear = [c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4 for c in channels]
                return sum(c*w for c,w in zip(linear, (.2126,.7152,.0722)))
            for mode in ('light', 'dark'):
                theme.apply(mode)
                for skin in ('#000000', '#ffffff'):
                    host.skin_controller.layer.image.fill(QColor(skin))
                    host.skin_controller.layer.update()
                    host.skin_controller.changed.emit()
                    app.processEvents()
                    foreground = luminance(app.palette().color(QPalette.WindowText))
                    for widget, point in points:
                        background = luminance(sample(widget, point))
                        contrast = (max(foreground, background)+.05)/(min(foreground, background)+.05)
                        assert contrast >= 4.5, (mode, skin, contrast)
                    assert sample(compare_canvas, video_point) == video_pixel
            # Excessive lag never reaches Alignment.accept or moves the primary.
            before=viewer.shifts()['1']
            with patch.object(viewer.alignment,'accept',wraps=viewer.alignment.accept) as accept:
                viewer._matched(viewer.generation,{'2':Match(26,1,'too far',refined=True)})
                accept.assert_not_called()
            for step in (0,.25,.55,.8):
                now[0]=120+step
                for row in viewer.rows.values():
                    row.decoder.last_frame_received=now[0]
                viewer.render()
            assert viewer.shifts()['1']==before and not viewer.sync_waiting
            assert all(row.sync_state=='已同步' for row in viewer.rows.values())
            assert all(row.mix_gain==1 for row in viewer.rows.values())
            assert '独立播放' in viewer.rows['2'].playback_status()
            assert '偏差超过' in viewer.rows['2'].status.text()
            with ExitStack() as stack:
                pcm_reads = [stack.enter_context(patch.object(row.decoder.history, 'pcm_at',
                    side_effect=lambda timestamp, frames: array('h', [1000, 1000] * frames).tobytes()))
                    for row in viewer.rows.values()]
                viewer.audio.sink = FakeSink()
                viewer.audio.device = FakeDevice(viewer.audio.sink)
                viewer.audio.anchor = now[0]
                viewer.audio.fill()
                assert all(read.called for read in pcm_reads), 'Both independent rooms must remain in the audible mix'
                assert any(viewer.audio.device.data)
                viewer.audio.stop()
            with patch.object(module.threading,'Thread') as worker:
                viewer.analyse()
                worker.assert_not_called()
            viewer.automatic.setChecked(False)
            viewer.rows['2'].delay.setValue(26)
            before_auto = viewer.shifts()['1']
            viewer.automatic.setChecked(True)
            assert '2' in viewer.independent_shifts
            assert viewer.shifts()['1'] == before_auto, 'Oversized auto enable must retain valid main progress'
            assert not viewer.sync_waiting
            viewer.automatic.setChecked(False)
            viewer.rows['2'].delay.setValue(0)
            viewer.automatic.setChecked(True)
            viewer.rows['2'].alignment_started = now[0] - 11
            viewer._matched(viewer.generation, {'2':Match(None,0,'共同动态画面不足')})
            assert '2' in viewer.independent_shifts and '无法确认' in viewer.rows['2'].status.text()
            # Hover controls survive closing the first main, and still operate on the second.
            viewer.picture.set_controls_visible(True)
            viewer.picture.close_button.click()
            assert set(viewer.rows)=={'2'} and viewer.picture.room['room_id']=='2'
            assert viewer.picture._overlay_visible and not viewer.picture.controls.isHidden()
            decoder=viewer.rows['2'].decoder
            viewer.picture.reload_button.click()
            assert decoder.stopped and viewer.rows['2'].decoder is not decoder
            viewer.picture.close_button.click()
            assert not viewer.rows
            host.skin_controller.layer.path=''
            host.skin_controller.changed.emit()
            assert not viewer.skin_visible and 'palette(base)' in viewer.panel.styleSheet()
        finally:
            viewer.close()
            host.close()
            theme.set_skin_active(False)
            theme.apply('dark')
            app.processEvents()
    print('PASS: light/dark fonts, host mask transparency, aligned controls, oversized-lag independent playback, main close hover handoff')

if __name__=='__main__':
    main()
