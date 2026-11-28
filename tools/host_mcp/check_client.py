"""End-to-end client used by the isolated host regression."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(pid):
    from server import pipe_request, request
    loop = asyncio.get_running_loop()
    with patch.object(loop, 'create_pipe_connection', side_effect=PermissionError()):
        try:
            await request(pid, 'state')
        except ValueError as error:
            assert 'denied access' in str(error)
        else:
            raise AssertionError('Missing pipe permission error')
    async def disconnected(factory, _address):
        protocol = factory()
        protocol.data_received(b'{"status":"armed"}\n')
        protocol.eof_received()
        return type('Transport', (), {'write': lambda *_args: None, 'close': lambda *_args: None})(), protocol

    with patch.object(loop, 'create_pipe_connection', side_effect=disconnected):
        try:
            await pipe_request(pid, dict(protocol=1, mode='playback'))
        except ValueError as error:
            assert 'disconnected before replying' in str(error)
        else:
            raise AssertionError('Missing interrupted capture error')

    with tempfile.TemporaryDirectory(prefix='ddm-mcp-client-') as temporary:
        root = Path(temporary)
        checkout = Path(__file__).resolve().parents[2]
        for name in ('tools/host_mcp/server.py', 'ddm/__init__.py', 'ddm/diagnostic_startup_request.py'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checkout / name, path)
        await check_tools(pid, root)


async def check_tools(pid, root):
    from ddm.diagnostic_startup_request import consume

    params = StdioServerParameters(command=sys.executable, args=[str(root / 'tools/host_mcp/server.py')])
    async with stdio_client(params) as streams, ClientSession(*streams) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert {'list_settings_pages', 'get_settings_state', 'open_settings_page', 'close_settings',
                'measure_sidebar_interactions', 'capture_diagnostics', 'capture_wall_buffers',
                'remove_wall_slots', 'undo_wall_removal',
                'list_startup_diagnostics', 'prepare_startup_diagnostics'} <= {
            tool.name for tool in tools.tools}

        async def call(name, **arguments):
            result = await session.call_tool(name, arguments)
            assert not result.isError, result.content
            return json.loads(result.content[0].text)

        assert pid in (await call('list_instances'))['pids']
        modes = (await call('list_startup_diagnostics'))['modes']
        assert {'window-resize', 'settings-scroll', 'douyu-deep'} <= set(modes)
        assert (await session.call_tool('prepare_startup_diagnostics', {'mode': 'unknown'})).isError
        assert consume(root) is None
        startup = await call('prepare_startup_diagnostics', mode='window-resize')
        assert consume(root) == startup and consume(root) is None

        folders = await call('capture_diagnostics', pid=pid, mode='folders')
        assert folders['reason'] == 'snapshot-finished' and folders['records'][1]['stage'] == 'folder-snapshot'
        playback = await call('capture_diagnostics', pid=pid, mode='playback', seconds=1)
        assert playback['reason'] == 'limit' and playback['records'][1]['limit_seconds'] == 1
        for mode in ('douyu', 'fullscreen', 'notices'):
            capture = await call('capture_diagnostics', pid=pid, mode=mode, seconds=1)
            assert capture['mode'] == mode and capture['reason'] == 'timeout'
            assert capture['records'][1]['stage'] == 'specialty-start'
        sidebar = await call('measure_sidebar_interactions', pid=pid, seconds=1)
        assert sidebar['pid'] == pid and sidebar['heartbeat']['idle']['intervals'] > 0
        assert not sidebar['phases'] and not sidebar['scroll'] and not any(sidebar['drag_outcomes'].values())
        assert (await call('set_pip_picker_visible', pid=pid, visible=True))['visible']
        assert (await call('set_pip_picker_visible', pid=pid, visible=True))['visible']
        assert not (await call('set_pip_picker_visible', pid=pid, visible=False))['visible']
        assert not (await call('get_state', pid=pid))['picture_in_picture']
        assert (await call('get_state', pid=pid))['slots'][0]['occupied']
        assert '2x2' in (await call('list_layouts', pid=pid))['builtin']
        assert (await call('set_layout', pid=pid, layout='2x2'))['state']['orientation'] == 'landscape'
        assert (await call('open_picture_in_picture', pid=pid, slots=[1]))['state']['picture_in_picture']
        assert not (await call('close_picture_in_picture', pid=pid))['state']['picture_in_picture']
        assert not (await call('remove_wall_slot', pid=pid, slot=1))['state']['slots'][0]['occupied']
        pages = (await call('list_settings_pages', pid=pid))['pages']
        assert any(row['id'] == 'general' for row in pages)

        async def wait_for(window, page):
            async with asyncio.timeout(12):
                while True:
                    state = await call('get_settings_state', pid=pid)
                    if (state['window'], state['page'], state['visible']) == (window, page, page is not None):
                        return
                    await asyncio.sleep(.05)

        for entry, window, page in (('monitor', 'worker', 'streamer_defaults'), ('sidebar', 'worker', 'general')):
            try:
                assert (await call('open_settings_page', pid=pid, page=page, entry=entry))['accepted']
                await wait_for(window, page)
                await call('open_settings_page', pid=pid, page='shortcuts')
                await wait_for(window, 'shortcuts')
            finally:
                await call('close_settings', pid=pid)
            await wait_for('closed', None)
        print('PASS stdio discovery, on-demand diagnostics, wall controls and settings navigation', flush=True)


if __name__ == '__main__':
    asyncio.run(check(int(sys.argv[1])))
