"""Windows stdio MCP server for the DD Monitor CE host."""
import asyncio
import json
import os

from mcp.server.fastmcp import FastMCP

server = FastMCP('DD Monitor CE host')
PREFIX = 'DDMonitorCE-diagnostics-'


async def request(pid, action, **args):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Invalid host PID')
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(15):
            transport, _ = await loop.create_pipe_connection(lambda: protocol, rf'\\.\pipe\{PREFIX}{pid}')
            try:
                payload = dict(protocol=1, mode='host-mcp', action=action, **args)
                transport.write(json.dumps(payload).encode('utf-8') + b'\n')
                line = await reader.readline()
            finally:
                transport.close()
    except TimeoutError as error:
        raise ValueError('Host timed out. Read state before retrying an action.') from error
    except PermissionError as error:
        raise ValueError('Windows denied access to the host pipe. Check the host and client user contexts.') from error
    except OSError as error:
        raise ValueError('Host pipe unavailable. Refresh list_instances.') from error
    if not line:
        raise ValueError('Host disconnected before replying')
    response = json.loads(line)
    if response.get('status') != 'complete':
        reason = response.get('reason', 'unknown-error')
        if reason == 'invalid-request':
            raise ValueError('Host rejected the request. Restart an updated host for MCP support.')
        raise ValueError(reason)
    return response['result']


@server.tool()
def list_instances() -> dict:
    """List Windows host diagnostic pipe PIDs. Use get_state to check MCP support."""
    return {'pids': sorted(int(name[len(PREFIX):]) for name in os.listdir('//./pipe/')
                           if name.startswith(PREFIX) and name[len(PREFIX):].isdigit())}


@server.tool()
async def get_state(pid: int) -> dict:
    """Read layout, orientation, one-based slots, playing count, PiP and last layout timing."""
    return await request(pid, 'state')


@server.tool()
async def list_layouts(pid: int) -> dict:
    """List builtin and saved layout IDs offered by this host."""
    return await request(pid, 'layouts')


@server.tool()
async def set_layout(pid: int, layout: str) -> dict:
    """Select a layout through the normal handler. Portrait layouts switch orientation."""
    return await request(pid, 'set_layout', layout=layout)


@server.tool()
async def open_picture_in_picture(pid: int, slots: list[int]) -> dict:
    """Open the selected occupied one-based wall slots in a PiP window."""
    return await request(pid, 'open_pip', slots=slots)


@server.tool()
async def close_picture_in_picture(pid: int) -> dict:
    """Close the floating PiP and restore the wall."""
    return await request(pid, 'close_pip')


@server.tool()
async def remove_wall_slot(pid: int, slot: int) -> dict:
    """Remove one occupied one-based slot using wall removal. UI undo stays available."""
    return await request(pid, 'remove', slot=slot)


if __name__ == '__main__':
    server.run(transport='stdio')
