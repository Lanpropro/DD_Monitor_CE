"""Bounded lifecycle evidence without retaining QObject wrappers or user data."""
from functools import wraps
import itertools
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time

_logger = None
_ids = itertools.count(1)


def start(directory):
    global _logger
    if _logger is not None:
        return
    logger = logging.getLogger('ddm.qt_lifecycle')
    handler = RotatingFileHandler(Path(directory) / f'qt-lifecycle-{os.getpid()}.jsonl',
                                  maxBytes=1024 * 1024, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    _logger = logger


def event(stage, identity, kind):
    if _logger is not None:
        _logger.info(json.dumps({'stage': stage, 'object': identity, 'kind': kind,
            'pid': os.getpid(), 'thread': threading.get_native_id(), 'at_ns': time.time_ns(),
            'mono_ns': time.perf_counter_ns()}, separators=(',', ':')))


def construction(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        if _logger is None:
            return function(self, *args, **kwargs)
        identity = f'{os.getpid()}:{next(_ids)}'
        kind = type(self).__name__
        event('construct.request', identity, kind)
        try:
            result = function(self, *args, **kwargs)
        except BaseException:
            event('construct.failed', identity, kind)
            raise
        self._diagnostic_identity = identity
        # Only immutable strings are closed over. Never touch self after destroyed.
        self.destroyed.connect(lambda *_: event('destroyed', identity, kind))
        event('construct.ready', identity, kind)
        return result
    return wrapped


def running(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        identity = getattr(self, '_diagnostic_identity', '')
        kind = type(self).__name__
        event('run.begin', identity, kind)
        try:
            return function(self, *args, **kwargs)
        finally:
            event('run.end', identity, kind)
    return wrapped


def delete_requested(obj):
    event('deleteLater.request', getattr(obj, '_diagnostic_identity', ''), type(obj).__name__)


def close():
    global _logger
    logger, _logger = _logger, None
    if logger is not None:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
