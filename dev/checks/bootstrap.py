"""在独立进程运行专项脚本，保留相邻导入与 Windows Qt 清理顺序。"""
import ipaddress
import os
from pathlib import Path
import platform
import runpy
import sys


def require_local_network(event, arguments, denied):
    if event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr'):
        host = arguments[0]
    elif event == 'socket.getnameinfo':
        host = arguments[0][0]
    elif event in ('socket.connect', 'socket.sendto', 'socket.sendmsg'):
        host = arguments[1][0]
    else:
        return
    if host is None or host in ('localhost', 'localhost.', b'localhost'):
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    denied.append(event)
    raise RuntimeError('Offline check attempted external network access')


def main():
    path = Path(sys.argv.pop(1)).resolve()
    sys.argv[0] = str(path)
    sys.path[:0] = [str(path.parent), str(Path(__file__).resolve().parents[2])]
    denied = []
    if os.environ.get('DDM_CHECK_MODE') == 'offline':
        sys.addaudithook(lambda event, arguments: require_local_network(event, arguments, denied))
    if sys.platform == 'win32':
        # 与主程序一致，避免平台信息查询进入 WMI 慢路径。
        platform._wmi_query = lambda *args: (_ for _ in ()).throw(OSError('Check process'))
        import ctypes
        cookie = ctypes.c_void_p()
        ctypes.windll.ole32.CoIncrementMTAUsage(ctypes.byref(cookie))
    try:
        runpy.run_path(str(path), run_name='__main__')
    finally:
        widgets = sys.modules.get('PySide6.QtWidgets')
        app = widgets.QApplication.instance() if widgets is not None else None
        if app is not None:
            app.shutdown()
        if sys.platform == 'win32':
            ctypes.windll.ole32.CoDecrementMTAUsage(cookie)
        if denied:
            raise RuntimeError(f'Offline check attempted external network access {len(denied)} time(s)')


if __name__ == '__main__':
    main()
