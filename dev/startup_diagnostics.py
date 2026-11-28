"""Install the source collectors explicitly prepared by the local MCP server."""
import atexit
import os

from ddm.diagnostic_startup_request import SESSION_MODES


ENVIRONMENT = {
    'fullscreen-input': {'DDM_FULLSCREEN_INPUT_CAPTURE': '1'},
    'settings-scroll': {'DDM_SETTINGS_SCROLL_CAPTURE': '1'},
    'settings-performance': {'DDM_SETTINGS_PERFORMANCE_CAPTURE': '1'},
    'live-elapsed': {'DDM_LIVE_ELAPSED_CAPTURE': '1'},
    'match-d3d11': {'DDM_MATCH_QUICK_DANMAKU': '0'},
    'match-d3d11-quick': {
        'DDM_MATCH_QUICK_DANMAKU': '1',
        'DDM_MATCH_MONITOR': '1',
        'DDM_MATCH_GUI_DISPATCH': '0',
        'DDM_MATCH_DESKTOP_CADENCE': '1',
    },
}


def install(root, directory, request):
    mode = request['mode']
    os.environ.update(ENVIRONMENT.get(mode, {}))
    if mode in SESSION_MODES:
        from ddm.diagnostic_session import install as install_session
        session = install_session(mode, directory, request_id=request['request_id'])
        return dict(mode=mode, request_id=request['request_id'], log_session=session.run)

    if mode in ('window-resize', 'window-dpi-profile'):
        from .diagnose_window_resize import WindowResizeTrace
        WindowResizeTrace(directory / 'window-resize.jsonl', profile_dpi=mode == 'window-dpi-profile').install()
    elif mode == 'wall-replacement':
        from .diagnose_wall_replacement import ReplacementTrace
        ReplacementTrace(directory / 'wall-replacement.jsonl').install()
    elif mode == 'control-swap':
        from .diagnose_control_swap import SwapTrace
        SwapTrace(directory / 'control-swap.jsonl').install()
    elif mode == 'sc':
        from .diagnose_super_chat import SuperChatTrace
        SuperChatTrace(directory / 'sc-paint').install()
    elif mode in ('danmaku-motion', 'match-d3d11', 'match-d3d11-quick'):
        from ddm.danmaku_diagnostics import MotionTrace
        if mode.startswith('match-d3d11'):
            from ddm import app
            from .match_gui_dispatch import install as install_dispatch
            os.environ['DDM_MATCH_D3D11_DIR'] = str(root / 'work/match-d3d11-prototype')
            if mode == 'match-d3d11-quick' and (source := os.environ.get('DDM_MATCH_QUICK_PLUGIN')):
                from ddm.plugins import PluginManager
                from .match_quick_trial import install_plugin_source
                install_plugin_source(PluginManager, source)
            install_dispatch(app)
        MotionTrace(directory / 'danmaku-motion.jsonl').install()
    elif mode == 'live-elapsed':
        from ddm.drag_diagnostics import Recorder
        recorder = Recorder(directory / 'drag-windows.jsonl')
        recorder.install()
        atexit.register(recorder.handler.close)
    elif mode == 'responsiveness-profile':
        from ddm.responsiveness import install as install_responsiveness
        install_responsiveness(directory / 'responsiveness.jsonl')
    elif mode == 'development-hang':
        from .watch_development_hang import start_for_current_process
        if start_for_current_process(root) is None:
            raise RuntimeError('Development hang monitor could not be started')
    return dict(mode=mode, request_id=request['request_id'])
