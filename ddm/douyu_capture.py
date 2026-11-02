"""Bounded asynchronous diagnostic metadata writer and FLV transport observer."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import re
import threading
import time
from urllib.parse import urlsplit
import uuid

from .douyu_flv import FlvInspector
from .diagnostics import sanitize


def metadata_value(value):
    if isinstance(value, bytes):
        return {'binary_bytes': len(value)}  # Unknown binary fields must not persist media or credentials.
    raise TypeError('Unsupported diagnostic field type: ' + type(value).__name__)


class Capture:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.run = uuid.uuid4().hex[:12]
        self.handler = RotatingFileHandler(path, maxBytes=20 * 1024 * 1024,
                                          backupCount=5, encoding='utf-8')
        self.logger = logging.Logger('douyu-capture')
        self.logger.addHandler(self.handler)
        self.queue = queue.Queue(maxsize=20000)
        self.dropped = 0
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._write, name='douyu-capture-writer', daemon=True)
        self.thread.start()
        self.probes = []

    def emit(self, stage, **values):
        row = dict(time=time.time(), monotonic=time.monotonic(), pid=os.getpid(),
                   qpc=time.perf_counter(), run=self.run, stage=stage, **values)
        with self.lock:
            if self.stopped.is_set():
                return
            try:
                self.queue.put_nowait(row)
            except queue.Full:
                self.dropped += 1

    def _write(self):
        while not self.stopped.is_set() or not self.queue.empty():
            try:
                row = self.queue.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                try:
                    text = json.dumps(row, ensure_ascii=False, default=metadata_value)
                except (TypeError, ValueError) as error:
                    with self.lock:
                        self.dropped += 1
                    text = json.dumps(dict(time=row['time'], qpc=row['qpc'], pid=row['pid'], run=self.run,
                        stage='capture.serialization-error', original_stage=row['stage'],
                        error=type(error).__name__))
                self.logger.warning(text)
            finally:
                self.queue.task_done()

    def flush(self):
        self.queue.join()
        self.handler.flush()

    def close(self):
        if self.stopped.is_set():
            return
        for probe in self.probes:
            probe.stop()
        with self.lock:
            self.stopped.set()
        self.thread.join()
        self.logger.warning(json.dumps(dict(time=time.time(), monotonic=time.monotonic(), pid=os.getpid(),
            qpc=time.perf_counter(), run=self.run, stage='capture-stop', dropped_records=self.dropped)))
        self.handler.close()


class TransportObserver:
    def __init__(self, emit, source):
        self.emit = emit
        self.connection = uuid.uuid4().hex[:8]
        self.host = urlsplit(source).hostname
        self.first = self.last = None
        self.total = 0
        self.flv = FlvInspector(self.packet)

    def packet(self, stage, **values):
        self.emit(stage, connection=self.connection, host=self.host, **values)

    def __call__(self, event, **values):
        now = time.perf_counter()
        error = values.pop('exception', None)
        if error is not None:
            chain = []
            while error is not None and len(chain) < 8:
                message = re.sub(r'(?:https?|rtmps?)://[^\s\"\'<>]+', '[URL]', sanitize(str(error)))
                reason = getattr(error, 'reason', None)
                if reason is not None:
                    reason = re.sub(r'(?:https?|rtmps?)://[^\s\"\'<>]+', '[URL]', sanitize(str(reason)))[:1024]
                chain.append(dict(error=type(error).__name__, message=message[:1024],
                                  ssl_reason=reason,
                                  verify_code=getattr(error, 'verify_code', None)))
                error = error.__cause__ or error.__context__
            values['error_chain'] = chain
        if event == 'chunk':
            data = values.pop('data')
            self.total += len(data)
            values.update(bytes=len(data), total_bytes=self.total,
                          first_chunk=self.first is None,
                          gap_ms=None if self.last is None else round((now - self.last) * 1000, 3))
            self.first = self.first or now
            self.last = now
            self.packet('network.chunk', **values)
            self.flv.feed(data)
        else:
            if event == 'end':
                self.flv.finish()
                values.update(total_bytes=self.total,
                              last_data_age_ms=None if self.last is None else (now - self.last) * 1000)
            self.packet('network.' + event, **values)
