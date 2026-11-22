"""Follow Windows' native drag before its queued Qt geometry notification."""
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QAbstractNativeEventFilter,QPoint
from PySide6.QtWidgets import QApplication


class _WindowPos(ctypes.Structure):
    _fields_=[('hwnd',wintypes.HWND),('after',wintypes.HWND),
              ('x',ctypes.c_int),('y',ctypes.c_int),('cx',ctypes.c_int),
              ('cy',ctypes.c_int),('flags',wintypes.UINT)]


class _MonitorInfo(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('monitor',wintypes.RECT),
              ('work',wintypes.RECT),('flags',wintypes.DWORD)]


class NativePopupFollower(QAbstractNativeEventFilter):
    def __init__(self,popup):
        super().__init__()
        self.popup=popup;self._dragging=False;self.installed=False
        self.user32=ctypes.WinDLL('user32',use_last_error=True)
        self.user32.GetWindowRect.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.RECT))
        self.user32.SetWindowPos.argtypes=(wintypes.HWND,wintypes.HWND,ctypes.c_int,
            ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT)
        self.user32.MonitorFromRect.argtypes=(ctypes.POINTER(wintypes.RECT),wintypes.DWORD)
        self.user32.MonitorFromRect.restype=wintypes.HANDLE
        self.user32.GetMonitorInfoW.argtypes=(wintypes.HANDLE,ctypes.POINTER(_MonitorInfo))
        self.user32.ClientToScreen.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.POINT))
        self.owner=None;self.owner_hwnd=self.popup_hwnd=0;self.origin=None

    @property
    def dragging(self):
        parent=getattr(self.owner,'_native_follow',None)
        return self._dragging or parent is not None and parent.dragging

    def start(self):
        owner=self.popup._owner
        if owner is None:return
        self.owner=owner;self.owner_hwnd=int(owner.winId());self.popup_hwnd=int(self.popup.winId())
        self.capture()
        if not self.installed:
            QApplication.instance().installNativeEventFilter(self);self.installed=True

    def stop(self):
        if self.installed:QApplication.instance().removeNativeEventFilter(self)
        self.installed=False;self._dragging=False;self.owner=None;self.origin=None

    def capture(self):
        if not self.owner_hwnd:return
        owner=wintypes.RECT();popup=wintypes.RECT()
        if (self.user32.GetWindowRect(self.owner_hwnd,ctypes.byref(owner)) and
                self.user32.GetWindowRect(self.popup_hwnd,ctypes.byref(popup))):
            # Keep the original offset rather than accumulating clamped deltas.
            self.origin=(owner.left,owner.top,popup.left,popup.top,
                         owner.right-owner.left,owner.bottom-owner.top,
                         popup.right-popup.left,popup.bottom-popup.top)
            local=self.popup._anchor.mapTo(self.owner,QPoint())
            client=wintypes.POINT();self.user32.ClientToScreen(self.owner_hwnd,ctypes.byref(client))
            scale=self.owner.devicePixelRatioF()
            self.anchor_y=client.y+round(local.y()*scale)-owner.top
            self.anchor_height=round(self.popup._anchor.height()*scale);self.gap=round(6*scale)

    def nativeEventFilter(self,event_type,message):
        if not self.__dict__.get('installed'):return False,0
        native=wintypes.MSG.from_address(int(message))
        if (native.hWnd!=self.owner_hwnd or native.message not in (0x231,0x232,0x46)
                or not self.popup._event_targets_alive()):return False,0
        if native.message==0x231:  # WM_ENTERSIZEMOVE
            self.capture();self._dragging=True;self.popup._owner_dragging=True
        elif native.message==0x232:  # WM_EXITSIZEMOVE
            self._dragging=False;self.popup._owner_dragging=False
            self.popup._schedule_placement()
        elif native.message==0x46 and self.dragging and self.origin:  # WM_WINDOWPOSCHANGING
            position=_WindowPos.from_address(native.lParam)
            ox,oy,px,py,ow,oh,pw,ph=self.origin
            if not position.flags&0x1 and (position.cx,position.cy)!=(ow,oh):
                # Resize and DPI transitions need the newly laid-out anchor.
                self._dragging=False;self.popup._owner_dragging=False
                return False,0
            if position.flags&0x2:return False,0  # SWP_NOMOVE
            x,y=px+position.x-ox,py+position.y-oy
            proposed=wintypes.RECT(position.x,position.y,position.x+ow,position.y+oh)
            monitor=self.user32.MonitorFromRect(ctypes.byref(proposed),2)
            info=_MonitorInfo();info.size=ctypes.sizeof(info)
            if self.user32.GetMonitorInfoW(monitor,ctypes.byref(info)):
                work=info.work
                y=position.y+self.anchor_y-ph-self.gap
                if y<work.top:y=position.y+self.anchor_y+self.anchor_height+self.gap
                x=max(work.left,min(x,work.right-pw));y=max(work.top,min(y,work.bottom-ph))
            self.user32.SetWindowPos(self.popup_hwnd,None,x,y,
                                    0,0,0x15)  # no resize, z-order or activation
        return False,0
