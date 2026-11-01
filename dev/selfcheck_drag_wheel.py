"""Windows 原生视频子窗口上的应用内拖拽、滚轮与连续交互耗时。仅本地合成视频。"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm.player import TilePlayer
from ddm.widgets import Sidebar, Tile
from selfcheck_mpv import mta_lifetime, pump, ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--physical', action='store_true', help='requires access to the interactive Windows desktop')
    args = parser.parse_args()
    with mta_lifetime():
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        window = QWidget()
        window.setGeometry(40, 40, 940, 720)
        sidebar = Sidebar([dict(room_id=str(i),uname=f'Fixture {i}',live=False) for i in range(30)],
                          window, auto_compact=False)
        sidebar.setGeometry(0, 0, 248, 700)
        target = Tile(dict(room_id='fixture', uname='Local video'), window)
        target.setGeometry(280, 20, 620, 500)
        video = target.video
        received = []
        def dropped(rid):
            assert QWidget.mouseGrabber() is None
            received.append(rid)
        target.roomDropped.connect(dropped)
        player = TilePlayer(video, window)
        cursor = QCursor.pos()
        timer = QTimer()
        timer.setInterval(10)
        ticks = []
        timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
        try:
            window.show()
            window.raise_()
            window.activateWindow()
            pump(app, .2)
            with tempfile.TemporaryDirectory(prefix='ddm-drag-video-') as directory:
                source = str(Path(directory)/'blue.mp4')
                subprocess.run([shutil.which('ffmpeg') or 'ffmpeg','-hide_banner','-loglevel','error','-y',
                    '-f','lavfi','-i','color=c=blue:s=320x180:r=30','-t','20',
                    '-c:v','libx264','-preset','ultrafast',source],check=True,timeout=30)
                player.set_muted(True)
                player.play(source)
                ready(app, player)
                before = player._prop('time-pos')
                # Qt must resolve a real native video child to the existing drop receiver.
                destination = video.mapToGlobal(video.rect().center())
                hit = QApplication.widgetAt(destination)
                assert hit is not None and (hit is video or video.isAncestorOf(hit)), type(hit)
                timings = []
                cpu_start = time.process_time()
                started = time.perf_counter()
                ticks.append(started)
                timer.start()
                with patch('ddm.widgets.QDrag',side_effect=AssertionError('Native drag was called')):
                    for cycle in range(60):
                        item = sidebar.items()[0]
                        QTest.mousePress(item,Qt.LeftButton,pos=QPoint(5,5))
                        began = time.perf_counter()
                        QTest.mouseMove(item,QPoint(35,35))
                        assert sidebar.drag_session.active
                        timings.append((time.perf_counter()-began)*1000)
                        assert QWidget.mouseGrabber() is window
                        QTest.mouseMove(window,window.mapFromGlobal(destination))
                        deadline = time.monotonic()+1
                        while sidebar.drag_session.active and sidebar.drag_session.target is not target and time.monotonic()<deadline:
                            pump(app,.01)
                        if sidebar.drag_session.target is not target:
                            print('TARGET FAILURE',cycle,'active',sidebar.drag_session.active,
                                'target_type',type(sidebar.drag_session.target).__name__,
                                'hit_type',type(QApplication.widgetAt(destination)).__name__,
                                'position',sidebar.drag_session.position.toTuple(),'destination',destination.toTuple(),
                                'grabber_type',type(QWidget.mouseGrabber()).__name__,flush=True)
                            raise AssertionError('Native video target not reached')
                        QTest.mouseRelease(window,Qt.LeftButton,pos=window.mapFromGlobal(destination))
                        assert not sidebar.drag_session.active and QWidget.mouseGrabber() is None
                        assert len(received) == cycle+1
                        pump(app,.01)
                timer.stop()
                assert player._prop('time-pos') > before and player._prop('vo-configured')
                print(json.dumps(dict(cycles=60,dpr=window.devicePixelRatioF(),
                    start_median_ms=round(statistics.median(timings),3),start_max_ms=round(max(timings),3),
                    heartbeat_max_ms=round(max((b-a)*1000 for a,b in zip(ticks,ticks[1:])),3),
                    wall_seconds=round(time.perf_counter()-started,3),
                    cpu_seconds=round(time.process_time()-cpu_start,3),pass_native_video_drop=True)),flush=True)
                if not args.physical:
                    return
                # Exercise Windows capture and release using actual mouse messages,
                # including the foreign mpv child HWND inside the video widget.
                user32 = ctypes.windll.user32
                user32.WindowFromPoint.argtypes = [wintypes.POINT]
                user32.WindowFromPoint.restype = wintypes.HWND
                user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                user32.GetAncestor.restype = wintypes.HWND
                user32.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,
                                               ctypes.c_int,ctypes.c_int,wintypes.UINT]
                handle = int(window.winId())
                user32.SetWindowPos(handle, -1, 0, 0, 0, 0, 0x13)
                pressed = False
                try:
                    item = sidebar.items()[0]
                    QCursor.setPos(item.mapToGlobal(QPoint(10,10)))
                    pump(app,.03)
                    point = wintypes.POINT()
                    assert user32.GetCursorPos(ctypes.byref(point)), 'Interactive Windows desktop is unavailable'
                    assert user32.GetAncestor(user32.WindowFromPoint(point),2) == handle, (
                        point.x,point.y,handle,user32.GetAncestor(user32.WindowFromPoint(point),2),
                        item.mapToGlobal(QPoint(10,10)).toTuple())
                    user32.mouse_event(0x2,0,0,0,0)
                    pressed = True
                    pump(app,.03)
                    QCursor.setPos(item.mapToGlobal(QPoint(40,40)))
                    pump(app,.05)
                    assert sidebar.drag_session.active
                    QCursor.setPos(destination)
                    pump(app,.06)
                    assert sidebar.drag_session.target is target and target.property('dropActive')
                    user32.mouse_event(0x4,0,0,0,0)
                    pressed = False
                    pump(app,.05)
                    assert not sidebar.drag_session.active and QWidget.mouseGrabber() is None
                    assert len(received) == 61 and not target.property('dropActive')
                    print('PASS: physical Windows mouse capture, native video highlight, drop and release',flush=True)
                finally:
                    if pressed:
                        user32.mouse_event(0x4,0,0,0,0)
                    user32.SetWindowPos(handle,-2,0,0,0,0,0x13)
        finally:
            timer.stop()
            sidebar.drag_session.cancel()
            player.release()
            window.close()
            app.processEvents()
            QCursor.setPos(cursor)
            app.shutdown()


if __name__ == '__main__':
    main()
