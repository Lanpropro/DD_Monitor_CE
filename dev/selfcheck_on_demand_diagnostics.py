"""On-demand lifecycle and pipe checks; fixtures are not bug reproductions."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QDrag
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm.on_demand_diagnostics import DiagnosticEndpoint, folder_snapshot
from ddm.widgets import Sidebar


class OnDemandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.window = QWidget()
        self.window.setGeometry(-12000, -12000, 500, 700)
        self.window.sidebar = Sidebar([dict(room_id=str(i), uname='PRIVATE_NAME') for i in range(5)],
                                      self.window, auto_compact=False)
        self.window.sidebar.setGeometry(0, 0, 248, 650)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.window.close)
        self.name = 'DDMonitorCE-test-' + uuid.uuid4().hex
        self.endpoint = DiagnosticEndpoint(self.window, self.root / 'logs', self.root, name=self.name)
        self.assertTrue(self.endpoint.listening)
        self.addCleanup(self.endpoint.close)
        self.sockets = []
        self.addCleanup(lambda: [socket.abort() for socket in self.sockets])

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(5)
        self.fail('Timed out waiting for diagnostic state')

    def connect(self, request):
        socket = QLocalSocket()
        self.sockets.append(socket)
        socket.connectToServer(self.name)
        self.wait(lambda: socket.state() == QLocalSocket.ConnectedState)
        socket.write(request)
        socket.flush()
        return socket

    def request(self, mode):
        return self.connect(json.dumps(dict(protocol=1, mode=mode)).encode() + b'\n')

    def reply(self, socket):
        self.wait(socket.canReadLine)
        return json.loads(bytes(socket.readLine()))

    def test_idle_endpoint_has_no_capture_timers_logs_or_wrappers(self):
        original = QDrag.exec
        QTest.qWait(50)
        self.assertIsNone(self.endpoint.active)
        self.assertFalse((self.root / 'logs').exists())
        self.assertFalse(self.endpoint.findChildren(type(self.window.sidebar.drag_session.timer)))
        self.assertIs(QDrag.exec, original)

    def test_playback_pipe_captures_live_state_and_disconnect_removes_observers(self):
        self.window.players = {}
        self.window.wall = SimpleNamespace(tiles=[])
        socket = self.request('playback')
        self.assertEqual(self.reply(socket)['status'], 'armed')
        observer = self.endpoint.active['observer']
        self.assertTrue(observer.timer.isActive())
        self.assertEqual(self.reply(self.request('folders'))['reason'], 'capture-busy')
        observer.started -= 61
        observer.sample()
        reply = self.reply(socket)
        self.assertEqual(reply['reason'], 'limit')
        self.assertTrue(any(row['stage'] == 'playback-sample' for row in reply['records']))
        self.assertIsNone(self.endpoint.active)
        socket = self.request('playback')
        self.assertEqual(self.reply(socket)['status'], 'armed')
        observer = self.endpoint.active['observer']
        socket.abort()
        self.wait(lambda: self.endpoint.active is None)
        self.assertTrue(observer.closed)

    def test_folder_snapshot_preserves_wrong_geometry_without_layout_or_screenshot(self):
        item = self.window.sidebar._items[0]
        item.move(item.pos() + QPoint(0, 300))
        before = [(entry.geometry(), entry.isHidden(), entry.internalWinId())
                  for entry in self.window.sidebar._items]
        with patch.object(self.window.sidebar.list_box, 'relayout', side_effect=AssertionError('No layout')), \
                patch.object(QWidget, 'winId', side_effect=AssertionError('No new HWND')), \
                patch.object(QWidget, 'grab', side_effect=AssertionError('No screenshot')):
            state = folder_snapshot(self.window.sidebar)
        self.assertGreater(state['mismatches'], 0)
        self.assertEqual(before, [(entry.geometry(), entry.isHidden(), entry.internalWinId())
                                  for entry in self.window.sidebar._items])
        self.assertNotIn('PRIVATE_', json.dumps(state))

    def test_folder_pipe_reply_and_log_are_complete_and_single_use(self):
        reply = self.reply(self.request('folders'))
        self.assertEqual(reply['status'], 'complete')
        self.assertFalse(reply['history_available'])
        self.assertEqual(reply['reason'], 'snapshot-finished')
        self.assertIsNone(self.endpoint.active)
        log = self.root / 'logs/on-demand.jsonl'
        contents = log.read_bytes()
        QTest.qWait(40)
        self.assertEqual(log.read_bytes(), contents)
        self.assertNotIn(b'PRIVATE_', contents)

    def test_invalid_and_oversized_requests_never_start_capture(self):
        for request in (b'{"protocol":1,"mode":"execute"}\n', b'[]\n',
                        b'{"protocol":1,"mode":"folders","path":"private"}\n'):
            self.assertEqual(self.reply(self.connect(request))['status'], 'error')
        socket = self.connect(b'x' * 4097)
        self.wait(lambda: socket.state() == QLocalSocket.UnconnectedState)
        self.assertFalse((self.root / 'logs').exists())

    def test_drag_disconnect_timeout_and_busy_restore_all_hooks(self):
        original = QDrag.exec
        cleanup = self.window.sidebar.drag_session._cleanup
        socket = self.request('drag')
        self.assertEqual(self.reply(socket)['status'], 'armed')
        self.assertEqual(self.reply(self.request('folders'))['reason'], 'capture-busy')
        self.assertIsNot(QDrag.exec, original)
        socket.abort()
        self.wait(lambda: self.endpoint.active is None)
        self.assertIs(QDrag.exec, original)
        self.assertEqual(self.window.sidebar.drag_session._cleanup, cleanup)
        socket = self.request('drag')
        self.assertEqual(self.reply(socket)['status'], 'armed')
        self.endpoint.active['observer'].timer.start(10)
        self.assertEqual(self.reply(socket)['reason'], 'timeout')
        self.assertIs(QDrag.exec, original)

    def test_native_drag_result_is_preserved_and_capture_stops_after_one_attempt(self):
        with patch.object(QDrag, 'exec', return_value='fixture-ignore') as original:
            socket = self.request('drag')
            self.assertEqual(self.reply(socket)['status'], 'armed')
            self.assertEqual(QDrag(self.window.sidebar).exec(), 'fixture-ignore')
            reply = self.reply(socket)
            self.assertEqual(reply['reason'], 'attempt-finished')
            self.assertEqual(next(r['action'] for r in reply['records'] if r['stage'] == 'drag-return'), 'fixture-ignore')
            self.assertIs(QDrag.exec, original)
            original.assert_called_once()

    def test_cancel_during_native_drag_does_not_write_when_drag_later_returns(self):
        def cancel_inside_drag(*args, **kwargs):
            self.endpoint.active['observer'].finish('timeout')
            log = self.root / 'logs/on-demand.jsonl'
            self.stopped_contents = log.read_bytes()
            return 'fixture-ignore'
        with patch.object(QDrag, 'exec', side_effect=cancel_inside_drag):
            socket = self.request('drag')
            self.assertEqual(self.reply(socket)['status'], 'armed')
            self.assertEqual(QDrag(self.window.sidebar).exec(), 'fixture-ignore')
            self.assertEqual(self.reply(socket)['reason'], 'timeout')
            self.assertEqual((self.root / 'logs/on-demand.jsonl').read_bytes(), self.stopped_contents)

    @unittest.skipUnless(os.name == 'nt', 'Windows .NET pipe interoperability')
    def test_dotnet_tool_connects_to_qt_and_packages_exact_live_evidence(self):
        # Compile the existing console test driver, which uses the actual tool client/collector.
        from selfcheck_diagnostics import DiagnosticTests
        DiagnosticTests.compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'
        driver = self.root / 'client.exe'
        DiagnosticTests.compile(driver, [ROOT / 'tools/diagnostics/Collector.cs',
            ROOT / 'tools/diagnostics/NativeDependencies.cs', ROOT / 'tools/diagnostics/Program.cs',
            ROOT / 'dev/diagnostics_tests.cs'])
        (self.root / 'main.py').write_text('# fixture: never execute\n', encoding='utf-8')
        self.endpoint.close()
        self.endpoint = DiagnosticEndpoint(self.window, self.root / 'logs', self.root)
        self.addCleanup(self.endpoint.close)
        import zipfile
        for mode in ('folders', 'drag', 'unsupported-host'):
            output = self.root / mode
            output.mkdir()
            pid = 2147483000 if mode == 'unsupported-host' else os.getpid()
            with patch.object(QDrag, 'exec', return_value=Qt.IgnoreAction):
                process = subprocess.Popen([str(driver), '--live-capture', str(self.root), str(pid),
                                            'folders' if mode == 'unsupported-host' else mode, str(output)],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if mode == 'drag':
                    self.wait(lambda: self.endpoint.active is not None and self.endpoint.active['observer'] is not None)
                    self.assertEqual(QDrag(self.window.sidebar).exec(), Qt.IgnoreAction)
                self.wait(lambda: process.poll() is not None, timeout=40)
                stdout, stderr = process.communicate()
            self.assertEqual(process.returncode, 0, stderr)
            with zipfile.ZipFile(next(output.glob('*.zip'))) as archive:
                evidence = json.loads(archive.read('live-capture.json'))
                self.assertEqual(evidence['status'], 'external-only' if mode == 'unsupported-host' else 'captured')
                if mode != 'unsupported-host':
                    self.assertEqual(evidence['host']['pid'], os.getpid())
                self.assertIn('logs/on-demand.jsonl', archive.namelist())
                self.assertNotIn('PRIVATE_', archive.read('live-capture.json').decode())
            self.assertIn(b'live capture passed', stdout)


if __name__ == '__main__':
    unittest.main()
