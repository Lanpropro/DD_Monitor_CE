"""Bounded lifecycle evidence without retaining QObject wrappers or user data."""
from functools import partial, wraps
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


def event(stage, identity, kind, parent="", source=""):
    if _logger is not None:
        row = {'stage': stage, 'object': identity, 'kind': kind,
            'parent': parent, 'pid': os.getpid(), 'thread': threading.get_native_id(), 'at_ns': time.time_ns(),
            'mono_ns': time.perf_counter_ns()}
        if source:
            row['source'] = source
        _logger.info(json.dumps(row, separators=(',', ':')))


def construction(function=None, *, sources=()):
    if function is None:
        return partial(construction, sources=sources)

    @wraps(function)
    def wrapped(self, *args, **kwargs):
        if _logger is None:
            return function(self, *args, **kwargs)
        identity = f'{os.getpid()}:{next(_ids)}'
        kind = type(self).__name__
        parent = kwargs.get('parent', args[1] if len(args) > 1 else None)
        parent_id = getattr(parent, '_diagnostic_identity', '')
        source = kwargs.get('diagnostic_source')
        source = source if source in sources else ''
        self._diagnostic_identity = identity
        self._diagnostic_parent = parent_id
        self._diagnostic_source = source
        event('construct.request', identity, kind, parent_id, source)
        try:
            result = function(self, *args, **kwargs)
        except BaseException:
            event('construct.failed', identity, kind, parent_id, source)
            raise
        # Only immutable strings are closed over. Never touch self after destroyed.
        self.destroyed.connect(lambda: event('destroyed', identity, kind, parent_id, source))
        event('construct.ready', identity, kind, parent_id, source)
        return result
    return wrapped


def running(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        identity = getattr(self, '_diagnostic_identity', '')
        kind = type(self).__name__
        context = (identity, kind, getattr(self, '_diagnostic_parent', ''),
                   getattr(self, '_diagnostic_source', ''))
        event('run.begin', *context)
        try:
            return function(self, *args, **kwargs)
        finally:
            event('run.end', *context)
    return wrapped


def delete_requested(obj):
    event('deleteLater.request', getattr(obj, '_diagnostic_identity', ''), type(obj).__name__,
          getattr(obj, '_diagnostic_parent', ''))


def close():
    global _logger
    logger, _logger = _logger, None
    if logger is not None:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
