"""枚举当前显示器信息（分辨率、缩放、可用区域），用于设计自适应布局。"""
from PySide6.QtGui import QGuiApplication

app = QGuiApplication([])
print("=== 屏幕 ===")
for index, screen in enumerate(app.screens()):
    geo = screen.geometry()
    avail = screen.availableGeometry()
    print(f"[{index}] name={screen.name()}")
    print(f"    geometry         : {geo.width()}x{geo.height()} @ ({geo.x()},{geo.y()})")
    print(f"    availableGeometry: {avail.width()}x{avail.height()} @ ({avail.x()},{avail.y()})")
    print(f"    devicePixelRatio : {screen.devicePixelRatio()}")
    print(f"    logicalDpi       : {screen.logicalDotsPerInch()}  (缩放约 {screen.logicalDotsPerInch() / 96:.2f}x)")
    print(f"    physicalDpi      : {screen.physicalDotsPerInch()}")
    print(f"    physicalSize     : {screen.physicalSize().width():.0f}x{screen.physicalSize().height():.0f} mm")
    print(f"    dpr*size         : {geo.width() * screen.devicePixelRatio():.0f}x"
          f"{geo.height() * screen.devicePixelRatio():.0f}")
primary = app.primaryScreen()
print(f"\n主屏: {primary.name()}")
print(f"虚拟桌面总区域: {app.primaryScreen().virtualGeometry().width()}x"
      f"{app.primaryScreen().virtualGeometry().height()}")
