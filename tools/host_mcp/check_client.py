"""End-to-end client used by the isolated host regression."""
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(pid):
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name('server.py'))])
    async with stdio_client(params) as streams, ClientSession(*streams) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert len(tools.tools) == 7

        async def call(name, **arguments):
            result = await session.call_tool(name, arguments)
            assert not result.isError, result.content
            return json.loads(result.content[0].text)

        assert pid in (await call('list_instances'))['pids']
        assert (await call('get_state', pid=pid))['slots'][0]['occupied']
        assert '2x2' in (await call('list_layouts', pid=pid))['builtin']
        assert (await call('set_layout', pid=pid, layout='2x2'))['state']['orientation'] == 'landscape'
        assert (await call('open_picture_in_picture', pid=pid, slots=[1]))['state']['picture_in_picture']
        assert not (await call('close_picture_in_picture', pid=pid))['state']['picture_in_picture']
        assert not (await call('remove_wall_slot', pid=pid, slot=1))['state']['slots'][0]['occupied']
        print('PASS stdio handshake, discovery and all seven tools', flush=True)


if __name__ == '__main__':
    asyncio.run(check(int(sys.argv[1])))
