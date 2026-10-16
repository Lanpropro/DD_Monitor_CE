"""Per-room rematching, crop retry, real row drop ordering and bottom restore control."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('DDM_NO_SAVE','1')
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QDialog
from ddm import plugins
from dev.selfcheck_match_sync import FakeDecoder, FakeChat, jpeg
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.engine import Match

def main():
    app=QApplication([])
    now=[120.0]
    with tempfile.TemporaryDirectory() as root, patch.object(module,'Decoder',FakeDecoder), \
            patch.object(module,'Chat',FakeChat), patch.object(module.AudioPump,'start',lambda _:None), \
            patch.object(module.time,'monotonic',side_effect=lambda:now[0]):
        host=QWidget()
        host.settings={}
        ctx=plugins.PluginContext(plugins.PluginManager(window=host,plugins_dir=root),'retry_rows_check')
        viewer=module.Viewer(ctx,{})
        try:
            for key in ('1','2','3'):
                viewer.add_room(key,{'alias':key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image=jpeg()
            for row in viewer.rows.values():
                for stamp in range(80*60,123*60):
                    row.decoder.history.append(stamp/60,image)
                row.decoder.last_frame_received=now[0]
                row.match_confirmed=True
                row.user_confirmed=True
            viewer.alignment.lags.update({'2':.4,'3':1.2})
            viewer.rematch_rooms.clear()
            viewer.render()
            viewer.show_comparison('2')
            viewer.show()
            app.processEvents()
            assert viewer.rows['1'].realign.isHidden()
            assert not viewer.rows['2'].realign.isHidden() and not viewer.rows['3'].realign.isHidden()
            row = viewer.rows['3']
            original = {key: item.geometry() for key, item in viewer.rows.items()}
            drags = []
            native_drag = module.QDrag
            def make_drag(source):
                drag = native_drag(source)
                drags.append(drag)
                return drag
            def cancel_drag(*_args):
                assert row.isHidden() and viewer.dragged_row == '3'
                assert bytes(drags[-1].mimeData().data(module.ROW_MIME)) == b'3'
                assert drags[-1].pixmap().width() >= row.width(), 'The entire card must move with the pointer'
                viewer.preview_row_drag(QPoint(0, 0))
                assert viewer.row_preview == ['3', '1', '2'] and viewer.row_animations
                QTest.qWait(170)
                assert viewer.rows['1'].y() > original['1'].y(), 'Other cards must make room during hover'
                return Qt.IgnoreAction
            with patch.object(module.motion, 'enabled', return_value=True), \
                    patch.object(module, 'QDrag', side_effect=make_drag), patch.object(native_drag, 'exec', side_effect=cancel_drag):
                QTest.mousePress(row, Qt.LeftButton, pos=QPoint(4, 4))
                app.sendEvent(row, QMouseEvent(QEvent.MouseMove, QPointF(35, 4), QPointF(35, 4),
                                               Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
            app.processEvents()
            assert viewer.dragged_row is None and not row.isHidden() and list(viewer.rows) == ['1', '2', '3']
            assert all(item.geometry() == original[key] for key, item in viewer.rows.items()), 'Cancelled drag restores every card'
            viewer.begin_row_drag('3')
            with patch.object(module.motion, 'enabled', return_value=False):
                viewer.preview_row_drag(QPoint(0, 0))
                assert not viewer.row_animations
                viewer.finish_row_drag(QPoint(0, 0))
            assert list(viewer.rows) == ['3', '1', '2']
            viewer.reorder_room('3', '2', after=True)
            assert list(viewer.rows) == ['1', '2', '3']
            assert not hasattr(viewer.comparison_panel, 'retry_buttons')
            assert viewer.rows['2'].realign.x() - viewer.rows['2'].main_button.geometry().right() <= 7
            originals={key:row.decoder for key,row in viewer.rows.items()}
            before=viewer.shifts()
            with patch.object(viewer,'analyse') as kick:
                viewer.rows['2'].realign.click()
                kick.assert_called_once()
            assert viewer.rematch_rooms=={'2'} and not viewer.rows['2'].match_confirmed
            assert viewer.rows['3'].match_confirmed and viewer.alignment.lags['3']==1.2
            assert viewer.shifts()['1']==before['1'] and viewer.shifts()['3']==before['3']
            deliveries=[]
            viewer.results.matched.connect(lambda epoch,results:deliveries.append(tuple(results)))
            with patch.object(module,'match_scenes',side_effect=[Match(lag,1,'fresh global match',refined=True) for lag in (2.5,1.2,2.5,1.2)]) as search, \
                    patch.object(module.threading,'Thread') as worker:
                worker.side_effect=lambda **kwargs:type('Inline',(),{'start':lambda self:kwargs['target']()})()
                viewer.analyse()
                viewer.analyse()
                viewer.analyse()
                viewer.analyse()
                assert search.call_count==4 and deliveries==[('2',),('3',),('2',),('3',)]
            assert abs(viewer.alignment.lags['2']-2.5)<1e-9 and viewer.rows['2'].match_confirmed
            assert not viewer.rematch_rooms and not viewer.rematch_admit
            assert all(viewer.rows[key].decoder is decoder and not decoder.stopped for key,decoder in originals.items())
            # Buffer recovery invalidates only the affected source and queues a fresh search.
            viewer.rows['2'].decoder.last_frame_received=116
            viewer.render()
            assert viewer.rows['2'].match_confirmed and '2' not in viewer.rematch_rooms, 'A receive gap covered by cache must preserve confirmation'
            target = viewer.audio.clock() + viewer.shifts()['2']
            with patch.object(viewer.rows['2'].decoder.history, 'bounds', return_value=(80, target - .5)):
                viewer.render()
            viewer.rows['2'].decoder.last_frame_received=now[0]
            viewer.render()
            assert '2' in viewer.rematch_rooms and not viewer.rows['2'].match_confirmed
            assert viewer.rows['2'].rematch_locally, 'A buffered resume should recheck the saved offset first'
            assert viewer.rows['3'].match_confirmed
            assert not viewer.sync_waiting
            # Accepting a crop clears the independent fallback and actively enables retry.
            viewer._block_alignment('2','blocked fixture')
            viewer.rows['2'].sync_state = '已同步'
            viewer.comparison_panel.render(viewer.audio.clock(), viewer.shifts())
            state = viewer.comparison_panel.cards['2'][3].text()
            assert '画面时间差尚未确认' in state and '独立播放' in state
            assert '提前' not in state and '延后' not in state
            viewer.automatic.setChecked(False)
            assert all(row.realign.isHidden() for row in viewer.rows.values())
            def crop(dialog):
                dialog.findChild(module.Canvas).crop=QRectF(.1,.1,.7,.7)
                return QDialog.Accepted
            with patch.object(module.QDialog,'exec',crop), patch.object(viewer,'analyse') as kick:
                viewer.choose_crop(viewer.rows['2'])
                kick.assert_called_once()
            assert viewer.automatic.isChecked() and '2' not in viewer.independent_shifts
            assert not viewer.rows['2'].realign.isHidden()
            assert '2' in viewer.rematch_rooms and viewer.rows['2'].crop==(.1,.1,.7,.7)
            # Use the row's actual drop handler, preserving IDs, main choice and decoders.
            main_id=viewer.alignment.reference
            mime=QMimeData()
            mime.setData(module.ROW_MIME,b'3')
            event=SimpleNamespace(source=lambda:viewer.rows['3'],mimeData=lambda:mime,
                                  position=lambda:QPointF(0,0),acceptProposedAction=Mock(),ignore=Mock())
            viewer.rows['1'].dropEvent(event)
            event.acceptProposedAction.assert_called_once()
            assert list(viewer.rows)==['3','1','2']
            assert [viewer.rows_layout.itemAt(i).widget().room_id for i in range(3)]==['3','1','2']
            assert viewer.alignment.reference==main_id
            viewer.save()
            assert [row['room_id'] for row in ctx.setting('rooms',[])]==['3','1','2']
            assert all(viewer.rows[key].decoder is decoder for key,decoder in originals.items())
            alien=SimpleNamespace(source=lambda:None,mimeData=lambda:mime,ignore=Mock())
            viewer.rows['1'].dropEvent(alien)
            alien.ignore.assert_called_once()
            viewer.minimize_settings.click()
            app.processEvents()
            button=viewer.restore_settings
            assert button.parentWidget() is viewer.picture.bottom and button.isVisible()
            bottom=viewer.picture.bottom.layout()
            assert bottom.indexOf(button)+1==bottom.indexOf(viewer.picture.danmaku_button)
            assert button.geometry().right()<viewer.picture.danmaku_button.geometry().left()
            button.click()
            assert viewer.settings_panel.isVisible() and button.isHidden()
            viewer.minimize_settings.click()
            viewer._fullscreen_picture()
            app.processEvents()
            button.click()
            app.processEvents()
            assert viewer.fullscreen_dialog is None and viewer.settings_panel.isVisible()
            viewer.select_main('3')
            assert viewer.rows['3'].realign.isHidden() and not viewer.rows['1'].realign.isHidden()
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: targeted global rematch, buffered-source recheck, crop auto retry, safe row drag ordering, bottom restore placement')

if __name__=='__main__':
    main()
