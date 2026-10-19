"""在独立进程运行专项脚本，保留相邻导入与 Windows Qt 清理顺序。"""
from pathlib import Path
import platform
import runpy
import sys


def main():
    path = Path(sys.argv.pop(1)).resolve()
    sys.argv[0] = str(path)
    sys.path[:0] = [str(path.parent), str(Path(__file__).resolve().parents[2])]
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


if __name__ == '__main__':
    main()
