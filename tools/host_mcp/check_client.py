"""End-to-end client used by the isolated host regression."""
import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(pid):
    from server import request
    loop = asyncio.get_running_loop()
    with patch.object(loop, 'create_pipe_connection', side_effect=PermissionError()):
        try:
            await request(pid, 'state')
        except ValueError as error:
            assert 'denied access' in str(error)
        else:
            raise AssertionError('Missing pipe permission error')
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name('server.py'))])
    async with stdio_client(params) as streams, ClientSession(*streams) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert {'list_settings_pages', 'get_settings_state', 'open_settings_page', 'close_settings',
                'measure_sidebar_interactions', 'capture_diagnostics'} <= {
            tool.name for tool in tools.tools}

        async def call(name, **arguments):
            result = await session.call_tool(name, arguments)
            assert not result.isError, result.content
            return json.loads(result.content[0].text)

        assert pid in (await call('list_instances'))['pids']
        folders = await call('capture_diagnostics', pid=pid, mode='folders')
        assert folders['reason'] == 'snapshot-finished' and folders['records'][1]['stage'] == 'folder-snapshot'
        for mode in ('douyu', 'fullscreen', 'notices'):
            capture = await call('capture_diagnostics', pid=pid, mode=mode, seconds=1)
            assert capture['mode'] == mode and capture['reason'] == 'timeout'
            assert capture['records'][1]['stage'] == 'specialty-start'
        sidebar = await call('measure_sidebar_interactions', pid=pid, seconds=1)
        assert sidebar['pid'] == pid and sidebar['heartbeat']['idle']['intervals'] > 0
        assert not sidebar['phases'] and not sidebar['scroll'] and not any(sidebar['drag_outcomes'].values())
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

        for entry, window, page in (('monitor', 'local', 'streamer_defaults'), ('sidebar', 'worker', 'general')):
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
