"""Opt-in theme-switch and animation capture hooks."""
import cProfile
import functools
import time
from .responsiveness_probe import profile_functions, Probe


def install_theme_capture(path, *, profile_calls=False):
    """Measure actual theme changes without a continuous sampler."""
    from . import responsiveness as capture_api
    import atexit
    from .theme_transition import ThemeTransition
    from . import theme

    probe = capture_api.Probe(path)
    original = ThemeTransition.change

    @functools.wraps(original)
    def change(transition, mode, *args, **kwargs):
        if probe.stopped.is_set():
            return original(transition, mode, *args, **kwargs)
        profile = cProfile.Profile() if profile_calls else None
        started = time.perf_counter()
        transition._theme_request_started = started
        if profile is not None:
            profile.enable()
        try:
            return original(transition, mode, *args, **kwargs)
        finally:
            if profile is not None:
                profile.disable()
            probe.write('theme-switch', mode=theme.normalize_mode(mode),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                functions=capture_api.profile_functions(profile) if profile is not None else [])

    ThemeTransition.change = change
    atexit.register(probe.stop)
    probe.write('start', mode='theme-switches-only')
    return probe


def install_theme_animation_capture(probe):
    """Bounded GUI-thread frame timings, separate from preparation costs."""
    from .theme_transition import ThemeTransition, WaveOverlay

    original_start = ThemeTransition._start_animation
    original_frame = ThemeTransition._frame
    original_finish = ThemeTransition.finish
    original_paint = WaveOverlay.paintEvent

    def start(transition):
        result = original_start(transition)
        if not probe.stopped.is_set() and transition.animation.state().name == 'Running':
            started = time.perf_counter()
            requested = getattr(transition, '_theme_request_started', None)
            record = {'started': started, 'frames': [], 'bitmap_paints': 0,
                'ready_ms': round((started - requested) * 1000, 3) if requested is not None else None}
            transition._motion_capture = record
            for overlay in transition.overlays:
                overlay._motion_capture = record
        return result

    def frame(transition, progress):
        record = getattr(transition, '_motion_capture', None)
        started = time.perf_counter()
        try:
            return original_frame(transition, progress)
        finally:
            if record is not None and len(record['frames']) < 40:
                record['frames'].append({'at_ms': round((started - record['started']) * 1000, 3),
                    'work_ms': round((time.perf_counter() - started) * 1000, 3),
                    'progress': round(float(progress), 5), 'overlays': len(transition.overlays),
                    'quick_overlays': sum(getattr(overlay, 'render_thread', False) for overlay in transition.overlays),
                    'caption_overlays': sum(getattr(overlay, 'caption_height', 0) > 0 for overlay in transition.overlays),
                    'native_overlays': sum(overlay._native_clip for overlay in transition.overlays)})

    def paint(overlay, event):
        record = getattr(overlay, '_motion_capture', None)
        if record is not None:
            record['bitmap_paints'] += 1
        return original_paint(overlay, event)

    def finish(transition):
        record = getattr(transition, '_motion_capture', None)
        transition._motion_capture = None
        progress = transition.progress
        try:
            return original_finish(transition)
        finally:
            if record is not None and not probe.stopped.is_set():
                probe.write('theme-animation', reason='complete' if progress >= 1 else 'interrupted',
                    duration_ms=round((time.perf_counter() - record['started']) * 1000, 3),
                    ready_ms=record['ready_ms'], frames=record['frames'], bitmap_paints=record['bitmap_paints'])

    ThemeTransition._start_animation = start
    ThemeTransition._frame = frame
    ThemeTransition.finish = finish
    WaveOverlay.paintEvent = paint
