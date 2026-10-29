"""Exercise application logging with temporary data and fake startup imports only."""
import io
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm import diagnostics


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.addCleanup(diagnostics.close)

    def test_streams_logging_tracebacks_and_disk_redaction(self):
        console = io.StringIO()
        with patch.object(sys, "stdout", console), patch.object(sys, "stderr", None):
            session = diagnostics.start(self.directory)
            print("[平台诊断] 阶段=source_request")
            sys.stdout.write("partial ")
            sys.stdout.write('{"token": "SECRET_JSON"}\n')
            print("Authorization: Bearer SECRET_AUTH", file=sys.stderr)
            print("Cookie: SESSDATA=SECRET_COOKIE; bili_jct=SECRET_CSRF", file=sys.stderr)
            print("wss://example.com/live?sign=SECRET_URL")
            logging.getLogger("platform").info("[取流失败] fixture")
            try:
                raise RuntimeError("password=SECRET_EXCEPTION")
            except RuntimeError:
                logging.getLogger("platform").exception("test exception")
            sys.stderr.write("without newline")
            session.close()
        contents = Path(session.path).read_text(encoding="utf-8")
        self.assertNotIn("SECRET_", contents)
        for message in ("阶段=source_request", "partial", "[取流失败]", "Traceback", "without newline"):
            self.assertIn(message, contents)
        self.assertIn("SECRET_JSON", console.getvalue())

    def test_rotation_retention_and_stable_crash_descriptor(self):
        old = self.directory / "ddm-2000-01-01.log.1"
        old.write_text("expired")
        os.utime(old, (0, 0))
        unrelated = self.directory / "other.log"
        unrelated.write_text("keep")
        os.utime(unrelated, (0, 0))
        (self.directory / "ddm-crash.log").write_text("previous crash\n" * 50)
        with patch.object(diagnostics, "MAX_BYTES", 256):
            session = diagnostics.start(self.directory)
            descriptor = session.crash_handle.fileno()
            for _ in range(25):
                session.logger.info("x" * 120)
            session.crash_handle.write("crash descriptor still open\n")
            session.close()
        self.assertFalse(old.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(Path(session.path + ".1").exists())
        self.assertLessEqual(len(list(self.directory.glob(Path(session.path).name + "*"))), 6)
        self.assertGreaterEqual(descriptor, 0)
        self.assertIn("still open", Path(session.crash_path).read_text())
        self.assertIn("previous crash", Path(session.crash_path + ".1").read_text())

    def test_unwritable_destination_falls_back_without_changing_config(self):
        blocked = self.directory / "file"
        blocked.write_text("not a directory")
        with patch.object(diagnostics.tempfile, "gettempdir", return_value=str(self.directory)):
            session = diagnostics.start(blocked / "logs")
        self.assertEqual(session.directory, self.directory / "DDMonitorCE-startup-logs")

    def test_early_import_failure_and_uncaught_thread_exception(self):
        # Execute the real entry point; replace config/app imports before Qt or accounts load.
        program = """
import runpy, sys, threading, types
from pathlib import Path
root, data = sys.argv[1:]
sys.path.insert(0, root)
config = types.ModuleType('ddm.config')
config.initialize_paths = lambda: None
config.REPO = data
sys.modules['ddm.config'] = config
class FailApp:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'ddm.app':
            raise ImportError('fixture Qt import failure token=SECRET_IMPORT')
sys.meta_path.insert(0, FailApp())
def fail():
    raise RuntimeError('fixture thread failure token=SECRET_THREAD')
# Start the thread after logging starts, during the fake app import.
original = FailApp.find_spec
def find(self, fullname, path=None, target=None):
    if fullname == 'ddm.app':
        thread = threading.Thread(target=fail)
        thread.start()
        thread.join()
    return original(self, fullname, path, target)
FailApp.find_spec = find
runpy.run_path(str(Path(root) / 'main.py'), run_name='__main__')
"""
        result = subprocess.run([sys.executable, "-c", program, str(ROOT), str(self.directory)],
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        contents = next((self.directory / "logs").glob("ddm-20*.log")).read_text(encoding="utf-8")
        self.assertIn("fixture Qt import failure", contents)
        self.assertIn("fixture thread failure", contents)
        self.assertNotIn("SECRET_", contents)

    def test_helper_entries_do_not_initialize_main_log_or_read_config(self):
        program = """
import runpy, sys, types
root, option = sys.argv[1:]
sys.path.insert(0, root)
module = types.ModuleType('ddm.settings_process' if option == '--settings-worker' else 'ddm.update_install')
def helper(*args):
    assert 'ddm.config' not in sys.modules
    assert 'ddm.diagnostics' not in sys.modules
    return 17
module.run_worker = module.run_helper = module.run_elevated_helper = helper
sys.modules[module.__name__] = module
sys.argv = ['main.py', option] + ([] if option == '--settings-worker' else ['fixture'])
runpy.run_path(root + '/main.py', run_name='__main__')
"""
        for option in ("--settings-worker", "--apply-update"):
            with self.subTest(option=option):
                result = subprocess.run([sys.executable, "-c", program, str(ROOT), option],
                                        capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 17, result.stderr)



if __name__ == "__main__":
    unittest.main()
