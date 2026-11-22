"""Byte progress and speed sampling shared by update presentations."""
import time


class DownloadSample:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.sampled = clock()
        self.previous = self.received = 0
        self.speed = 0.0
        self.attempt = 0

    def update(self, received, total):
        now = self.clock()
        if received == 0 or received < self.received:
            self.sampled = now
            self.previous = 0
            self.speed = 0.0
            self.attempt += 1
        elapsed = now - self.sampled
        if elapsed >= .25:
            self.speed = max(0, received - self.previous) / elapsed
            self.previous, self.sampled = received, now
        self.received = received
        return dict(received=received, total=total, speed=self.speed,
                    attempt=self.attempt,
                    percent=int(received * 100 / max(total, 1)),
                    phase='verifying' if received >= total and total > 0 else 'downloading')


def byte_text(value):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.2f} {unit}'
        value /= 1024


def progress_text(state):
    size = byte_text(state.get('received', 0)) + ' / ' + byte_text(state.get('total', 0))
    phase = state.get('phase')
    if phase == 'failed':
        return size + ' · 下载失败：' + state['error']
    if phase == 'ready':
        return size + ' · 已就绪，重启后应用'
    if phase == 'verifying':
        return size + ' · 校验／准备中'
    retry = f" · 重试 {state['attempt'] - 1}/2" if state.get('attempt', 0) > 1 else ''
    return size + ' · ' + byte_text(state.get('speed', 0)) + '/s' + retry
