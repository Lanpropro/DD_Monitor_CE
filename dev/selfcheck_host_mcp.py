"""Exercise the local host pipe and optional real MCP client in an isolated Qt host."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from selfcheck_main_notices import MainNoticesTests
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QPushButton
from ddm.app import MainWindow
from ddm.bili import StreamResolver
from ddm.on_demand_diagnostics import DiagnosticEndpoint
from ddm.online_ui import UpdateNotice, show_result
from ddm.player import TilePlayer


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

                def open_request(payload):
                    socket = QLocalSocket()
                    socket.connectToServer(endpoint.server.serverName())
                    assert socket.waitForConnected(1000)
                    socket.write(json.dumps(payload).encode() + b'\n')
                    socket.flush()
                    return socket

                def response(socket):
                    deadline = time.monotonic() + 5
                    while not socket.canReadLine() and time.monotonic() < deadline:
                        fixture.app.processEvents()
                        time.sleep(.001)
                    assert socket.canReadLine()
                    return json.loads(bytes(socket.readLine()))

                def call(action, **params):
                    return response(open_request(dict(protocol=1, mode='host-mcp', action=action, **params)))

                def capture(mode, seconds=1):
                    return open_request(dict(protocol=1, mode=mode, seconds=seconds))

                def check_specialty(mode, hook, operation, log):
                    original = getattr(*hook)
                    socket = capture(mode)
                    assert response(socket)['status'] == 'armed', mode
                    assert getattr(*hook) is not original, mode
                    operation()
                    result = response(socket)
                    assert (result['mode'], result['reason']) == (mode, 'timeout'), result
                    assert result['records'][1]['stage'] == 'specialty-start', result
                    contents = (Path(directory) / log).read_text(encoding='utf-8')
                    assert getattr(*hook) is original and endpoint.active is None, mode
                    return contents

                assert call('state')['result']['slots'][0]['occupied']
                assert response(capture('douyu', 61))['reason'] == 'invalid-request'
                assert response(capture('notices', True))['reason'] == 'invalid-request'
                assert not any(Path(directory).iterdir())

                def toggle_fullscreen():
                    tile = window.wall.tiles[0]
                    tile.fullscreenRequested.emit(tile)
                    assert window._fullscreen_tile is tile
                    window._exit_fullscreen()

                assert '"phase": "fullscreen"' in check_specialty(
                    'fullscreen', (MainWindow, '_on_fullscreen'), toggle_fullscreen,
                    'fullscreen-on-demand.jsonl')

                private_notice = 'PRIVATE_NOTICE_MCP_FIXTURE'
                show_result(window, private_notice, persistent=True)
                close = window._result_notice.findChild(QPushButton, 'NoticeClose')
                notices = check_specialty('notices', (UpdateNotice, 'dismiss'), close.click, 'on-demand.jsonl')
                assert 'button:clicked' in notices and private_notice not in notices

                player_check = TilePlayer._check
                resolver = SimpleNamespace(room_id='douyu:fixture', quality=2, codec='h264', preview=False,
                                           source_offset=0, is_cancelled=lambda: False)
                source = ('https://fixture.invalid/live?token=PRIVATE_TOKEN', 2, 'douyu')
                def resolve_douyu():
                    assert StreamResolver._platform_play_url(resolver) == source

                with patch.object(StreamResolver, '_platform_play_url', return_value=source):
                    douyu = check_specialty('douyu', (StreamResolver, '_platform_play_url'), resolve_douyu,
                                            'douyu-on-demand.jsonl')
                assert all(stage in douyu for stage in ('source.request', 'source.result', 'capture-stop'))
                assert 'fixture.invalid' in douyu and 'PRIVATE_TOKEN' not in douyu
                socket = capture('douyu', seconds=60)
                assert response(socket)['status'] == 'armed'
                assert response(capture('notices'))['reason'] == 'capture-busy'
                socket.abort()
                deadline = time.monotonic() + 2
                while endpoint.active is not None and time.monotonic() < deadline:
                    fixture.app.processEvents()
                    time.sleep(.001)
                assert endpoint.active is None and TilePlayer._check is player_check

                pages = call('settings_pages')['result']['pages']
                assert call('pip_picker', visible=1)['reason'] == 'invalid-visibility'
                socket = capture('sidebar-performance', seconds=2)
                assert response(socket)['status'] == 'armed'
                assert call('pip_picker', visible=True)['result']['visible']
                report = next(row for row in response(socket)['records'] if row['stage'] == 'sidebar-performance')
                assert len(report['picker_first_paint_ms']) == 1 and report['phases']['picker-choice']['calls'] > 0
                assert not call('pip_picker', visible=False)['result']['visible']
                assert len(pages) == 11 and any(row['id'] == 'streamer_defaults' for row in pages)
                assert call('settings_state')['result'] == dict(window='closed', visible=False, page=None)
                assert call('settings_open', page=[], entry='sidebar')['reason'] == 'unknown-settings-page'
                assert call('settings_open', page='general', entry='monitor')['reason'] == 'invalid-settings-entry'
                assert call('settings_close')['result']['accepted']
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
