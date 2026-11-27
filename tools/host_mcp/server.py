"""Windows stdio MCP server for the DD Monitor CE host."""
import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Literal

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ddm import diagnostic_startup_request

server = FastMCP('DD Monitor CE host')
PREFIX = 'DDMonitorCE-diagnostics-'


async def request(pid, action, **args):
    response = await pipe_request(pid, dict(protocol=1, mode='host-mcp', action=action, **args))
    return response['result']


async def pipe_request(pid, payload, timeout=15):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Invalid host PID')
    reader = asyncio.StreamReader(limit=1024 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(timeout):
            transport, _ = await loop.create_pipe_connection(lambda: protocol, rf'\\.\pipe\{PREFIX}{pid}')
            try:
                transport.write(json.dumps(payload).encode('utf-8') + b'\n')
                line = await reader.readline()
                if line and json.loads(line).get('status') == 'armed':
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
    return response


@server.tool()
async def capture_diagnostics(
    pid: int,
    mode: Literal['folders', 'drag', 'playback', 'dock-hover', 'douyu', 'fullscreen', 'notices'],
    seconds: int | None = None,
) -> dict:
    """Capture an already-running host. Douyu, fullscreen, notices and playback accept 1–60 seconds.

    Folders is an immediate snapshot and drag observes one attempt. Drag and dock-hover are limited to 60 seconds.
    Douyu samples the current route and upcoming requests without replacing the transport.
    """
    if seconds is not None and not 1 <= seconds <= 60:
        raise ValueError('Capture duration must be 1–60 seconds')
    payload = dict(protocol=1, mode=mode)
    if mode in ('douyu', 'fullscreen', 'notices'):
        payload['seconds'] = seconds = 30 if seconds is None else seconds
    elif mode == 'playback':
        payload['seconds'] = seconds = 60 if seconds is None else seconds
    else:
        seconds = 60
    reply = await pipe_request(pid, payload, seconds + 15)
    if reply['reason'] == 'capture-error':
        raise ValueError('Host could not start the capture')
    return reply


@server.tool()
def list_startup_diagnostics() -> dict:
    """List source-checkout diagnostics that must be armed before the next normal launch."""
    return {'modes': diagnostic_startup_request.available_modes(ROOT)}


@server.tool()
def prepare_startup_diagnostics(mode: str) -> dict:
    """Arm a single source startup capture for ten minutes. The user exits normally and runs run.cmd.

    A newer request replaces the pending one. This tool neither launches nor closes the application.
    The started host reports the matching request_id through get_state.
    """
    return diagnostic_startup_request.prepare(ROOT, mode)


@server.tool()
async def measure_sidebar_interactions(pid: int, seconds: int = 30) -> dict:
    """Observe manual sidebar card drags and scrolling for 1–60 seconds. Returns timings after the window."""
    if not 1 <= seconds <= 60:
        raise ValueError('Capture duration must be 1–60 seconds')
    reply = await pipe_request(pid, dict(protocol=1, mode='sidebar-performance', seconds=seconds), seconds + 15)
    for row in reply['records']:
        if row['stage'] == 'sidebar-performance':
            return row
    raise ValueError(reply['reason'])


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


@server.tool()
async def list_settings_pages(pid: int) -> dict:
    """List the settings page IDs and labels supported by this host."""
    return await request(pid, 'settings_pages')


@server.tool()
async def get_settings_state(pid: int) -> dict:
    """Read the actual selected page, window type and visibility."""
    return await request(pid, 'settings_state')


@server.tool()
async def open_settings_page(pid: int, page: str, entry: str = 'sidebar') -> dict:
    """Open or select a settings page. Use entry=monitor for streamer_defaults via the monitor panel.
    Returns acceptance. Poll get_settings_state for visibility and the selected page."""
    return await request(pid, 'settings_open', page=page, entry=entry)


@server.tool()
async def close_settings(pid: int) -> dict:
    """Request normal settings dismissal. Poll get_settings_state for completion."""
    return await request(pid, 'settings_close')


if __name__ == '__main__':
    server.run(transport='stdio')
