"""Raw image cache and visible-only QMovie playback, without account cookies."""
from collections import deque
import hashlib
import math
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit
import requests
from PySide6.QtCore import QEvent,QObject,QSize,Qt,Signal,Slot
from PySide6.QtGui import QImage,QImageReader,QMovie,QPixmap
from PySide6.QtWidgets import QLabel
from .workers import Request,start_worker

_downloads=threading.BoundedSemaphore(4)
_MAX_BYTES=8*1024*1024

def _fetch(url,cache_dir):
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname:
        raise ValueError('不支持的图片地址')
    target=Path(cache_dir)/(hashlib.sha256(url.encode()).hexdigest()+'.image')
    if target.is_file() and not QImage(str(target)).isNull():return str(target)
    with _downloads:
        if target.is_file() and not QImage(str(target)).isNull():return str(target)
        response=requests.get(url,timeout=10)
        response.raise_for_status()
        data=response.content
        length=response.headers.get('Content-Length')
        if (not data or len(data)>_MAX_BYTES or length and int(length)!=len(data) or
                QImage.fromData(data).isNull()):
            raise ValueError('图片下载不完整或格式无效')
        Path(cache_dir).mkdir(parents=True,exist_ok=True)
        handle,path=tempfile.mkstemp(prefix='.partial-',dir=cache_dir)
        try:
            with os.fdopen(handle,'wb') as output:output.write(data)
            os.replace(path,target)
        finally:
            if os.path.exists(path):os.unlink(path)
    return str(target)

class GiftMediaLoader(QObject):
    loaded=Signal(int,str,str)
    failed=Signal(int,str)

    def __init__(self,cache_dir,parent=None):
        super().__init__(parent)
        self.cache_dir=str(cache_dir);self._serial=0;self._generation=0
        self._pending=deque();self._running={};self._closed=False

    def request(self,urls,generation):
        if self._closed:return
        self.cancel();self._generation=generation
        self.enqueue(urls,generation)

    def enqueue(self,urls,generation):
        """Append fallbacks without canceling this view's other visible images."""
        if self._closed or generation!=self._generation:return
        scheduled=set(self._pending)
        scheduled.update(context[2] for context in self._running.values() if context[0]==self._serial)
        for url in urls:
            if url not in scheduled:
                self._pending.append(url);scheduled.add(url)
        self._pump()

    def cancel(self):
        self._serial+=1;self._pending.clear()
        for worker in tuple(self._running):worker.cancel()

    def _pump(self):
        if self._closed:return
        while self._pending and len(self._running)<4:
            url=self._pending.popleft();context=(self._serial,self._generation,url)
            worker=Request(context,lambda c,u=url:_fetch(u,self.cache_dir),cookies={},account_generation=0)
            self._running[worker]=context
            worker.completed.connect(self._done);worker.failed.connect(self._failed)
            worker.finished.connect(self._finished)
            start_worker(worker)

    @Slot(object,object)
    def _done(self,context,path):
        if not self._closed and context[0]==self._serial:self.loaded.emit(context[1],context[2],path)

    @Slot(object,object)
    def _failed(self,context,error):
        if not self._closed and context[0]==self._serial:self.failed.emit(context[1],context[2])

    @Slot()
    def _finished(self):
        self._running.pop(self.sender(),None);self._pump()

    def shutdown(self):
        if not self._closed:self.cancel();self._closed=True

class GiftImageLabel(QLabel):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.movie=None;self._playing=True;self._path='';self._fallback_path='';self._dpr=0
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(40,40)

    def set_file(self,path,*,fallback_path=''):
        if (path,fallback_path,self.devicePixelRatioF())==(self._path,self._fallback_path,self._dpr):return
        self._path,self._fallback_path=path,fallback_path
        self._render_file()

    def _render_file(self):
        self._dpr=self.devicePixelRatioF()
        if self.movie:
            self.movie.stop();self.movie.setFileName('');self.movie.deleteLater();self.movie=None
        self.clear()
        if not self._path:return
        target=QSize(math.ceil(self.width()*self._dpr),math.ceil(self.height()*self._dpr))
        path=self._path
        native=QImageReader(path).size()
        fallback=QImageReader(self._fallback_path).size() if self._fallback_path else QSize()
        # A low-resolution animation must not replace a sharper static original
        # when the current display needs more pixels than the GIF contains.
        if native.isValid() and fallback.isValid():
            scale=min(target.width()/native.width(),target.height()/native.height())
            fallback_scale=min(target.width()/fallback.width(),target.height()/fallback.height())
            if scale>1 and fallback_scale<scale:path=self._fallback_path;native=fallback
        reader=QImageReader(path)
        animated=reader.supportsAnimation() and reader.imageCount()>1
        del reader
        if animated:
            movie=QMovie(path,parent=self)
            movie.setCacheMode(QMovie.CacheAll)
            movie.setScaledSize(native.scaled(target,Qt.KeepAspectRatio))
            self.movie=movie;movie.frameChanged.connect(self._show_frame)
            movie.jumpToFrame(0);self._show_frame();self.set_playing(self._playing)
        else:
            pixmap=QPixmap(path)
            if not pixmap.isNull():
                pixmap=pixmap.scaled(target,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                pixmap.setDevicePixelRatio(self._dpr);self.setPixmap(pixmap)

    def _show_frame(self,*args):
        if self.movie:
            frame=self.movie.currentPixmap()
            frame.setDevicePixelRatio(self._dpr);self.setPixmap(frame)

    def event(self,event):
        handled=super().event(event)
        if event.type()==QEvent.DevicePixelRatioChange and hasattr(self,'_path'):
            self._render_file()
        return handled

    def set_playing(self,playing):
        self._playing=bool(playing)
        if self.movie:
            if self._playing and self.isVisible():
                if self.movie.state()==QMovie.NotRunning:self.movie.start()
                else:self.movie.setPaused(False)
            elif self.movie.state()!=QMovie.NotRunning:self.movie.setPaused(True)

    def hideEvent(self,event):
        if self.movie and self.movie.state()!=QMovie.NotRunning:self.movie.setPaused(True)
        super().hideEvent(event)

    def showEvent(self,event):
        super().showEvent(event);self.set_playing(self._playing)
