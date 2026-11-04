"""Compatibility launcher for the Windows drag/OLE investigation."""
from pathlib import Path
import os
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'main.py'), run_name='diagnostic_bootstrap')
from ddm import drag_diagnostics

if __name__ != '__main__':
    sys.modules[__name__] = drag_diagnostics
else:
    from dev.watch_development_hang import start_for_current_process
    start_for_current_process()
    Recorder = drag_diagnostics.Recorder
    path = ROOT / 'logs' / 'drag-windows.jsonl'
    recorder = Recorder(path)
    recorder.install()
    if os.environ.get('DDM_NOTICE_CLOSE_CAPTURE') == '1':
        from dev.diagnose_notice_close import NoticeCloseTrace
        notice_close_trace = NoticeCloseTrace(ROOT / 'logs' / 'notice-close.jsonl')
        notice_close_trace.install()
    if os.environ.get('DDM_DANMAKU_MOTION_CAPTURE') == '1':
        from dev.diagnose_danmaku_motion import MotionTrace
        motion_trace = MotionTrace(ROOT / 'logs' / 'danmaku-motion.jsonl')
        motion_trace.install()
    if os.environ.get('DDM_SC_PAINT_CAPTURE') == '1':
        from dev.diagnose_super_chat import SuperChatTrace
        sc_trace = SuperChatTrace(ROOT / 'logs' / 'sc-paint')
        sc_trace.install()
    if os.environ.get('DDM_WALL_REPLACEMENT_CAPTURE') == '1':
        from dev.diagnose_wall_replacement import ReplacementTrace
        replacement_trace = ReplacementTrace(ROOT / 'logs' / 'wall-replacement.jsonl')
        replacement_trace.install()
    if os.environ.get('DDM_CONTROL_SWAP_CAPTURE') == '1':
        from dev.diagnose_control_swap import SwapTrace
        swap_trace = SwapTrace(ROOT / 'logs' / 'control-swap.jsonl')
        swap_trace.install()
    print('Window diagnostics:', path, file=sys.stderr, flush=True)
    runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
