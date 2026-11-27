"""Exercise the local host pipe and optional real MCP client in an isolated Qt host."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from selfcheck_main_notices import MainNoticesTests
from PySide6.QtNetwork import QLocalSocket
from ddm.on_demand_diagnostics import DiagnosticEndpoint


def main():
    fixture = MainNoticesTests()
    fixture.setUpClass()
    fixture.setUp()
    try:
        window = fixture.window([{'room_id': '101', 'live': False}], offscreen=True)
        with tempfile.TemporaryDirectory() as directory:
            endpoint = DiagnosticEndpoint(window, directory, directory)
            try:
                assert endpoint.listening

                def call(action, **params):
                    socket = QLocalSocket()
                    socket.connectToServer(endpoint.server.serverName())
                    assert socket.waitForConnected(1000)
                    payload = dict(protocol=1, mode='host-mcp', action=action, **params)
                    socket.write(json.dumps(payload).encode() + b'\n')
                    socket.flush()
                    deadline = time.monotonic() + 5
                    while not socket.canReadLine() and time.monotonic() < deadline:
                        fixture.app.processEvents()
                    assert socket.canReadLine(), action
                    return json.loads(bytes(socket.readLine()))

                assert call('state')['result']['slots'][0]['occupied']
                assert 'portrait_main4' in call('layouts')['result']['builtin']
                assert call('set_layout', layout='INVALID')['status'] == 'error'
                assert call('remove', slot=0)['reason'] == 'invalid-slot'
                assert call('remove', slot=True)['reason'] == 'invalid-slot'
                assert call('remove', slot=1, extra=2)['reason'] == 'invalid-request'
                assert call('open_pip', slots=[1, 1])['reason'] == 'invalid-pip-slots'
                window.sidebar.layoutChosen.emit('1x2')
                assert call('state')['result']['last_layout_change']['layout'] == '1x2'
                state = call('set_layout', layout='portrait_main4')['result']['state']
                assert state['orientation'] == 'portrait' and state['last_layout_change']['sync_ms'] >= 0
                assert call('open_pip', slots=[1])['result']['state']['picture_in_picture']
                assert call('remove', slot=1)['reason'] == 'slot-unavailable'
                assert not call('close_pip')['result']['state']['picture_in_picture']
                tile = window.wall.tiles[0]
                window._pending_capture[tile] = True
                try:
                    assert call('remove', slot=1)['reason'] == 'slot-recording'
                finally:
                    del window._pending_capture[tile]
                assert not call('remove', slot=1)['result']['state']['slots'][0]['occupied']
                assert window.wall_removal.can_undo() and window.wall_removal.undo()
                if python := os.environ.get('DDM_MCP_PYTHON'):
                    client = Path(__file__).resolve().parents[1] / 'tools/host_mcp/check_client.py'
                    with subprocess.Popen([python, str(client), str(os.getpid())]) as process:
                        deadline = time.monotonic() + 45
                        while process.poll() is None and time.monotonic() < deadline:
                            fixture.app.processEvents()
                            time.sleep(.005)
                        if process.poll() is None:
                            process.kill()
                        assert process.wait() == 0, 'stdio MCP client failed'
            finally:
                endpoint.close()
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    main()
