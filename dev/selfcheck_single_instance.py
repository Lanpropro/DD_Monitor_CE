"""Offline process-level instance ownership and window activation checks."""
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm.single_instance import SingleInstance


def child(root):
    app = QApplication([])
    instance = SingleInstance(app, runtime_dir=root)
    if not instance.start():
        print('secondary', flush=True)
        return 0
    with (Path(root) / 'owners.txt').open('a') as handle:
        handle.write(str(os.getpid()) + '\n')
    print('primary', flush=True)
    timer = QTimer()
    timer.timeout.connect(lambda: app.quit() if (Path(root) / 'stop').exists() else None)
    timer.start(20)
    QTimer.singleShot(15000, app.quit)
    result = app.exec()
    instance.close()
    return result


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-instance-')))
        self.instances = []
        self.children = []

    def tearDown(self):
        for process in self.children:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        for instance in self.instances:
            instance.close()
            instance.deleteLater()
        self.app.processEvents()

    def instance(self):
        instance = SingleInstance(self.app, runtime_dir=self.root)
        self.instances.append(instance)
        return instance

    def spawn(self):
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--claim', str(self.root)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding='utf-8', errors='replace')
        self.children.append(process)
        return process

    def wait(self, condition):
        deadline = time.monotonic() + 10
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(condition(), 'Timed out waiting for instance fixture')

    def test_repeated_launch_notifies_owner_and_exits(self):
        owner = self.instance()
        self.assertTrue(owner.start())
        restore = Mock()
        owner.set_restore(restore)
        for count in range(1, 4):
            process = self.spawn()
            self.wait(lambda: process.poll() is not None)
            output, errors = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 0, errors)
            self.assertEqual(output.strip(), 'secondary')
            self.wait(lambda: restore.call_count == count)
        self.assertFalse((self.root / 'owners.txt').exists())

    def test_launch_during_startup_restores_after_window_is_ready(self):
        owner = self.instance()
        self.assertTrue(owner.start())
        process = self.spawn()
        self.wait(lambda: process.poll() is not None)
        output, errors = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 0, errors)
        self.assertEqual(output.strip(), 'secondary')
        self.wait(lambda: owner._pending)
        restore = Mock()
        owner.set_restore(restore)
        restore.assert_called_once()

    def test_fast_peer_acknowledges_repeated_requests(self):
        process = self.spawn()
        self.wait(lambda: (self.root / 'owners.txt').exists())
        for _ in range(10):
            self.assertFalse(self.instance().start())
        self.assertIsNone(process.poll())
        (self.root / 'stop').touch()
        output, errors = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 0, errors)
        self.assertEqual(output.strip(), 'primary')

    def test_release_allows_restart_before_old_process_exits(self):
        previous = self.instance()
        self.assertTrue(previous.start())
        previous.close()
        restarted = self.instance()
        self.assertTrue(restarted.start())
        previous.close()  # Closing the former owner cannot unlock its successor.
        restore = Mock()
        restarted.set_restore(restore)
        process = self.spawn()
        self.wait(lambda: process.poll() is not None)
        process.communicate(timeout=8)
        self.wait(lambda: restore.called)

    def test_crashed_owner_does_not_block_next_launch(self):
        process = self.spawn()
        self.wait(lambda: (self.root / 'owners.txt').exists())
        process.kill()
        process.communicate(timeout=5)
        recovered = self.instance()
        self.assertTrue(recovered.start())

    def test_simultaneous_launches_create_exactly_one_owner(self):
        processes = [self.spawn() for _ in range(4)]
        self.wait(lambda: sum(process.poll() is not None for process in processes) == 3)
        owners = (self.root / 'owners.txt').read_text().splitlines()
        self.assertEqual(len(owners), 1)
        (self.root / 'stop').touch()
        for process in processes:
            output, errors = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 0, errors)
        self.assertEqual(len((self.root / 'owners.txt').read_text().splitlines()), 1)

    def test_secondary_main_does_not_load_state_or_create_window(self):
        from ddm import app as host
        with (patch.object(host, 'QApplication', return_value=self.app),
              patch.object(host, 'SingleInstance') as guard,
              patch.object(host.config_module, 'load') as load,
              patch.object(host, 'MainWindow') as window,
              patch.object(host, 'setup_file_log') as log):
            guard.return_value.start.return_value = False
            self.assertEqual(host.main(['main.py']), 0)
            load.assert_not_called()
            window.assert_not_called()
            log.assert_not_called()


if __name__ == '__main__':
    if sys.argv[1:2] == ['--claim']:
        raise SystemExit(child(sys.argv[2]))
    unittest.main()
