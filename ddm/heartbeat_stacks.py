"""Sample Python locations during a delayed GUI heartbeat, without reading Qt off-thread."""
import sys
import threading
import time

from .responsiveness_probe import stack_locations


class HeartbeatStacks:
    def __init__(self):
        self.gui_thread = threading.get_ident()
        self.tick = time.perf_counter()
        self.samples = []
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.worker = threading.Thread(target=self.watch, name='sidebar-heartbeat', daemon=True)

    def watch(self):
        while not self.stopped.wait(.025):
            tick = self.tick
            delay = time.perf_counter() - tick
            if delay < .045 or len(self.samples) >= 8:
                continue
            frame = sys._current_frames().get(self.gui_thread)
            locations = stack_locations(frame)[:8]
            del frame
            with self.lock:
                if self.tick == tick:
                    self.samples.append(dict(at_ms=round(delay * 1000, 1), stack=locations))

    def pulse(self, now):
        with self.lock:
            elapsed = round((now - self.tick) * 1000, 3)
            samples, self.samples = self.samples, []
            self.tick = now
        return elapsed, samples

    def stop(self):
        self.stopped.set()
        if self.worker.is_alive():
            self.worker.join()
