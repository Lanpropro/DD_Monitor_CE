"""Startup must not query WMI before importing dependencies or showing a window."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = """
import sys, types, runpy
fake_wmi = types.ModuleType('_wmi')
def query(*args):
    raise AssertionError('Startup called WMI')
fake_wmi.exec_query = query
sys.modules['_wmi'] = fake_wmi
runpy.run_path('main.py', run_name='startup_check')
import platform
assert platform.system() == 'Windows'
assert platform.win32_ver()[1]
from ddm import danmaku
assert not danmaku.IMPORT_ERROR, danmaku.IMPORT_ERROR
"""


@unittest.skipUnless(sys.platform == "win32", "Windows WMI regression")
class StartupWmiTests(unittest.TestCase):
    def run_child(self, code, *, native=False, windowed=False):
        env = dict(os.environ, DDM_NO_SAVE="1", PYTHONIOENCODING="utf-8",
                   QT_QPA_PLATFORM="windows" if native else "offscreen",
                   PYTHON_VLC_LIB_PATH=str(ROOT / "libvlc.dll"))
        executable = str(Path(sys.executable).with_name("pythonw.exe")) if windowed else sys.executable
        result = subprocess.run([executable, "-X", "utf8", "-c", code],
                                cwd=ROOT, env=env, capture_output=True,
                                text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dependency_import_uses_native_windows_metadata(self):
        self.run_child(BOOTSTRAP)

    def test_preimported_platform_uses_native_windows_metadata(self):
        self.run_child(BOOTSTRAP.replace("runpy.run_path", "import platform\nrunpy.run_path", 1))

    def test_native_window_opens_with_isolated_state(self):
        self.check_native_window()

    def test_pythonw_window_opens_with_isolated_state(self):
        self.check_native_window(windowed=True)

    def check_native_window(self, *, windowed=False):
        self.run_child(BOOTSTRAP + """
from contextlib import ExitStack
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from ddm.app import MainWindow
app = QApplication([])
with ExitStack() as stack:
    for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                   'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                   'load_cached_covers', 'load_cached_avatars'):
        stack.enter_context(patch.object(MainWindow, method))
    window = MainWindow([], [], layout_id='1x1',
                        state={'settings': {'auto_update': False}, 'plugins_enabled': []})
    window.show()
    app.processEvents()
    assert window.isVisible()
    window.close()
    app.processEvents()
""", native=True, windowed=windowed)


if __name__ == "__main__":
    unittest.main()
