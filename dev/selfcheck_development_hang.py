"""External watchdog mechanics, not evidence that a real application hang is fixed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev import watch_development_hang as monitor


class DevelopmentHangTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'work').mkdir()
        self.settings = self.root / 'work/development-hang-monitor.json'
        self.settings.write_text(json.dumps(dict(enabled=True, py_spy='fixture-spy',
                                                 native_sampler='fixture-native')), encoding='utf-8')

    def test_launch_is_local_opt_in_and_isolated_checks_do_not_start_it(self):
        with patch.object(monitor.subprocess, 'Popen') as launch, \
                patch.dict(os.environ, {'DDM_NO_SAVE': '', 'DDM_CHECK_MODE': ''}), \
                patch.object(monitor.sys, 'platform', 'win32'):
            monitor.start_for_current_process(self.root)
            args = launch.call_args.args[0]
            self.assertEqual(args[-2:], ['--pid', str(os.getpid())])
            self.assertEqual(launch.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
            launch.reset_mock()
            with patch.dict(os.environ, {'DDM_NO_SAVE': '1'}):
                self.assertIsNone(monitor.start_for_current_process(self.root))
            self.settings.unlink()
            self.assertIsNone(monitor.start_for_current_process(self.root))
            launch.assert_not_called()

    def test_invalid_local_config_does_not_block_application_startup(self):
        self.settings.write_text('{', encoding='utf-8')
        with patch.dict(os.environ, {'DDM_NO_SAVE': '', 'DDM_CHECK_MODE': ''}), \
                patch.object(monitor.sys, 'platform', 'win32'), patch.object(monitor.sys, 'stderr'):
            self.assertIsNone(monitor.start_for_current_process(self.root))

    def test_three_timeouts_capture_once_and_recovery_rearms(self):
        kernel = SimpleNamespace(OpenProcess=Mock(return_value=1), CloseHandle=Mock(),
            WaitForSingleObject=Mock(side_effect=[258, 258, 258, 258, 0]))
        with patch.object(monitor, 'ROOT', self.root), patch.object(monitor, 'prepare_windows'), \
                patch.object(monitor, 'kernel32', kernel, create=True), \
                patch.object(monitor.sys, 'argv', ['watch', '--pid', '42']), \
                patch.object(monitor, 'targets', return_value=[(42, 13, 7)]) as targets, \
                patch.object(monitor, 'responsive', side_effect=[False, False, False, True]), \
                patch.object(monitor, 'capture') as capture, \
                patch.object(monitor.time, 'monotonic', side_effect=[0, 16, 18, 20, 22]), \
                patch.object(monitor.time, 'sleep'):
            monitor.main()
            capture.assert_called_once_with(42, 13, 7)
            self.assertTrue(all(c.args == (42,) for c in targets.call_args_list))
        rows = [json.loads(line) for p in (self.root / 'logs').rglob('monitor.jsonl')
                for line in p.read_text(encoding='utf-8').splitlines()]
        self.assertIn('recovered', [r['phase'] for r in rows])
        kernel.CloseHandle.assert_called_once_with(1)

    def test_stack_sampling_excludes_locals_and_never_kills_native_sampler(self):
        native = Mock()
        native.pid = 99
        native.wait.side_effect = subprocess.TimeoutExpired('fixture', 20)
        with patch.object(monitor, 'OUT', self.root, create=True), \
                patch.object(monitor, 'SPY', Path('fixture-spy'), create=True), \
                patch.object(monitor, 'NATIVE', Path('fixture-native'), create=True), \
                patch.object(monitor.subprocess, 'Popen', return_value=native), \
                patch.object(monitor.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=b'function stacks', stderr=b'')) as sample, \
                patch.object(monitor.time, 'sleep'):
            monitor.capture(42, 13, 7)
            self.assertEqual(sample.call_count, 2)
            for call in sample.call_args_list:
                self.assertIn('--nonblocking', call.args[0])
                self.assertNotIn('--locals', call.args[0])
            native.terminate.assert_not_called()
            native.kill.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows process handle lifetime')
    def test_observer_exits_after_real_isolated_target_exits(self):
        target = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.4)'],
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with patch.object(monitor, 'ROOT', self.root), \
                    patch.object(monitor.sys, 'argv', ['watch', '--pid', str(target.pid)]), \
                    patch.object(monitor, 'capture') as capture:
                monitor.main()
                capture.assert_not_called()
            self.assertIsNotNone(target.poll())
        finally:
            target.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
